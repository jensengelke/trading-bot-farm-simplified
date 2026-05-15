from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.ic.config import IcConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import ComboLeg, Contract, ContractDetails
from ibapi.order import Order
from ibapi.tag_value import TagValue
from ibapi.ticktype import TickTypeEnum
from datetime import datetime, timedelta, date
from typing import Optional, Any
import pytz
from src.utils import trace

class IcBot(BaseBot):
    """Iron Condor Bot - Creates an iron condor spread on SPX with configurable deltas and widths."""
    
    @trace
    def __init__(self, config: IcConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.clear_internal_state()

    @trace
    def clear_internal_state(self):
        """Reset all internal state variables."""
        self.underlying_contract: Optional[Contract] = None
        self.underlying_contract_details: Optional[ContractDetails] = None
        
        # Put spread contracts
        self.put_short_contract: Optional[Contract] = None
        self.put_long_contract: Optional[Contract] = None
        
        # Call spread contracts
        self.call_short_contract: Optional[Contract] = None
        self.call_long_contract: Optional[Contract] = None
        
        # Iron condor spread contract
        self.ic_spread_contract: Optional[Contract] = None
        self.ic_spread_min_tick: float = 0.05
        self.ic_spread_price_subscription_req_id: Optional[int] = None
        self.ic_spread_price: Optional[dict] = None
        
        # Market data tracking
        self.option_market_data_req_ids: dict[int, Contract] = {}
        
        # State tracking
        self.entry_in_progress = False
        self.expiration_date: Optional[str] = None

    @trace
    def start(self):
        """Called when bot is started."""
        self.logger.info(f"Starting IcBot: {self.config.bot_name}")
        
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        
        if self.config.test_mode:
            self.logger.info("Test mode enabled. Triggering in 3 seconds.")
            entry_datetime = now + timedelta(seconds=3)
        else:
            entry_time = datetime.strptime(self.config.entry_time, "%H:%M:%S")
            entry_datetime = entry_time.replace(
                tzinfo=tz, year=now.year, month=now.month, day=now.day
            )
            
            if entry_datetime < now:
                entry_datetime += timedelta(days=1)
        
        self.logger.info(f"Entry scheduled for: {entry_datetime}")
        trigger_time = entry_datetime.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
        self.timer_manager.add_timer(
            self.config.bot_name, 
            "check_entry", 
            self.on_timer, 
            trigger_time=trigger_time
        )

    @trace
    def stop(self):
        """Called when bot is stopped."""
        self.logger.info(f"Stopping IcBot: {self.config.bot_name}")
        # Clean up any subscriptions
        if self.ic_spread_contract:
            self.unsubscribe_market_data(self.ic_spread_contract)

    @trace
    def on_timer(self, event_name: str, event_data: Any = None):
        """Handle timer events."""
        if event_name == "check_entry":
            self.on_check_entry()

    @trace
    def on_check_entry(self):
        """Entry point - resolve SPX underlying contract."""
        if self.entry_in_progress:
            self.logger.debug("Entry already in progress, skipping")
            return
        
        self.entry_in_progress = True
        self.clear_internal_state()
        self.entry_in_progress = True
        
        self.logger.info("Checking entry conditions...")
        
        # Calculate expiration date (today + DTE)
        today = date.today()
        if self.config.test_mode and today.weekday() >= 5:
            # If weekend in test mode, move to next Monday
            today += timedelta(days=7 - today.weekday())
        
        expiration_date = today + timedelta(days=self.config.dte)
        self.expiration_date = expiration_date.strftime("%Y%m%d")
        self.logger.info(f"Target expiration: {self.expiration_date} ({self.config.dte} DTE)")
        
        # Resolve SPX underlying contract
        self.underlying_contract = Contract()
        self.underlying_contract.symbol = "SPX"
        self.underlying_contract.secType = "IND"
        self.underlying_contract.exchange = ""
        self.underlying_contract.currency = "USD"
        
        status = ContractResolutionStatus()
        self.resolve_contracts(
            search_contract=self.underlying_contract,
            status=status,
            callback=self.on_underlying_resolved
        )

    @trace
    def on_underlying_resolved(self, status: ContractResolutionStatus, result_contracts: list[ContractDetails]):
        """Callback when SPX underlying is resolved."""
        if len(status.errors) > 0 or len(result_contracts) != 1 or not status.complete:
            self.logger.error(f"Failed to resolve SPX underlying: {status.errors}")
            self.entry_in_progress = False
            return
        
        self.underlying_contract_details = result_contracts[0]
        self.underlying_contract = self.underlying_contract_details.contract
        self.logger.info(f"Resolved SPX underlying: conId={self.underlying_contract.conId}")
        
        # Get current SPX price from market data
        self.subscribe_underlying_price()

    @trace
    def subscribe_underlying_price(self):
        """Subscribe to SPX market data to get current price."""
        self.logger.info("Requesting robust SPX price...")
        self.request_market_data(self.underlying_contract, self.on_underlying_price_received)

    @trace
    def on_underlying_price_received(self, success: bool, price_data: dict):
        """Callback when underlying price is received."""
        if not price_data:
            self.logger.error("Failed to get SPX price data. Aborting entry.")
            self.entry_in_progress = False
            return

        if not success:
            self.logger.warning("Timed out waiting for complete SPX price data. Using partial data.")

        # Try Bid/Ask first, then Last, then Close
        bid = price_data.get(TickTypeEnum.BID)
        ask = price_data.get(TickTypeEnum.ASK)
        last = price_data.get(TickTypeEnum.LAST)
        close = price_data.get(TickTypeEnum.CLOSE)

        if bid is not None and ask is not None and bid > 0 and ask > 0 and bid < 1e308 and ask < 1e308:
            underlying_price = (bid + ask) / 2
        elif last is not None and last > 0 and last < 1e308:
            underlying_price = last
        elif close is not None and close > 0 and close < 1e308:
            underlying_price = close
        else:
            self.logger.error(f"No valid SPX price found in data: {price_data}. Aborting entry.")
            self.entry_in_progress = False
            return

        self.logger.info(f"SPX price determined: {underlying_price:.2f}")
        # Start finding put spread
        self.find_put_short(underlying_price)

    @trace
    def tick_price(self, reqId, tickType, price, attrib):
        """Handle market data price updates."""
        # Call base class to handle robust market data requests
        super().tick_price(reqId, tickType, price, attrib)
        
        if reqId not in self.option_market_data_req_ids:
            return
        
        contract = self.option_market_data_req_ids[reqId]
        
        # Handle IC spread price (we still handle this manually because BAG contracts 
        # might not provide all OHLC ticks)
        if contract == self.ic_spread_contract:
            data = self.get_cached_price(reg_id=reqId)
            if not data: return
            self.ic_spread_price = data.copy()
            
            bid = self.ic_spread_price.get(TickTypeEnum.BID)
            ask = self.ic_spread_price.get(TickTypeEnum.ASK)
            
            if bid is not None and ask is not None and bid > -1e308 and ask < 1e308:
                # For BAG, Bid/Ask can be negative, so we just check for infinite
                self.logger.info(f"IC spread price - Bid: {bid}, Ask: {ask}")
                
                # Unsubscribe and place order
                self.unsubscribe_market_data(self.ic_spread_contract)
                del self.option_market_data_req_ids[reqId]
                self.create_order()

    @trace
    def find_put_short(self, underlying_price: float):
        """Find the short put by delta."""
        self.logger.info(f"Finding short put with delta {self.config.put_short_delta}")
        
        self.options_finder.find_option_by_delta(
            underlying=self.underlying_contract,
            underlying_price=underlying_price,
            target_delta=self.config.put_short_delta,
            right="P",
            expiration=self.expiration_date,
            callback=self.on_put_short_found,
            exchange="CBOE",
            trading_class="SPXW",
            timeout_ms=15000
        )

    @trace
    def on_put_short_found(self, contract, greeks):
        """Callback when short put is found."""
        if contract is None:
            self.logger.error("Failed to find short put. Aborting entry.")
            self.entry_in_progress = False
            return
        
        self.put_short_contract = contract
        self.logger.info(f"Found short put: strike={contract.strike}, delta={greeks.delta:.4f}")
        
        # Find long put
        self.find_put_long()

    @trace
    def find_put_long(self):
        """Find the long put at specified width below short put."""
        long_strike = self.put_short_contract.strike - self.config.put_width
        self.logger.info(f"Finding long put at strike {long_strike}")
        
        long_contract_spec = Contract()
        long_contract_spec.symbol = self.underlying_contract.symbol
        long_contract_spec.secType = "OPT"
        long_contract_spec.exchange = "SMART"
        long_contract_spec.currency = self.underlying_contract.currency
        long_contract_spec.lastTradeDateOrContractMonth = self.expiration_date
        long_contract_spec.strike = long_strike
        long_contract_spec.right = "P"
        
        self.options_finder.resolve_contract(
            long_contract_spec,
            self.on_put_long_found,
            timeout_ms=5000
        )

    @trace
    def on_put_long_found(self, contract, contract_details):
        """Callback when long put is resolved."""
        if contract is None:
            self.logger.error("Failed to resolve long put. Aborting entry.")
            self.entry_in_progress = False
            return
        
        self.put_long_contract = contract
        self.logger.info(f"Found long put: strike={contract.strike}")
        
        # Extract minTick
        if contract_details and hasattr(contract_details, 'minTick'):
            self.ic_spread_min_tick = contract_details.minTick
            self.logger.info(f"Using minTick: {self.ic_spread_min_tick}")
        
        # Now find call spread - need to get underlying price again
        self.find_call_short()

    @trace
    def find_call_short(self):
        """Find the short call by delta."""
        self.logger.info(f"Finding short call with delta {self.config.call_short_delta}")
        
        # Request robust market data for underlying again to ensure we have fresh price
        self.get_robust_market_data(self.underlying_contract, self.on_call_short_underlying_price_received)

    @trace
    def on_call_short_underlying_price_received(self, success: bool, underlying_price: Optional[float]):
        """Callback when underlying price for call search is received."""
        if underlying_price is None:
            self.logger.error("Cannot determine underlying price for call search. Aborting entry.")
            self.entry_in_progress = False
            return

        if not success:
            self.logger.warning("Timed out waiting for complete SPX price for call search. Using best available.")

        self.options_finder.find_option_by_delta(
            underlying=self.underlying_contract,
            underlying_price=underlying_price,
            target_delta=self.config.call_short_delta,
            right="C",
            expiration=self.expiration_date,
            callback=self.on_call_short_found,
            exchange="CBOE",
            trading_class="SPXW",
            timeout_ms=15000
        )

    @trace
    def on_call_short_found(self, contract, greeks):
        """Callback when short call is found."""
        if contract is None:
            self.logger.error("Failed to find short call. Aborting entry.")
            self.entry_in_progress = False
            return
        
        self.call_short_contract = contract
        self.logger.info(f"Found short call: strike={contract.strike}, delta={greeks.delta:.4f}")
        
        # Find long call
        self.find_call_long()

    @trace
    def find_call_long(self):
        """Find the long call at specified width above short call."""
        long_strike = self.call_short_contract.strike + self.config.call_width
        self.logger.info(f"Finding long call at strike {long_strike}")
        
        long_contract_spec = Contract()
        long_contract_spec.symbol = self.underlying_contract.symbol
        long_contract_spec.secType = "OPT"
        long_contract_spec.exchange = "SMART"
        long_contract_spec.currency = self.underlying_contract.currency
        long_contract_spec.lastTradeDateOrContractMonth = self.expiration_date
        long_contract_spec.strike = long_strike
        long_contract_spec.right = "C"
        
        self.options_finder.resolve_contract(
            long_contract_spec,
            self.on_call_long_found,
            timeout_ms=5000
        )

    @trace
    def on_call_long_found(self, contract, contract_details):
        """Callback when long call is resolved."""
        if contract is None:
            self.logger.error("Failed to resolve long call. Aborting entry.")
            self.entry_in_progress = False
            return
        
        self.call_long_contract = contract
        self.logger.info(f"Found long call: strike={contract.strike}")
        
        # All four legs found - create iron condor spread
        self.create_ic_spread_contract()

    @trace
    def create_ic_spread_contract(self):
        """Create the iron condor BAG contract with all four legs."""
        self.logger.info("Creating iron condor spread contract")
        
        contract = Contract()
        contract.symbol = self.underlying_contract.symbol
        contract.secType = "BAG"
        contract.currency = self.underlying_contract.currency
        contract.exchange = "SMART"
        
        # Put spread legs
        put_short_leg = ComboLeg()
        put_short_leg.conId = self.put_short_contract.conId
        put_short_leg.ratio = 1
        put_short_leg.action = "SELL"
        put_short_leg.exchange = "SMART"
        
        put_long_leg = ComboLeg()
        put_long_leg.conId = self.put_long_contract.conId
        put_long_leg.ratio = 1
        put_long_leg.action = "BUY"
        put_long_leg.exchange = "SMART"
        
        # Call spread legs
        call_short_leg = ComboLeg()
        call_short_leg.conId = self.call_short_contract.conId
        call_short_leg.ratio = 1
        call_short_leg.action = "SELL"
        call_short_leg.exchange = "SMART"
        
        call_long_leg = ComboLeg()
        call_long_leg.conId = self.call_long_contract.conId
        call_long_leg.ratio = 1
        call_long_leg.action = "BUY"
        call_long_leg.exchange = "SMART"
        
        contract.comboLegs = [put_short_leg, put_long_leg, call_short_leg, call_long_leg]
        
        self.ic_spread_contract = contract
        
        self.logger.info(f"Iron Condor structure:")
        self.logger.info(f"  Put spread: SELL {self.put_short_contract.strike}P / BUY {self.put_long_contract.strike}P")
        self.logger.info(f"  Call spread: SELL {self.call_short_contract.strike}C / BUY {self.call_long_contract.strike}C")
        
        # Subscribe to spread price
        req_id = self.subscribe_market_data(contract, "101,106")
        self.ic_spread_price_subscription_req_id = req_id
        self.option_market_data_req_ids[req_id] = self.ic_spread_contract
        self.logger.info(f"Subscribed to IC spread price, req_id={req_id}")

    @trace
    def create_order(self):
        """Create and place the iron condor order."""
        if self.ic_spread_price is None:
            self.logger.error("IC spread price not available")
            self.entry_in_progress = False
            return
        
        # Calculate mid price
        mid_price = (self.ic_spread_price[TickTypeEnum.BID] + self.ic_spread_price[TickTypeEnum.ASK]) / 2
        
        # Adjust to respect minTick
        adjusted_lmt_price = round(mid_price / self.ic_spread_min_tick) * self.ic_spread_min_tick
        
        self.logger.info(f"Order pricing - Bid: {self.ic_spread_price[TickTypeEnum.BID]:.2f}, "
                        f"Ask: {self.ic_spread_price[TickTypeEnum.ASK]:.2f}, "
                        f"Mid: {mid_price:.2f}, minTick: {self.ic_spread_min_tick}, "
                        f"Adjusted Limit: {adjusted_lmt_price:.2f}")

        self.logger.info(f"Placing iron condor order...{self.ic_spread_contract}")
        
        order = Order()
        order.action = "BUY"  # BUY the iron condor (selling premium)
        order.tif = "DAY"
        order.totalQuantity = 1
        order.orderType = "LMT"
        order.lmtPrice = adjusted_lmt_price
        
        # Allow legs to be filled independently if needed
        order.smartComboRoutingParams = []
        order.smartComboRoutingParams.append(TagValue("NonGuaranteed", "1"))
        
        order_id = self.place_order(self.ic_spread_contract, order)
        
        if order_id:
            self.logger.info(f"Iron condor order placed: order_id={order_id}")
        else:
            self.logger.error("Failed to place iron condor order")
        
        self.entry_in_progress = False

# Made with Bob
