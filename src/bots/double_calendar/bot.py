from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.double_calendar.config import DoubleCalendarConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum
from ibapi.order import Order
from datetime import datetime, timedelta
import pytz

class DoubleCalendarBot(BaseBot):
    def __init__(self, config: DoubleCalendarConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.ping_timer_id = None
        self.pinging = False
        
        # test_mode
        self.ping_counter = 0

        self.underlying = None
        self.underlying_contract_candidates = []
        self.underlying_contract_resolution_status = ContractResolutionStatus()
        self.underlying_market_data_req_id = None
        # pending_contract_resolutions is a list of Objects of type ContractResolutionStatus
        self.pending_contract_resolutions: list[ContractResolutionStatus] = []
        self.option_contracts: list[Contract] = []
        self.option_market_data_req_ids: dict[int, Contract] = {}
        self.option_market_data: dict[Contract, str, dict] = {}
        self.option_prices = {}
        self.option_chain_data = []
        self.highest_put_strike = None
        self.lowest_call_strike = None
        self.option_timeout_timer_id = None
        self.entry_order_put_req_id = None
        self.entry_order_call_req_id = None

    def start(self):
        self.logger.info(f"Starting DoubleCalendarBot with config: {self.config.bot_name}")
        if self.config.test_mode:
            tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
            tz = pytz.timezone(tz_name)
            trigger_time = (datetime.now(tz) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
            self.timer_manager.add_timer(self.config.bot_name, "start", self.on_timer, trigger_time=trigger_time)

    def stop(self):
        self.logger.info(f"Stopping DoubleCalendarBot with config: {self.config.bot_name}")

    def tick_price(self, reqId, tickType, price, attrib):
        self.logger.info(f"DoubleCalendarBot received tick: {reqId}, {tickType}, {price}")
        if reqId == self.underlying_market_data_req_id:
            self.underlying_pricedata = self.get_cached_price(self.underlying.conId)
            self.logger.info(f"Underlying market data received: {self.underlying_pricedata}")
            if TickTypeEnum.BID in self.underlying_pricedata and \
               TickTypeEnum.ASK in self.underlying_pricedata and \
               TickTypeEnum.CLOSE in self.underlying_pricedata:
                if self.underlying_pricedata[TickTypeEnum.BID] <= 0 or self.underlying_pricedata[TickTypeEnum.ASK] <= 0:
                    self.underlying_price = self.underlying_pricedata[TickTypeEnum.CLOSE] 
                else:
                    self.underlying_price = (self.underlying_pricedata[TickTypeEnum.BID] + self.underlying_pricedata[TickTypeEnum.ASK]) / 2
                self.logger.info(f"Underlying price: {self.underlying_price}")
                self.unsubscribe_market_data(self.underlying)
                self.underlying_market_data_req_id = None

    def tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        self.logger.info(f"DoubleCalendarBot received tick option computation: {reqId}, {tickType}, {impliedVol}, delta: {delta}, {optPrice}, {pvDividend}, {gamma}, {vega}, {theta}, {undPrice}")
        if not delta is None and reqId in self.option_market_data_req_ids:
            contract = self.option_market_data_req_ids[reqId]
            self.option_prices[contract.conId] = self.get_cached_price(contract.conId).copy()
            self.logger.info(f"cached data: {self.get_cached_price(contract.conId)} stored in {self.option_prices[contract.conId]}")
            self.unsubscribe_market_data(contract=contract)
            self.option_market_data_req_ids.pop(reqId)
        if len(self.option_market_data_req_ids)==0:
            self.logger.info("All Option prices and greeks received")
            self.select_strikes()
        else:
            self.logger.info(f"Option prices and greeks not all received, {len(self.option_market_data_req_ids)} remaining")

    def on_timer(self, event_name: str, event_data: any = None):
        self.logger.info(f"DoubleCalendarBot received timer event: {event_name}")
        if event_name == "start":
            self.test_start()
        elif event_name == "ping":
            self.test_ping()
            if self.pinging:
                # Reschedule the ping timer
                tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
                tz = pytz.timezone(tz_name)
                trigger_time = (datetime.now(tz) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
                self.timer_id = self.timer_manager.add_timer(self.config.bot_name, "ping", self.on_timer, trigger_time=trigger_time)
        elif event_name == "stop":
            self.test_stop()
        elif event_name == "option_price_timeout":
            self.on_option_price_timeout()
        elif event_name == "verify_entry_order":
            self.verify_entry_order(event_data)

    def test_start(self):
        self.logger.info("test_start() called")
        tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
        tz = pytz.timezone(tz_name)
        
        stop_trigger_time = (datetime.now(tz) + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.timer_manager.add_timer(self.config.bot_name, "stop", self.on_timer, trigger_time=stop_trigger_time)

        self.pinging = True
        ping_trigger_time = (datetime.now(tz) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.ping_timer_id = self.timer_manager.add_timer(self.config.bot_name, "ping", self.on_timer, trigger_time=ping_trigger_time)

    def test_ping(self):
        self.logger.info(f"test_ping() called, underlying resolution status: {self.underlying_contract_resolution_status.total_contracts}")
        self.ping_counter += 1
        self.logger.info(f"ping counter: {self.ping_counter}")
        if self.ping_counter == 1:
            underlying = Contract()
            underlying.symbol = "SPX"
            underlying.secType = "IND"
            underlying.exchange = "CBOE"
            underlying.currency = "USD"

            self.resolve_contracts(search_contract=underlying,
            status=self.underlying_contract_resolution_status,
            callback=self.on_underlying_contract_resolved)
        
        if self.ping_counter == 3: 
            self.resolve_option_chain(underlying=self.underlying, 
                                    callback=self.on_option_chain_resolved,
                                    timeout=4000)
            
    def test_stop(self):
        self.logger.info("test_stop() called")
        self.pinging = False
        self.logger.info(f"timer id: {self.ping_timer_id}")
        if self.ping_timer_id:
            self.timer_manager.remove_timer(self.ping_timer_id)
            self.ping_timer_id = None

    def on_underlying_contract_resolved(self, status: ContractResolutionStatus, result_contracts: list[Contract]):
        self.logger.info("on_underlying_contract_resolved() called")
        self.logger.info(f"Underlying contract candidates: {result_contracts}")
        if len(result_contracts) > 0:
            self.underlying = result_contracts[0]
            self.logger.info(f"Selected underlying contract: {self.underlying}")
            self.underlying_market_data_req_id = self.subscribe_market_data(self.underlying)
        else:
            self.logger.error("No underlying contract found")

    def on_option_contract_resolved(self, status: ContractResolutionStatus, result_contracts: list[Contract]):
        self.logger.info("on_option_contract_resolved() called")
        self.logger.info(f"Option contract resolved: {result_contracts}")
        self.logger.info(f"TradingClass {result_contracts[0].tradingClass}")
        if status in self.pending_contract_resolutions:
            self.pending_contract_resolutions.remove(status)
            # subscribe to market data for the resolved contract
            req_id = self.subscribe_market_data(result_contracts[0], "10,11,12,13,101,106")
            self.option_contracts.append(result_contracts[0])
            self.option_market_data_req_ids[req_id] = result_contracts[0]

        if len(self.pending_contract_resolutions) == 0:
            self.logger.info("All option contracts resolved")
        

    def _resolve_option_contracts(self, strikes: list[float], right: str, expiration_str: str):
        for strike in strikes:
            c = Contract()
            c.symbol = "SPX"
            c.secType = "OPT"
            c.exchange = "SMART"
            c.currency = "USD"
            c.lastTradeDateOrContractMonth = expiration_str
            c.strike = strike
            c.right = right

            # Create ContractResolutionStatus object and add it to the dictionary
            status = ContractResolutionStatus()
            self.resolve_contracts(search_contract=c, status=status, callback=self.on_option_contract_resolved)
            self.pending_contract_resolutions.append(status)

    def on_option_chain_resolved(self, option_chain_data: list[dict], resolve_puts: bool = True, resolve_calls: bool = True):
        self.logger.info(f"on_option_chain_resolved() called")
        # keep the option_chain for later use
        self.option_chain_data = option_chain_data

        # calculate two expirations in YYYYMMDD format
        # today +7 days and today +14 days
        today = datetime.now()
        
        expiration1 = today + timedelta(days=5)
        expiration2 = today + timedelta(days=10)
        if expiration2.weekday() == 5:
            expiration2 += timedelta(days=2)
        elif expiration2.weekday() == 6:
            expiration2 += timedelta(days=1)
        expiration1_str = expiration1.strftime("%Y%m%d")
        expiration2_str = expiration2.strftime("%Y%m%d")
        self.logger.info(f"Expiration 1: {expiration1_str}")
        self.logger.info(f"Expiration 2: {expiration2_str}")

        # filter the array of option chains to only include those with the following criteria:
        # - expiration contains expiration1_str or expiration2_str
        # - exchange is SMART
        # - tradingclass is "SPXW"

        filtered_option_chain_data = [option for option in option_chain_data 
                                    if (expiration1_str in option["expirations"] or expiration2_str in option["expirations"]) and 
                                    option["exchange"] == "CBOE" and 
                                    option["tradingClass"] == "SPXW"]
        self.logger.info(f"Filtered option chain data: {filtered_option_chain_data}")

        self.option_contract_resolutions = {}
        if resolve_puts:
            self.logger.info(f"Resolving put contracts")
            # For put legs, resolve contracts for all strikes for both expirations which are lower than the current SPX price
            # sort the list of strikes
            # the list should have at most 10 entries
            if self.highest_put_strike is None:
                self.highest_put_strike = self.underlying_price
            put_strikes = sorted([strike for strike in filtered_option_chain_data[0]["strikes"] if strike < self.highest_put_strike], reverse=True)[:10]
            self.logger.info(f"Put Strikes: {put_strikes}")
            self.highest_put_strike = put_strikes[-1]
            self._resolve_option_contracts(put_strikes, "P", expiration1_str)

        if resolve_calls:
            self.logger.info(f"Resolving call contracts")
            # For call legs, resolve contracts for all strikes for both expirations which are higher than the current SPX price
            # sort the list of strikes
            # the list should have at most 10 entries
            if self.lowest_call_strike is None:
                self.lowest_call_strike = self.underlying_price
            call_strikes = sorted([strike for strike in filtered_option_chain_data[0]["strikes"] if strike > self.lowest_call_strike], reverse=False)[:10]
            self.logger.info(f"Call Strikes: {call_strikes}")
            self.lowest_call_strike = call_strikes[-1]
            self._resolve_option_contracts(call_strikes, "C", expiration1_str)

        # schedule a timer as timeout of option price retrieval for 5 seconds
        tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
        tz = pytz.timezone(tz_name)
        timeout_trigger_time = (datetime.now(tz) + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.option_timeout_timer_id = self.timer_manager.add_timer(self.config.bot_name, "option_price_timeout", self.on_timer, trigger_time=timeout_trigger_time)
         

    def select_strikes(self):
        self.logger.info("select_strikes() ENTRY")
        # cancel the timeout timer
        self.timer_manager.remove_timer(self.option_timeout_timer_id)

        # Create a data structure that stores the contract for each delta for puts and another one for calls
        put_contracts = {}
        call_contracts = {}

        for c in self.option_contracts:
            price_data = self.option_prices.get(c.conId)
            if price_data is None:
                self.logger.info(f"No price data found for contract {c.conId}")
                continue
            if c.right == "P":
                put_contracts[price_data['greeks']['delta']] = c
            else:
                call_contracts[price_data['greeks']['delta']] = c
        
        # find lowest delta for put strikes, put delta should be negative
        highest_put_delta = -1
        lowest_call_delta = 1
        for delta in put_contracts.keys():
            if delta > highest_put_delta:
                highest_put_delta = delta
        for delta in call_contracts.keys():
            if delta < lowest_call_delta:
                lowest_call_delta = delta
        self.logger.info(f"Highest put delta: {highest_put_delta}")
        self.logger.info(f"Lowest call delta: {lowest_call_delta}")

        resolve_puts = highest_put_delta < -0.14
        resolve_calls = lowest_call_delta > 0.14

        if resolve_puts or resolve_calls:
            self.on_option_chain_resolved(self.option_chain_data, resolve_puts=resolve_puts, resolve_calls=resolve_calls)
            return
        
        self.logger.info("We can select a strike now.")
        # Find the strike with delta closest to -0.16 for puts and 0.16 for calls
        closest_put_distance=1
        closest_put_contract=None
        for delta, contract in put_contracts.items():
            if abs(delta - (-0.16)) < closest_put_distance:
                closest_put_delta = delta
                closest_put_distance = abs(delta - (-0.16))
                closest_put_contract = contract
        closest_call_distance=1
        closest_call_contract=None
        for delta, contract in call_contracts.items():
            if abs(delta - 0.16) < closest_call_distance:
                closest_call_delta = delta
                closest_call_distance = abs(delta - 0.16)
                closest_call_contract = contract
        self.logger.info(f"Closest put contract: {closest_put_contract.strike} with delta {closest_put_delta}")
        self.logger.info(f"Closest call contract: {closest_call_contract.strike} with delta {closest_call_delta}")

        self.place_entry_order(closest_put_contract)
        self.place_entry_order(closest_call_contract)
        

    def place_entry_order(self, contract: Contract):
        order = Order()
        order.action = "SELL"
        order.orderType = "LMT"
        order.totalQuantity = 1
        # get bid/ask from self.option_prices
        price_data = self.option_prices.get(contract.conId)
        if price_data:
            bid = price_data.get(TickTypeEnum.BID)
            ask = price_data.get(TickTypeEnum.ASK)
            if bid is not None and ask is not None and bid > 0 and ask > 0:
                order.lmtPrice = round((bid + ask) / 2, 2)
            else:
                self.logger.error(f"Cannot place order for {contract.symbol} {contract.right} {contract.strike}, bid/ask not available in {price_data}.")
                return
        else:
            self.logger.error(f"Cannot place order for {contract.symbol} {contract.right} {contract.strike}, price data not available.")
            return

        if contract.right == "P":
            order.orderRef = "entry_put"
        else:
            order.orderRef = "entry_call"

        req_id = self.place_order(contract, order)
        if req_id:
            if contract.right == "P":
                self.entry_order_put_req_id = req_id
            else:
                self.entry_order_call_req_id = req_id

            tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
            tz = pytz.timezone(tz_name)
            trigger_time = (datetime.now(tz) + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
            self.timer_manager.add_timer(self.config.bot_name, "verify_entry_order", self.on_timer, trigger_time=trigger_time, event_data=req_id)
            self.logger.info(f"Placed entry order for {contract.right} with reqId: {req_id}")

    def verify_entry_order(self, req_id: int):
        self.logger.info(f"Verifying entry order for reqId: {req_id}")
        # Logic to verify and adapt order will be added later by the user.

    def on_option_price_timeout(self):
        self.logger.info("on_option_price_timeout() called")
        self.logger.info(f"Option prices and greeks not all received, {len(self.option_market_data_req_ids)} remaining")
        for req_id in self.option_market_data_req_ids:
            # TODO: do I need to repeat?
            self.unsubscribe_market_data(self.option_market_data_req_ids[req_id])
        self.option_market_data_req_ids = {}
        self.select_strikes()
