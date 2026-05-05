# Bot Development Guide

This guide walks you through creating custom trading bots for the Trading Bot Farm Framework.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Bot Structure](#bot-structure)
3. [Configuration](#configuration)
4. [Core Concepts](#core-concepts)
5. [Common Patterns](#common-patterns)
6. [Testing](#testing)
7. [Deployment](#deployment)

## Quick Start

### Step 1: Create Bot Directory

Create a new directory under [`src/bots/`](../src/bots/) for your bot:

```
src/bots/my_bot/
├── __init__.py
├── bot.py
├── config.py
└── README.md (optional)
```

### Step 2: Define Configuration

Create [`config.py`](../src/bots/my_bot/config.py):

```python
from src.bots.config_base import ConfigBase

class MyBotConfig(ConfigBase):
    """Configuration for MyBot."""
    
    # Required fields (inherited from ConfigBase)
    # - bot_name: str
    # - bot_type: str
    # - log_level: LogLevel
    
    # Add your custom configuration fields
    timezone: str = "America/New_York"
    entry_time: str = "09:30:00"
    target_symbol: str = "SPY"
    position_size: int = 100
    test_mode: bool = False
```

### Step 3: Implement Bot Class

Create [`bot.py`](../src/bots/my_bot/bot.py):

```python
from src.bots.base_bot import BaseBot
from src.bots.my_bot.config import MyBotConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from ibapi.contract import Contract
from datetime import datetime, timedelta
import pytz

class MyBot(BaseBot):
    def __init__(self, config: MyBotConfig, ib_connection: IBConnection, 
                 timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        
        # Initialize bot-specific state
        self.position = None
        self.target_contract = None
    
    def start(self):
        """Called when bot is started."""
        self.logger.info(f"Starting MyBot: {self.config.bot_name}")
        
        # Schedule entry check
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        entry_time = datetime.strptime(self.config.entry_time, "%H:%M:%S")
        entry_datetime = entry_time.replace(
            tzinfo=tz, year=now.year, month=now.month, day=now.day
        )
        
        if entry_datetime < now:
            entry_datetime += timedelta(days=1)
        
        trigger_time = entry_datetime.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
        self.timer_manager.add_timer(
            self.config.bot_name, 
            "check_entry", 
            self.on_timer, 
            trigger_time=trigger_time
        )
    
    def stop(self):
        """Called when bot is stopped."""
        self.logger.info(f"Stopping MyBot: {self.config.bot_name}")
        # Clean up resources, cancel subscriptions, etc.
    
    def on_timer(self, event_name: str, event_data: any = None):
        """Handle timer events."""
        if event_name == "check_entry":
            self.check_entry_conditions()
    
    def check_entry_conditions(self):
        """Check if entry conditions are met."""
        self.logger.info("Checking entry conditions...")
        # Implement your entry logic here
```

### Step 4: Create Configuration File

Create [`config/default/my_bot.yaml`](../config/default/my_bot.yaml):

```yaml
bot_name: "my-bot-1"
bot_type: "my_bot"
log_level: "INFO"
timezone: "America/New_York"
entry_time: "09:30:00"
target_symbol: "SPY"
position_size: 100
test_mode: true
```

### Step 5: Run Your Bot

```bash
python main.py --config-dir config/default
```

## Bot Structure

### Required Files

#### `__init__.py`
```python
from .bot import MyBot
from .config import MyBotConfig

__all__ = ['MyBot', 'MyBotConfig']
```

#### `config.py`
Defines bot configuration using Pydantic models:

```python
from src.bots.config_base import ConfigBase
from typing import Optional

class MyBotConfig(ConfigBase):
    # Custom fields with type hints and defaults
    entry_time: str = "09:30:00"

## BaseBot Methods Reference

The [`BaseBot`](../src/bots/base_bot.py) class provides the following methods for bot development:

### Contract Resolution

#### `resolve_contracts(search_contract, status, callback)`
Resolves contract details asynchronously.

**Parameters**:
- `search_contract`: Contract object with search criteria
- `status`: ContractResolutionStatus object to track progress
- `callback`: Function called when resolution completes

**Example**:
```python
from src.bots.base_bot import ContractResolutionStatus
from ibapi.contract import Contract

def check_entry(self):
    contract = Contract()
    contract.symbol = "SPY"
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    
    status = ContractResolutionStatus()
    self.resolve_contracts(contract, status, self.on_contract_resolved)

def on_contract_resolved(self, status, contracts):
    if status.complete and len(contracts) > 0:
        self.my_contract = contracts[0].contract
        self.logger.info(f"Resolved: {self.my_contract.symbol}")
```

#### `resolve_option_chain(underlying, callback, timeout=5000)`
Resolves available option chain for an underlying contract.

**Parameters**:
- `underlying`: Underlying contract
- `callback`: Function called with option chain data
- `timeout`: Timeout in milliseconds (default: 5000)

### Market Data

#### `subscribe_market_data(contract, generic_tick_list="") -> int`
Subscribes to market data for a contract.

**Returns**: Request ID for this subscription

**Example**:
```python
req_id = self.subscribe_market_data(spy_contract)
```

#### `unsubscribe_market_data(contract)`
Unsubscribes from market data for a contract.

#### `get_cached_price(con_id=None, req_id=None) -> dict`
Gets cached price data for a contract.

**Returns**: Dictionary with tick types as keys (BID, ASK, LAST, etc.)

### Historical Data

#### `request_historical_data(contract, end_datetime, duration, bar_size, what_to_show, use_rth, keep_up_to_date, callback_historical_data_end, callback_historical_data_update=None) -> int`
Requests historical bar data.

**Parameters**:
- `contract`: Contract to get data for
- `end_datetime`: End date/time (format: "yyyyMMdd HH:mm:ss" or empty for current)
- `duration`: Duration string (e.g., "1 D", "1 W", "1 M")
- `bar_size`: Bar size (e.g., "1 min", "5 mins", "1 hour", "1 day")
- `what_to_show`: Data type ("TRADES", "MIDPOINT", "BID", "ASK")
- `use_rth`: 1 for regular trading hours only, 0 for all hours
- `keep_up_to_date`: True to receive live updates
- `callback_historical_data_end`: Called when initial data is complete
- `callback_historical_data_update`: Called for live updates (if keep_up_to_date=True)

**Returns**: Request ID

**Example**:
```python
req_id = self.request_historical_data(
    contract=spy_contract,
    end_datetime="",  # Empty = current time
    duration="5 D",
    bar_size="1 day",
    what_to_show="TRADES",
    use_rth=1,
    keep_up_to_date=False,
    callback_historical_data_end=self.on_historical_data
)

def on_historical_data(self, bars):
    for bar in bars:
        self.logger.info(f"Bar: {bar.date} O:{bar.open} H:{bar.high} L:{bar.low} C:{bar.close}")
```

#### `cancel_historical_data(req_id)`
Cancels a historical data subscription.

### Order Management

#### `place_order(contract, order) -> int`
Places an order.

**Parameters**:
- `contract`: Contract to trade
- `order`: Order object with order details

**Returns**: Order ID

**Note**: The bot name is automatically added to `order.orderRef` for tracking.

**Example**:
```python
from ibapi.order import Order

order = Order()
order.action = "BUY"
order.orderType = "LMT"
order.totalQuantity = 100
order.lmtPrice = 450.00
order.orderRef = "entry_order"

order_id = self.place_order(spy_contract, order)
```

### Callbacks (Override These)

#### `tick_price(reqId, tickType, price, attrib)`
Called when price tick is received.

#### `tick_option_computation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)`
Called when option greeks are received.

#### `order_status(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)`
Called when order status changes.

#### `exec_details(reqId, contract, execution)`
Called when execution details are received.

#### `open_order(orderId, contract, order, orderState)`
Called for open orders.

#### `on_timer(event_name, event_data=None)`
Called when a scheduled timer fires.

#### `historicalDataEnd(reqId, start, end, bars)`
Called when historical data request completes.

#### `historicalDataUpdate(reqId, bar)`
Called for live historical data updates (if keep_up_to_date=True).

### OptionsFinder Utility

The `self.options_finder` utility provides advanced option selection:

```python
# Find option by delta
self.options_finder.find_option_by_delta(
    underlying=spx_contract,
    expiration="20260515",
    right="P",  # Put
    target_delta=-0.35,
    callback=self.on_option_found
)

def on_option_found(self, success, contract, greeks):
    if success:
        self.logger.info(f"Found put: strike={contract.strike}, delta={greeks.delta}")
```

See [`src/utils/options_finder.py`](../src/utils/options_finder.py) for full API.

    exit_time: str = "15:45:00"
    max_position_size: int = 1000
    risk_per_trade: float = 0.02
    
    # Optional fields
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
```

#### `bot.py`
Implements the bot logic by inheriting from [`BaseBot`](../src/bots/base_bot.py):

```python
from src.bots.base_bot import BaseBot, ContractResolutionStatus
from src.bots.my_bot.config import MyBotConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager

class MyBot(BaseBot):
    def __init__(self, config: MyBotConfig, ib_connection: IBConnection,
                 timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        # Initialize state
    
    def start(self):
        # Bot startup logic
        pass
    
    def stop(self):
        # Bot cleanup logic
        pass
```

## Configuration

### ConfigBase Fields

All bots inherit these fields from [`ConfigBase`](../src/bots/config_base.py):

- `bot_name: str` - Unique identifier for the bot instance
- `bot_type: str` - Bot type (must match directory name)
- `log_level: LogLevel` - Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

### Custom Configuration

Add custom fields with type hints and defaults:

```python
class MyBotConfig(ConfigBase):
    # Strings
    timezone: str = "America/New_York"
    symbol: str = "SPY"
    
    # Numbers
    position_size: int = 100
    risk_percentage: float = 0.02
    
    # Booleans
    test_mode: bool = False
    allow_overnight: bool = True
    
    # Optional fields
    stop_loss: Optional[float] = None
    
    # Lists
    symbols: list[str] = ["SPY", "QQQ", "IWM"]
    
    # Nested objects
    entry_rules: dict = {
        "min_volume": 1000000,
        "max_spread": 0.05
    }
```

### Validation

Pydantic automatically validates configuration:

```python
from pydantic import validator

class MyBotConfig(ConfigBase):
    position_size: int = 100
    
    @validator('position_size')
    def validate_position_size(cls, v):
        if v <= 0:
            raise ValueError('position_size must be positive')
        if v > 10000:
            raise ValueError('position_size too large')
        return v
```

## Core Concepts

### 1. Asynchronous Operations

All IBAPI operations are asynchronous. Use callbacks:

```python
def check_entry(self):
    # Request contract details
    contract = Contract()
    contract.symbol = "SPY"
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    
    status = ContractResolutionStatus()
    self.resolve_contracts(
        search_contract=contract,
        status=status,
        callback=self.on_contract_resolved
    )

def on_contract_resolved(self, status: ContractResolutionStatus, contracts):
    if status.complete and len(contracts) == 1:
        self.target_contract = contracts[0].contract
        self.logger.info(f"Contract resolved: {self.target_contract.conId}")
        # Continue with next step
    else:
        self.logger.error(f"Contract resolution failed: {status.errors}")
```

### 2. Market Data Subscriptions

Subscribe to real-time market data:

```python
def subscribe_to_market_data(self):
    # Subscribe to market data
    req_id = self.subscribe_market_data(
        contract=self.target_contract,
        generic_tick_list=""  # or "100,101,104" for specific ticks
    )
    self.market_data_req_id = req_id

def tick_price(self, reqId, tickType, price, attrib):
    """Called when market data is received."""
    if reqId == self.market_data_req_id:
        self.logger.info(f"Price update: {tickType} = {price}")
        
        # Get cached data
        cached_data = self.get_cached_price(con_id=self.target_contract.conId)
        
        # Process price update
        self.process_price_update(cached_data)

def cleanup(self):
    # Always unsubscribe when done
    if self.target_contract:
        self.unsubscribe_market_data(self.target_contract)
```

### 3. Option Chain Resolution

Use the framework's option chain resolution:

```python
def find_options(self):
    # Resolve option chain
    self.resolve_option_chain(
        underlying=self.underlying_contract,
        callback=self.on_option_chain_resolved,
        timeout=5000  # 5 seconds
    )

def on_option_chain_resolved(self, chain_data):
    self.logger.info(f"Received {len(chain_data)} option chain entries")
    
    for entry in chain_data:
        self.logger.info(f"Exchange: {entry['exchange']}")
        self.logger.info(f"Expirations: {entry['expirations']}")
        self.logger.info(f"Strikes: {entry['strikes']}")
    
    # Use OptionsFinder for advanced selection
    self.options_finder.find_option_by_delta(
        underlying=self.underlying_contract,
        expiration="20260515",
        right="P",
        target_delta=-0.35,
        callback=self.on_option_found
    )

def on_option_found(self, option_contract, actual_delta):
    if option_contract:
        self.logger.info(f"Found option: {option_contract.localSymbol}")
        self.logger.info(f"Delta: {actual_delta}")
    else:
        self.logger.warning("No suitable option found")
```

### 4. Order Placement

Place orders through the framework:

```python
from ibapi.order import Order

def place_entry_order(self):
    # Create order
    order = Order()
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = self.config.position_size
    order.lmtPrice = 100.50
    order.tif = "DAY"
    order.orderRef = "Entry Order"  # Will be prefixed with bot_name
    
    # Place order
    order_id = self.place_order(self.target_contract, order)
    
    if order_id:
        self.logger.info(f"Order placed: {order_id}")
        self.pending_order_id = order_id
    else:
        self.logger.error("Failed to place order")

def order_status(self, orderId, status, filled, remaining, 
                 avgFillPrice, permId, parentId, lastFillPrice, 
                 clientId, whyHeld, mktCapPrice):
    """Called when order status changes."""
    if orderId == self.pending_order_id:
        self.logger.info(f"Order {orderId} status: {status}")
        self.logger.info(f"Filled: {filled}, Remaining: {remaining}")
        
        if status == "Filled":
            self.on_order_filled(orderId, filled, avgFillPrice)

def exec_details(self, reqId, contract, execution):
    """Called when order is executed."""
    self.logger.info(f"Execution: {execution.execId}")
    self.logger.info(f"Price: {execution.price}, Qty: {execution.shares}")
```

### 5. Timer Management

Schedule operations using TimerManager:

```python
def schedule_exit_check(self):
    # One-time timer
    tz = pytz.timezone(self.config.timezone)
    exit_time = datetime.now(tz) + timedelta(hours=1)
    trigger_time = exit_time.strftime("%Y-%m-%d %H:%M:%S") + f" {self.config.timezone}"
    
    timer_id = self.timer_manager.add_timer(
        bot_id=self.config.bot_name,
        event_name="check_exit",
        callback=self.on_timer,
        trigger_time=trigger_time
    )
    self.exit_timer_id = timer_id

def schedule_daily_check(self):
    # Recurring timer (CRON)
    timer_id = self.timer_manager.add_timer(
        bot_id=self.config.bot_name,
        event_name="daily_check",
        callback=self.on_timer,
        cron_expression="30 9 * * 1-5"  # Weekdays at 9:30 AM
    )

def on_timer(self, event_name: str, event_data: any = None):
    if event_name == "check_exit":
        self.check_exit_conditions()
    elif event_name == "daily_check":
        self.perform_daily_check()
```

### 6. Historical Data

Request historical data:

```python
def request_historical_bars(self):
    req_id = self.request_historical_data(
        contract=self.target_contract,
        end_datetime="",  # Empty = now
        duration="1 D",   # 1 day
        bar_size="5 mins",
        what_to_show="TRADES",
        use_rth=1,  # Regular trading hours only
        keep_up_to_date=False,
        callback_historical_data_end=self.on_historical_data_received
    )
    self.hist_data_req_id = req_id

def on_historical_data_received(self, bars):
    self.logger.info(f"Received {len(bars)} historical bars")
    
    for bar in bars:
        self.logger.debug(f"Bar: {bar.date} O:{bar.open} H:{bar.high} "
                         f"L:{bar.low} C:{bar.close} V:{bar.volume}")
    
    # Process bars
    self.analyze_historical_data(bars)
```

## Common Patterns

### Pattern 1: Entry/Exit Strategy

```python
class EntryExitBot(BaseBot):
    def __init__(self, config, ib_connection, timer_manager, config_dir):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.position = None
        self.entry_price = None
    
    def start(self):
        # Schedule entry check
        self.schedule_entry_check()
    
    def schedule_entry_check(self):
        tz = pytz.timezone(self.config.timezone)
        entry_time = self.parse_time(self.config.entry_time, tz)
        
        self.timer_manager.add_timer(
            self.config.bot_name,
            "check_entry",
            self.on_timer,
            trigger_time=entry_time
        )
    
    def on_timer(self, event_name, event_data):
        if event_name == "check_entry":
            self.check_entry_conditions()
        elif event_name == "check_exit":
            self.check_exit_conditions()
    
    def check_entry_conditions(self):
        # Resolve contract
        # Subscribe to market data
        # Analyze conditions
        # Place order if conditions met
        pass
    
    def check_exit_conditions(self):
        # Check stop loss
        # Check take profit
        # Check time-based exit
        # Place exit order if needed
        pass
```

### Pattern 2: Option Spread Strategy

```python
class OptionSpreadBot(BaseBot):
    def __init__(self, config, ib_connection, timer_manager, config_dir):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.short_leg = None
        self.long_leg = None
    
    def find_spread_legs(self):
        # Find short leg
        self.options_finder.find_option_by_delta(
            underlying=self.underlying,
            expiration=self.config.expiration,
            right="P",
            target_delta=self.config.short_delta,
            callback=self.on_short_leg_found
        )
    
    def on_short_leg_found(self, contract, delta):
        self.short_leg = contract
        
        # Find long leg (protective)
        target_strike = contract.strike - self.config.width
        self.options_finder.find_option_by_strike(
            underlying=self.underlying,
            expiration=self.config.expiration,
            right="P",
            strike=target_strike,
            callback=self.on_long_leg_found
        )
    
    def on_long_leg_found(self, contract, delta):
        self.long_leg = contract
        
        # Create spread order
        self.place_spread_order()
    
    def place_spread_order(self):
        # Create BAG contract for spread
        from ibapi.contract import ComboLeg
        
        spread = Contract()
        spread.symbol = self.underlying.symbol
        spread.secType = "BAG"
        spread.currency = "USD"
        spread.exchange = "SMART"
        
        leg1 = ComboLeg()
        leg1.conId = self.short_leg.conId
        leg1.ratio = 1
        leg1.action = "SELL"
        leg1.exchange = "SMART"
        
        leg2 = ComboLeg()
        leg2.conId = self.long_leg.conId
        leg2.ratio = 1
        leg2.action = "BUY"
        leg2.exchange = "SMART"
        
        spread.comboLegs = [leg1, leg2]
        
        # Place order
        order = Order()
        order.action = "BUY"  # BUY the spread
        order.orderType = "LMT"
        order.totalQuantity = self.config.quantity
        order.lmtPrice = self.calculate_spread_price()
        
        self.place_order(spread, order)
```

### Pattern 3: Market Data Analysis

```python
class AnalysisBot(BaseBot):
    def __init__(self, config, ib_connection, timer_manager, config_dir):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.price_history = []
        self.sma_period = config.sma_period
    
    def start(self):
        # Resolve contract and subscribe
        self.resolve_and_subscribe()
    
    def tick_price(self, reqId, tickType, price, attrib):
        if reqId == self.market_data_req_id:
            # Store price
            self.price_history.append({
                'time': datetime.now(),
                'price': price,
                'type': tickType
            })
            
            # Keep only recent history
            if len(self.price_history) > 1000:
                self.price_history = self.price_history[-1000:]
            
            # Calculate indicators
            sma = self.calculate_sma()
            
            # Check signals
            if self.check_entry_signal(price, sma):
                self.enter_position()
    
    def calculate_sma(self):
        if len(self.price_history) < self.sma_period:
            return None
        
        recent_prices = [p['price'] for p in self.price_history[-self.sma_period:]]
        return sum(recent_prices) / len(recent_prices)
```

## Testing

### Test Mode

Enable test mode in configuration:

```yaml
test_mode: true
```

Use test mode to:
- Trigger events immediately instead of waiting for scheduled times
- Use smaller position sizes
- Add extra logging
- Skip certain validations

```python
def start(self):
    if self.config.test_mode:
        self.logger.info("TEST MODE: Triggering entry check in 3 seconds")
        trigger_time = (datetime.now(pytz.UTC) + timedelta(seconds=3)).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    else:
        trigger_time = self.calculate_entry_time()
    
    self.timer_manager.add_timer(
        self.config.bot_name,
        "check_entry",
        self.on_timer,
        trigger_time=trigger_time
    )
```

### Paper Trading

Always test with paper trading first:

```yaml
# .config.yaml
connection:
  host: "127.0.0.1"
  port: 7497  # Paper trading port
  client_id: 1
  selected_account: "DU123456"  # Paper account
```

### Logging

Use appropriate log levels:

```python
# Debug: Detailed information
self.logger.debug(f"Contract details: {contract}")

# Info: General progress
self.logger.info("Entry conditions met, placing order")

# Warning: Unexpected but handled
self.logger.warning("Market data delayed, using last price")

# Error: Failures
self.logger.error(f"Failed to resolve contract: {error}")
```

## Deployment

### 1. Configuration Management

Create separate config directories:

```
config/
├── paper/          # Paper trading
│   ├── .config.yaml
│   └── my_bot.yaml
└── live/           # Live trading
    ├── .config.yaml
    └── my_bot.yaml
```

Run with specific config:
```bash
python main.py --config-dir config/paper
```

### 2. Monitoring

Monitor bot logs:
```bash
tail -f logs/default/my-bot-1.log
```

Check system log:
```bash
tail -f logs/default/system.log
```

### 3. Error Recovery

Implement graceful error handling:

```python
def start(self):
    try:
        self.initialize()
    except Exception as e:
        self.logger.error(f"Initialization failed: {e}", exc_info=True)
        # Implement recovery logic or alert

def on_contract_resolved(self, status, contracts):
    if len(status.errors) > 0:
        self.logger.error(f"Contract resolution errors: {status.errors}")
        # Retry or alert
        return
    
    # Continue normal flow
```

### 4. Position Tracking

Track positions in bot state:

```python
def __init__(self, config, ib_connection, timer_manager, config_dir):
    super().__init__(config, ib_connection, timer_manager, config_dir)
    self.positions = {}  # conId -> position info

def exec_details(self, reqId, contract, execution):
    # Update position tracking
    con_id = contract.conId
    if con_id not in self.positions:
        self.positions[con_id] = {
            'quantity': 0,
            'avg_price': 0
        }
    
    # Update based on execution
    # ...
```

## Best Practices

1. **State Management**: Keep bot state minimal and recoverable
2. **Error Handling**: Always handle errors gracefully
3. **Logging**: Log important events and decisions
4. **Testing**: Test thoroughly in paper trading
5. **Documentation**: Document your strategy and configuration
6. **Monitoring**: Set up alerts for critical errors
7. **Cleanup**: Always clean up resources in `stop()`
8. **Idempotency**: Make operations idempotent where possible

## Example Bots

Study the included sample bots:

- [`FkkBot`](../src/bots/fkk/bot.py) - Option spread strategy with entry/exit logic
- [`DoubleCalendarBot`](../src/bots/double_calendar/bot.py) - Calendar spread strategy

## Next Steps

- Review [Framework Overview](./FRAMEWORK_OVERVIEW.md) for architecture details
- Study [Sample Bots](./SAMPLE_BOTS.md) for implementation examples
- Check [API Reference](./API_REFERENCE.md) for detailed method documentation