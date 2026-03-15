import threading
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional, Callable
from croniter import croniter
import pytz

logger = logging.getLogger(__name__)

class TimerManager:
    """
    Manages scheduled timers for bots with support for one-time and recurring (CRON) timers.
    Handles timezone-aware scheduling.
    """
    
    def __init__(self):
        self.timers: Dict[str, Dict[str, Any]] = {}  # timer_id -> timer_info
        self.lock = threading.RLock()
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False
        self._timer_counter = 0
        
    def start(self):
        """Start the timer worker thread."""
        if self.running:
            logger.warning("TimerManager is already running")
            return
            
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="TimerWorker")
        self.worker_thread.start()
        logger.info("TimerManager started")
        
    def stop(self):
        """Stop the timer worker thread."""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("TimerManager stopped")
        
    def add_timer(
        self,
        bot_id: str,
        event_name: str,
        callback: Callable[[str, Any], None],
        event_data: Any = None,
        trigger_time: Optional[str] = None,
        cron_expression: Optional[str] = None
    ) -> str:
        """
        Add a timer for a bot.
        
        Args:
            bot_id: The bot instance identifier
            event_name: Human-readable event name
            callback: Function to call when timer fires (receives event_name, event_data)
            event_data: Optional data to pass to the callback
            trigger_time: One-time trigger in format "YYYY-MM-DD HH:MM:SS TIMEZONE" (e.g., "2025-12-23 14:54:30 US/Central")
            cron_expression: CRON expression for recurring timers (e.g., "0 9 * * 1-5" for weekdays at 9am)
            
        Returns:
            timer_id: Unique identifier for this timer
            
        Raises:
            ValueError: If neither or both trigger_time and cron_expression are provided
        """
        # Validate inputs
        if (trigger_time is None and cron_expression is None) or \
           (trigger_time is not None and cron_expression is not None):
            raise ValueError("Exactly one of 'trigger_time' or 'cron_expression' must be provided")
        
        with self.lock:
            self._timer_counter += 1
            timer_id = f"{bot_id}_timer_{self._timer_counter}"
            
            timer_info = {
                "timer_id": timer_id,
                "bot_id": bot_id,
                "event_name": event_name,
                "callback": callback,
                "event_data": event_data,
                "trigger_time": trigger_time,
                "cron_expression": cron_expression,
                "next_trigger": None,
                "timezone": None,
                "cron_iter": None
            }
            
            # Parse and validate trigger_time or cron_expression
            if trigger_time:
                timer_info["next_trigger"], timer_info["timezone"] = self._parse_trigger_time(trigger_time)
                logger.info(f"One-time timer '{timer_id}' scheduled for {timer_info['next_trigger']} ({event_name})")
                
            elif cron_expression:
                # For CRON, we need a timezone. Default to UTC if not specified in event_data
                # Users can pass timezone in event_data as {'timezone': 'US/Eastern', ...}
                tz_name = "UTC"
                if isinstance(event_data, dict) and "timezone" in event_data:
                    tz_name = event_data["timezone"]
                
                try:
                    tz = pytz.timezone(tz_name)
                    timer_info["timezone"] = tz
                    timer_info["cron_iter"] = croniter(cron_expression, datetime.now(tz))
                    timer_info["next_trigger"] = timer_info["cron_iter"].get_next(datetime)
                    logger.info(f"Recurring timer '{timer_id}' scheduled with CRON '{cron_expression}' in {tz_name} ({event_name})")
                except Exception as e:
                    raise ValueError(f"Invalid CRON expression or timezone: {e}")
            
            self.timers[timer_id] = timer_info
            return timer_id
    
    def remove_timer(self, timer_id: str):
        """Remove a timer by its ID."""
        logger.info(f"Removing timer_id: {timer_id} from timers: {self.timers}")
        with self.lock:
            if timer_id in self.timers:
                del self.timers[timer_id]
                logger.info(f"Timer '{timer_id}' removed")
                
    def remove_bot_timers(self, bot_id: str):
        """Remove all timers for a specific bot."""
        with self.lock:
            to_remove = [tid for tid, info in self.timers.items() if info["bot_id"] == bot_id]
            for tid in to_remove:
                del self.timers[tid]
            if to_remove:
                logger.info(f"Removed {len(to_remove)} timer(s) for bot '{bot_id}'")
    
    def _parse_trigger_time(self, trigger_time: str) -> tuple:
        """
        Parse a trigger time string with timezone.
        
        Format: "YYYY-MM-DD HH:MM:SS TIMEZONE"
        Example: "2025-12-23 14:54:30 US/Central"
        
        Returns:
            (datetime, timezone): Timezone-aware datetime and timezone object
        """
        parts = trigger_time.strip().rsplit(" ", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid trigger_time format: '{trigger_time}'. "
                "Expected format: 'YYYY-MM-DD HH:MM:SS TIMEZONE' (e.g., '2025-12-23 14:54:30 US/Central')"
            )
        
        time_str, tz_name = parts
        
        try:
            tz = pytz.timezone(tz_name)
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValueError(f"Unknown timezone: '{tz_name}'. Use standard timezone names like 'US/Eastern', 'US/Central', 'Europe/London', etc.")
        
        try:
            # Parse the datetime string
            naive_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            # Localize to the specified timezone
            aware_dt = tz.localize(naive_dt)
            return aware_dt, tz
        except ValueError as e:
            raise ValueError(f"Invalid datetime format in '{time_str}': {e}")
    
    def _worker_loop(self):
        """Background worker that checks and fires timers."""
        while self.running:
            try:
                now = datetime.now(pytz.UTC)
                timers_to_fire = []
                
                with self.lock:
                    for timer_id, timer_info in list(self.timers.items()):
                        next_trigger = timer_info["next_trigger"]
                        
                        if next_trigger and now >= next_trigger:
                            timers_to_fire.append(timer_info.copy())
                            
                            # Handle recurring vs one-time
                            if timer_info["cron_iter"]:
                                # Recurring: schedule next occurrence
                                timer_info["next_trigger"] = timer_info["cron_iter"].get_next(datetime)
                            else:
                                # One-time: remove after firing
                                del self.timers[timer_id]
                
                # Fire timers outside the lock to avoid blocking
                for timer_info in timers_to_fire:
                    try:
                        logger.info(f"Firing timer '{timer_info['timer_id']}' for event '{timer_info['event_name']}'")
                        timer_info["callback"](timer_info["event_name"], timer_info["event_data"])
                    except Exception as e:
                        logger.error(f"Error firing timer '{timer_info['timer_id']}': {e}", exc_info=True)
                
                # Sleep for 1 second before next check
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in timer worker loop: {e}", exc_info=True)
                time.sleep(1)
