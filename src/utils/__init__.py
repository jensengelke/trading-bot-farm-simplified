"""Utility modules for the trading bot framework."""

import functools
import logging
from zoneinfo import ZoneInfo

system_logger = logging.getLogger("system_debug")

def trace(func):
    """
    Decorator that logs entry and exit of the decorated function at DEBUG level.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        class_name = ""
        log_args = args
        # Crude check for an instance method. If the first arg has the same name as the function,
        # it's probably an instance method.
        if args and hasattr(args[0], func.__name__):
            class_name = f"{args[0].__class__.__name__}."
            log_args = args[1:]
        
        logger = system_logger

        if logger:
            logger.debug(f"ENTRY: {class_name}{func.__name__} | args: {log_args} kwargs: {kwargs}")

        try:
            result = func(*args, **kwargs)
            if logger:
                logger.debug(f"EXIT : {class_name}{func.__name__} | returned: {result}")
            return result
        except Exception as e:
            if logger:
                logger.debug(f"EXIT (EXCEPTION): {class_name}{func.__name__} | raised {type(e).__name__}: {e}")
            raise
    return wrapper

@trace
def get_ib_timezone(tz_string):
    # Map common IB legacy strings to IANA standards if needed
    mapping = {
        "EST5EDT": "America/New_York",
        "CST6CDT": "America/Chicago",
        "MST7MDT": "America/Denver",
        "PST8PDT": "America/Los_Angeles",
        "US/Central": "America/Chicago",
        "MET": "Europe/Berlin", # Middle European Time
    }
    tz_name = mapping.get(tz_string, tz_string)
    return ZoneInfo(tz_name)

def is_valid_price(val: float) -> bool:
    """Check if a price value is valid (non-None, positive, and finite)."""
    return val is not None and 0 < val < 1.797e308

__all__ = ['trace', 'get_ib_timezone', 'options_finder', 'is_valid_price']

# Made with Bob
