from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.chudfly.config import ChudflyConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from src.utils import get_ib_timezone, trace
from ibapi.contract import ComboLeg, Contract, ContractDetails
from ibapi.order import Order
from ibapi.tag_value import TagValue
from ibapi.ticktype import TickTypeEnum
from datetime import datetime, timedelta, date
from typing import Optional, Any, List
import pytz

class ChudflyBot(BaseBot):
    """
    Chudfly Bot: Trades SPX 0 DTE butterfly/spread on open range breakout.
    """
    
    @trace
    def __init__(self, config: ChudflyConfig, ib_connection: IBConnection, 
                 timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.clear_internal_state()

    @trace
    def clear_internal_state(self):
        """Reset internal state."""
        self.underlying_contract: Optional[Contract] = None
        self.underlying_details: Optional[ContractDetails] = None
        self.historical_bars = []
        self.historical_data_req_id: Optional[int] = None
        
        # Strategy state
        self.prev_closes: List[float] = []
        self.sma_value: Optional[float] = None
        self.yesterday_close: Optional[float] = None
        self.today_open: Optional[float] = None
        self.trigger_price: Optional[float] = None
        self.observation_started = False
        self.entry_in_progress = False
        self.position_opened = False
        
        # Contract legs
        self.leg1_long: Optional[Contract] = None
        self.leg2_short: Optional[Contract] = None
        self.leg3_long: Optional[Contract] = None
        self.spread_contract: Optional[Contract] = None
        self.spread_min_tick: float = 0.05
        
        # Order tracking
        self.entry_order_id: Optional[int] = None
        self.initial_debit: Optional[float] = None
        self.stop_loss_order_id: Optional[int] = None

    @trace
    def start(self):
        """Start the bot and schedule the daily routine."""
        self.logger.info(f"Starting ChudflyBot: {self.config.bot_name}")
        
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        
        # Schedule the first task: resolve underlying and check gap/SMA
        market_open_time = datetime.strptime(self.config.market_open_time, "%H:%M:%S")
        market_open_dt = market_open_time.replace(
            tzinfo=tz, year=now.year, month=now.month, day=now.day
        )
        self.scheduled_entry_time = market_open_dt
        
        if market_open_dt < now:
            if not self.config.test_mode:
                market_open_dt += timedelta(days=1)
        
        # Check trade days
        day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        while day_map[market_open_dt.weekday()] not in self.config.trade_days:
            market_open_dt += timedelta(days=1)
            
        trigger_time = market_open_dt.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
        self.logger.info(f"Daily routine scheduled for {trigger_time}")
        
        self.timer_manager.add_timer(
            self.config.bot_name,
            "daily_start",
            self.on_timer,
            trigger_time=trigger_time
        )

    @trace
    def on_timer(self, event_name: str, event_data: Any = None):
        if event_name == "daily_start":
            self.on_daily_start()
        elif event_name == "start_observation":
            self.on_start_observation()
        elif event_name == "stop_observation":
            self.on_stop_observation()

    @trace
    def on_daily_start(self):
        """Initial daily setup: resolve SPX and get historical data."""
        self.clear_internal_state()
        self.logger.info("Starting daily setup...")
        
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "IND"
        contract.exchange = ""
        contract.currency = "USD"
        self.underlying_contract = contract
        
        status = ContractResolutionStatus()
        self.resolve_contracts(
            self.underlying_contract,
            status,
            self.on_underlying_resolved
        )

    @trace
    def on_underlying_resolved(self, status: ContractResolutionStatus, result: List[ContractDetails]):
        if not status.complete or not result:
            self.logger.error(f"Failed to resolve SPX: {status.errors}")
            return
            
        self.underlying_details = result[0]
        self.underlying_contract = self.underlying_details.contract
        if self.underlying_contract:
            self.logger.info(f"Resolved SPX: conId={self.underlying_contract.conId}")
            
            self.historical_data_req_id = self.request_historical_data(
                contract=self.underlying_contract,
                end_datetime="",
                duration=f"{self.config.sma_period + 1} D",
                bar_size="1 day",
                what_to_show="TRADES",
                use_rth=1,
                keep_up_to_date=False,
                callback_historical_data_end=self.on_daily_historical_data_end
            )

    @trace
    def on_daily_historical_data_end(self, bars: List[Any]):
        if len(bars) < self.config.sma_period:
            self.logger.error(f"Not enough historical bars. Need {self.config.sma_period}, got {len(bars)}")
            return
            
        self.logger.info(f"Received {len(bars)} daily bars. Latest bar date: {bars[-1].date}")
        
        today_str = date.today().strftime("%Y%m%d")
        if bars[-1].date == today_str:
            self.yesterday_close = float(bars[-2].close)
            self.prev_closes = [float(bars[-3].close), float(bars[-2].close)]
            self.today_open = float(bars[-1].open)
        else:
            self.yesterday_close = float(bars[-1].close)
            self.prev_closes = [float(bars[-2].close), float(bars[-1].close)]
            self.today_open = None

        if self.today_open is not None and self.yesterday_close is not None:
            gap_pct = (self.today_open - self.yesterday_close) / self.yesterday_close * 100
            if gap_pct > 0 and gap_pct > self.config.max_gap_up_pct:
                self.logger.info(f"Gap up too large: {gap_pct:.2f}% > {self.config.max_gap_up_pct}%. Strategy skipped for today.")
                self.start()
                return
            elif gap_pct < 0 and abs(gap_pct) > self.config.max_gap_down_pct:
                self.logger.info(f"Gap down too large: {abs(gap_pct):.2f}% > {self.config.max_gap_down_pct}%. Strategy skipped for today.")
                self.start()
                return
            else:
                self.logger.info(f"Gap check passed: {gap_pct:.2f}%")

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        range_end_time = datetime.strptime(self.config.open_range_end_time, "%H:%M:%S")
        range_end_dt = range_end_time.replace(
            tzinfo=tz, year=now.year, month=now.month, day=now.day
        )
        
        if range_end_dt > now:
            trigger_time = range_end_dt.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
            self.timer_manager.add_timer(
                self.config.bot_name,
                "start_observation",
                self.on_timer,
                trigger_time=trigger_time
            )
            self.logger.info(f"Observation scheduled to start at {trigger_time}")
        else:
            observation_end_time = datetime.strptime(self.config.observation_end_time, "%H:%M:%S")
            observation_end_dt = observation_end_time.replace(
                tzinfo=tz, year=now.year, month=now.month, day=now.day
            )
            if now < observation_end_dt:
                self.on_start_observation()
            else:
                self.logger.info("Past observation window. Skipping today.")
                self.start()

    @trace
    def on_start_observation(self):
        """Calculate trigger price from 9:30-9:45 range and start observing."""
        self.logger.info("Calculating open range breakout trigger...")
        
        tz = pytz.timezone(self.config.timezone)
        range_end_time = datetime.strptime(self.config.open_range_end_time, "%H:%M:%S")
        now = datetime.now(tz)
        range_end_dt = range_end_time.replace(
            tzinfo=tz, year=now.year, month=now.month, day=now.day
        )
        
        end_str = range_end_dt.strftime("%Y%m%d %H:%M:%S")
        
        if self.underlying_contract:
            self.request_historical_data(
                contract=self.underlying_contract,
                end_datetime=end_str,
                duration="15 M",
                bar_size="1 min",
                what_to_show="TRADES",
                use_rth=1,
                keep_up_to_date=False,
                callback_historical_data_end=self.on_range_data_end
            )

    @trace
    def on_range_data_end(self, bars: List[Any]):
        if not bars:
            self.logger.error("No range data received.")
            return
            
        self.trigger_price = max(float(bar.high) for bar in bars)
        self.logger.info(f"Open Range High (Trigger): {self.trigger_price}")
        
        if self.today_open is None:
            self.today_open = float(bars[0].open)
            if self.yesterday_close is not None:
                gap_pct = (self.today_open - self.yesterday_close) / self.yesterday_close * 100
                if gap_pct > 0 and gap_pct > self.config.max_gap_up_pct:
                    self.logger.info(f"Gap up too large: {gap_pct:.2f}% > {self.config.max_gap_up_pct}%. Strategy skipped for today.")
                    self.start()
                    return
                elif gap_pct < 0 and abs(gap_pct) > self.config.max_gap_down_pct:
                    self.logger.info(f"Gap down too large: {abs(gap_pct):.2f}% > {self.config.max_gap_down_pct}%. Strategy skipped for today.")
                    self.start()
                    return
                else:
                    self.logger.info(f"Gap check passed (late check): {gap_pct:.2f}%")

        self.observation_started = True
        if self.underlying_contract:
            self.subscribe_market_data(self.underlying_contract)
        
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        stop_time = datetime.strptime(self.config.observation_end_time, "%H:%M:%S")
        stop_dt = stop_time.replace(
            tzinfo=tz, year=now.year, month=now.month, day=now.day
        )
        
        trigger_time = stop_dt.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
        self.timer_manager.add_timer(
            self.config.bot_name,
            "stop_observation",
            self.on_timer,
            trigger_time=trigger_time
        )

    @trace
    def on_stop_observation(self):
        if self.observation_started and not self.position_opened:
            self.logger.info("Observation window ended without entry. Stopping for today.")
            if self.underlying_contract:
                self.unsubscribe_market_data(self.underlying_contract)
            self.observation_started = False
            self.start()

    @trace
    def tick_price(self, reqId: int, tickType: int, price: float, attrib: Any):
        super().tick_price(reqId, tickType, price, attrib)

        # Avoid calling BaseBot's is_entry_timeout_exceeded since Chudfly uses a hard stop time for observation. The timer will handle stopping the observation window.
        # if self.is_entry_timeout_exceeded():
        #     self.on_stop_observation()
        #     return
        
        if not self.observation_started or self.entry_in_progress or self.position_opened:
            return
            
        if price <= 0 or price >= 1e308:
            return

        if self.trigger_price is not None and price > self.trigger_price:
            self.sma_value = (sum(self.prev_closes) + price) / 3
            
            if price > self.sma_value:
                self.logger.info(f"Entry triggered! Price {price} > Trigger {self.trigger_price} and Price > SMA {self.sma_value:.2f}")
                self.entry_in_progress = True
                self.on_entry_triggered(price)

    @trace
    def on_entry_triggered(self, current_price: float):
        """Find option legs and place order."""
        self.observation_started = False
        if self.underlying_contract:
            self.unsubscribe_market_data(self.underlying_contract)
        
        today_str = date.today().strftime("%Y%m%d")
        if self.underlying_contract:
            self.logger.info(f"Finding {self.config.lower_long_leg_delta} delta call for {today_str}...")
            self.options_finder.find_option_by_delta(
                underlying=self.underlying_contract,
                underlying_price=current_price,
                target_delta=self.config.lower_long_leg_delta,
                right="C",
                expiration=today_str,
                callback=self.on_leg1_found,
                exchange="CBOE",
                trading_class="SPXW"
            )

    @trace
    def on_leg1_found(self, contract: Optional[Contract], greeks: Any):
        if not contract:
            self.logger.error(f"Failed to find Leg 1 ({self.config.lower_long_leg_delta} delta call).")
            self.entry_in_progress = False
            return
            
        self.leg1_long = contract
        self.logger.info(f"Leg 1: {contract.localSymbol} at strike {contract.strike}")
        
        leg2_strike = float(contract.strike) + self.config.short_leg_offset
        self.logger.info(f"Resolving Leg 2 (short) at strike {leg2_strike}...")
        
        leg2_spec = Contract()
        leg2_spec.symbol = "SPX"
        leg2_spec.secType = "OPT"
        leg2_spec.exchange = "SMART"
        leg2_spec.currency = "USD"
        leg2_spec.lastTradeDateOrContractMonth = str(contract.lastTradeDateOrContractMonth)
        leg2_spec.strike = leg2_strike
        leg2_spec.right = "C"
        
        self.options_finder.resolve_contract(
            leg2_spec,
            self.on_leg2_found
        )

    @trace
    def on_leg2_found(self, contract: Optional[Contract], details: Optional[ContractDetails]):
        if not contract or self.leg1_long is None:
            self.logger.error("Failed to resolve Leg 2.")
            self.entry_in_progress = False
            return
            
        self.leg2_short = contract
        self.logger.info(f"Leg 2: {contract.localSymbol} at strike {contract.strike}")
        
        leg3_strike = float(contract.strike) + self.config.upper_long_leg_offset
        self.logger.info(f"Resolving Leg 3 (long) at strike {leg3_strike}...")
        
        leg3_spec = Contract()
        leg3_spec.symbol = "SPX"
        leg3_spec.secType = "OPT"
        leg3_spec.exchange = "SMART"
        leg3_spec.currency = "USD"
        leg3_spec.lastTradeDateOrContractMonth = str(self.leg1_long.lastTradeDateOrContractMonth)
        leg3_spec.strike = leg3_strike
        leg3_spec.right = "C"
        
        self.options_finder.resolve_contract(
            leg3_spec,
            self.on_leg3_found
        )

    @trace
    def on_leg3_found(self, contract: Optional[Contract], details: Optional[ContractDetails]):
        if not contract:
            self.logger.error("Failed to resolve Leg 3.")
            self.entry_in_progress = False
            return
            
        self.leg3_long = contract
        self.logger.info(f"Leg 3: {contract.localSymbol} at strike {contract.strike}")
        
        if details and hasattr(details, "minTick"):
            self.spread_min_tick = float(details.minTick)
            
        self.create_butterfly_contract()

    @trace
    def create_butterfly_contract(self):
        if not self.leg1_long or not self.leg2_short or not self.leg3_long:
            self.logger.error("Butterfly legs missing.")
            return

        self.logger.info("Creating Butterfly BAG contract...")
        
        contract = Contract()
        contract.symbol = "SPX"
        contract.secType = "BAG"
        contract.currency = "USD"
        contract.exchange = "SMART"
        
        l1 = ComboLeg()
        l1.conId = int(self.leg1_long.conId)
        l1.ratio = 1
        l1.action = "BUY"
        l1.exchange = "SMART"
        
        l2 = ComboLeg()
        l2.conId = int(self.leg2_short.conId)
        l2.ratio = 2
        l2.action = "SELL"
        l2.exchange = "SMART"
        
        l3 = ComboLeg()
        l3.conId = int(self.leg3_long.conId)
        l3.ratio = 1
        l3.action = "BUY"
        l3.exchange = "SMART"
        
        contract.comboLegs = [l1, l2, l3]
        self.spread_contract = contract
        
        self.subscribe_market_data(self.spread_contract, "101,106")

    @trace
    def tick_price_bag(self, reqId: int, tickType: int, price: float, attrib: Any):
        if self.position_opened or not self.entry_in_progress or self.spread_contract is None:
            return
            
        data = self.get_cached_price(reg_id=reqId)
        if not data: return
        
        bid = data.get(TickTypeEnum.BID)
        ask = data.get(TickTypeEnum.ASK)
        
        if bid is not None and ask is not None:
            mid = (float(bid) + float(ask)) / 2
            lmt_price = round(mid / self.spread_min_tick) * self.spread_min_tick
            
            self.logger.info(f"Placing entry order for Butterfly. Bid: {bid}, Ask: {ask}, Mid: {mid}, Limit: {lmt_price}")
            
            order = Order()
            order.action = "BUY"
            order.totalQuantity = 1
            order.orderType = "LMT"
            order.lmtPrice = float(lmt_price)
            order.tif = "DAY"
            order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
            
            self.entry_order_id = self.place_order(self.spread_contract, order)
            self.unsubscribe_market_data(self.spread_contract)
            self.entry_in_progress = False

    @trace
    def order_status(self, orderId: int, status: str, filled: float, remaining: float, 
                     avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, 
                     clientId: int, whyHeld: str, mktCapPrice: float):
        super().order_status(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        
        if orderId == self.entry_order_id and status == "Filled" and not self.position_opened:
            self.position_opened = True
            self.initial_debit = float(avgFillPrice)
            self.logger.info(f"Entry filled at {avgFillPrice}. Setting up stop loss.")
            self.place_stop_loss_order(float(avgFillPrice))

    @trace
    def place_stop_loss_order(self, entry_price: float):
        if self.spread_contract is None: return
        
        stop_price = entry_price * (1 - (self.config.stop_loss_pct / 100))
        stop_price = round(stop_price / self.spread_min_tick) * self.spread_min_tick
        
        self.logger.info(f"Placing Stop Loss order at {stop_price}")
        
        order = Order()
        order.action = "SELL"
        order.totalQuantity = 1
        order.orderType = "STP"
        order.auxPrice = float(stop_price)
        order.tif = "DAY"
        order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        
        self.stop_loss_order_id = self.place_order(self.spread_contract, order)

    def tick_price_all(self, reqId: int, tickType: int, price: float, attrib: Any):
        if self.spread_contract and reqId == self.get_req_id_for_contract(self.spread_contract):
            self.tick_price_bag(reqId, tickType, price, attrib)
        else:
            self.tick_price(reqId, tickType, price, attrib)

    def get_req_id_for_contract(self, contract: Contract) -> Optional[int]:
        # Implementation of req_id lookup if needed, otherwise rely on BaseBot behavior
        return None
