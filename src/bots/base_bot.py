import logging
import os
from abc import ABCMeta, abstractmethod
from ibapi.contract import Contract
from ibapi.order import Order
from src.bots.config_base import ConfigBase
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
from src.utils import trace
from typing import Optional

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

        self._contract_resolution_requests = {}
        self._option_chain_resolution_requests = {}
        self._historical_data_requests = {}

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
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{self.config.bot_name}.log")

        self.logger = logging.getLogger(self.config.bot_name)

        # Clear existing handlers and filters to avoid duplicates
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        self.logger.filters.clear()

        self.logger.setLevel(logging.DEBUG)

        # Prevent logs from propagating to the root logger
        self.logger.propagate = False

        # Add custom filter
        self.logger.addFilter(BaseBotFilter())

        # Add file handler for the bot
        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

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
        pass

    @trace
    def tick_option_computation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        pass

    @trace
    def order_status(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        pass

    @trace
    def exec_details(self, reqId, contract, execution):
        pass

    @trace
    def get_cached_price(self, con_id: int):
        return self.ib_connection.get_cached_price(con_id)

    @trace
    def place_order(self, contract: Contract, order: Order) -> Optional[int]:
        if hasattr(order, "orderRef") and order.orderRef:
            order.orderRef = f"{self.config.bot_name} - {order.orderRef}"
        else:
            order.orderRef = self.config.bot_name

        return self.ib_connection.place_order(contract, order)


    @trace
    def open_order(self, orderId, contract, order, orderState):
        pass

    @trace
    def on_timer(self, event_name: str, event_data: any = None):
        pass

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

            self.logger.error(f"Calling callback {context['callback']} with data {context['data']}")
            context["callback"](context["data"])
