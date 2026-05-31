from src.bots.config_base import ConfigBase

class FkkConfig(ConfigBase):
    timezone: str = "America/New_York"
    entry_time: str = "14:15"
    entry_timeout_seconds: int = 300 # 5 minutes
    delta: float = -0.35
    width: int = 5
    sma_period: int = 5
    intraday_move_pct: float = 0.3
    test_mode: bool = False
    force_open_position: bool = False
    trade_days: list[str] = ["Tue", "Wed", "Thu", "Fri"]
