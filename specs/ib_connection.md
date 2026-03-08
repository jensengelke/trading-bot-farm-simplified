# Specification: IBConnection Component

## 1. Overview
The `IBConnection` component is the core infrastructure layer responsible for communicating directly with the Interactive Brokers (IBKR) Trader Workstation (TWS) or IB Gateway. It encapsulates the underlying `ibapi` Python API, providing a clean, thread-safe, and asynchronous interface for the rest of the trading bot farm.

## 2. Responsibilities
- **Lifecycle Management**: Handle connecting, disconnecting, and auto-reconnecting to the IBKR Gateway/TWS.
- **Protocol Encapsulation**: Inherit from and implement the callbacks for `ibapi.wrapper.EWrapper` and call the methods of `ibapi.client.EClient`.
- **Multiplexing Data**: Subscribe to market data streams (e.g., live ticks) exactly once per instrument to avoid rate limits, and dispatch the updates to all subscribed bots.
- **Request Throttling**: Manage an active request queue to ensure the system does not exceed the IBKR API rate limit of 50 messages per second.
- **State Synchronization**: Maintain a comprehensive near real-time cache of account balances, portfolio positions, and active orders.
- **Account Isolation**: A single `IBConnection` is bound to one specific account. If events arrive for another account (which can happen when bound to a financial advisor master account), they are ignored at the `IBConnection` boundary.

## 3. Architecture

### 3.1 Class Definition
The component will be implemented as a unified class that acts as both the client and the wrapper.

```python
class IBConnection(EWrapper, EClient):
    pass
```

### 3.2 State/Cache Management
To allow independent bots to operate without redundant API calls, `IBConnection` will maintain robust internal caches:
- `market_data`: Cached stream of most recent price data for subscribed contracts.
- `portfolio_data`: Tracks current open positions, average costs, and unrealized PNL.
- `account_data`: Net liquidation value, available funds, and buying power for the `selected_account`.
- `orders_data`: Order status, filled quantities, and average fill prices. 

**Account Context**: An internal `selected_account` string property will be established upon initialization. Any incoming callback (like `updatePortfolio` or `orderStatus`) that references an account outside of `selected_account` will be immediately dropped to prevent state bleeding.

### 3.3 Event Dispatching
Since multiple bots will be running simultaneously and acting independently, `IBConnection` must support an event-driven distribution model.
- Upon receiving an API callback (e.g., `tickPrice`, `orderStatus`, `position`), `IBConnection` will construct a standardized internal event object and submit it to a centralized `EventDispatcher` or `WorkQueue`.
- The strategy layer will be responsible for routing these events to the specific bot instances that are subscribed.

## 4. Key Workflows

### 4.1 Connection Lifecycle
1. The system instantiates `IBConnection(host, port, client_id, selected_account)`.
2. `connect_and_start()` is called, which attempts the socket connection and starts a dedicated daemon thread to process the `ibapi` message loop (`self.run()`).
3. Connection is confirmed when the `nextValidId` callback is received.
4. Auto-sync starts: The component requests current open orders (`reqAllOpenOrders`) and current positions (`reqPositions`). Before committing these to cache, they are filtered against `self.selected_account`.

### 4.2 Handling Market Data (Multiplexing)
To fulfill the requirement of "support for live data subscription... IBConnection should subscribe only once and dispatch events to subscribed bots":
1. A bot requests market data for Symbol X.
2. `IBConnection` checks if an active subscription for Symbol X already exists (via `reqMktData`).
3. If not, it reserves a unique `reqId` and fires `reqMktData`.
4. As `tickPrice` or `tickSize` strings arrive, the internal `market_data` cache is updated, and a `MARKET_DATA` event is dispatched.
5. All bots listening to Symbol X will receive the update via the event dispatcher.
6. A reference counter will track subscriptions. When all bots unsubscribe from Symbol X, `cancelMktData` is called.

### 4.3 Order Execution
1. A bot formulates an `Order` and `Contract` object.
2. It passes these to `IBConnection.place_order(contract, order)`.
3. `IBConnection` allocates the next valid sequence ID (`next_order_id`).
4. The API `placeOrder` command is sent.
5. Subsequent `orderStatus` and `execDetails` callbacks are parsed, used to update internal `orders_data` state, and bubbled up as `ORDER_STATUS` and `EXECUTION` events.

## 5. Threading Model
- **Main/Worker Threads**: Used by the multi-layered Web UI and Command Line Interface to query cached state and submit new orders.
- **API Thread**: A singular, dedicated thread that runs the `ibapi` read loop. Blocking operations inside the API Thread are strictly prohibited to avoid disconnecting the socket.
- **Queue/Locking**: Shared resources (like the request queue or cache dictionaries) must be protected with thread locks if mutated directly, or isolated by passing deep copies to the event dispatcher.

## 6. Historical & Flex Web Service Hooks
While the primary responsibility of `IBConnection` is real-time interaction, it will provide hooks for initializing long-term transaction data via the Flex Web Service protocol.
- `reqHistoricalData`: Provides intraday or recent historical bars directly via the TWS API.
- **Flex Query Integration**: For long-term historical transaction retrieval (spanning months/years), an adjacent service (`FlexQueryService`) will authenticate with IBKR's Web Service (`https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/`) utilizing tokens provided in the central configuration. `IBConnection` will coordinate with the Persistence Layer to ingest this data for shadow bookkeeping.

## 7. Interfaces
The component must expose methods suitable for the Bot instances to call (e.g., via their `TradingBot` base class):
- `subscribe_market_data(contract)`
- `unsubscribe_market_data(contract)`
- `place_order(contract, order)`
- `cancel_order(order_id)`
- `get_orders(include_closed=False)` (returns filtered list of orders)
- `get_cached_positions()`
- `get_cached_account_summary()`

### 7.1 Data Request Interfaces
The `IBConnection` component must also proxy requests to Interactive Brokers for various types of fundamental, historical, and contract data. The following table identifies the underlying `EClient` request methods, their corresponding `EWrapper` callbacks, and the proposed unified interface method to expose to `TradingBot` clients:

| Requested Data Type | EClient Method | EWrapper Callbacks | Proposed Interface Method |
| :--- | :--- | :--- | :--- |
| **Contract Details** | `reqContractDetails(reqId: int, contract: Contract)` | `contractDetails`, `contractDetailsEnd` | `request_contract_details(contract)` |
| **Option Chain** | `reqSecDefOptParams(reqId: int, underlyingSymbol: str, futFopExchange: str, underlyingSecType: str, underlyingConId: int)` | `securityDefinitionOptionParameter`, `securityDefinitionOptionParameterEnd` | `request_option_chain(underlying_symbol, exchange, sec_type, conid)` |
| **Historical Data (Bars)** | `reqHistoricalData(reqId: int, contract: Contract, endDateTime: str, durationStr: str, barSizeSetting: str, whatToShow: str, useRTH: int, formatDate: int, keepUpToDate: bool, chartOptions)` | `historicalData`, `historicalDataEnd`, `historicalDataUpdate` | `request_historical_data(contract, end_datetime, duration, bar_size, what_to_show, use_rth, keep_up_to_date)` |
| **Real-time Bars** | `reqRealTimeBars(reqId: int, contract: Contract, barSize: int, whatToShow: str, useRTH: bool, realTimeBarsOptions)` | `realtimeBar` | `subscribe_realtime_bars(contract, bar_size, what_to_show, use_rth)` |
| **Market Depth (Level 2)**| `reqMktDepth(reqId: int, contract: Contract, numRows: int, isSmartDepth: bool, mktDepthOptions)` | `updateMktDepth`, `updateMktDepthL2` | `subscribe_market_depth(contract, num_rows, is_smart_depth)` |
| **Fundamental Data** | `reqFundamentalData(reqId: int, contract: Contract, reportType: str, fundamentalDataOptions)` | `fundamentalData` | `request_fundamental_data(contract, report_type)` |
| **Executions / Trades** | `reqExecutions(reqId: int, execFilter: ExecutionFilter)` | `execDetails`, `execDetailsEnd` | `request_executions(execution_filter)` |
| **News Article** | `reqNewsArticle(reqId: int, providerCode: str, articleId: str, newsArticleOptions)` | `newsArticle` | `request_news_article(provider_code, article_id)` |
| **Historical News** | `reqHistoricalNews(reqId: int, conId: int, providerCodes: str, startDateTime: str, endDateTime: str, totalResults: int, historicalNewsOptions)` | `historicalNews` | `request_historical_news(conid, provider_codes, start, end, total_results)` |
| **Market Scanners** | `reqScannerSubscription(reqId: int, subscription: ScannerSubscription, scannerSubscriptionOptions, scannerSubscriptionFilterOptions)` | `scannerData`, `scannerDataEnd` | `subscribe_market_scanner(scanner_subscription)` |

*Note: Since these `EClient` requests are asynchronous, the proposed interface methods should return a unique `reqId` (or a Future/Promise object), and the results will be dispatched asynchronously via the Event system once the corresponding `EWrapper` callbacks fire.*
