from src.bots.config_base import ConfigBase

class PingBotConfig(ConfigBase):
    timezone: str = "UTC"
    start_in_seconds: int = 1
    ping_interval_seconds: int = 5
    stop_after_pings: int = 10
