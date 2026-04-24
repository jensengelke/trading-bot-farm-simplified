"""
OptionsFinder - Centralized utility for option contract discovery and selection.

This module provides a reusable, thread-safe utility class for finding and resolving
option contracts with intelligent caching and delta-based selection algorithms.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, List, Set, Tuple, Any
from dataclasses import dataclass, field
from ibapi.contract import Contract, ContractDetails
import pytz
from src.utils import trace

logger = logging.getLogger(__name__)


@dataclass
class CachedOptionChain:
    """Cached option chain data with TTL."""
    exchange: str
    underlying_con_id: int
    trading_class: str
    multiplier: str
    expirations: Set[str]
    strikes: Set[float]
    cached_at: datetime
    ttl_seconds: int = 28800  # 8 hours (until market close)
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return (datetime.now() - self.cached_at).total_seconds() > self.ttl_seconds


@dataclass
class CachedContract:
    """Cached resolved contract with TTL."""
    contract: Contract
    contract_details: ContractDetails
    cached_at: datetime
    ttl_seconds: int = 86400  # 24 hours
    
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return (datetime.now() - self.cached_at).total_seconds() > self.ttl_seconds


@dataclass
class GreeksData:
    """Option greeks and pricing data."""
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    implied_vol: Optional[float] = None
    opt_price: Optional[float] = None
    und_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class PendingRequest:
    """Tracks a pending request with callbacks and timeout."""
    request_id: int
    callbacks: List[Callable]
    timer_id: Optional[str] = None
    data: Any = None
    completed: bool = False


class OptionsFinder:
    """
    Centralized utility for option contract discovery and selection.
    
    Features:
    - Smart caching with TTL for chains and contracts
    - Thread-safe for concurrent bot access
    - Transparent request multiplexing
    - Intelligent chunked delta search algorithm
    - Asynchronous callback-based API
    """
    
    @trace
    def __init__(self, ib_connection, timer_manager):
        """
        Initialize OptionsFinder.
        
        Args:
            ib_connection: IBConnection instance for API calls
            timer_manager: TimerManager instance for timeouts
        """
        self.ib_connection = ib_connection
        self.timer_manager = timer_manager
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Caches
        self._option_chain_cache: Dict[str, CachedOptionChain] = {}
        self._contract_cache: Dict[str, CachedContract] = {}
        
        # Request tracking
        self._pending_chain_requests: Dict[int, PendingRequest] = {}
        self._pending_contract_requests: Dict[int, PendingRequest] = {}
        self._pending_greeks_requests: Dict[int, PendingRequest] = {}
        
        # Market data subscriptions for greeks
        self._greeks_subscriptions: Dict[int, Dict[str, Any]] = {}
        
        logger.info("OptionsFinder initialized")
    
    @trace
    def _make_chain_cache_key(self, symbol: str, con_id: int, exchange: str, trading_class: str) -> str:
        """Generate cache key for option chain."""
        return f"{symbol}_{con_id}_{exchange}_{trading_class}"
    
    @trace
    def _make_contract_cache_key(self, contract: Contract) -> str:
        """Generate cache key for contract."""
        return f"{contract.symbol}_{contract.secType}_{contract.strike}_{contract.right}_{contract.lastTradeDateOrContractMonth}"
    
    @trace
    def get_option_chain(
        self,
        underlying: Contract,
        callback: Callable[[Optional[Dict]], None],
        exchange: str = "",
        trading_class: str = "",
        timeout_ms: int = 5000
    ):
        """
        Get option chain (strikes and expirations) for an underlying.
        
        Args:
            underlying: Underlying contract (must have conId)
            callback: Called with chain data dict or None on error
            exchange: Exchange filter (empty for all)
            trading_class: Trading class filter (empty for all)
            timeout_ms: Request timeout in milliseconds
        """
        if not underlying.conId:
            logger.error("Underlying contract must have conId set")
            callback(None)
            return
        
        # Check cache
        cache_key = self._make_chain_cache_key(
            underlying.symbol, underlying.conId, exchange, trading_class
        )
        
        with self._lock:
            if cache_key in self._option_chain_cache:
                cached = self._option_chain_cache[cache_key]
                if not cached.is_expired():
                    logger.debug(f"Option chain cache hit for {cache_key}")
                    callback({
                        'exchange': cached.exchange,
                        'underlyingConId': cached.underlying_con_id,
                        'tradingClass': cached.trading_class,
                        'multiplier': cached.multiplier,
                        'expirations': cached.expirations,
                        'strikes': cached.strikes
                    })
                    return
                else:
                    logger.debug(f"Option chain cache expired for {cache_key}")
                    del self._option_chain_cache[cache_key]
        
        # Make API request
        req_id = self.ib_connection.request_option_chain(
            self, underlying.symbol, exchange, underlying.secType, underlying.conId
        )
        
        with self._lock:
            self._pending_chain_requests[req_id] = PendingRequest(
                request_id=req_id,
                callbacks=[callback],
                data={'cache_key': cache_key, 'results': []}
            )
        
        # Set timeout
        if timeout_ms > 0:
            self._set_timeout(req_id, timeout_ms, self._on_chain_timeout)
        
        logger.debug(f"Requested option chain for {underlying.symbol} (reqId: {req_id})")
    
    @trace
    def resolve_contract(
        self,
        partial_contract: Contract,
        callback: Callable[[Optional[Contract], Optional[ContractDetails]], None],
        timeout_ms: int = 5000
    ):
        """
        Resolve a partial contract specification to a fully qualified contract.
        
        Args:
            partial_contract: Contract with partial details (symbol, strike, expiry, etc.)
            callback: Called with (contract, contract_details) or (None, None) on error
            timeout_ms: Request timeout in milliseconds
        """
        # Check cache
        cache_key = self._make_contract_cache_key(partial_contract)
        
        with self._lock:
            if cache_key in self._contract_cache:
                cached = self._contract_cache[cache_key]
                if not cached.is_expired():
                    logger.debug(f"Contract cache hit for {cache_key}")
                    callback(cached.contract, cached.contract_details)
                    return
                else:
                    logger.debug(f"Contract cache expired for {cache_key}")
                    del self._contract_cache[cache_key]
        
        # Make API request
        req_id = self.ib_connection.request_contract_details(self, partial_contract)
        
        with self._lock:
            self._pending_contract_requests[req_id] = PendingRequest(
                request_id=req_id,
                callbacks=[callback],
                data={'cache_key': cache_key, 'results': []}
            )
        
        # Set timeout
        if timeout_ms > 0:
            self._set_timeout(req_id, timeout_ms, self._on_contract_timeout)
        
        logger.debug(f"Requested contract details for {partial_contract.symbol} (reqId: {req_id})")
    
    @trace
    def get_contract_greeks(
        self,
        contracts: List[Contract],
        callback: Callable[[Dict[int, Tuple[Contract, GreeksData]]], None],
        timeout_ms: int = 10000
    ):
        """
        Get greeks for multiple option contracts.
        
        Args:
            contracts: List of contracts to get greeks for (must have conId)
            callback: Called with dict mapping conId -> (contract, greeks_data)
            timeout_ms: Request timeout in milliseconds
        """
        if not contracts:
            callback({})
            return
        
        # Generate a unique request ID for this batch
        batch_id = self.ib_connection.get_next_req_id()
        
        with self._lock:
            self._pending_greeks_requests[batch_id] = PendingRequest(
                request_id=batch_id,
                callbacks=[callback],
                data={
                    'contracts': {c.conId: c for c in contracts},
                    'greeks': {},
                    'pending_count': len(contracts)
                }
            )
        
        # Subscribe to market data for each contract
        for contract in contracts:
            if not contract.conId:
                logger.error(f"Contract must have conId: {contract.symbol}")
                continue
            
            req_id = self.ib_connection.subscribe_market_data(self, contract, "101,106")
            
            with self._lock:
                self._greeks_subscriptions[req_id] = {
                    'batch_id': batch_id,
                    'contract': contract
                }
        
        # Set timeout
        if timeout_ms > 0:
            self._set_timeout(batch_id, timeout_ms, self._on_greeks_timeout)
        
        logger.debug(f"Requested greeks for {len(contracts)} contracts (batchId: {batch_id})")
    
    @trace
    def find_option_by_delta(
        self,
        underlying: Contract,
        underlying_price: float,
        target_delta: float,
        right: str,
        expiration: str,
        callback: Callable[[Optional[Contract], Optional[GreeksData]], None],
        exchange: str = "",
        trading_class: str = "",
        strike_range: Optional[Tuple[float, float]] = None,
        max_strikes_per_chunk: int = 10,
        timeout_ms: int = 15000
    ):
        """
        Find option contract closest to target delta using chunked search.
        
        Algorithm:
        1. Assume ATM = ±0.5 delta at underlying price
        2. Determine walk direction based on target delta
        3. Request strikes in chunks (default 10 per iteration)
        4. Check if target is bracketed (found deltas on both sides)
        5. Iterate if needed until target is bracketed
        6. Select best match from all evaluated strikes
        
        Args:
            underlying: Underlying contract
            underlying_price: Current price of underlying
            target_delta: Target delta to find (e.g., -0.35 for puts, 0.35 for calls)
            right: "P" for put, "C" for call
            expiration: Expiration date in YYYYMMDD format
            callback: Called with (contract, greeks) or (None, None) if not found
            exchange: Exchange filter
            trading_class: Trading class filter
            strike_range: Optional (min_strike, max_strike) to limit search
            max_strikes_per_chunk: Number of strikes to evaluate per iteration
            timeout_ms: Total timeout for the entire search
        """
        # Validate inputs
        if right not in ["P", "C"]:
            logger.error(f"Invalid right: {right}. Must be 'P' or 'C'")
            callback(None, None)
            return
        
        # Start by getting the option chain
        def on_chain_received(chain_data):
            if not chain_data:
                logger.error("Failed to get option chain")
                callback(None, None)
                return
            
            if expiration not in chain_data['expirations']:
                logger.error(f"Expiration {expiration} not in chain")
                callback(None, None)
                return
            
            # Filter strikes by range if provided
            available_strikes = sorted(chain_data['strikes'])
            if strike_range:
                min_strike, max_strike = strike_range
                available_strikes = [s for s in available_strikes if min_strike <= s <= max_strike]
            
            if not available_strikes:
                logger.error("No strikes available in specified range")
                callback(None, None)
                return
            
            # Start chunked search
            self._chunked_delta_search(
                underlying=underlying,
                underlying_price=underlying_price,
                target_delta=target_delta,
                right=right,
                expiration=expiration,
                available_strikes=available_strikes,
                exchange=exchange,
                trading_class=trading_class,
                max_strikes_per_chunk=max_strikes_per_chunk,
                callback=callback,
                timeout_ms=timeout_ms
            )
        
        self.get_option_chain(underlying, on_chain_received, exchange, trading_class, timeout_ms)
    
    @trace
    def _chunked_delta_search(
        self,
        underlying: Contract,
        underlying_price: float,
        target_delta: float,
        right: str,
        expiration: str,
        available_strikes: List[float],
        exchange: str,
        trading_class: str,
        max_strikes_per_chunk: int,
        callback: Callable,
        timeout_ms: int,
        evaluated_strikes: Optional[Dict[float, Tuple[Contract, GreeksData]]] = None,
        iteration: int = 0
    ):
        """Internal method for chunked delta search algorithm."""
        if evaluated_strikes is None:
            evaluated_strikes = {}
        
        # Determine ATM strike (closest to underlying price)
        atm_strike = min(available_strikes, key=lambda s: abs(s - underlying_price))
        atm_index = available_strikes.index(atm_strike)
        
        # Determine walk direction based on target delta
        # For puts: delta is negative, more negative = more ITM (higher strike)
        # For calls: delta is positive, more positive = more ITM (lower strike)
        if right == "P":
            # Put: if target_delta > -0.5 (e.g., -0.35), walk DOWN (lower strikes, higher deltas)
            # Put: if target_delta < -0.5 (e.g., -0.65), walk UP (higher strikes, lower deltas)
            walk_up = target_delta < -0.5
        else:
            # Call: if target_delta > 0.5 (e.g., 0.65), walk DOWN (lower strikes, higher deltas)
            # Call: if target_delta < 0.5 (e.g., 0.35), walk UP (higher strikes, lower deltas)
            walk_up = target_delta < 0.5
        
        # Select next chunk of strikes
        if walk_up:
            start_idx = atm_index
            end_idx = min(atm_index + max_strikes_per_chunk, len(available_strikes))
            chunk_strikes = available_strikes[start_idx:end_idx]
        else:
            start_idx = max(0, atm_index - max_strikes_per_chunk + 1)
            end_idx = atm_index + 1
            chunk_strikes = available_strikes[start_idx:end_idx]
        
        # Filter out already evaluated strikes
        chunk_strikes = [s for s in chunk_strikes if s not in evaluated_strikes]
        
        if not chunk_strikes:
            # No more strikes to evaluate, select best from what we have
            self._select_best_delta_match(evaluated_strikes, target_delta, callback)
            return
        
        logger.debug(f"Iteration {iteration}: Evaluating {len(chunk_strikes)} strikes around {atm_strike}")
        
        # Create contracts for this chunk
        contracts = []
        for strike in chunk_strikes:
            contract = Contract()
            contract.symbol = underlying.symbol
            contract.secType = "OPT"
            contract.exchange = exchange if exchange else "SMART"
            contract.currency = underlying.currency
            contract.lastTradeDateOrContractMonth = expiration
            contract.strike = strike
            contract.right = right
            contracts.append(contract)
        
        # Resolve contracts and get greeks
        def on_contracts_resolved(resolved_contracts):
            if not resolved_contracts:
                logger.error("Failed to resolve contracts in chunk")
                callback(None, None)
                return
            
            # Get greeks for resolved contracts
            def on_greeks_received(greeks_dict):
                # Add to evaluated strikes
                for con_id, (contract, greeks) in greeks_dict.items():
                    if greeks.delta is not None:
                        evaluated_strikes[contract.strike] = (contract, greeks)
                
                # Check if we've bracketed the target
                deltas = [g.delta for _, g in evaluated_strikes.values() if g.delta is not None]
                if not deltas:
                    logger.error("No valid deltas received")
                    callback(None, None)
                    return
                
                min_delta = min(deltas)
                max_delta = max(deltas)
                
                is_bracketed = min_delta <= target_delta <= max_delta
                
                if is_bracketed or iteration >= 3:  # Max 3 iterations
                    # Select best match
                    self._select_best_delta_match(evaluated_strikes, target_delta, callback)
                else:
                    # Continue search with remaining strikes
                    remaining_strikes = [s for s in available_strikes if s not in evaluated_strikes]
                    if not remaining_strikes:
                        self._select_best_delta_match(evaluated_strikes, target_delta, callback)
                    else:
                        # Recurse with updated ATM based on current findings
                        self._chunked_delta_search(
                            underlying, underlying_price, target_delta, right, expiration,
                            remaining_strikes, exchange, trading_class, max_strikes_per_chunk,
                            callback, timeout_ms, evaluated_strikes, iteration + 1
                        )
            
            self.get_contract_greeks(resolved_contracts, on_greeks_received, timeout_ms)
        
        # Resolve all contracts in chunk
        self._resolve_multiple_contracts(contracts, on_contracts_resolved, timeout_ms)
    
    @trace
    def _resolve_multiple_contracts(
        self,
        contracts: List[Contract],
        callback: Callable[[List[Contract]], None],
        timeout_ms: int
    ):
        """Resolve multiple contracts in parallel."""
        resolved = []
        pending_count = len(contracts)
        lock = threading.Lock()
        
        def on_single_resolved(contract, contract_details):
            nonlocal pending_count
            with lock:
                if contract:
                    resolved.append(contract)
                pending_count -= 1
                if pending_count == 0:
                    callback(resolved)
        
        for contract in contracts:
            self.resolve_contract(contract, on_single_resolved, timeout_ms)
    
    @trace
    def _select_best_delta_match(
        self,
        evaluated_strikes: Dict[float, Tuple[Contract, GreeksData]],
        target_delta: float,
        callback: Callable
    ):
        """Select the contract with delta closest to target."""
        if not evaluated_strikes:
            logger.warning("No strikes evaluated")
            callback(None, None)
            return
        
        best_contract = None
        best_greeks = None
        best_distance = float('inf')
        
        for strike, (contract, greeks) in evaluated_strikes.items():
            if greeks.delta is None:
                continue
            distance = abs(greeks.delta - target_delta)
            if distance < best_distance:
                best_distance = distance
                best_contract = contract
                best_greeks = greeks
        
        if best_contract and best_greeks and best_greeks.delta is not None:
            logger.info(f"Found option: strike={best_contract.strike}, delta={best_greeks.delta:.4f}, target={target_delta:.4f}")
        else:
            logger.warning("No valid option found with delta")
        
        callback(best_contract, best_greeks)
    
    @trace
    def find_atm_option(
        self,
        underlying: Contract,
        underlying_price: float,
        right: str,
        expiration: str,
        callback: Callable[[Optional[Contract], Optional[GreeksData]], None],
        exchange: str = "",
        trading_class: str = "",
        timeout_ms: int = 15000
    ):
        """
        Find at-the-money option (delta closest to ±0.5).
        
        Args:
            underlying: Underlying contract
            underlying_price: Current price of underlying
            right: "P" for put, "C" for call
            expiration: Expiration date in YYYYMMDD format
            callback: Called with (contract, greeks) or (None, None) if not found
            exchange: Exchange filter
            trading_class: Trading class filter
            timeout_ms: Request timeout
        """
        target_delta = -0.5 if right == "P" else 0.5
        self.find_option_by_delta(
            underlying, underlying_price, target_delta, right, expiration,
            callback, exchange, trading_class, None, 10, timeout_ms
        )
    
    @trace
    def find_later_contract(
        self,
        current_contract: Contract,
        days_later: int,
        callback: Callable[[Optional[Contract], Optional[GreeksData]], None],
        same_strike: bool = True,
        target_delta: Optional[float] = None,
        underlying_price: Optional[float] = None,
        exchange: str = "",
        trading_class: str = "",
        timeout_ms: int = 15000
    ):
        """
        Find a contract with a later expiration.
        
        Args:
            current_contract: Current option contract
            days_later: Minimum days later for new expiration
            callback: Called with (contract, greeks) or (None, None) if not found
            same_strike: If True, use same strike; if False, use target_delta
            target_delta: Target delta for new contract (required if same_strike=False)
            underlying_price: Current underlying price (required if same_strike=False)
            exchange: Exchange filter
            trading_class: Trading class filter
            timeout_ms: Request timeout
        """
        if not same_strike and (target_delta is None or underlying_price is None):
            logger.error("target_delta and underlying_price required when same_strike=False")
            callback(None, None)
            return
        
        # Parse current expiration
        current_exp_str = current_contract.lastTradeDateOrContractMonth
        current_exp = datetime.strptime(current_exp_str, "%Y%m%d")
        target_exp = current_exp + timedelta(days=days_later)
        
        # Get underlying contract
        underlying = Contract()
        underlying.symbol = current_contract.symbol
        underlying.secType = "IND" if current_contract.symbol == "SPX" else "STK"
        underlying.currency = current_contract.currency
        underlying.exchange = ""
        
        # Resolve underlying to get conId
        def on_underlying_resolved(und_contract, und_details):
            if not und_contract:
                logger.error("Failed to resolve underlying")
                callback(None, None)
                return
            
            # Get option chain
            def on_chain_received(chain_data):
                if not chain_data:
                    logger.error("Failed to get option chain")
                    callback(None, None)
                    return
                
                # Find next expiration >= target
                expirations = sorted(chain_data['expirations'])
                next_exp = None
                for exp in expirations:
                    exp_date = datetime.strptime(exp, "%Y%m%d")
                    if exp_date >= target_exp:
                        next_exp = exp
                        break
                
                if not next_exp:
                    logger.error(f"No expiration found >= {target_exp.strftime('%Y%m%d')}")
                    callback(None, None)
                    return
                
                # Find contract
                if same_strike:
                    # Use same strike
                    contract = Contract()
                    contract.symbol = current_contract.symbol
                    contract.secType = "OPT"
                    contract.exchange = exchange if exchange else "SMART"
                    contract.currency = current_contract.currency
                    contract.lastTradeDateOrContractMonth = next_exp
                    contract.strike = current_contract.strike
                    contract.right = current_contract.right
                    
                    def on_resolved(resolved_contract, details):
                        if resolved_contract:
                            # Get greeks
                            self.get_contract_greeks(
                                [resolved_contract],
                                lambda greeks_dict: callback(
                                    resolved_contract,
                                    greeks_dict.get(resolved_contract.conId, (None, None))[1] if greeks_dict else None
                                ),
                                timeout_ms
                            )
                        else:
                            callback(None, None)
                    
                    self.resolve_contract(contract, on_resolved, timeout_ms)
                else:
                    # Find by delta (type check already done at function start)
                    if underlying_price is not None and target_delta is not None:
                        self.find_option_by_delta(
                            und_contract, underlying_price, target_delta,
                            current_contract.right, next_exp, callback,
                            exchange, trading_class, None, 10, timeout_ms
                        )
                    else:
                        callback(None, None)
            
            self.get_option_chain(und_contract, on_chain_received, exchange, trading_class, timeout_ms)
        
        self.resolve_contract(underlying, on_underlying_resolved, timeout_ms)
    
    # Callback handlers for IB API
    
    @trace
    def securityDefinitionOptionParameter(
        self, reqId: int, exchange: str, underlyingConId: int,
        tradingClass: str, multiplier: str, expirations: set, strikes: set
    ):
        """Handle option chain data from IB."""
        with self._lock:
            if reqId not in self._pending_chain_requests:
                return
            
            request = self._pending_chain_requests[reqId]
            request.data['results'].append({
                'exchange': exchange,
                'underlyingConId': underlyingConId,
                'tradingClass': tradingClass,
                'multiplier': multiplier,
                'expirations': expirations,
                'strikes': strikes
            })
    
    @trace
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        """Handle end of option chain data."""
        with self._lock:
            if reqId not in self._pending_chain_requests:
                return
            
            request = self._pending_chain_requests.pop(reqId)
            
            # Cancel timeout
            if request.timer_id:
                self.timer_manager.remove_timer(request.timer_id)
            
            results = request.data['results']
            cache_key = request.data['cache_key']
            
            if results:
                # Merge all results - combine expirations and strikes from all exchanges
                merged_expirations = set()
                merged_strikes = set()
                result = results[0]  # Use first result for metadata
                
                for r in results:
                    merged_expirations.update(r['expirations'])
                    merged_strikes.update(r['strikes'])
                
                # Create merged result
                merged_result = {
                    'exchange': result['exchange'],
                    'underlyingConId': result['underlyingConId'],
                    'tradingClass': result['tradingClass'],
                    'multiplier': result['multiplier'],
                    'expirations': merged_expirations,
                    'strikes': merged_strikes
                }
                
                # Log available expirations for debugging
                exp_list = sorted(list(merged_expirations))
                logger.info(f"Option chain received with {len(exp_list)} expirations from {len(results)} exchanges: {exp_list[:10]}{'...' if len(exp_list) > 10 else ''}")
                
                cached = CachedOptionChain(
                    exchange=result['exchange'],
                    underlying_con_id=result['underlyingConId'],
                    trading_class=result['tradingClass'],
                    multiplier=result['multiplier'],
                    expirations=merged_expirations,
                    strikes=merged_strikes,
                    cached_at=datetime.now()
                )
                self._option_chain_cache[cache_key] = cached
                
                # Call callbacks with merged result
                for callback in request.callbacks:
                    callback(merged_result)
            else:
                # No results
                for callback in request.callbacks:
                    callback(None)
    
    @trace
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        """Handle contract details from IB."""
        with self._lock:
            if reqId not in self._pending_contract_requests:
                return
            
            request = self._pending_contract_requests[reqId]
            request.data['results'].append(contractDetails)
    
    @trace
    def contractDetailsEnd(self, reqId: int):
        """Handle end of contract details."""
        with self._lock:
            if reqId not in self._pending_contract_requests:
                return
            
            request = self._pending_contract_requests.pop(reqId)
            
            # Cancel timeout
            if request.timer_id:
                self.timer_manager.remove_timer(request.timer_id)
            
            results = request.data['results']
            cache_key = request.data['cache_key']
            
            if len(results) == 1:
                # Cache the result
                contract_details = results[0]
                cached = CachedContract(
                    contract=contract_details.contract,
                    contract_details=contract_details,
                    cached_at=datetime.now()
                )
                self._contract_cache[cache_key] = cached
                
                # Call callbacks
                for callback in request.callbacks:
                    callback(contract_details.contract, contract_details)
            else:
                # No results or multiple results (error)
                for callback in request.callbacks:
                    callback(None, None)
    
    @trace
    def tick_option_computation(
        self, reqId: int, tickType: int, tickAttrib: int,
        impliedVol: float, delta: float, optPrice: float, pvDividend: float,
        gamma: float, vega: float, theta: float, undPrice: float
    ):
        """Handle option greeks from IB."""
        with self._lock:
            if reqId not in self._greeks_subscriptions:
                return
            
            sub_info = self._greeks_subscriptions[reqId]
            batch_id = sub_info['batch_id']
            contract = sub_info['contract']
            
            if batch_id not in self._pending_greeks_requests:
                return
            
            request = self._pending_greeks_requests[batch_id]
            
            # Store greeks
            greeks = GreeksData(
                delta=delta if delta != float('inf') and delta != float('-inf') else None,
                gamma=gamma if gamma != float('inf') and gamma != float('-inf') else None,
                vega=vega if vega != float('inf') and vega != float('-inf') else None,
                theta=theta if theta != float('inf') and theta != float('-inf') else None,
                implied_vol=impliedVol if impliedVol != float('inf') and impliedVol != float('-inf') else None,
                opt_price=optPrice if optPrice != float('inf') and optPrice != float('-inf') else None,
                und_price=undPrice if undPrice != float('inf') and undPrice != float('-inf') else None
            )
            
            request.data['greeks'][contract.conId] = (contract, greeks)
            
            # Unsubscribe from this contract
            self.ib_connection.unsubscribe_market_data(self, contract)
            del self._greeks_subscriptions[reqId]
            
            request.data['pending_count'] -= 1
            
            # Check if all greeks received
            if request.data['pending_count'] == 0:
                self._complete_greeks_request(batch_id)
    
    @trace
    def tick_price(self, reqId: int, tickType: str, price: float, attrib):
        """Handle price ticks for greeks requests."""
        with self._lock:
            if reqId not in self._greeks_subscriptions:
                return
            
            sub_info = self._greeks_subscriptions[reqId]
            batch_id = sub_info['batch_id']
            contract = sub_info['contract']
            
            if batch_id not in self._pending_greeks_requests:
                return
            
            request = self._pending_greeks_requests[batch_id]
            
            # Store price data
            if contract.conId in request.data['greeks']:
                _, greeks = request.data['greeks'][contract.conId]
                if tickType == "BID":
                    greeks.bid = price
                elif tickType == "ASK":
                    greeks.ask = price
    
    @trace
    def error(self, reqId: int, errorCode: int, errorString: str):
        """Handle errors from IB."""
        logger.error(f"OptionsFinder error for reqId {reqId}: [{errorCode}] {errorString}")
        
        with self._lock:
            # Check if it's a chain request
            if reqId in self._pending_chain_requests:
                request = self._pending_chain_requests.pop(reqId)
                if request.timer_id:
                    self.timer_manager.remove_timer(request.timer_id)
                for callback in request.callbacks:
                    callback(None)
            
            # Check if it's a contract request
            elif reqId in self._pending_contract_requests:
                request = self._pending_contract_requests.pop(reqId)
                if request.timer_id:
                    self.timer_manager.remove_timer(request.timer_id)
                for callback in request.callbacks:
                    callback(None, None)
    
    @trace
    def _complete_greeks_request(self, batch_id: int):
        """Complete a greeks request and call callbacks."""
        with self._lock:
            if batch_id not in self._pending_greeks_requests:
                return
            
            request = self._pending_greeks_requests.pop(batch_id)
            
            # Cancel timeout
            if request.timer_id:
                self.timer_manager.remove_timer(request.timer_id)
            
            # Call callbacks
            for callback in request.callbacks:
                callback(request.data['greeks'])
    
    @trace
    def _set_timeout(self, req_id: int, timeout_ms: int, timeout_callback: Callable):
        """Set a timeout for a request."""
        now = datetime.now(pytz.UTC)
        trigger_datetime = now + timedelta(milliseconds=timeout_ms)
        trigger_time_str = trigger_datetime.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        timer_id = self.timer_manager.add_timer(
            bot_id="OptionsFinder",
            event_name=f"timeout_{req_id}",
            callback=lambda event_name, event_data: timeout_callback(req_id),
            event_data=req_id,
            trigger_time=trigger_time_str
        )
        
        # Store timer_id in the request
        with self._lock:
            if req_id in self._pending_chain_requests:
                self._pending_chain_requests[req_id].timer_id = timer_id
            elif req_id in self._pending_contract_requests:
                self._pending_contract_requests[req_id].timer_id = timer_id
            elif req_id in self._pending_greeks_requests:
                self._pending_greeks_requests[req_id].timer_id = timer_id
    
    @trace
    def _on_chain_timeout(self, req_id: int):
        """Handle timeout for option chain request."""
        logger.warning(f"Option chain request {req_id} timed out")
        with self._lock:
            if req_id in self._pending_chain_requests:
                request = self._pending_chain_requests.pop(req_id)
                for callback in request.callbacks:
                    callback(None)
    
    @trace
    def _on_contract_timeout(self, req_id: int):
        """Handle timeout for contract resolution request."""
        logger.warning(f"Contract resolution request {req_id} timed out")
        with self._lock:
            if req_id in self._pending_contract_requests:
                request = self._pending_contract_requests.pop(req_id)
                for callback in request.callbacks:
                    callback(None, None)
    
    @trace
    def _on_greeks_timeout(self, batch_id: int):
        """Handle timeout for greeks request."""
        logger.warning(f"Greeks request {batch_id} timed out")
        self._complete_greeks_request(batch_id)

# Made with Bob
