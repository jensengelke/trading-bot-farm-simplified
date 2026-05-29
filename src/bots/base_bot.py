import logging
import os
from abc import ABCMeta, abstractmethod
from ibapi.contract import Contract
from ibapi.order import Order
from src.bots.config_base import ConfigBase
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from src.utils import trace, is_valid_price
from src.logging_config import setup_logging
from src.utils.options_finder import OptionsFinder
from typing import Optional, Callable

class BaseBotFilter(logging.Filter):
    """
    A logging filter that prefixes messages from base_bot.py with "BaseBot: ".
    """
    def filter(self, record):
        if os.path.basename(record.pathname) == 'base_bot.py':
            record.msg = f"BaseBot: {record.msg}"
        return True

class ContractResolutionStatus:
    def __init__(self):
        self.complete = False
        self.total_contracts = 0
        self.errors = []

    def __str__(self):
        error_count = len(self.errors)
        return f"complete={self.complete}, total_contracts={self.total_contracts}, errors={error_count}"


class BaseBot(metaclass=ABCMeta):
    @trace
    def __init__(self, config: ConfigBase, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        self.config = config
        self.ib_connection = ib_connection
        self.timer_manager = timer_manager
        self._init_logger(config_dir)

        # Initialize OptionsFinder utility
        self.options_finder = OptionsFinder(ib_connection, timer_manager)

        self._contract_resolution_requests = {}
        self._option_chain_resolution_requests = {}
        self._historical_data_requests = {}
        self.scheduled_entry_time: Optional[datetime] = None

    @trace
    def request_historical_data(self, contract: Contract, end_datetime: str, duration: str, bar_size: str, what_to_show: str, use_rth: int, keep_up_to_date: bool, callback_historical_data_end, callback_historical_data_update=None) -> int:
        req_id = self.ib_connection.request_historical_data(self, contract, end_datetime, duration, bar_size, what_to_show, use_rth, keep_up_to_date)
        self._historical_data_requests[req_id] = {
            "keep_up_to_date": keep_up_to_date,
            "callback_historical_data_end": callback_historical_data_end,
            "callback_historical_data_update": callback_historical_data_update
        }
        return req_id

    @trace
    def cancel_historical_data(self, req_id: int):
        self.ib_connection.cancel_historical_data(req_id)
        if req_id in self._historical_data_requests:
            del self._historical_data_requests[req_id]


    @trace
    def historicalDataUpdate(self, reqId: int, bar):
        if reqId in self._historical_data_requests:
            request_context = self._historical_data_requests[reqId]
            if request_context["keep_up_to_date"] and request_context["callback_historical_data_update"]:
                request_context["callback_historical_data_update"](bar)

    @trace
    def historicalDataEnd(self, reqId: int, start: str, end: str, bars):
        if reqId in self._historical_data_requests:
            request_context = self._historical_data_requests[reqId]
            if request_context["callback_historical_data_end"]:
                request_context["callback_historical_data_end"](bars)
            
            # Cleanup if not kept up to date
            if not request_context["keep_up_to_date"]:
                del self._historical_data_requests[reqId]

    @trace
    def resolve_contracts(self, search_contract: Contract, status: ContractResolutionStatus, callback):
        result_contracts = []
        req_id = self.ib_connection.request_contract_details(self, search_contract)
        self._contract_resolution_requests[req_id] = {
            "search_contract": search_contract,
            "result_contracts": result_contracts,
            "status": status,
            "callback": callback
        }


    @trace
    def subscribe_market_data(self, contract: Contract, generic_tick_list: str = "") -> Optional[int]:
        return self.ib_connection.subscribe_market_data(self, contract, generic_tick_list)

    @trace
    def unsubscribe_market_data(self, contract: Contract):
        self.ib_connection.unsubscribe_market_data(self, contract)

    @trace
    def _init_logger(self, config_dir: str):
        """Initializes a dedicated logger for the bot."""
        log_dir = os.path.join("logs", os.path.basename(config_dir))
        self.logger = setup_logging(self.config.bot_name, log_dir)
        self.logger.addFilter(BaseBotFilter())

    @abstractmethod
    @trace
    def start(self):
        pass

    @abstractmethod
    @trace
    def stop(self):
        pass

    @trace
    def tick_price(self, reqId, tickType, price, attrib):
        self._handle_base_tick_price(reqId, tickType, price, attrib)

    @trace
    def request_market_data(self, contract: Contract, callback: Callable, timeout_ms: Optional[int] = None):
        """
        Request market data and wait for a complete set of prices (Open, High, Low, Close, Bid, Ask).
        
        Args:
            contract: The contract to subscribe to
            callback: Called with (success, price_data)
            timeout_ms: Optional timeout in milliseconds. If None, uses global price_retrieval_timeout.
        """
        if timeout_ms is None:
            timeout_ms = self.ib_connection.price_retrieval_timeout * 1000

        req_id = self.subscribe_market_data(contract)
        
        from datetime import datetime, timedelta
        import pytz
        now = datetime.now(pytz.UTC)
        trigger_datetime = now + timedelta(milliseconds=timeout_ms)
        trigger_time_str = trigger_datetime.strftime("%Y-%m-%d %H:%M:%S UTC")

        timer_id = self.timer_manager.add_timer(
            bot_id=self.config.bot_name,
            event_name=f"market_data_timeout_{req_id}",
            callback=self._on_market_data_timeout,
            event_data={"req_id": req_id, "contract": contract, "callback": callback},
            trigger_time=trigger_time_str
        )

        if not hasattr(self, "_market_data_requests"):
            self._market_data_requests = {}
        
        self._market_data_requests[req_id] = {
            "contract": contract,
            "callback": callback,
            "timer_id": timer_id
        }
        return req_id

    @trace
    def _on_market_data_timeout(self, event_name: str, event_data: dict):
        req_id = event_data["req_id"]
        contract = event_data["contract"]
        callback = event_data["callback"]

        if req_id in self._market_data_requests:
            self.logger.warning(f"Market data request for {contract.symbol} (reqId: {req_id}) timed out.")
            data = self.get_cached_price(reg_id=req_id)
            del self._market_data_requests[req_id]
            self.unsubscribe_market_data(contract)
            callback(False, data)

    @trace
    def _handle_base_tick_price(self, reqId, tickType, price, attrib):
        """Internal handler to check for complete market data."""
        if not hasattr(self, "_market_data_requests") or reqId not in self._market_data_requests:
            return

        # IB tickType constants
        # BID = 1, ASK = 2, LAST = 4, HIGH = 6, LOW = 7, CLOSE = 9, OPEN = 14
        
        data = self.get_cached_price(reg_id=reqId)
        if not data:
            return

        # We wait for Bid, Ask, Open, High, Low, Close
        required_ticks = [1, 2, 6, 7, 9, 14]
        if all(is_valid_price(data.get(t)) for t in required_ticks):
            context = self._market_data_requests.pop(reqId)
            self.timer_manager.remove_timer(context["timer_id"])
            self.unsubscribe_market_data(context["contract"])
            self.logger.info(f"Complete market data received for {context['contract'].symbol} (reqId: {reqId})")
            context["callback"](True, data)

    @trace
    def tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        pass

    @trace
    def order_status(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        self.logger.debug(f"order_status: orderId={orderId}, status={status}, filled={filled}, remaining={remaining}, avgFillPrice={avgFillPrice}, permId={permId}, parentId={parentId}, lastFillPrice={lastFillPrice}, clientId={clientId}, whyHeld={whyHeld}, mktCapPrice={mktCapPrice}")

    @trace
    def exec_details(self, reqId, contract, execution):
        self.logger.debug(f"exec_details: reqId={reqId}, contract={contract.symbol}, execution={execution.execId}")

    @trace
    def get_cached_price(self, con_id: int = None, reg_id: int = None):
        return self.ib_connection.get_cached_price(con_id = con_id, req_id = reg_id)

    @trace
    def place_order(self, contract: Contract, order: Order) -> Optional[int]:
        if hasattr(order, "orderRef") and order.orderRef:
            order.orderRef = f"{self.config.bot_name} - {order.orderRef}"
        else:
            order.orderRef = self.config.bot_name

        return self.ib_connection.place_order(self, contract, order)


    @trace
    def open_order(self, orderId, contract, order, orderState):
        self.logger.debug(f"open_order: orderId={orderId}, contract={contract.symbol}, order={order.orderRef}, orderState={orderState.status}")

    @trace
    def on_timer(self, event_name: str, event_data: any = None):
        pass

    @trace
    def is_entry_timeout_exceeded(self) -> bool:
        """
        Checks if the entry timeout has been exceeded since the scheduled entry time.
        If exceeded, logs a warning and returns True.
        """
        if self.scheduled_entry_time is None:
            return False
            
        timeout_seconds = self.config.entry_timeout_seconds
        if timeout_seconds is None:
            return False
            
        import pytz
        from datetime import datetime
        now = datetime.now(pytz.UTC)
        
        # Ensure scheduled_entry_time is UTC for comparison
        scheduled_utc = self.scheduled_entry_time.astimezone(pytz.UTC)
        elapsed = (now - scheduled_utc).total_seconds()
        
        if elapsed > timeout_seconds:
            self.logger.warning(f"Entry timeout exceeded: {elapsed:.1f}s elapsed since scheduled time {scheduled_utc}, timeout is {timeout_seconds}s. Skipping to tomorrow.")
            self.scheduled_entry_time = None # Reset to avoid repeated timeout warnings
            return True
            
        return False

    @trace
    def contractDetails(self, reqId, contractDetails):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["result_contracts"].append(contractDetails)
            request_context["status"].total_contracts += 1

    @trace
    def contractDetailsEnd(self, reqId):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["status"].complete = True
            del self._contract_resolution_requests[reqId]
            request_context["callback"](request_context["status"], request_context["result_contracts"])

    @trace
    def error(self, reqId, errorCode, errorString):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["status"].errors.append({"errorCode": errorCode, "errorString": errorString})

    @trace
    def resolve_option_chain(self, underlying: Contract, callback, timeout: int = 5000):
        underlying_symbol = underlying.symbol
        underlying_conid = underlying.conId
        underlying_secType = underlying.secType
        if underlying.secType == "FUT":
            exchange = underlying.exchange
        else:
            exchange = ""

        self.logger.info(f"Resolving option chain for {underlying_symbol} (conId: {underlying_conid}, secType: {underlying_secType}, exchange: {exchange})")
        req_id = self.ib_connection.request_option_chain(self, underlying_symbol, exchange, underlying_secType, underlying_conid)
        
        self._option_chain_resolution_requests[req_id] = {
            "underlying": underlying,
            "callback": callback,
            "data": [],
            "timer_id": None
        }

        if timeout > 0:
            from datetime import datetime, timedelta
            import pytz
            now = datetime.now(pytz.UTC)
            trigger_datetime = now + timedelta(milliseconds=timeout)
            trigger_time_str = trigger_datetime.strftime("%Y-%m-%d %H:%M:%S UTC")

            timer_id = self.timer_manager.add_timer(
                bot_id=self.config.bot_name,
                event_name="resolve_option_chain_timeout",
                callback=self._on_resolve_option_chain_timeout,
                event_data=req_id,
                trigger_time=trigger_time_str
            )
            self._option_chain_resolution_requests[req_id]["timer_id"] = timer_id

    @trace
    def _on_resolve_option_chain_timeout(self, event_name: str, event_data: any):
        req_id = event_data
        if req_id in self._option_chain_resolution_requests:
            self.logger.warning(f"Option chain resolution for reqId {req_id} timed out.")
            self.securityDefinitionOptionParameterEnd(req_id)

    @trace
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str, underlyingConId: int, tradingClass: str, multiplier: str, expirations: set, strikes: set):
        if reqId in self._option_chain_resolution_requests:
            self._option_chain_resolution_requests[reqId]["data"].append({
                "exchange": exchange,
                "underlyingConId": underlyingConId,
                "tradingClass": tradingClass,
                "multiplier": multiplier,
                "expirations": expirations,
                "strikes": strikes
            })

    @trace
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        self.logger.info(f"Option chain resolution for reqId {reqId} completed.")
        if reqId in self._option_chain_resolution_requests:
            context = self._option_chain_resolution_requests.pop(reqId)
            if context["timer_id"]:
                self.timer_manager.remove_timer(context["timer_id"])

        # Check if we received any data
        if not context["data"]:
            self.logger.warning(f"Option chain resolution for reqId {reqId} returned no data. This may occur outside trading hours.")
        
        self.logger.debug(f"Calling callback {context['callback']} with data {context['data']}")
        context["callback"](context["data"])

    @trace
    def get_robust_market_data(self, contract: Contract, callback: Callable, timeout_ms: Optional[int] = None):
        """
        Request market data and wait for a complete set of prices.
        This is a convenience method that wraps request_market_data and provides 
        a standard validation logic in the callback.
        """
        def robust_callback(success, price_data):
            if not price_data:
                callback(False, None)
                return

            # Determination logic for a single 'price' from the data
            # Try Bid/Ask first, then Last, then Close
            bid = price_data.get(1) # BID
            ask = price_data.get(2) # ASK
            last = price_data.get(4) # LAST
            close = price_data.get(9) # CLOSE

            price = None
            if is_valid_price(bid) and is_valid_price(ask):
                price = (bid + ask) / 2
            elif is_valid_price(last):
                price = last
            elif is_valid_price(close):
                price = close
            
            callback(success and price is not None, price)

        self.request_market_data(contract, robust_callback, timeout_ms)
