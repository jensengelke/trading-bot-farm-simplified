from enum import Enum
from pydantic import BaseModel

class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class ConfigBase(BaseModel):
    bot_name: str
    bot_type: str
    log_level: LogLevel = LogLevel.INFO
