from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.fkk.config import FkkConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import Contract, ContractDetails
from datetime import datetime, timedelta
import pytz
import threading

class FkkBot(BaseBot):
    def __init__(self, config: FkkConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.underlying_contract: Contract = None
        self.underlying_contract_resolution_status: ContractResolutionStatus = None
        self.historical_bars = []
        self.historical_data_req_id: int = None

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
            #self.resolve_option_chain(underlying=self.underlying_contract, callback=self.on_option_chain_resolved, timeout=4000)
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
        if close > sma and close > (1 + self.config.intraday_move_pct / 100) * open_price:
            self.logger.info("Entry conditions are met.")
        else:
            self.logger.info("Entry conditions are not met.")
    
    def on_stop_confirm_entry_conditions(self):
        self.logger.info("on_stop_confirm_entry_conditions() called")
        if self.historical_data_req_id is not None:
            self.cancel_historical_data(self.historical_data_req_id)
            req_id = self.historical_data_req_id
            self.historical_data_req_id = None
            self.logger.info(f"Cancelled historical data request with req_id: {req_id}")
