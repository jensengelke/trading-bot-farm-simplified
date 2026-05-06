# Order Cache Debug Instrumentation

## Overview
Added comprehensive debug logging to trace how the order cache (`self.orders_data`) is populated in the IBConnection class.

**Note**: The debug logger is set to **ERROR level by default**, so it's **SILENT during normal operations**. To enable debug output, change the level to DEBUG (see instructions below).

## Changes Made

### 1. New Debug Logger (`order_cache_debug`)
- **Location**: `src/ib_connection.py` (line 19-21)
- **Purpose**: Dedicated logger for order cache investigation
- **Output**: Writes to `logs/default/order_cache_debug.log` and console
- **Can be easily removed**: Just delete the logger setup and all `debug_logger.info()` calls

### 2. Instrumented Functions

#### `connect_and_start()` (lines 77-88)
Logs:
- When `reqAutoOpenOrders()` is called
- When `reqAllOpenOrders()` is called
- Cache size before requesting orders

#### `openOrder()` callback (lines 240-257)
Logs:
- Every time the callback is invoked with order details
- Account filtering decisions
- Orders being added to cache
- Cache size and keys after each addition

#### `orderStatus()` callback (lines 262-278)
Logs:
- Every status update received
- Whether the order exists in cache
- Warning if status update for non-cached order

#### `managedAccounts()` callback (lines 297-316)
Logs:
- Accounts received from IB
- Current selected account
- When `reqAccountUpdates()` and `reqAutoOpenOrders()` are called

#### `get_orders()` method (lines 474-500)
Logs:
- Total orders in cache when method is called
- All cache keys
- Each order being processed
- Filtering decisions (account mismatch, closed orders)
- Final count of returned orders

## How to Use

### Normal Operations (Debug Disabled)
By default, the debug logger is silent. Just run your application normally:
```bash
python main.py
```

### Enable Debug Logging (When Investigating Issues)

To enable debug output, change the logging level in **TWO places**:

1. **In `src/ib_connection.py` (line 22)**:
   ```python
   debug_logger.setLevel(logging.DEBUG)  # Change from logging.ERROR
   ```

2. **In `main.py` (line 123)** when calling setup_debug_logger:
   ```python
   setup_debug_logger("order_cache_debug", log_dir, level=logging.DEBUG)
   ```

Then run your application and check the debug log:
   ```bash
   cat logs/default/order_cache_debug.log
   ```
   Or watch it in real-time:
   ```bash
   tail -f logs/default/order_cache_debug.log
   ```

3. **Look for patterns**:
   - Are `openOrder()` callbacks being received?
   - How many orders are being added to cache?
   - Are orders being filtered out due to account mismatch?
   - What are the cache keys when `get_orders()` is called?

## Expected Debug Output

When working correctly, you should see:
```
[ORDER_CACHE] Calling reqAllOpenOrders()
[ORDER_CACHE] openOrder() called: orderId=X, symbol=Y, ...
[ORDER_CACHE] ADDING to cache: orderId=X
[ORDER_CACHE] Cache size after add: N
[ORDER_CACHE] get_orders() called
[ORDER_CACHE] Total orders in cache: N
[ORDER_CACHE] Returning N orders
```

## Cleanup

To remove all debug instrumentation:
1. Delete `DEBUG_ORDER_CACHE.md`
2. Remove `order_cache_debug` logger setup from `main.py` (lines 121-123)
3. Remove `setup_debug_logger()` function from `src/logging_config.py`
4. Remove all `debug_logger.info()` calls from `src/ib_connection.py`
5. Remove `debug_logger` variable declaration from `src/ib_connection.py` (lines 19-21)