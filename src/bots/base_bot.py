import logging
import os
from abc import ABCMeta, abstractmethod
from ibapi.contract import Contract
from src.bots.config_base import ConfigBase
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager

class ContractResolutionStatus:
    def __init__(self):
        self.complete = False
        self.total_contracts = 0
        self.errors = []


class BaseBot(metaclass=ABCMeta):
    def __init__(self, config: ConfigBase, ib_connection: IBConnection, timer_manager: TimerManager, config_dir: str):
        self.config = config
        self.ib_connection = ib_connection
        self.timer_manager = timer_manager
        self._init_logger(config_dir)

        self._contract_resolution_requests = {}

    def resolve_contracts(self, search_contract: Contract, result_contracts: list, status: ContractResolutionStatus, callback):
        req_id = self.ib_connection.request_contract_details(search_contract)
        self._contract_resolution_requests[req_id] = {
            "search_contract": search_contract,
            "result_contracts": result_contracts,
            "status": status,
            "callback": callback
        }


    def _init_logger(self, config_dir: str):
        """Initializes a dedicated logger for the bot."""
        self.logger = logging.getLogger(self.config.bot_name)
        self.logger.setLevel(logging.DEBUG)

        # Prevent bot logs from propagating to the system logger
        self.logger.propagate = False

        config_dir_name = os.path.basename(os.path.normpath(config_dir))
        log_dir = os.path.join("logs", config_dir_name)
        os.makedirs(log_dir, exist_ok=True)
        
        # Log to a file specific to the bot
        log_file = os.path.join(log_dir, f"{self.config.bot_name}.log")
        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add handler to the logger, only if it doesn't have one
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    def tick_price(self, reqId, tickType, price, attrib):
        pass

    def order_status(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        pass

    def exec_details(self, reqId, contract, execution):
        pass

    def open_order(self, orderId, contract, order, orderState):
        pass

    def on_timer(self, event_name: str, event_data: any = None):
        pass

    def contractDetails(self, reqId, contractDetails):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["result_contracts"].append(contractDetails.contract)
            request_context["status"].total_contracts += 1

    def contractDetailsEnd(self, reqId):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["status"].complete = True
            request_context["callback"]()
            del self._contract_resolution_requests[reqId]

    def error(self, reqId, errorCode, errorString):
        if reqId in self._contract_resolution_requests:
            request_context = self._contract_resolution_requests[reqId]
            request_context["status"].errors.append({"errorCode": errorCode, "errorString": errorString})
