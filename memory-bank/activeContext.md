# Active Context

## Current Work Focus
The project is currently focused on stabilizing the FKK bot strategy and resolving issues with market data caching and order placement.

## Recent Changes
- Implementation of a shared `IBConnection` layer with multiplexing.
- Addition of structured logging with automatic rotation.
- Integration of Flex Query for historical data synchronization.
- Development of the `OptionsFinder` utility for automated option selection.
- Refinement of `BotManager` for dynamic bot loading.

## Active Decisions and Considerations
- **Order Cache Keying**: Decisions were made to use `permId` instead of transient `orderId` for tracking orders across sessions.
- **Data Sync Sequence**: Bots are now strictly prevented from starting until `SyncManager` reports a complete account synchronization.
- **Logging Level**: A dedicated `order_cache_debug` logger was added to troubleshoot order tracking issues.

## Problem Solving and Troubleshooting
- **Request Maintenance**: Suspicions exist that the list of open requests is not being maintained correctly, possibly mixing up option chain requests and spread requests.

## Next Steps
- [ ] Investigate the request maintenance logic in `IBConnection` and bots to ensure clean separation of request types.
- [ ] Verify the order caching logic under various connection scenarios.
