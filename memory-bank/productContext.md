# Product Context

## Why this project exists
Trading automated strategies often involves high overhead in terms of connection management and data subscriptions. Traditional setups might require one connection per bot, which is inefficient and costly. This framework solves that by allowing multiple bots to share a single, multiplexed connection to Interactive Brokers.

## Problems it solves
- **Connection Overhead**: Eliminates the need for multiple TWS/Gateway instances or multiple API connections.
- **Data Redundancy**: Multiplexes market data requests, so multiple bots can watch the same symbol using a single subscription.
- **Complexity of IBAPI**: Wraps the complex, callback-driven IBAPI into a more manageable framework.
- **Synchronization Issues**: Automates the reconciliation of historical trades (via Flex Query) and real-time execution data.
- **Scheduling**: Handles timezone-aware trading sessions and execution windows.

## How it should work
1. **Startup**: The user runs `main.py` pointing to a configuration directory.
2. **Initialization**: The system loads configurations, initializes the database, and discovers available bots.
3. **Connection**: It establishes a connection to TWS/Gateway and performs an initial account synchronization (Flex Query + API).
4. **Execution**: Once synchronized, bots are started. They subscribe to market data, schedule timers, and place orders based on their strategies.
5. **Monitoring**: Users can monitor status, positions, and orders via a CLI menu.
6. **Persistence**: All trading activity and state are saved to a local SQLite database.

## User Experience Goals
- **Simple Configuration**: Use YAML files to define bot parameters without changing code.
- **Transparent Logging**: Provide detailed, organized logs for debugging and auditing.
- **Reliable Execution**: Ensure bots only start after a full data sync to prevent trading on stale or incomplete information.
- **System Stability**: Handle IBAPI "errors" and connection drops gracefully.
