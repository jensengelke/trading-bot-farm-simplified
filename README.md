# Trading Bot Farm - Simplified

A Python-based framework for running multiple automated trading bots that share a single connection to Interactive Brokers TWS (Trader Workstation) via the IBAPI.

## Overview

This framework provides a robust, asynchronous architecture for developing and deploying trading bots with:

- **Shared Connection**: Single IBAPI connection for all bots (resource efficient)
- **Request Multiplexing**: Multiple bots can subscribe to the same market data without duplication
- **Asynchronous Design**: Callback-based API handling for non-blocking operations
- **Data Synchronization**: Automatic sync with IB using Flex Query API and real-time API
- **Timer Management**: Timezone-aware scheduling for bot operations
- **Option Utilities**: Built-in tools for option chain resolution and delta-based selection
- **Database Integration**: SQLAlchemy-based persistence for trades, positions, and analytics

## Features

### Framework Features

- ✅ **Single Connection Architecture**: All bots share one TWS connection
- ✅ **Request Multiplexing**: Efficient market data subscription management
- ✅ **Asynchronous Operations**: Non-blocking request/response pattern
- ✅ **Smart Caching**: Market data, positions, and account info cached for quick access
- ✅ **Account Isolation**: Filter data by selected account
- ✅ **Timezone-Aware Scheduling**: CRON and one-time timers with timezone support
- ✅ **Comprehensive Logging**: Structured logging with automatic log rotation
- ✅ **Configuration-Driven**: YAML-based bot configuration
- ✅ **Dynamic Bot Loading**: Automatic bot discovery and instantiation

### Data Synchronization

- ✅ **Flex Query Integration**: Historical data sync (trades, orders, positions)
- ✅ **API Sync**: Real-time execution data
- ✅ **Shadow Positions**: Independent position tracking and verification
- ✅ **Batch Initialization**: Automatic historical data loading on first run
- ✅ **Incremental Updates**: Daily sync for new data

### Bot Development

- ✅ **Simple Base Class**: Inherit from `BaseBot` for easy development
- ✅ **OptionsFinder Utility**: Delta-based option selection with caching
- ✅ **Contract Resolution**: Simplified contract lookup and validation
- ✅ **Market Data Subscriptions**: Easy subscribe/unsubscribe pattern
- ✅ **Order Management**: Simplified order placement and tracking
- ✅ **Historical Data**: Request and process historical bars

## Quick Start

### Prerequisites

- Python 3.8+
- Interactive Brokers TWS or IB Gateway
- IB account (paper or live)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/trading-bot-farm-simplified.git
cd trading-bot-farm-simplified
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure TWS/Gateway:
   - Enable API connections in TWS/Gateway settings
   - Note your port number (7497 for paper, 7496 for live)
   - Set a client ID (default: 1)

### Configuration

1. Create configuration directory:
```bash
mkdir -p config/default
```

2. Copy the configuration template:
```bash
cp config/default/.config.yaml.template config/default/.config.yaml
```

3. Edit `config/default/.config.yaml` with your settings:
```yaml
connection:
  host: "127.0.0.1"
  port: 7497  # Paper trading (7496 for live)
  client_id: 1
  selected_account: "DU123456"  # Your paper account

database:
  url: "sqlite:///data/trading_farm.db"

flex:
  flex_token: "your_flex_token_here"  # Optional - for historical data sync
  flex_query_id: "123456"  # Optional - your Flex Query ID

ui:
  port: 5000  # Optional - for future web UI
```

4. Create a bot configuration file `config/default/my_bot.yaml`:
```yaml
bot_name: "my-bot-1"
bot_type: "fkk"  # or "double_calendar"
log_level: "INFO"
timezone: "America/New_York"
test_mode: true
```

### Running the Framework

```bash
python main.py --config-dir config/default
```

The framework will:
1. Connect to TWS/Gateway
2. Sync historical data (if configured)
3. Load and start all configured bots
4. Display an interactive menu

### Interactive Menu

```
==========================================
 V2 Farm API Interface
==========================================
  1. Connect to IBKR
  2. Disconnect
  3. Check Status
  4. View Cached Positions
  5. View Open Orders
  6. View Account Summary
  7. Exit
==========================================
```

## Project Structure

```
trading-bot-farm-simplified/
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── README.md                    # This file
│
├── config/                      # Configuration files
│   ├── default/                 # Default config directory
│   │   ├── .config.yaml.template  # Configuration template
│   │   ├── .config.yaml        # Main configuration (gitignored)
│   │   └── *.yaml              # Bot configurations
│   └── demo/                    # Demo/paper trading configs
│
├── src/                         # Source code
│   ├── ib_connection.py        # IBAPI wrapper
│   ├── bot_manager.py          # Bot orchestration
│   ├── timer_manager.py        # Scheduling system
│   ├── logging_config.py       # Logging setup
│   ├── utils.py                # Utility functions
│   │
│   ├── bots/                   # Bot implementations
│   │   ├── base_bot.py         # Base class for all bots
│   │   ├── config_base.py      # Base configuration
│   │   ├── fkk/                # FKK bot (bull put spread)
│   │   └── double_calendar/    # Double calendar bot
│   │
│   ├── db/                     # Database layer
│   │   ├── database.py         # Database setup
│   │   ├── models.py           # SQLAlchemy models
│   │   └── repository.py       # Data access layer
│   │
│   ├── services/               # Services
│   │   ├── sync_manager.py     # Data synchronization
│   │   └── flex_query_service.py # Flex Query API
│   │
│   └── utils/                  # Utilities
│       └── options_finder.py   # Option selection utility
│
├── docs/                        # Documentation
│   ├── FRAMEWORK_OVERVIEW.md   # Architecture & components
│   ├── BOT_DEVELOPMENT_GUIDE.md # How to create bots
│   └── SAMPLE_BOTS.md          # Sample bot documentation
│
├── logs/                        # Log files (auto-created)
│   └── default/
│       ├── system.log          # Main application log
│       └── bot-name.log        # Bot-specific logs
│
└── data/                        # Data files (auto-created)
    └── trading_farm.db         # SQLite database
```

## Documentation

### Core Documentation

- **[Framework Overview](docs/FRAMEWORK_OVERVIEW.md)** - Architecture, components, and data flow
- **[Bot Development Guide](docs/BOT_DEVELOPMENT_GUIDE.md)** - Step-by-step guide to creating bots
- **[Sample Bots](docs/SAMPLE_BOTS.md)** - Detailed explanation of included sample bots

### Key Concepts

#### 1. Asynchronous Operations

All IBAPI operations are asynchronous. Use callbacks:

```python
def check_entry(self):
    # Request contract details
    self.resolve_contracts(
        search_contract=contract,
        status=status,
        callback=self.on_contract_resolved
    )

def on_contract_resolved(self, status, contracts):
    # Handle result
    if status.complete:
        self.my_contract = contracts[0].contract
```

#### 2. Request Multiplexing

Multiple bots can subscribe to the same market data:

```python
# Bot 1 subscribes to SPY
req_id1 = self.subscribe_market_data(spy_contract)

# Bot 2 subscribes to SPY (reuses same subscription)
req_id2 = self.subscribe_market_data(spy_contract)

# Note: req_id1 and req_id2 are different, but both bots receive
# updates from the same underlying IB subscription (identified by conId).
# This reduces API load and subscription costs.
```

#### 3. Timer Management

Schedule operations with timezone awareness:

```python
# One-time timer
timer_id = self.timer_manager.add_timer(
    bot_id=self.config.bot_name,
    event_name="check_entry",
    callback=self.on_timer,
    event_data={"some": "data"},  # Optional data passed to callback
    trigger_time="2026-05-03 14:30:00 America/New_York"
)
# Returns timer_id for later reference/cancellation

# Recurring timer (CRON)
timer_id = self.timer_manager.add_timer(
    bot_id=self.config.bot_name,
    event_name="daily_check",
    callback=self.on_timer,
    cron_expression="30 9 * * 1-5"  # Weekdays at 9:30 AM
)
```

## Sample Bots

### FKK Bot (Bull Put Spread)

A systematic bull put spread strategy on SPX:

- **Entry**: When SPX closes above 5-day SMA with 0.3%+ intraday move
- **Structure**: Sell put at -0.35 delta, buy put 5-10 points lower
- **Expiration**: Same-day (0DTE)
- **Timing**: Configurable entry time (default: 14:15 ET)

**Configuration**:
```yaml
bot_name: "fkk-1"
bot_type: "fkk"
log_level: "INFO"
timezone: "America/New_York"
entry_time: "14:15:00"
entry_time_observation_period: 300  # Seconds to observe before deciding
delta: -0.35
width: 10  # Strike width between short and long puts
sma_period: 5
intraday_move_pct: 0.3
test_mode: false  # Set to true for immediate testing
force_open_position: false  # Set to true to skip entry condition checks
```

### Double Calendar Bot

A double calendar spread strategy:

- **Structure**: Sell near-term, buy far-term options
- **Legs**: Both put and call calendars
- **Strike Selection**: Based on delta and proximity to current price
- **Expirations**: ~7 days (near) and ~10 days (far)

**Configuration**:
```yaml
bot_name: "double-calendar-1"
bot_type: "double_calendar"
test_mode: true
```

## Creating Your Own Bot

### 1. Create Bot Directory

```bash
mkdir -p src/bots/my_bot
touch src/bots/my_bot/__init__.py
touch src/bots/my_bot/bot.py
touch src/bots/my_bot/config.py
```

### 2. Define Configuration

```python
# src/bots/my_bot/config.py
from src.bots.config_base import ConfigBase

class MyBotConfig(ConfigBase):
    timezone: str = "America/New_York"
    entry_time: str = "09:30:00"
    position_size: int = 100
```

### 3. Implement Bot

```python
# src/bots/my_bot/bot.py
from src.bots.base_bot import BaseBot

class MyBot(BaseBot):
    def start(self):
        self.logger.info("Bot started")
        # Schedule operations, subscribe to data, etc.
    
    def stop(self):
        self.logger.info("Bot stopped")
        # Clean up resources
```

### 4. Create Configuration File

```yaml
# config/default/my_bot.yaml
bot_name: "my-bot-1"
bot_type: "my_bot"
log_level: "INFO"
timezone: "America/New_York"
entry_time: "09:30:00"
position_size: 100
```

### 5. Run Your Bot

```bash
python main.py --config-dir config/default
```

See the [Bot Development Guide](docs/BOT_DEVELOPMENT_GUIDE.md) for detailed instructions.

## Data Synchronization

The framework automatically synchronizes data with Interactive Brokers:

### Flex Query Sync (Historical)

- Downloads historical trades, orders, and positions
- Runs on first startup (batch mode) and daily (incremental)
- Covers data up to yesterday (T-1)

### API Sync (Real-time)

- Fetches today's executions via IBAPI
- Runs after Flex Query sync
- Provides real-time trade data

### Shadow Positions

- Calculates positions from execution history
- Provides independent verification
- Enables historical position tracking

## Logging

Logs are organized by configuration directory:

```
logs/
└── default/
    ├── system.log           # Main application log
    ├── fkk-bot-1.log       # Bot-specific log
    └── 2026-05-03-14-30-15/ # Rolled logs
        ├── system.log
        └── fkk-bot-1.log
```

**Log Levels**:
- `DEBUG`: Detailed trace information
- `INFO`: General operational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical failures

## Testing

### Paper Trading

Always test with paper trading first:

```yaml
# config/paper/.config.yaml
connection:
  host: "127.0.0.1"
  port: 7497  # Paper trading port
  client_id: 1
  selected_account: "DU123456"
```

### Test Mode

Enable test mode in bot configuration:

```yaml
test_mode: true
```

This triggers immediate execution instead of waiting for scheduled times.

## Best Practices

1. **Always use paper trading first** - Test thoroughly before live trading
2. **Monitor logs** - Check `logs/*/system.log` for issues
3. **Handle errors gracefully** - Implement proper error handling in bots
4. **Use callbacks** - Never block waiting for IBAPI responses
5. **Clean up resources** - Always unsubscribe from market data when done
6. **Backup database** - Regularly backup your trading database
7. **Version control configs** - Keep configuration files in version control
8. **Document strategies** - Document your trading logic and parameters

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to TWS/Gateway

**Solutions**:
- Verify TWS/Gateway is running
- Check API settings are enabled
- Verify port number (7497 for paper, 7496 for live)
- Check firewall settings

### Bot Not Starting

**Problem**: Bot doesn't start or execute

**Solutions**:
- Check bot configuration file exists
- Verify `bot_type` matches directory name
- Check logs for error messages
- Enable `test_mode` for immediate execution

### Market Data Issues

**Problem**: Not receiving market data

**Solutions**:
- Verify market data subscriptions are active
- Check if market is open
- Verify contract details are correct
- Check IB account has market data permissions

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This software is for educational purposes only. Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software. Always test thoroughly in paper trading before using with real money.

## Support

- **Documentation**: See [docs/](docs/) directory
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Use GitHub Discussions for questions

## Acknowledgments

- Interactive Brokers for the IBAPI
- The Python trading community
- All contributors to this project

## Related Projects

- [IBAPI Documentation](https://interactivebrokers.github.io/tws-api/)
- [TWS API](https://www.interactivebrokers.com/en/trading/tws-api.php)

---

**Happy Trading! 🚀📈**