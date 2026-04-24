from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.fkk.config import FkkConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from src.utils import get_ib_timezone
from ibapi.contract import ComboLeg, Contract, ContractDetails
from ibapi.order import Order
from ibapi.ticktype import TickTypeEnum
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
        self.option_chain_data = {}
        self.option_contracts = []
        self.option_prices = {}
        self.pending_contract_resolutions: list[ContractResolutionStatus] = []
        self.option_market_data_req_ids: dict[int, Contract] = {}
        self.option_market_data_req_ids_lock = threading.Lock()
        self.long_option_market_data_req_ids: dict[int, Contract] = {}
        self.short_contract: Contract = None
        self.long_contract: Contract = None
        self.long_strike: float = None
        self.highest_put_strike: float = None
        self.spread_contract: Contract = None
        self.spread_price_subscription_reg_id = None
        self.spread_price: dict = None

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
        self.timer_manager.add_timer(self.config.bot_name, "stop_confirm_entry_conditions", self.on_timer, trigger_time=trigger_time)

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
            self.on_entry_conditions_are_met()
        else:
            self.logger.info("Entry conditions are not met.")
    
    @trace
    def on_entry_conditions_are_met(self):
        self.resolve_option_chain(
            underlying=self.underlying_contract, 
            callback=lambda res: self.on_option_chain_resolved(
                next((x for x in res if x.get('exchange') == 'CBOE' and x.get('tradingClass') == 'SPXW'), None)
            ),
            timeout=4000
        )

    @trace
    def on_option_chain_resolved(self, result: dict = None):
        if result is not None:
            self.option_chain_data = result
        elif not self.option_chain_data:
            self.logger.error("No option chain data found for CBOE with trading class SPXW.")
            return

        today = date.today()
        if self.config.test_mode:
            if today.weekday() >= 5: # Monday is 0 and Sunday is 6
                today += timedelta(days=7 - today.weekday())

        expiration_str = today.strftime("%Y%m%d")
        self.logger.debug(f"Looking for options with expiration: {expiration_str}")
        
        if expiration_str in self.option_chain_data['expirations']:
            #strikes = list(self.option_chain_data['strikes'])
            # for now, just take 10 strikes around the money
            underlying_price = self.historical_bars[-1].close
            if self.highest_put_strike is None:
                self.highest_put_strike = underlying_price
            put_strikes = sorted([strike for strike in self.option_chain_data["strikes"] if strike < self.highest_put_strike], reverse=True)[:10]
            self.logger.debug(f"Found {len(put_strikes)} strikes for expiration {expiration_str}. Resolving puts.")
            self._resolve_option_contracts(put_strikes, "P", expiration_str)
        else:
            self.logger.error(f"Expiration {expiration_str} not found in option chain. Available expirations: {self.option_chain_data['expirations']}")

    @trace
    def _resolve_option_contracts(self, strikes: set, right: str, expiration: str):
        for strike in strikes:
            contract = Contract()
            contract.symbol = self.underlying_contract.symbol
            contract.secType = "OPT"
            contract.exchange = "SMART"
            contract.currency = self.underlying_contract.currency
            contract.lastTradeDateOrContractMonth = expiration
            contract.strike = strike
            contract.right = right
            
            status = ContractResolutionStatus()
            self.resolve_contracts(search_contract=contract, status=status, callback=self.on_option_contract_resolved)
            self.pending_contract_resolutions.append(status)

    @trace
    def on_option_contract_resolved(self, status: ContractResolutionStatus, result_contracts: list[ContractDetails]):
        if status.complete and len(result_contracts) == 1:
            contract = result_contracts[0].contract
        
            if status in self.pending_contract_resolutions:
                self.pending_contract_resolutions.remove(status)
                # subscribe to market data for the resolved contract
                req_id = self.subscribe_market_data(contract, "101,106") # removed 10,11,12,13,
                self.option_market_data_req_ids[req_id] = contract
                if self.short_contract and self.long_strike == contract.strike:
                    self.long_contract = contract
                    self.logger.info(f"Resolved long contract: {self.long_contract.strike}")
                    self.select_long_contract()
                else:
                    self.option_contracts.append(contract)
        else:
             self.logger.error(f"Failed to resolve option contract: {status.errors}")
             if status in self.pending_contract_resolutions:
                self.pending_contract_resolutions.remove(status)

        if len(self.pending_contract_resolutions) == 0:
            self.logger.info("All option contracts resolutions requests are done.")

    @trace
    def tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        if not delta is None and reqId in self.option_market_data_req_ids:
            with self.option_market_data_req_ids_lock:
                if reqId in self.option_market_data_req_ids:
                    contract = self.option_market_data_req_ids[reqId]
                    self.option_prices[contract.conId] = self.get_cached_price(contract.conId).copy()
                    self.unsubscribe_market_data(contract=contract)
                    del self.option_market_data_req_ids[reqId]

        if len(self.option_market_data_req_ids) == 0:
            self.logger.info("All Option prices and greeks received")
            if not self.short_contract:
                self.select_strike()
            else:
                self.create_spread_contract()
        else:
            self.logger.debug(f"Option prices and greeks not all received, {len(self.option_market_data_req_ids)} remaining")

    @trace
    def select_strike(self):
        self.logger.info("select_strike() ENTRY")
        
        put_contracts = {}

        for c in self.option_contracts:
            price_data = self.option_prices.get(c.conId)
            if price_data is None:
                self.logger.info(f"No price data found for contract {c.conId}")
                continue
            if c.right == "P":
                if 'greeks' in price_data and price_data['greeks'] is not None and 'delta' in price_data['greeks'] and price_data['greeks']['delta'] is not None:
                    put_contracts[price_data['greeks']['delta']] = c
        
        highest_put_delta = -1
        for delta in put_contracts.keys():
            if delta > highest_put_delta:
                highest_put_delta = delta
                self.highest_put_strike = put_contracts[delta].strike
        
        self.logger.debug(f"Highest put delta: {highest_put_delta}")

        if highest_put_delta < (self.config.delta):
            self.on_option_chain_resolved(None)
            return
        
        self.logger.debug("We can select a strike now.")
        # Find the strike with delta closest to configured delta for puts
        closest_put_distance=1
        closest_put_contract=None
        closest_put_delta = None
        for delta, contract in put_contracts.items():
            self.logger.debug(f"Checking put contract with strike {contract.strike} and delta {delta}, comparing with closest_put_delta {(-1 * self.config.delta)}")
            if abs(delta - self.config.delta) < closest_put_distance:                
                closest_put_delta = delta
                closest_put_distance = abs(delta - self.config.delta)
                closest_put_contract = contract

        if closest_put_contract is not None:
            self.logger.info(f"Closest put contract: {closest_put_contract.strike} with delta {closest_put_delta}")
            self.short_contract = closest_put_contract
            self.select_long_contract()
        else:
            self.logger.info("Could not find a suitable put contract.")

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
       self.long_strike = self.short_contract.strike - self.config.width
       # See if we have the contract already
       order_created : bool = False
       for c in self.option_contracts:
           if c.strike == self.long_strike and c.right == "P":
               self.long_contract = c
               self.logger.info(f"Found long contract: {self.long_contract.strike}, creating spread contract")
               self.create_spread_contract()
               order_created = True
       
       if not order_created:
           self.logger.info(f"Could not find long contract, resolving: {self.long_strike}")
           self._resolve_option_contracts([self.long_strike], "P", self.short_contract.lastTradeDateOrContractMonth)
        
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
            self.spread_price = self.get_cached_price(req_id=self.spread_price_subscription_reg_id).copy()

        lmt_price = (self.spread_price[TickType.BID] + self.spread_price[TickType.ASK]) / 2 # TODO

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
        self.place_order(contract, order)
    
    @trace
    def tick_price(self, reqId, tickType, price, attrib):
        self.logger.debug(f"tick_price: reqId={reqId}, tickType={tickType}, price={price}, attrib={attrib}")
        if reqId in self.option_market_data_req_ids:            
            if self.spread_contract == self.option_market_data_req_ids[reqId]:
                self.spread_price = self.get_cached_price(req_id = self.spread_price_subscription_reg_id).copy()
                self.logger.debug(f"spread_price: {spread_price}")
                if spread_price.get(TickTypeEnum.BID) is not None and spread_price.get(TickTypeEnum.ASK) is not None:
                    self.unsubscribe_market_data(self.spread_contract)
                    self.logger.debug(f"removing reqid from list: {reqId}")
                    del self.option_market_data_req_ids[reqId]
                    self.create_order()
        pass
                
            
