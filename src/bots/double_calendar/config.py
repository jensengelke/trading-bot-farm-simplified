from src.bots.config_base import ConfigBase

class DoubleCalendarConfig(ConfigBase):
    test_mode: bool = False
    timezone: str = "America/New_York"
    entry_timeout_seconds: int = 3600 # 1 hour
