from src.bots.config_base import ConfigBase

class IcConfig(ConfigBase):
    """Configuration for IC (Iron Condor) Bot."""
    
    # Timezone and scheduling
    timezone: str = "America/New_York"
    entry_time: str = "09:45:00"
    entry_timeout_seconds: int = 300 # 5 minutes
    
    # Days to expiration
    dte: int = 14
    
    # Put spread configuration
    put_short_delta: float = -0.25
    put_width: int = 10  # Points offset for long put
    
    # Call spread configuration
    call_short_delta: float = 0.65
    call_width: int = 5  # Points offset for long call
    
    # Test mode
    test_mode: bool = False
    
    # Take Profit configuration
    take_profit_percent: float = 10.0  # Percentage of credit to keep
    rounding_step: float = 0.1        # Round TP price to this multiple
    tp_tif: str = "GTC"               # Time in force for TP order

# Made with Bob
