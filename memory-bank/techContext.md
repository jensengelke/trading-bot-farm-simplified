# Technical Context

## Technologies Used
- **Language**: Python 3.8+
- **Broker API**: Interactive Brokers Python API (`ibapi`)
    - Workspace root: `C:\TWSAPI-latest\source\pythonclient`
- **Database**: SQLite with SQLAlchemy ORM
- **Configuration**: YAML (via `PyYAML`)
- **Data Validation**: `pydantic`
- **Scheduling**: `croniter` for CRON support
- **Time/Timezones**: `pytz` and `tzdata`
- **Networking**: `requests` for Flex Query API

## Development Setup
- **Multi-root Workspace**:
    - `c:\git\trading-bot-farm-simplified` (Primary)
    - `C:\TWSAPI-latest\source\pythonclient` (IBAPI source)
    - `c:\git\TWS` (Related repository)
- **TWS/Gateway**: Must be running and configured to allow API connections.
    - Paper Trading Port: `7497`
    - Live Trading Port: `7496`
- **Environment Variables/Config**: Main configuration stored in `config/<dir>/.config.yaml`.

## Technical Constraints
- **Asynchronous Nature**: All interactions with IBKR must be non-blocking. Reliance on callbacks.
- **IBAPI Limitations**: Throttling on certain requests (e.g., market data subscriptions, historical data).
- **Data Freshness**: Flex Query data is typically T-1. Real-time sync must bridge the gap.
- **Connectivity**: Requires a stable connection to TWS/Gateway.

## Tool Usage Patterns
- **CLI Interface**: `main.py` provides an interactive menu for management.
- **Logging**: Structured logs per bot and a global `system.log`. Automatic rotation on startup.
- **Flex Query**: Requires a `flex_token` and `flex_query_id` from the IBKR Portal.

## Dependencies (from requirements.txt)
- `PyYAML>=6.0`
- `sqlalchemy`
- `requests`
- `pydantic`
- `croniter`
- `pytz`
- `tzdata`
- `ibapi` (linked from `c:\twsapi-latest\source\pythonclient`)
