from datetime import datetime
from zoneinfo import ZoneInfo

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

def parse_execution_time(time_str):
    print(f"Parsing: '{time_str}'")
    try:
        parts = time_str.split()
        if len(parts) >= 2:
            dt_str = f"{parts[0]} {parts[1]}"
            exec_time = datetime.strptime(dt_str, "%Y%m%d %H:%M:%S")
            if len(parts) >= 3:
                tz_str = " ".join(parts[2:])
                try:
                    tz = get_ib_timezone(tz_str)
                    exec_time = exec_time.replace(tzinfo=tz)
                except Exception as tz_e:
                    print(f"  Could not resolve timezone '{tz_str}': {tz_e}")
        else:
            exec_time = datetime.strptime(time_str, "%Y%m%d")
        print(f"  Result: {exec_time} (tzinfo: {exec_time.tzinfo})")
        return exec_time
    except Exception as e:
        print(f"  Failed: {e}")
        return datetime.now()

# Test cases from log
test_strings = [
    "20260508 02:00:37 America/New_York",
    "20260508 01:00:37 US/Central",
    "20260508", # Date only
    "20260508 12:00:00" # Date and time, no TZ
]

for s in test_strings:
    parse_execution_time(s)
