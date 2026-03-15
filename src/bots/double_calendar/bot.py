from src.bots.base_bot import BaseBot
from src.bots.double_calendar.config import DoubleCalendarConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from datetime import datetime, timedelta
import pytz

class DoubleCalendarBot(BaseBot):
    def __init__(self, config: DoubleCalendarConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.ping_timer_id = None

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
        if event_name == "start":
            self.test_start()
        elif event_name == "ping":
            self.test_ping()
            # Reschedule the ping timer
            tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
            tz = pytz.timezone(tz_name)
            trigger_time = (datetime.now(tz) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
            self.ping_timer_id = self.timer_manager.add_timer(self.config.bot_name, "ping", self.on_timer, trigger_time=trigger_time)
        elif event_name == "stop":
            self.test_stop()

    def test_start(self):
        self.logger.info("test_start() called")
        tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
        tz = pytz.timezone(tz_name)
        
        stop_trigger_time = (datetime.now(tz) + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.timer_manager.add_timer(self.config.bot_name, "stop", self.on_timer, trigger_time=stop_trigger_time)

        ping_trigger_time = (datetime.now(tz) + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.ping_timer_id = self.timer_manager.add_timer(self.config.bot_name, "ping", self.on_timer, trigger_time=ping_trigger_time)

    def test_ping(self):
        self.logger.info("test_ping() called")

    def test_stop(self):
        self.logger.info("test_stop() called")
        if self.ping_timer_id:
            self.timer_manager.remove_timer(self.ping_timer_id)
            self.ping_timer_id = None
