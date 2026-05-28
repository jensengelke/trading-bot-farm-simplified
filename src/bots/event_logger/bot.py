from src.bots.base_bot import BaseBot
from src.bots.event_logger.config import EventLoggerConfig
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager
import json

class EventLoggerBot(BaseBot):
    def __init__(self, config: EventLoggerConfig, ib_connection: IBConnection, 
                 timer_manager: TimerManager, config_dir: str):
        super().__init__(config, ib_connection, timer_manager, config_dir)
        self.logger.info(f"Initialized EventLoggerBot: {self.config.bot_name}")

    def start(self):
        """Called when bot is started."""
        self.logger.info(f"Starting EventLoggerBot: {self.config.bot_name}")
        self.logger.info("Bot is active and listening for order events.")

    def stop(self):
        """Called when bot is stopped."""
        self.logger.info(f"Stopping EventLoggerBot: {self.config.bot_name}")

    def order_status(self, orderId, status, filled, remaining, avgFillPrice, permId, 
                     parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Called when order status changes."""
        event_data = {
            "orderId": orderId,
            "status": status,
            "filled": filled,
            "remaining": remaining,
            "avgFillPrice": avgFillPrice,
            "permId": permId,
            "parentId": parentId,
            "lastFillPrice": lastFillPrice,
            "clientId": clientId,
            "whyHeld": whyHeld,
            "mktCapPrice": mktCapPrice
        }
        self.logger.info(f"ORDER_STATUS EVENT: {json.dumps(event_data, default=str)}")

    def open_order(self, orderId, contract, order, orderState):
        """Called for open orders."""
        event_data = {
            "orderId": orderId,
            "contract": {
                "symbol": contract.symbol,
                "secType": contract.secType,
                "exchange": contract.exchange,
                "currency": contract.currency,
                "conId": contract.conId
            },
            "order": {
                "action": order.action,
                "orderType": order.orderType,
                "totalQuantity": order.totalQuantity,
                "lmtPrice": order.lmtPrice,
                "auxPrice": order.auxPrice,
                "tif": order.tif,
                "orderRef": order.orderRef
            },
            "orderState": {
                "status": orderState.status,
                "initMarginBefore": orderState.initMarginBefore,
                "maintMarginBefore": orderState.maintMarginBefore,
                "equityWithLoanBefore": orderState.equityWithLoanBefore,
                "initMarginChange": orderState.initMarginChange,
                "maintMarginChange": orderState.maintMarginChange,
                "equityWithLoanChange": orderState.equityWithLoanChange,
                "initMarginAfter": orderState.initMarginAfter,
                "maintMarginAfter": orderState.maintMarginAfter,
                "equityWithLoanAfter": orderState.equityWithLoanAfter,
                "commission": orderState.commission,
                "minCommission": orderState.minCommission,
                "maxCommission": orderState.maxCommission,
                "commissionCurrency": orderState.commissionCurrency,
                "warningText": orderState.warningText
            }
        }
        self.logger.info(f"OPEN_ORDER EVENT: {json.dumps(event_data, default=str)}")

    def exec_details(self, reqId, contract, execution):
        """Called when execution details are received."""
        event_data = {
            "reqId": reqId,
            "contract": {
                "symbol": contract.symbol,
                "secType": contract.secType,
                "exchange": contract.exchange,
                "currency": contract.currency,
                "conId": contract.conId
            },
            "execution": {
                "execId": execution.execId,
                "time": execution.time,
                "acctNumber": execution.acctNumber,
                "exchange": execution.exchange,
                "side": execution.side,
                "shares": execution.shares,
                "price": execution.price,
                "permId": execution.permId,
                "clientId": execution.clientId,
                "orderId": execution.orderId,
                "cumQty": execution.cumQty,
                "avgPrice": execution.avgPrice,
                "orderRef": execution.orderRef,
                "evRule": execution.evRule,
                "evMultiplier": execution.evMultiplier,
                "modelCode": execution.modelCode,
                "lastLiquidity": execution.lastLiquidity
            }
        }
        self.logger.info(f"EXEC_DETAILS EVENT: {json.dumps(event_data, default=str)}")
