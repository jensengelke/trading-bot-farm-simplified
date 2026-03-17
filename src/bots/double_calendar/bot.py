from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.double_calendar.config import DoubleCalendarConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import Contract
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

    def start(self):
        self.logger.info(f"Starting DoubleCalendarBot with config: {self.config.bot_name}")
        if self.config.test_mode:
            tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
            tz = pytz.timezone(tz_name)
            trigger_time = (datetime.now(tz) + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
            self.timer_manager.add_timer(self.config.bot_name, "start", self.on_timer, trigger_time=trigger_time)

    def stop(self):
        self.logger.info(f"Stopping DoubleCalendarBot with config: {self.config.bot_name}")

    def tick_price(self, reqId, tickType, price, attrib):
        self.logger.info(f"DoubleCalendarBot received tick: {reqId}, {tickType}, {price}")

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
        if self.ping_counter == 2:
            underlying = Contract()
            underlying.symbol = "SPX"
            underlying.secType = "IND"
            underlying.exchange = "CBOE"
            underlying.currency = "USD"

            self.resolve_contracts(search_contract=underlying,
            status=self.underlying_contract_resolution_status,
            callback=self.on_underlying_contract_resolved)
        
        if self.ping_counter == 5: 
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

    def on_underlying_contract_resolved(self, result_contracts: list[Contract]):
        self.logger.info("on_underlying_contract_resolved() called")
        self.logger.info(f"Underlying contract candidates: {result_contracts}")
        if len(result_contracts) > 0:
            self.underlying = result_contracts[0]
            self.logger.info(f"Selected underlying contract: {self.underlying}")
            self.subscribe_market_date(self.underlying)
        else:
            self.logger.error("No underlying contract found")

    def on_option_chain_resolved(self, option_chain_data: list[dict]):
        self.logger.info("on_option_chain_resolved() called")
        # Filter the array of option chains to only include those with the following criteria:
        # - exchange is SMART
        # - tradingclass is "SPXW"
        filtered_option_chain_data = [option for option in option_chain_data if option["exchange"] == "SMART" and option["tradingClass"] == "SPXW"]
        self.logger.info(f"Filtered option chain data: {filtered_option_chain_data}")

        # calculate two expirations in YYYYMMDD format
        # today +7 days and today +14 days
        today = datetime.now()
        expiration1 = today + timedelta(days=7)
        expiration2 = today + timedelta(days=14)
        expiration1_str = expiration1.strftime("%Y%m%d")
        expiration2_str = expiration2.strftime("%Y%m%d")
        self.logger.info(f"Expiration 1: {expiration1_str}")
        self.logger.info(f"Expiration 2: {expiration2_str}")

        # filter the array of option chains to only include those with the following criteria:
        # - expiration is expiration1_str or expiration2_str
        filtered_option_chain_data = [option for option in filtered_option_chain_data if option["expirations"] == expiration1_str or option["expiration"] == expiration2_str]
        self.logger.info(f"Filtered option chain data: {filtered_option_chain_data}")

        # For put legs, resolve contracts for all strikes for both expirations which are lower than the current SPX price
        
