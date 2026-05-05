import sys
import threading
import logging
from typing import Optional, Dict, Any

from ibapi.ticktype import TickTypeEnum
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.execution import ExecutionFilter, Execution
from ibapi.scanner import ScannerSubscription
from decimal import Decimal

from src.utils import trace

logger = logging.getLogger("system")

class IBConnection(EWrapper, EClient):
    """
    IBConnection core infrastructure layer encapsulating the ibapi EWrapper and EClient.
    Maintains cached state and handles multiplexing data updates.
    """
    @trace
    def __init__(self, host: str, port: int, client_id: int, selected_account: str = ""):
        EClient.__init__(self, self)
        
        self.logger = logger
        
        self._host = host
        self._port = port
        self._client_id = client_id
        self.selected_account = selected_account

        # Internal caches
        self.market_data: Dict[int, Dict[str, Any]] = {}  # reqId -> {tickType -> value}
        self.portfolio_data: Dict[str, Dict[str, Any]] = {}  # account -> {symbol -> {position, avgCost}}
        self.account_data: Dict[str, Dict[str, Any]] = {}  # account -> {key -> value}
        self.orders_data: Dict[int, Any] = {}  # orderId -> details
        self.executions_data: Dict[int, list] = {}
        self.execution_events: Dict[int, threading.Event] = {}
        self.contract_details_data: Dict[int, list] = {}
        self.contract_details_events: Dict[int, threading.Event] = {}
        self.historical_data_config: Dict[int, Dict[str, Any]] = {}

        # State and concurrency mapping
        self.next_order_id: Optional[int] = None
        self._connected_event = threading.Event()
        self.api_thread: Optional[threading.Thread] = None
        self.account_sync_complete: bool = False  # Set to True when accountDownloadEnd is called
        
        self.request_listeners: Dict[int, list] = {} # reqId -> listener for a specific request
        # Subscriptions tracking
        self.req_id_counter = 1000
        self.active_subscriptions: Dict[int, int] = {}  # conId -> reqId

    @trace
    def get_next_req_id(self) -> int:
        req_id = self.req_id_counter
        self.req_id_counter += 1
        return req_id

    @trace
    def connect_and_start(self) -> bool:
        """Attempts the socket connection and starts a dedicated daemon thread."""
        logger.info(f"Connecting to IB Gateway/TWS at {self._host}:{self._port} (Client: {self._client_id})")
        self.connect(self._host, self._port, self._client_id)

        self.api_thread = threading.Thread(target=self.run, daemon=True)
        self.api_thread.start()

        # Wait until nextValidId confirms connection
        is_connected = self._connected_event.wait(timeout=5)
        if is_connected:
            logger.info("Successfully connected to IB API.")
            
            # Initiate auto-sync
            logger.debug("Requesting sync data: open orders, positions, and account updates.")
            if self._client_id == 0:
                self.reqAutoOpenOrders(True)
            self.reqAllOpenOrders()
            self.reqPositions()
            
            # Subscribing to account updates is deferred until `managedAccounts` 
            # provides the list of available accounts from the broker.
            
            return True
        else:
            logger.error("Connection timed out. Please check if TWS/Gateway is running.")
            return False

    @trace
    def disconnect_and_stop(self):
        """Disconnects from the broker and stops the loop."""
        if self.isConnected():
            logger.info("Disconnecting from IB API...")
            self.disconnect()
            self._connected_event.clear()

    # --- EWrapper Overrides (Incoming Data) ---

    @trace
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.next_order_id = orderId
        self._connected_event.set()
        logger.debug(f"Received nextValidId: {orderId}")

    @trace
    def error(self, reqId: int, errorTime: str, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        super().error(reqId, errorTime, errorCode, errorString, advancedOrderRejectJson)

        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                listener.error(reqId, errorCode, errorString)

        # IB produces many informational "errors". Only log important ones as actual errors.
        if errorCode in [2104, 2106, 2158]:
            logger.debug(f"IB Info [{errorCode}]: {errorString}")
        else:
            logger.error(f"IB Error [{errorCode}]: {errorString}")

    @trace
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib):
        super().tickPrice(reqId, tickType, price, attrib)
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        self.market_data[reqId][tickType] = price
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                tick_name = TickTypeEnum.toStr(tickType)
                logger.debug(f"Tick price received for reqId {reqId}: {tick_name} = {price}")
                listener.tick_price(reqId, tick_name, price, attrib)

    @trace
    def tickOptionComputation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
        
        greeks = {
            "impliedVol": impliedVol, "delta": delta, "optPrice": optPrice,
            "pvDividend": pvDividend, "gamma": gamma, "vega": vega,
            "theta": theta, "undPrice": undPrice
        }

        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        self.market_data[reqId]["greeks"] = greeks

        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                tick_name = TickTypeEnum.toStr(tickType)
                self.logger.debug(f"Tick option computation for reqId {reqId}: {tick_name} - {greeks}")
                if hasattr(listener, "tick_option_computation"):
                    listener.tick_option_computation(
                        reqId, tickType, tickAttrib, impliedVol, delta,
                        optPrice, pvDividend, gamma, vega, theta, undPrice
                    )

    @trace
    def position(self, account: str, contract: Contract, position: Decimal, avgCost: float):
        super().position(account, contract, position, avgCost)
        # Apply Account Isolation
        if self.selected_account and account != self.selected_account:
            return

        if account not in self.portfolio_data:
            self.portfolio_data[account] = {}
        
        # Use conId as primary key, fallback to localSymbol or symbol
        key = str(contract.conId) if contract.conId else (contract.localSymbol or contract.symbol)
        
        # Update only the fields available in position() callback
        if key not in self.portfolio_data[account]:
            self.portfolio_data[account][key] = {}
        
        self.portfolio_data[account][key].update({
            "contract": contract,
            "position": position,
            "averageCost": avgCost
        })

    @trace
    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        # Apply Account Isolation
        if self.selected_account and accountName != self.selected_account:
            return

        if accountName not in self.account_data:
            self.account_data[accountName] = {}
            
        # Group by currency. If no currency is provided, group under "INFO"
        curr_key = currency if currency else "INFO"
        
        if curr_key not in self.account_data[accountName]:
            self.account_data[accountName][curr_key] = {}
        
        self.account_data[accountName][curr_key][key] = val
        
    @trace
    def updatePortfolio(self, contract: Contract, position: Decimal, marketPrice: float, marketValue: float, averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str):
        super().updatePortfolio(contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName)
        # Apply Account Isolation
        if self.selected_account and accountName != self.selected_account:
            return

        if accountName not in self.portfolio_data:
            self.portfolio_data[accountName] = {}
        
        # Use conId as primary key, fallback to localSymbol or symbol
        key = str(contract.conId) if contract.conId else (contract.localSymbol or contract.symbol)
        
        self.portfolio_data[accountName][key] = {
            "contract": contract,
            "position": position,
            "marketPrice": marketPrice,
            "marketValue": marketValue,
            "averageCost": averageCost,
            "unrealizedPNL": unrealizedPNL,
            "realizedPNL": realizedPNL
        }
        
        logger.debug(f"Portfolio update for {accountName}/{key}: pos={position}, avgCost={averageCost}, unrealizedPNL={unrealizedPNL}")

    @trace
    def accountDownloadEnd(self, accountName: str):
        super().accountDownloadEnd(accountName)
        # Apply Account Isolation
        if self.selected_account and accountName != self.selected_account:
            return
            
        logger.info(f"Account download complete for {accountName}. Full initial snapshot received.")
        self.account_sync_complete = True
        

    @trace
    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        # Account context protection
        if self.selected_account and order.account and order.account != self.selected_account:
            return

        self.orders_data[orderId] = {
            "contract": contract,
            "order": order,
            "state": orderState.status
        }

    
    @trace
    def orderStatus(self, orderId: int, status: str, filled: Decimal, remaining: Decimal, avgFillPrice: float, permId: int, parentId: int, lastFillPrice: float, clientId: int, whyHeld: str, mktCapPrice: float):
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        # Check isolated account directly or skip check if we assume order is ours
        if orderId in self.orders_data:
            self.orders_data[orderId]["state"] = status
            self.orders_data[orderId]["filled"] = filled
            self.orders_data[orderId]["remaining"] = remaining
            self.orders_data[orderId]["avgFillPrice"] = avgFillPrice


    @trace
    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        if self.selected_account and execution.acctNumber and execution.acctNumber != self.selected_account:
            return
            
        if reqId not in self.executions_data:
            self.executions_data[reqId] = []
            
        self.executions_data[reqId].append({
            "contract": contract,
            "execution": execution
        })


    @trace
    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        if reqId in self.execution_events:
            self.execution_events[reqId].set()

    @trace
    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        logger.info(f"Managed Accounts received: {accountsList}")
        accounts = [a.strip() for a in accountsList.split(",") if a.strip()]
        
        # If no selected_account was configured, pick the first one from the list automatically
        if not self.selected_account and accounts:
            self.selected_account = accounts[0]
            logger.warning(f"No selected_account configured. Auto-selecting first account: {self.selected_account}")
            
        # As soon as we know our account, start polling its full update stream
        if self.selected_account:
            logger.info(f"Requesting consistent account updates for {self.selected_account}")
            self.reqAccountUpdates(True, self.selected_account)


    @trace
    def contractDetails(self, reqId: int, contractDetails):
        super().contractDetails(reqId, contractDetails)
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                listener.contractDetails(reqId, contractDetails)
            return

        if reqId not in self.contract_details_data:
            self.contract_details_data[reqId] = []
        self.contract_details_data[reqId].append(contractDetails)

    @trace
    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                listener.contractDetailsEnd(reqId)
            del self.request_listeners[reqId]
            return

        if reqId in self.contract_details_events:
            self.contract_details_events[reqId].set()

    @trace
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str, underlyingConId: int, tradingClass: str, multiplier: str, expirations: set, strikes: set):
        logger.info(f"Security definition option parameter received for reqId {reqId}")
        super().securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                listener.securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)
            return

    @trace
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        logger.info(f"Security definition option parameter end received for reqId {reqId}")
        super().securityDefinitionOptionParameterEnd(reqId)
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                listener.securityDefinitionOptionParameterEnd(reqId)
            del self.request_listeners[reqId]
            return

    @trace
    def historicalData(self, reqId: int, bar):
        super().historicalData(reqId, bar)
        if reqId in self.request_listeners:
            config = self.historical_data_config.get(reqId, {})
            if 'data' not in config:
                config['data'] = []
            config['data'].append(bar)

    @trace
    def historicalDataUpdate(self, reqId: int, bar):
        super().historicalDataUpdate(reqId, bar)
        if reqId in self.request_listeners:
            for listener in self.request_listeners[reqId]:
                if hasattr(listener, 'historicalDataUpdate'):
                    listener.historicalDataUpdate(reqId, bar)

    @trace
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        if reqId in self.request_listeners:
            config = self.historical_data_config.get(reqId, {})
            keep_up_to_date = config.get('keep_up_to_date', False)
            
            # Dispatch accumulated data to all listeners
            for listener in self.request_listeners[reqId]:
                if hasattr(listener, 'historicalDataEnd'):
                    listener.historicalDataEnd(reqId, start, end, config.get('data', []))

            # Clean up if not keeping the subscription alive
            if not keep_up_to_date:
                del self.request_listeners[reqId]
                if reqId in self.historical_data_config:
                    del self.historical_data_config[reqId]


    # --- API Action Methods (Outgoing Requests) ---

    @trace
    def subscribe_market_data(self, listener: Any, contract: Contract, generic_tick_list: str = "") -> Optional[int]:
        con_id = contract.conId
        if not con_id and contract.secType != "BAG":
            logger.error(f"Cannot subscribe to market data: Invalid or missing conId for {contract.symbol}")
            return None
            
        # Multiplex check
        if con_id in self.active_subscriptions:
            req_id = self.active_subscriptions[con_id]
            logger.debug(f"Already multiplexing market data for conId {con_id}.")
            if listener not in self.request_listeners.get(req_id, []):
                self.request_listeners.setdefault(req_id, []).append(listener)
            return req_id

        req_id = self.get_next_req_id()
        self.active_subscriptions[con_id] = req_id
        self.request_listeners[req_id] = [listener]
        logger.info(f"Subscribing to market data for {contract.symbol} (conId: {con_id}, ReqId: {req_id})")
        self.reqMktData(req_id, contract, generic_tick_list, False, False, [])
        return req_id

    @trace
    def unsubscribe_market_data(self, listener: Any, contract: Contract):
        con_id = contract.conId
        req_id = self.active_subscriptions.get(con_id)
        if req_id is not None:
            if req_id in self.request_listeners and listener in self.request_listeners[req_id]:
                self.request_listeners[req_id].remove(listener)
                if not self.request_listeners[req_id]: # if no more listeners for this req_id
                    logger.info(f"Unsubscribing from market data for {contract.symbol} (conId: {con_id}, ReqId: {req_id})")
                    self.cancelMktData(req_id)
                    del self.active_subscriptions[con_id]
                    del self.request_listeners[req_id]

    @trace
    def get_cached_price(self, con_id: int = None, req_id: int=None) -> Optional[Dict[str, Any]]:
        """
        Retrieves cached market data for a given conId.
        """
        if req_id is None:
            req_id = self.active_subscriptions.get(con_id)
        
        if req_id is None:
            logger.warning(f"No active market data subscription found for conId {con_id}")
            return None
        
        if req_id not in self.market_data:
            logger.warning(f"No market data cache found for reqId {req_id} (conId: {con_id})")
            return None
            
        return self.market_data.get(req_id)


    @trace
    def place_order(self, contract: Contract, order: Order) -> Optional[int]:
        if self.next_order_id is None:
            logger.error("Cannot place order: Not connected or missing nextValidId.")
            return None
            
        order_id = self.next_order_id
        self.next_order_id += 1
        
        logger.info(f"Placing Order {order_id} for {contract.symbol}: {order.action} {order.totalQuantity} with orderRef: {order.orderRef if hasattr(order, 'orderRef') and order.orderRef else 'N/A'}")
        self.placeOrder(order_id, contract, order)
        return order_id

    @trace
    def cancel_order(self, order_id: int):
        logger.info(f"Canceling order {order_id}")
        self.cancelOrder(order_id, "")

    @trace
    def get_orders(self, include_closed: bool = False) -> Dict[int, Any]:
        """Returns a copy of the active (and optionally closed) orders for the selected account."""
        filtered_orders = {}
        for k, v in self.orders_data.items():
            if self.selected_account and v["order"].account and v["order"].account != self.selected_account:
                continue
            if not include_closed and v.get("state") in ["Filled", "Cancelled", "Inactive"]:
                continue
            filtered_orders[k] = v
        return filtered_orders

    @trace
    def get_cached_positions(self) -> Dict[str, Dict[str, Any]]:
        # Only return data for the selected account
        if self.selected_account:
            return {self.selected_account: self.portfolio_data.get(self.selected_account, {}).copy()}
        return self.portfolio_data.copy()

    @trace
    def get_portfolio_position(self, con_id: int = None, symbol: str = None) -> Optional[Dict[str, Any]]:
        """
        Get a specific portfolio position by conId or symbol.
        Returns position data including contract, position size, costs, and PnL.
        """
        if not self.selected_account:
            logger.warning("No selected account available for portfolio lookup")
            return None
            
        account_portfolio = self.portfolio_data.get(self.selected_account, {})
        
        # Try lookup by conId first
        if con_id:
            key = str(con_id)
            if key in account_portfolio:
                return account_portfolio[key].copy()
        
        # Fallback to symbol lookup
        if symbol:
            if symbol in account_portfolio:
                return account_portfolio[symbol].copy()
        
        logger.debug(f"No portfolio position found for conId={con_id}, symbol={symbol}")
        return None

    @trace
    def get_all_portfolio_positions(self) -> Dict[str, Any]:
        """
        Get all portfolio positions for the selected account.
        Returns a dictionary keyed by conId (or symbol as fallback).
        """
        if self.selected_account:
            return self.portfolio_data.get(self.selected_account, {}).copy()
        return {}

    @trace
    def is_account_sync_complete(self) -> bool:
        """
        Check if the initial account synchronization is complete.
        Bots should only start after this returns True.
        """
        return self.account_sync_complete

    @trace
    def get_cached_account_summary(self) -> Dict[str, Dict[str, Any]]:
        # Only return data for the selected account
        if self.selected_account:
            return {self.selected_account: self.account_data.get(self.selected_account, {}).copy()}
        return self.account_data.copy()

    # --- Async Data Request Interfaces ---

    @trace
    def request_contract_details(self, listener: Any, contract: Contract) -> int:
        req_id = self.get_next_req_id()
        self.request_listeners[req_id] = [listener]
        logger.info(f"Requesting contract details for {contract.symbol} (ReqId: {req_id})")
        self.reqContractDetails(req_id, contract)
        return req_id

    @trace
    def request_option_chain(self, listener: Any, underlying_symbol: str, exchange: str, sec_type: str, conid: int) -> int:
        req_id = self.get_next_req_id()
        self.request_listeners[req_id] = [listener]
        logger.info(f"Requesting option chain for {underlying_symbol} (ReqId: {req_id})")
        # For reqSecDefOptParams, the 3rd parameter (futFopExchange) should be empty string for stock/index options
        # The exchange parameter is only used for futures options
        fut_fop_exchange = "" if sec_type in ["STK", "IND"] else exchange
        self.reqSecDefOptParams(req_id, underlying_symbol, fut_fop_exchange, sec_type, conid)
        return req_id

    @trace
    def request_historical_data(self, listener: Any, contract: Contract, end_datetime: str, duration: str, bar_size: str, what_to_show: str, use_rth: int = 1, keep_up_to_date: bool = False) -> int:
        req_id = self.get_next_req_id()
        self.request_listeners[req_id] = [listener]
        self.historical_data_config[req_id] = {
            'keep_up_to_date': keep_up_to_date,
            'data': []
        }
        logger.info(f"Requesting historical data for {contract.symbol} (ReqId: {req_id})")
        self.reqHistoricalData(req_id, contract, end_datetime, duration, bar_size, what_to_show, use_rth, 1, keep_up_to_date, [])
        return req_id

    @trace
    def cancel_historical_data(self, req_id: int):
        logger.info(f"Canceling historical data for ReqId: {req_id}")
        self.cancelHistoricalData(req_id)
        if req_id in self.request_listeners:
            del self.request_listeners[req_id]
        if req_id in self.historical_data_config:
            del self.historical_data_config[req_id]

    @trace
    def subscribe_realtime_bars(self, contract: Contract, bar_size: int, what_to_show: str, use_rth: bool = True) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Subscribing to real-time bars for {contract.symbol} (ReqId: {req_id})")
        self.reqRealTimeBars(req_id, contract, bar_size, what_to_show, use_rth, [])
        return req_id

    @trace
    def subscribe_market_depth(self, contract: Contract, num_rows: int = 5, is_smart_depth: bool = False) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Subscribing to market depth for {contract.symbol} (ReqId: {req_id})")
        self.reqMktDepth(req_id, contract, num_rows, is_smart_depth, [])
        return req_id

    @trace
    def request_fundamental_data(self, contract: Contract, report_type: str) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Requesting fundamental data ({report_type}) for {contract.symbol} (ReqId: {req_id})")
        self.reqFundamentalData(req_id, contract, report_type, [])
        return req_id

    @trace
    def request_executions(self, execution_filter: ExecutionFilter) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Requesting executions (ReqId: {req_id})")
        self.reqExecutions(req_id, execution_filter)
        return req_id

    @trace
    def request_news_article(self, provider_code: str, article_id: str) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Requesting news article {article_id} from {provider_code} (ReqId: {req_id})")
        self.reqNewsArticle(req_id, provider_code, article_id, [])
        return req_id

    @trace
    def request_historical_news(self, conid: int, provider_codes: str, start: str, end: str, total_results: int) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Requesting historical news for conId {conid} (ReqId: {req_id})")
        self.reqHistoricalNews(req_id, conid, provider_codes, start, end, total_results, [])
        return req_id

    @trace
    def subscribe_market_scanner(self, scanner_subscription: ScannerSubscription) -> int:
        req_id = self.get_next_req_id()
        logger.info(f"Subscribing to market scanner (ReqId: {req_id})")
        self.reqScannerSubscription(req_id, scanner_subscription, [], [])
        return req_id
