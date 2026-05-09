from src.bots.config_base import ConfigBase

class IcConfig(ConfigBase):
    """Configuration for IC (Iron Condor) Bot."""
    
    # Timezone and scheduling
    timezone: str = "America/New_York"
    entry_time: str = "09:45:00"
    
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

# Made with Bob
