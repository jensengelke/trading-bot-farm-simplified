# Project Brief: Trading Bot Farm - Simplified

This project is a Python-based framework designed to run multiple automated trading bots concurrently while sharing a single connection to Interactive Brokers (IBKR) via the TWS (Trader Workstation) or IB Gateway API.

## Core Goals
- **Efficiency**: Use a single IBAPI connection for multiple bots to save resources and costs.
- **Robustness**: Provide an asynchronous, callback-based architecture for non-blocking operations.
- **Scalability**: Support multiple bots with different strategies (e.g., FKK, Double Calendar).
- **Data Integrity**: Synchronize historical and real-time data using Flex Query and IBAPI.
- **Ease of Development**: Offer a simple base class (`BaseBot`) and utilities (e.g., `OptionsFinder`) for rapid bot creation.

## Key Requirements
- Shared IBKR connection with request multiplexing.
- Timezone-aware scheduling (CRON and one-time timers).
- Persistence of trades, positions, and analytics using SQLAlchemy.
- Configuration-driven bot management (YAML-based).
- Comprehensive structured logging with automatic rotation.

## Scope
- Core infrastructure for IBKR connection and multiplexing.
- Bot management and discovery system.
- Data synchronization services (Flex Query + API).
- Database layer for persistence.
- Initial set of sample bots (FKK, Double Calendar).
- Interactive CLI for system monitoring and control.
