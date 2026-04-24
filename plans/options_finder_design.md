# OptionsFinder Design Specification

## Executive Summary

This document outlines the design for `OptionsFinder`, a utility class that encapsulates Interactive Brokers API interactions for finding and resolving options contracts. It consolidates common patterns from [`FkkBot`](../src/bots/fkk/bot.py) and [`DoubleCalendarBot`](../src/bots/double_calendar/bot.py).

## Current State Analysis

### Common Patterns Identified

Both bots perform similar operations:

1. **Option Chain Resolution** (lines 188-194 in fkk/bot.py, lines 68 in double_calendar/bot.py)
   - Request option chain via [`IBConnection.request_option_chain()`](../src/ib_connection.py:462-467)
   - Filter by exchange and trading class
   - Handle timeout scenarios

2. **Contract Resolution** (lines 225-238 in fkk/bot.py, lines 134-148 in double_calendar/bot.py)
   - Create partial contract specifications
   - Request full contract details via [`BaseBot.resolve_contracts()`](../src/bots/base_bot.py:81-89)
   - Track pending resolutions with `ContractResolutionStatus`

3. **Market Data Subscription for Greeks** (lines 248-249 in fkk/bot.py, lines 125-127 in double_calendar/bot.py)
   - Subscribe to market data with generic tick list "101,106" (option greeks)
   - Wait for [`tick_option_computation()`](../src/bots/base_bot.py:122-123) callbacks
   - Cache price and greeks data
   - Unsubscribe after receiving data

4. **Delta-Based Selection** (lines 284-327 in fkk/bot.py, lines 217-278 in double_calendar/bot.py)
   - Filter contracts by delta thresholds
   - Find closest match to target delta
   - Handle iterative refinement when initial strikes don't meet criteria

### IBAPI Asynchronous Pattern

The Interactive Brokers API uses a request/response pattern:

**Request Methods (EClient):**
- `reqSecDefOptParams()` - Request option chain
- `reqContractDetails()` - Request contract details
- `reqMktData()` - Subscribe to market data

**Response Methods (EWrapper):**
- `securityDefinitionOptionParameter()` + `securityDefinitionOptionParameterEnd()`
- `contractDetails()` + `contractDetailsEnd()`
- `tickPrice()`, `tickOptionComputation()`

**Current Implementation:**
- [`IBConnection`](../src/ib_connection.py) implements both EClient and EWrapper
- Uses `request_listeners` dict to route callbacks to requesting bots
- [`BaseBot`](../src/bots/base_bot.py) acts as listener, implementing callback methods
- Callbacks are dispatched through [`IBConnection`](../src/ib_connection.py:113-115, 144-148, 164-172)

## OptionsFinder Architecture

### Design Principles

1. **Singleton Pattern**: Single instance shared across all bots
2. **Asynchronous by Design**: All methods return immediately, results via callbacks
3. **Smart Caching**: Cache static data (option chains, resolved contracts) with TTL
4. **Thread-Safe**: Support concurrent requests from multiple bots
5. **Transparent Multiplexing**: Consolidate duplicate requests automatically

### Class Structure

```python
class OptionsFinder:
    """
    Utility class for finding and resolving options contracts.
    Encapsulates IB API interactions and provides caching.
    """
    
    def __init__(self, ib_connection: IBConnection):
        self.ib_connection = ib_connection
        
        # Caches with TTL
        self._option_chain_cache: Dict[str, CachedOptionChain] = {}
        self._resolved_contracts_cache: Dict[str, CachedContract] = {}
        
        # Active request tracking
        self._pending_chain_requests: Dict[int, ChainRequest] = {}
        self._pending_contract_requests: Dict[int, ContractRequest] = {}
        self._pending_greeks_requests: Dict[int, GreeksRequest] = {}
        
        # Thread safety
        self._lock = threading.RLock()
```

### Caching Strategy

#### 1. Option Chain Cache

**Key:** `f"{underlying.symbol}_{underlying.conId}_{exchange}_{tradingClass}"`

**TTL:** Until market close (option chains don't change intraday)

**Data Structure:**
```python
@dataclass
class CachedOptionChain:
    underlying_symbol: str
    underlying_conid: int
    exchange: str
    trading_class: str
    multiplier: str
    expirations: Set[str]
    strikes: Set[float]
    cached_at: datetime
    expires_at: datetime
```

**Rationale:** Option chains (available strikes and expirations) are static during trading hours. Cache until market close to avoid repeated API calls.

#### 2. Resolved Contract Cache

**Key:** `f"{symbol}_{secType}_{exchange}_{strike}_{right}_{expiry}"`

**TTL:** 24 hours

**Data Structure:**
```python
@dataclass
class CachedContract:
    contract: Contract  # Fully resolved with conId
    contract_details: ContractDetails
    cached_at: datetime
    expires_at: datetime
```

**Rationale:** Contract IDs don't change. Once resolved, cache for the day.

#### 3. Greeks/Price Data - NO CACHING

**Rationale:** Market data (prices, greeks) changes constantly. Always fetch fresh data. However, we can multiplex concurrent requests for the same contract.

### Method Signatures

#### 1. get_option_chain()

```python
def get_option_chain(
    self,
    underlying: Contract,
    callback: Callable[[List[OptionChainData]], None],
    exchange: Optional[str] = None,
    trading_class: Optional[str] = None,
    timeout_ms: int = 5000
) -> int:
    """
    Request option chain for an underlying contract.
    
    Args:
        underlying: The underlying contract (must have conId set)
        callback: Function called with list of OptionChainData when complete
        exchange: Filter by exchange (e.g., "CBOE", "SMART")
        trading_class: Filter by trading class (e.g., "SPXW")
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(option_chains: List[OptionChainData])
        
    OptionChainData structure:
        - exchange: str
        - underlying_conid: int
        - trading_class: str
        - multiplier: str
        - expirations: Set[str]  # YYYYMMDD format
        - strikes: Set[float]
    """
```

**Implementation Notes:**
- Check cache first using cache key
- If cached and not expired, call callback immediately with cached data
- If not cached, check if request already pending (multiplex)
- If new request, call [`IBConnection.request_option_chain()`](../src/ib_connection.py:462-467)
- Implement timeout using timer
- Filter results by exchange/trading_class if specified

#### 2. resolve_contract()

```python
def resolve_contract(
    self,
    partial_contract: Contract,
    callback: Callable[[Optional[Contract], Optional[ContractDetails]], None],
    timeout_ms: int = 5000
) -> int:
    """
    Resolve a partial contract specification to a fully qualified contract.
    
    Args:
        partial_contract: Contract with symbol, secType, strike, right, expiry, etc.
        callback: Function called with resolved contract and details
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(contract: Optional[Contract], details: Optional[ContractDetails])
        Returns None, None if resolution fails
    """
```

**Implementation Notes:**
- Generate cache key from contract attributes
- Check cache first
- If not cached, call [`IBConnection.request_contract_details()`](../src/ib_connection.py:454-459)
- Handle multiple matches (log warning, return first)
- Handle no matches (return None, None)
- Cache successful resolutions

#### 3. find_option_by_delta() - CHUNKED ITERATIVE APPROACH

```python
def find_option_by_delta(
    self,
    underlying: Contract,
    underlying_price: float,
    target_delta: float,
    right: str,  # "C" or "P"
    expiration: str,  # YYYYMMDD
    callback: Callable[[Optional[Contract], Optional[Dict]], None],
    exchange: Optional[str] = "SMART",
    trading_class: Optional[str] = None,
    strike_range: Optional[Tuple[float, float]] = None,
    max_strikes_per_chunk: int = 10,
    timeout_ms: int = 10000
) -> int:
    """
    Find option contract with delta closest to target using iterative chunked approach.
    
    This method intelligently walks toward the target delta by requesting strikes in chunks,
    evaluating their deltas, and iterating until the target is bracketed.
    
    Algorithm:
    1. Assume underlying_price corresponds to delta ±0.5 (ATM)
    2. Determine direction to walk based on target_delta:
       - For puts with target_delta > -0.5: walk down (strikes below underlying)
       - For puts with target_delta < -0.5: walk up (strikes above underlying)
       - For calls with target_delta < 0.5: walk up (strikes above underlying)
       - For calls with target_delta > 0.5: walk down (strikes below underlying)
    3. Request max_strikes_per_chunk strikes in that direction
    4. Get deltas for those strikes
    5. Check if target is bracketed (at least one delta closer to/further from 0 than target)
    6. If not bracketed, request next chunk in same direction
    7. Once bracketed, select strike with delta closest to target
    
    Args:
        underlying: The underlying contract
        underlying_price: Current price of underlying (used as delta ±0.5 reference)
        target_delta: Target delta value (e.g., -0.35 for puts, 0.16 for calls)
        right: "C" for call, "P" for put
        expiration: Expiration date in YYYYMMDD format
        callback: Function called with best match contract and greeks
        exchange: Exchange to use (default "SMART")
        trading_class: Trading class filter (e.g., "SPXW")
        strike_range: Optional (min_strike, max_strike) to limit search
        max_strikes_per_chunk: Maximum strikes to evaluate per iteration (default 10)
        timeout_ms: Timeout in milliseconds for entire operation
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(contract: Optional[Contract], greeks: Optional[Dict])
        
    Greeks dict structure:
        {
            'delta': float,
            'gamma': float,
            'vega': float,
            'theta': float,
            'impliedVol': float,
            'optPrice': float,
            'undPrice': float,
            'bid': float,
            'ask': float
        }
        
    Example for puts:
        - underlying_price = 5800, target_delta = -0.35 (> -0.5, closer to 0)
        - First chunk: strikes [5795, 5790, 5785, ..., 5750] (below underlying)
        - If highest delta received is -0.40 (< -0.35), target is bracketed
        - Select strike with delta closest to -0.35
        
        - underlying_price = 5800, target_delta = -0.65 (< -0.5, further from 0)
        - First chunk: strikes [5805, 5810, 5815, ..., 5850] (above underlying)
        - If lowest delta received is -0.60 (> -0.65), need next chunk
        - Second chunk: strikes [5855, 5860, ..., 5900]
        - Once delta <= -0.65 found, target is bracketed
        - Select strike with delta closest to -0.65
    """
```

**Implementation Algorithm:**

**Phase 1: Determine Walk Direction**
```python
# For puts: delta is negative, closer to 0 means higher strike
# For calls: delta is positive, closer to 0 means lower strike
if right == "P":
    if target_delta > -0.5:  # Closer to 0 than ATM
        walk_direction = "down"  # Lower strikes (higher deltas, closer to 0)
        start_strike = underlying_price - 5  # Start just below ATM
    else:  # Further from 0 than ATM (target_delta < -0.5)
        walk_direction = "up"  # Higher strikes (lower deltas, further from 0)
        start_strike = underlying_price + 5  # Start just above ATM
else:  # Calls
    if target_delta < 0.5:  # Closer to 0 than ATM
        walk_direction = "up"  # Higher strikes (lower deltas, closer to 0)
        start_strike = underlying_price + 5
    else:  # Further from 0 than ATM (target_delta > 0.5)
        walk_direction = "down"  # Lower strikes (higher deltas, further from 0)
        start_strike = underlying_price - 5
```

**Phase 2: Iterative Chunk Processing**
```python
current_strike = start_strike
all_evaluated_contracts = {}  # conId -> (contract, greeks)
iteration = 0
max_iterations = 5  # Safety limit

while iteration < max_iterations:
    # Get next chunk of strikes from option chain
    strikes = get_next_strike_chunk(
        current_strike, 
        walk_direction, 
        max_strikes_per_chunk,
        strike_range,
        available_strikes_from_chain
    )
    
    if not strikes:
        break  # No more strikes available
    
    # Resolve contracts and get greeks for this chunk
    contracts_with_greeks = await_greeks_for_strikes(strikes, expiration, right)
    all_evaluated_contracts.update(contracts_with_greeks)
    
    # Check if target is bracketed
    deltas = [g['delta'] for c, g in contracts_with_greeks.values()]
    
    if right == "P":
        if target_delta > -0.5:
            # Need at least one delta > target_delta (closer to 0)
            # Example: target=-0.35, need delta like -0.30
            bracketed = any(d > target_delta for d in deltas)
        else:
            # Need at least one delta < target_delta (further from 0)
            # Example: target=-0.65, need delta like -0.70
            bracketed = any(d < target_delta for d in deltas)
    else:  # Calls
        if target_delta < 0.5:
            # Need at least one delta < target_delta (closer to 0)
            # Example: target=0.35, need delta like 0.30
            bracketed = any(d < target_delta for d in deltas)
        else:
            # Need at least one delta > target_delta (further from 0)
            # Example: target=0.65, need delta like 0.70
            bracketed = any(d > target_delta for d in deltas)
    
    if bracketed:
        break  # Found range containing target
    
    # Move to next chunk
    if walk_direction in ["down", "up"]:
        current_strike = strikes[-1]  # Continue from last strike
    iteration += 1
```

**Phase 3: Select Best Match**
```python
# Find contract with delta closest to target
best_contract = None
best_greeks = None
min_distance = float('inf')

for contract, greeks in all_evaluated_contracts.values():
    distance = abs(greeks['delta'] - target_delta)
    if distance < min_distance:
        min_distance = distance
        best_contract = contract
        best_greeks = greeks

callback(best_contract, best_greeks)
```

**Phase 4: Cleanup**
- Unsubscribe from all market data subscriptions
- Clear temporary tracking structures

#### 4. find_atm_option()

```python
def find_atm_option(
    self,
    underlying: Contract,
    underlying_price: float,
    right: str,  # "C" or "P"
    expiration: str,  # YYYYMMDD
    callback: Callable[[Optional[Contract], Optional[Dict]], None],
    exchange: Optional[str] = "SMART",
    trading_class: Optional[str] = None,
    timeout_ms: int = 10000
) -> int:
    """
    Find at-the-money option (strike closest to underlying price).
    
    Args:
        underlying: The underlying contract
        underlying_price: Current price of underlying
        right: "C" for call, "P" for put
        expiration: Expiration date in YYYYMMDD format
        callback: Function called with ATM contract and greeks
        exchange: Exchange to use (default "SMART")
        trading_class: Trading class filter
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(contract: Optional[Contract], greeks: Optional[Dict])
    """
```

**Implementation Notes:**
- Get option chain
- Find strike closest to underlying_price
- Resolve that specific contract
- Get greeks for that contract
- Call callback

#### 5. find_later_contract()

```python
def find_later_contract(
    self,
    current_contract: Contract,
    days_later: int,
    callback: Callable[[Optional[Contract], Optional[Dict]], None],
    same_strike: bool = True,
    target_delta: Optional[float] = None,
    underlying_price: Optional[float] = None,
    timeout_ms: int = 10000
) -> int:
    """
    Find a later-dated contract for rolling or calendar spreads.
    
    Args:
        current_contract: The current option contract
        days_later: Minimum days later for new expiration
        callback: Function called with later contract and greeks
        same_strike: If True, find same strike; if False, use target_delta
        target_delta: If same_strike=False, target delta for new contract
        underlying_price: Required if same_strike=False
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(contract: Optional[Contract], greeks: Optional[Dict])
    """
```

**Implementation Notes:**
- Parse current contract's expiration
- Get option chain for underlying
- Find expirations >= days_later from current
- If same_strike: resolve contract with same strike, new expiration
- If target_delta: use find_option_by_delta() for new expiration
- Get greeks
- Call callback

#### 6. get_contract_greeks()

```python
def get_contract_greeks(
    self,
    contracts: List[Contract],
    callback: Callable[[Dict[int, Dict]], None],
    timeout_ms: int = 5000
) -> int:
    """
    Get current greeks for one or more contracts.
    
    Args:
        contracts: List of contracts to get greeks for
        callback: Function called with dict mapping conId to greeks
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Request ID for tracking
        
    Callback signature:
        callback(greeks_by_conid: Dict[int, Dict])
        
    Each greeks dict contains:
        {
            'delta': float,
            'gamma': float,
            'vega': float,
            'theta': float,
            'impliedVol': float,
            'optPrice': float,
            'undPrice': float,
            'bid': float,
            'ask': float
        }
    """
```

**Implementation Notes:**
- Subscribe to market data for all contracts with "101,106"
- Track which contracts have received greeks
- When all received or timeout, unsubscribe all
- Call callback with collected data

### Request Multiplexing

When multiple bots request the same data simultaneously:

1. **Option Chain Requests**: If request for same underlying+exchange+tradingClass is pending, add callback to existing request
2. **Contract Resolution**: If request for same contract specification is pending, add callback to existing request
3. **Greeks Requests**: If subscription already exists for a contract, reuse it and add callback

### Error Handling

All callbacks should handle errors gracefully:

```python
# Success case
callback(contract, greeks)

# Failure cases
callback(None, None)  # Resolution failed
callback(contract, None)  # Contract found but no greeks
```

Errors logged but not raised to avoid disrupting other bots.

### Integration with Existing Code

#### BaseBot Integration

Add to [`BaseBot`](../src/bots/base_bot.py):

```python
class BaseBot:
    def __init__(self, config, ib_connection, timer_manager, config_dir):
        # ... existing code ...
        self.options_finder = OptionsFinder(ib_connection)
```

#### Migration Path for FkkBot

Current code (lines 188-327):
```python
# Old approach
self.resolve_option_chain(...)
self._resolve_option_contracts(...)
# Wait for callbacks
# Subscribe to market data
# Wait for greeks
# Select by delta
```

New approach:
```python
# New approach - single method call!
self.options_finder.find_option_by_delta(
    underlying=self.underlying_contract,
    underlying_price=self.historical_bars[-1].close,
    target_delta=self.config.delta,
    right="P",
    expiration=expiration_str,
    callback=self.on_short_contract_found,
    trading_class="SPXW",
    exchange="CBOE",
    max_strikes_per_chunk=10
)

def on_short_contract_found(self, contract, greeks):
    if contract:
        self.short_contract = contract
        # Find long contract at specific strike
        long_strike = self.short_contract.strike - self.config.width
        self.options_finder.find_option_by_delta(
            underlying=self.underlying_contract,
            underlying_price=self.historical_bars[-1].close,
            target_delta=self.config.delta,  # Same delta
            right="P",
            expiration=expiration_str,
            callback=self.on_long_contract_found,
            strike_range=(long_strike, long_strike),  # Exact strike
            max_strikes_per_chunk=1
        )
```

#### Migration Path for DoubleCalendarBot

Similar simplification - replace manual chain resolution, contract resolution, and greeks fetching with single method calls.

## Implementation Plan

### Phase 1: Core Infrastructure
1. Create `src/utils/options_finder.py`
2. Implement caching data structures
3. Implement request tracking structures
4. Add thread safety mechanisms

### Phase 2: Basic Methods
1. Implement `get_option_chain()` with caching
2. Implement `resolve_contract()` with caching
3. Implement `get_contract_greeks()` without caching

### Phase 3: High-Level Methods
1. Implement `find_option_by_delta()` with chunked algorithm
2. Implement `find_atm_option()`
3. Implement `find_later_contract()`

### Phase 4: Integration
1. Add OptionsFinder to BaseBot
2. Update FkkBot to use OptionsFinder
3. Update DoubleCalendarBot to use OptionsFinder

### Phase 5: Testing & Refinement
1. Test with both bots in demo mode
2. Verify caching behavior
3. Verify multiplexing behavior
4. Verify chunked algorithm efficiency
5. Performance optimization

## Benefits

1. **Code Reduction**: ~200 lines per bot reduced to ~20 lines
2. **Consistency**: Same logic for all bots
3. **Performance**: Caching reduces API calls
4. **Efficiency**: Chunked algorithm minimizes strikes evaluated
5. **Maintainability**: Single place to fix bugs
6. **Testability**: Isolated component easier to test
7. **Reusability**: New bots can use immediately

## Considerations

### Thread Safety
- All public methods must be thread-safe
- Use `threading.RLock()` for cache access
- Callbacks may be invoked from IB API thread

### Memory Management
- Implement cache cleanup for expired entries
- Limit cache size if needed
- Unsubscribe from market data promptly

### API Rate Limits
- IB limits: 50 messages/second
- OptionsFinder should respect this
- Chunked algorithm helps by evaluating fewer strikes

### Timeout Handling
- All methods have configurable timeouts
- Use TimerManager for timeout callbacks
- Clean up resources on timeout

## Future Enhancements

1. **Batch Operations**: `find_multiple_options_by_delta()` for efficiency
2. **Spread Helpers**: `find_vertical_spread()`, `find_calendar_spread()`
3. **Strategy Helpers**: `find_iron_condor()`, `find_butterfly()`
4. **Analytics**: Track cache hit rates, API call counts, chunk iterations
5. **Persistence**: Save/restore cache across restarts
6. **Adaptive Chunking**: Adjust chunk size based on strike spacing