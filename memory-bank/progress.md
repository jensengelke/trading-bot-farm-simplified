# Project Progress

## What Works
- **Core Infrastructure**: Shared IBKR connection, request multiplexing, and callback routing.
- **Bot Management**: Dynamic discovery and loading of bots from YAML configurations.
- **Scheduling**: Timezone-aware timers and CRON scheduling.
- **Data Sync**: Flex Query integration and real-time execution sync.
- **Database**: SQLAlchemy models and repository for persistence.
- **Utilities**: `OptionsFinder` for delta-based option selection.
- **CLI**: Interactive menu for status, positions, and orders.
- **FKK Strategy**: Basic implementation of the Bull Put Spread strategy.
- **Double Calendar Strategy**: Basic implementation of the strategy.

## What's Left to Build
- **Stability Improvements**: Resolve race conditions in market data caching.
- **Web UI**: A future web-based interface for monitoring (placeholder in config).
- **Advanced Strategies**: Implementation of more complex trading strategies.
- **Performance Optimization**: Optimize database queries and data handling for high-frequency updates.
- **Comprehensive Testing**: Automated unit and integration tests.

## Current Status
- **Version**: V2 (Simplified Farm)
- **Active Strategy**: FKK Bot (in testing/stabilization phase).

## Known Issues
- Request maintenance logic in bots might need more robust tracking of different request types.
- Occasional connection timeouts to TWS/Gateway.
- **Fixed**: `AttributeError` in `EventLoggerBot.open_order` due to `ibapi` version differences in `OrderState` attributes (e.g., `commission` vs `commissionAndFees`).

## Evolution of Project Decisions
1. **From Single to Shared Connection**: Shifted from individual bot connections to a centralized `IBConnection` for efficiency.
2. **Chudfly Flexibility**: Refined Chudfly configuration to allow independent upward/downward gap thresholds and more flexible leg strike selection using relative offsets instead of a fixed spread width.
3. **SQLite for Persistence**: Chose SQLite for ease of setup and sufficient performance for the current scale.
4. **YAML-driven Config**: Selected YAML for human-readable and easily modifiable bot configurations.
5. **PermId for Orders**: Switched to `permId` as the primary key for order tracking to ensure consistency across TWS restarts.
