from src.bots.config_base import ConfigBase
from typing import List, Optional

class ChudflyConfig(ConfigBase):
    """Configuration for Chudfly Bot."""
    
    # Timezone and scheduling
    timezone: str = "America/New_York"
    observation_start_time: str = "09:45:00"
    observation_end_time: str = "12:30:00"
    market_open_time: str = "09:30:00"
    open_range_end_time: str = "09:45:00"
    
    # Strategy parameters
    sma_period: int = 3
    max_gap_up_pct: float = 1.0
    max_gap_down_pct: float = 1.0
    
    # Position parameters
    dte: int = 0
    lower_long_leg_delta: float = 0.5
    short_leg_offset: int = 35
    upper_long_leg_offset: int = 35
    stop_loss_pct: float = 80.0
    
    # Days to trade
    trade_days: List[str] = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    
    # Test mode
    test_mode: bool = False
    # entry_timeout_seconds is ignored in Chudfly implementation as we have observation_end_time
