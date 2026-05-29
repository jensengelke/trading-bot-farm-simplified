from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.ping_bot.config import PingBotConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from datetime import datetime, timedelta
import pytz
import threading

class PingBotBot(BaseBot):
    def __init__(self, config: PingBotConfig, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.ping_timer_id = None
        self.pinging = False
        self.ping_counter = 0

    def start(self):
        self.logger.info(f"Starting PingBot with config: {self.config.bot_name}")
        tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
        tz = pytz.timezone(tz_name)
        start_in_seconds = self.config.start_in_seconds if hasattr(self.config, "start_in_seconds") else 10
        self.logger.info(f"start_in_seconds: {start_in_seconds}")
        trigger_datetime = datetime.now(tz) + timedelta(seconds=start_in_seconds)
        self.scheduled_entry_time = trigger_datetime
        trigger_time = trigger_datetime.strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
        self.timer_manager.add_timer(self.config.bot_name, "start", self.on_timer, trigger_time=trigger_time)

    def stop(self):
        self.logger.info(f"Stopping PingBot with config: {self.config.bot_name}")

    def on_timer(self, event_name: str, event_data: any = None):
        self.logger.info(f"Received timer event: {event_name}")
        if event_name == "start":
            if self.is_entry_timeout_exceeded():
                self.logger.info("Timeout exceeded. Rescheduling for tomorrow.")
                self.start()
                return
            self.test_start()
        elif event_name == "ping":
            self.test_ping()
            if self.pinging:
                # Reschedule the ping timer
                tz_name = self.config.timezone if hasattr(self.config, "timezone") else "UTC"
                tz = pytz.timezone(tz_name)
                ping_interval_seconds = self.config.ping_interval_seconds if hasattr(self.config, "ping_interval_seconds") else 5
                trigger_time = (datetime.now(tz) + timedelta(seconds=ping_interval_seconds)).strftime("%Y-%m-%d %H:%M:%S") + f" {tz_name}"
                self.timer_id = self.timer_manager.add_timer(self.config.bot_name, "ping", self.on_timer, trigger_time=trigger_time)
                self.logger.info(f"Rescheduled ping timer, next ping at {trigger_time}")
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
        self.logger.info(f"test_ping() called")
        self.ping_counter += 1
        stop_after_pings = self.config.stop_after_pings if hasattr(self.config, "stop_after_pings") else 10
        if self.ping_counter >= stop_after_pings:
            self.on_timer("stop")
        self.logger.info(f"ping counter: {self.ping_counter}")
            
    def test_stop(self):
        self.logger.info("test_stop() called")
        self.pinging = False
        self.logger.info(f"timer id: {self.ping_timer_id}")
        if self.ping_timer_id:
            self.timer_manager.remove_timer(self.ping_timer_id)
            self.ping_timer_id = None
