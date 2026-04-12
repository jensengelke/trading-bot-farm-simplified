from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.fkk.config import FkkConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import Contract, ContractDetails
from datetime import datetime, timedelta, date
import pytz
import threading

class FkkBot(BaseBot):
    def __init__(self, config: FkkConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
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

    def stop(self):
        self.logger.info(f"Stopping FkkBot with config: {self.config.bot_name}")

    def on_timer(self, event_name: str, event_data: any = None):
        self.logger.info(f"Received timer event: {event_name}")
        if event_name == "confirm_entry_conditions":
            self.on_confirm_entry_conditions()
        elif event_name == "stop_confirm_entry_conditions":
            self.on_stop_confirm_entry_conditions()
        elif event_name == "stop":
            self.test_stop()

    def on_confirm_entry_conditions(self):
        self.logger.info("on_confirm_entry_conditions() called")
        
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
           
    def on_confirm_entry_conditions_on_underlying_contract_resolved(self,status: ContractResolutionStatus, result_contracts: list[ContractDetails]):
        self.logger.info("on_confirm_entry_conditions_on_underlying_contract_resolved() called")
        self.logger.info(f"status: {status}")
        self.logger.info(f"result_contracts: {result_contracts} ({len(result_contracts)})")
        if len(status.errors) == 0 and len(result_contracts) == 1 and status.complete:
            self.underlying_contract_details = result_contracts[0]
            self.underlying_contract = self.underlying_contract_details.contract
            self.logger.info(f"Underlying contract resolved: {self.underlying_contract}")
            self.logger.info(f"hours: {self.underlying_contract_details.tradingHours}")
            self.logger.info(f"liquid hours: {self.underlying_contract_details.liquidHours}")
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

    def on_historical_data_end(self, bars):
        self.logger.info(f"Historical data received: {bars}")
        self.historical_bars = bars
        self.historical_data_req_id = None
        self.evaluate_entry_conditions()

    def on_historical_data_update(self, bar):
        # This callback is invoked about once every 5 seconds when keepUpToDate is active after on historical_data_end() has retrieved the initial set of bars 
        self.logger.info(f"Historical data update received: {bar}")
        for i, b in enumerate(self.historical_bars):
            if b.date == bar.date:
                self.historical_bars[i] = bar
                break
        self.evaluate_entry_conditions()

    def evaluate_entry_conditions(self):
        self.logger.info("Evaluating entry conditions...")
        if len(self.historical_bars) < self.config.sma_period:
            self.logger.info("Not enough historical data to evaluate entry conditions.")
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
    
    def on_entry_conditions_are_met(self):
        self.logger.info("on_entry_conditions_are_met() called")
        self.resolve_option_chain(underlying=self.underlying_contract, callback=self.on_option_chain_resolved,timeout=4000)

    def on_option_chain_resolved(self, result: dict):
        self.logger.info("on_option_chain_resolved() called")
        
        # Filter for CBOE and SPXW
        cboe_data = None
        for exchange_data in result:
            if exchange_data['exchange'] == 'CBOE' and exchange_data['tradingClass'] == 'SPXW':
                cboe_data = exchange_data
                break
        
        if not cboe_data:
            self.logger.error("No option chain data found for CBOE with trading class SPXW.")
            return

        self.option_chain_data = cboe_data

        today = date.today()
        if self.config.test_mode:
            if today.weekday() >= 5: # Monday is 0 and Sunday is 6
                today += timedelta(days=7 - today.weekday())

        expiration_str = today.strftime("%Y%m%d")
        self.logger.info(f"Looking for options with expiration: {expiration_str}")

        if expiration_str in self.option_chain_data['expirations']:
            strikes = list(self.option_chain_data['strikes'])
            # for now, just take 10 strikes around the money
            underlying_price = self.historical_bars[-1].close
            strikes.sort(key=lambda x: abs(x - underlying_price))
            put_strikes = strikes[:10]
            self.logger.info(f"Found {len(put_strikes)} strikes for expiration {expiration_str}. Resolving puts.")
            self._resolve_option_contracts(put_strikes, "P", expiration_str)
        else:
            self.logger.error(f"Expiration {expiration_str} not found in option chain. Available expirations: {self.option_chain_data['expirations']}")

    def _resolve_option_contracts(self, strikes: set, right: str, expiration: str):
        self.logger.info(f"_resolve_option_contracts() ENTRY with {len(strikes)} strikes, right: {right}, expiration: {expiration}")
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

    def on_option_contract_resolved(self, status: ContractResolutionStatus, result_contracts: list[ContractDetails]):
        self.logger.info("on_option_contract_resolved() called")
        if status.complete and len(result_contracts) == 1:
            contract = result_contracts[0].contract
            self.logger.info(f"Option contract resolved: {contract}")

            if status in self.pending_contract_resolutions:
                self.pending_contract_resolutions.remove(status)
                # subscribe to market data for the resolved contract
                req_id = self.subscribe_market_data(contract, "10,11,12,13,101,106")
                self.option_contracts.append(contract)
                self.option_market_data_req_ids[req_id] = contract
        else:
             self.logger.error(f"Failed to resolve option contract: {status.errors}")
             if status in self.pending_contract_resolutions:
                self.pending_contract_resolutions.remove(status)

        if len(self.pending_contract_resolutions) == 0:
            self.logger.info("All option contracts resolutions requests are done.")

    def tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        self.logger.info(f"FkkBot received tick option computation: {reqId}, {tickType}, {impliedVol}, delta: {delta}, {optPrice}, {pvDividend}, {gamma}, {vega}, {theta}, {undPrice}")
        if not delta is None and reqId in self.option_market_data_req_ids:
            with self.option_market_data_req_ids_lock:
                if reqId in self.option_market_data_req_ids:
                    contract = self.option_market_data_req_ids[reqId]
                    self.option_prices[contract.conId] = self.get_cached_price(contract.conId).copy()
                    self.logger.info(f"cached data: {self.get_cached_price(contract.conId)} stored in {self.option_prices[contract.conId]}")
                    self.unsubscribe_market_data(contract=contract)
                    del self.option_market_data_req_ids[reqId]

        if len(self.option_market_data_req_ids)==0:
            self.logger.info("All Option prices and greeks received")
            self.select_strike()
        else:
            self.logger.info(f"Option prices and greeks not all received, {len(self.option_market_data_req_ids)} remaining")

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
        
        self.logger.info(f"Highest put delta: {highest_put_delta}")

        if highest_put_delta < (-1 * self.config.delta):
             self.on_option_chain_resolved(self.option_chain_data)
             return
        
        self.logger.info("We can select a strike now.")
        # Find the strike with delta closest to -0.16 for puts
        closest_put_distance=1
        closest_put_contract=None
        closest_put_delta = None
        for delta, contract in put_contracts.items():
            if abs(delta - (self.config.delta)) < closest_put_distance:
                closest_put_delta = delta
                closest_put_distance = abs(delta - (-1 * self.config.delta))
                closest_put_contract = contract

        if closest_put_contract is not None:
            self.logger.info(f"Closest put contract: {closest_put_contract.strike} with delta {closest_put_delta}")
        else:
            self.logger.info("Could not find a suitable put contract.")

    def on_stop_confirm_entry_conditions(self):
        self.logger.info("on_stop_confirm_entry_conditions() called")
        if self.historical_data_req_id is not None:
            self.cancel_historical_data(self.historical_data_req_id)
            req_id = self.historical_data_req_id
            self.historical_data_req_id = None
            self.logger.info(f"Cancelled historical data request with req_id: {req_id}")
