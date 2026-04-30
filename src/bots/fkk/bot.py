from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.fkk.config import FkkConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from src.utils import get_ib_timezone
from ibapi.contract import ComboLeg, Contract, ContractDetails
from ibapi.order import Order
from ibapi.tag_value import TagValue
from ibapi.ticktype import TickTypeEnum, TickType
from datetime import datetime, timedelta, date
import pytz
import threading
import os
from src.utils import trace

class FkkBot(BaseBot):
    @trace
    def __init__(self, config: FkkConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.clear_internal_state()

    @trace
    def clear_internal_state(self):
        self.underlying_contract: Contract = None
        self.underlying_contract_resolution_status: ContractResolutionStatus = None
        self.historical_bars = []
        self.historical_data_req_id: int = None
        self.short_contract: Contract = None
        self.long_contract: Contract = None
        self.spread_contract: Contract = None
        self.spread_price_subscription_reg_id = None
        self.spread_price: dict = None
        self.option_market_data_req_ids: dict[int, Contract] = {}
        self.stop_confirm_entry_conditions_timer_id: str | None = None

    @trace
    def start(self):
        self.logger.info(f"Starting FkkBot with config: {self.config.bot_name}")
        tz_name = self.config.timezone if hasattr(self.config, "timezone") else "America/New_York"
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        
        if hasattr(self.config, "test_mode") and self.config.test_mode:
            self.logger.info("Test mode enabled. Triggering in 3 seconds.")
            entry_datetime = now + timedelta(seconds=3)
        else:
            entry_time = self.config.entry_time if hasattr(self.config, "entry_time") else "14:15:00"
            # determine if entry_time is in the past by creating a datetime object for entry_time and comparing it to the current time
            entry_datetime = datetime.strptime(entry_time, "%H:%M:%S").replace(tzinfo=tz,year=now.year,month=now.month,day=now.day)        
            
            if entry_datetime < now:
                entry_datetime += timedelta(days=1)
        
        self.logger.info(f"entry_datetime: {entry_datetime}")
        trigger_time = entry_datetime.strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.timer_manager.add_timer(self.config.bot_name, "confirm_entry_conditions", self.on_timer, trigger_time=trigger_time)

    @trace
    def stop(self):
        self.logger.info(f"Stopping FkkBot with config: {self.config.bot_name}")

    @trace
    def on_timer(self, event_name: str, event_data: any = None):
        if event_name == "confirm_entry_conditions":
            self.on_confirm_entry_conditions()
        elif event_name == "stop_confirm_entry_conditions":
            self.on_stop_confirm_entry_conditions()
        elif event_name == "stop":
            self.test_stop()

    @trace
    def on_confirm_entry_conditions(self):
        self.clear_internal_state()
        now = datetime.now(pytz.timezone(self.config.timezone))
        trigger_datetime = now + timedelta(seconds=self.config.entry_time_observation_period)
        trigger_time = trigger_datetime.strftime(f"%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
        self.stop_confirm_entry_conditions_timer_id = self.timer_manager.add_timer(self.config.bot_name, "stop_confirm_entry_conditions", self.on_timer, trigger_time=trigger_time)

        # resolve underlying SPX contract
        self.underlying_contract = Contract()
        self.underlying_contract.symbol = "SPX"
        self.underlying_contract.secType = "IND"
        self.underlying_contract.exchange = ""
        self.underlying_contract.currency = "USD"
        self.underlying_contract_resolution_status = ContractResolutionStatus()

        self.resolve_contracts(search_contract=self.underlying_contract,
            status=self.underlying_contract_resolution_status,
            callback=self.on_confirm_entry_conditions_on_underlying_contract_resolved)
           
    @trace
    def on_confirm_entry_conditions_on_underlying_contract_resolved(self,status: ContractResolutionStatus, result_contracts: list[ContractDetails]):
        if len(status.errors) == 0 and len(result_contracts) == 1 and status.complete:
            self.underlying_contract_details = result_contracts[0]
            self.underlying_contract = self.underlying_contract_details.contract
            self.logger.info(f"timezoneId: {self.underlying_contract_details.timeZoneId}")
            self.logger.info(f"trading hours: {self.underlying_contract_details.tradingHours}")
            self.logger.info(f"liquid hours: {self.underlying_contract_details.liquidHours}")


            # 1. Get the timezone object from IB's timeZoneId
            ib_tz = get_ib_timezone(self.underlying_contract_details.timeZoneId)

            # 2. Get the current time in THAT specific timezone
            # This is the most reliable way to compare
            now_in_exchange_tz = datetime.now(ib_tz)

            # 3. Parse the IB string
            # The string is in the format "YYYYMMDD:HHMM-YYYYMMDD:HHMM;YYYYMMDD:HHMM-YYYYMMDD:HHMM;..."
            # Today is the part before first semicolon
            todays_tradinghours = self.underlying_contract_details.tradingHours.split(";")[0]
            # Split at - to get start and end time
            ib_start_str, ib_end_str = todays_tradinghours.split("-")
            # Convert to datetime object, considering timezone
            start_dt = datetime.strptime(ib_start_str, "%Y%m%d:%H%M").replace(tzinfo=ib_tz)
            end_dt = datetime.strptime(ib_end_str, "%Y%m%d:%H%M").replace(tzinfo=ib_tz)
            self.logger.info(f"Today's trading hours: start_dt {start_dt} end_dt: {end_dt}. In local time at the exchange, it is now {now_in_exchange_tz}")

            # 4. Compare
            if start_dt <= now_in_exchange_tz and end_dt >= now_in_exchange_tz:
                self.logger.info("Market should be open!")
            else:
                self.logger.info("Market should be closed!")


            # request historical data for SPX
            self.historical_bars.clear()
            self.historical_data_req_id = self.request_historical_data(contract=self.underlying_contract, 
                end_datetime="", 
                duration=f"{self.config.sma_period} D", 
                bar_size="1 day", 
                what_to_show="TRADES", 
                use_rth=1, 
                keep_up_to_date=True, 
                callback_historical_data_end=self.on_historical_data_end, 
                callback_historical_data_update=self.on_historical_data_update)

        else:
            self.logger.error(f"Failed to resolve underlying contract: {status.errors}")

    @trace
    def on_historical_data_end(self, bars):
        self.historical_bars = bars
        self.historical_data_req_id = None
        self.evaluate_entry_conditions()

    @trace
    def on_historical_data_update(self, bar):
        # This callback is invoked about once every 5 seconds when keepUpToDate is active after on historical_data_end() has retrieved the initial set of bars 
        self.logger.info(f"Historical data update received, reevaluating entry conditions: {bar}")
        for i, b in enumerate(self.historical_bars):
            if b.date == bar.date:
                self.historical_bars[i] = bar
                break
        self.evaluate_entry_conditions()

    @trace
    def evaluate_entry_conditions(self):
        if len(self.historical_bars) < self.config.sma_period:
            return

        # Calculate SMA
        last_closes = [bar.close for bar in self.historical_bars[-self.config.sma_period:]]
        sma = sum(last_closes) / len(last_closes)
        
        # Current day's data
        current_bar = self.historical_bars[-1]
        close = current_bar.close
        open_price = current_bar.open
        
        self.logger.info(f"Close: {close}, Open: {open_price}, Percent move: {(close - open_price) / open_price * 100:.2f}%, SMA({self.config.sma_period}): {sma}")

        # Evaluate conditions
        entry_conditions_met = close > sma and close > (1 + self.config.intraday_move_pct / 100) * open_price
        if entry_conditions_met or self.config.force_open_position:
            self.logger.info("Entry conditions are met.")
            # stop listening to entry conditions. Move the timer to now to trigger the stop asynchronously.
            if self.stop_confirm_entry_conditions_timer_id:
                self.timer_manager.remove_timer(self.stop_confirm_entry_conditions_timer_id)
            now = datetime.now(pytz.timezone(self.config.timezone))
            trigger_time = now.strftime(f"%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
            self.stop_confirm_entry_conditions_timer_id = self.timer_manager.add_timer(self.config.bot_name, "stop_confirm_entry_conditions", self.on_timer, trigger_time=trigger_time)
            self.on_entry_conditions_are_met()
        else:
            self.logger.info("Entry conditions are not met.")
    
    @trace
    def on_entry_conditions_are_met(self):
        """Use OptionsFinder to find the short put contract by delta."""
        today = date.today()
        if self.config.test_mode:
            if today.weekday() >= 5:  # Monday is 0 and Sunday is 6
                today += timedelta(days=7 - today.weekday())

        expiration_str = today.strftime("%Y%m%d")
        underlying_price = self.historical_bars[-1].close
        
        self.logger.info(f"Finding short put with delta {self.config.delta} for expiration {expiration_str}")
        
        # Use OptionsFinder to find the short contract
        self.options_finder.find_option_by_delta(
            underlying=self.underlying_contract,
            underlying_price=underlying_price,
            target_delta=self.config.delta,
            right="P",
            expiration=expiration_str,
            callback=self.on_short_contract_found,
            exchange="CBOE",
            trading_class="SPXW",
            timeout_ms=15000
        )
    
    @trace
    def on_short_contract_found(self, contract, greeks):
        """Callback when short contract is found."""
        if contract is None:
            self.logger.error("Failed to find short put contract")
            return
        
        self.short_contract = contract
        self.logger.info(f"Found short put: strike={contract.strike}, delta={greeks.delta:.4f}")
        
        # Now find the long contract
        self.select_long_contract()

    @trace
    def on_stop_confirm_entry_conditions(self):
        self.logger.info("Stopping to observe market for entry conditions.")
        if self.historical_data_req_id is not None:
            self.cancel_historical_data(self.historical_data_req_id)
            req_id = self.historical_data_req_id
            self.historical_data_req_id = None
            self.logger.info(f"Cancelled historical data request with req_id: {req_id}")

    @trace
    def select_long_contract(self):
        """Find the long put contract at the specified width."""
        long_strike = self.short_contract.strike - self.config.width
        expiration = self.short_contract.lastTradeDateOrContractMonth
        
        self.logger.info(f"Finding long put at strike {long_strike}")
        
        # Create contract specification for the long put
        long_contract_spec = Contract()
        long_contract_spec.symbol = self.underlying_contract.symbol
        long_contract_spec.secType = "OPT"
        long_contract_spec.exchange = "SMART"
        long_contract_spec.currency = self.underlying_contract.currency
        long_contract_spec.lastTradeDateOrContractMonth = expiration
        long_contract_spec.strike = long_strike
        long_contract_spec.right = "P"
        
        # Use OptionsFinder to resolve the contract
        self.options_finder.resolve_contract(
            long_contract_spec,
            self.on_long_contract_found,
            timeout_ms=5000
        )
    
    @trace
    def on_long_contract_found(self, contract, contract_details):
        """Callback when long contract is resolved."""
        if contract is None:
            self.logger.error("Failed to resolve long put contract")
            return
        
        self.long_contract = contract
        self.logger.info(f"Found long put: strike={contract.strike}")
        
        # Create the spread contract
        self.create_spread_contract()
        
    @trace
    def create_spread_contract(self):
        if self.underlying_contract is None:
            self.logger.error("underlying_contract is not set, cannot create spread contract")
            return
        contract = Contract()
        contract.symbol = self.underlying_contract.symbol
        contract.secType = "BAG"
        contract.currency = self.underlying_contract.currency
        contract.exchange = "SMART"  # Usually SMART for combo routing
        leg1 = ComboLeg()
        leg1.conId = self.short_contract.conId  # Use the unique Contract ID
        leg1.ratio = 1
        leg1.action = "SELL"
        leg1.exchange = "SMART"
        leg2 = ComboLeg()
        leg2.conId = self.long_contract.conId  # Use the unique Contract ID
        leg2.ratio = 1
        leg2.action = "BUY"
        leg2.exchange = "SMART"
        contract.comboLegs = [leg1, leg2]
        self.spread_contract = contract
        self.spread_price_subscription_reg_id = self.subscribe_market_data(contract, "101,106") #  removed 10,11,12,13,
        self.option_market_data_req_ids[self.spread_price_subscription_reg_id] = self.spread_contract
        self.logger.debug(f"spread_price_subscription_reg_id: {self.spread_price_subscription_reg_id}")

    @trace
    def create_order(self):
        if self.spread_price == None:
            self.spread_price = self.get_cached_price(con_id=None, reg_id=self.spread_price_subscription_reg_id).copy()

        lmt_price = (self.spread_price[TickTypeEnum.BID] + self.spread_price[TickTypeEnum.ASK]) / 2 # TODO

        order = Order()
        order.action = "BUY"
        order.tif = "DAY"
        order.totalQuantity = 1 # TODO
        order.orderType = "LMT"
        order.lmtPrice = lmt_price
        
        # Crucial for complex combos to ensure they fill
        # NonGuaranteed = 1 allows the legs to be filled independently if needed - IBKR will still try to fill the combo as a whole
        # Without this flag, many combos will be rejected
        # If a leg cannot be filled, the entire combo order will be rejected
        order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
        self.place_order(self.spread_contract, order)
    
    @trace
    def tick_price(self, reqId, tickType, price, attrib):
        self.logger.debug(f"tick_price: reqId={reqId}, tickType={tickType}, price={price}, attrib={attrib}")
        if reqId in self.option_market_data_req_ids:
            if self.spread_contract == self.option_market_data_req_ids[reqId]:
                self.spread_price = self.get_cached_price(con_id=None, reg_id=self.spread_price_subscription_reg_id).copy()
                self.logger.debug(f"spread_price: {self.spread_price}")
                if self.spread_price.get(TickTypeEnum.BID) is not None and self.spread_price.get(TickTypeEnum.ASK) is not None:
                    self.unsubscribe_market_data(self.spread_contract)
                    self.logger.debug(f"removing reqid from list: {reqId}")
                    del self.option_market_data_req_ids[reqId]
                    self.create_order()
                
            
