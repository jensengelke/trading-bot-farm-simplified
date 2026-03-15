import logging
import threading
from ..db.repository import Repository
import yaml
import os

def load_config(filepath=".config.yaml") -> dict:
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r") as f:
        return yaml.safe_load(f)
from ..utils import trace
from .flex_query_service import FlexQueryService
from datetime import datetime, timedelta
import os

logger = logging.getLogger("system")

class SyncManager:
    @trace
    def __init__(self, repository: Repository, flex_service: FlexQueryService, ib_conn=None):
        self.repo = repository
        self.flex_service = flex_service
        self.ib_conn = ib_conn
        self.config = load_config()
        self._lock = threading.Lock()

    @trace
    def sync_account(self, account_id: str) -> bool:
        """
        Performs a full sync for the given account:
        1. Checks config for token/query_id
        2. Retrieves last sync date from DB
        3. Downloads Flex Data (skipped if already synced today)
        4. Parses and saves executions
        5. Performs API Sync for executions since last Flex Sync
        6. Recalculates Shadow Positions
        """
        logger.info(f"Starting sync for account {account_id}...")
        
        with self._lock:
            # 1. Find account config
            flex_conf = self.config.get("flex", {})
            token = flex_conf.get("flex_token")
            query_id = flex_conf.get("flex_query_id")
            
            if not token or not query_id:
                logger.warning(f"Missing flex_token or flex_query_id for account {account_id}. Skipping Flex Query.")
            else:
                # 2. Get last sync state from DB
                sync_state = self.repo.get_sync_state(account_id)
                last_flex_date = sync_state.last_flex_sync_date.date() if sync_state and sync_state.last_flex_sync_date else None
                
                today = datetime.now().date()
                yesterday = today - timedelta(days=1)
                
                if not last_flex_date:
                    logger.info("Initializing database for the first time. Batching Flex Query backward by month...")
                    current_end = yesterday
                    current_start = current_end.replace(day=1)
                    
                    last_xml_dates = None
                    empty_months_count = 0
                    
                    while True:
                        xml_data, effective_start, effective_end = self.flex_service.download_flex_data(token, query_id, start_date=current_start, end_date=current_end)
                        
                        if not xml_data:
                            logger.info(f"Flex query returned no data or failed for {current_start} to {current_end}. Stopping initialization.")
                            break
                            
                        # Safety check: if IB ignores fd/td and returns the exact same statement dates, break to prevent infinite loop
                        import xml.etree.ElementTree as ET
                        try:
                            root = ET.fromstring(xml_data)
                            statement = root.find(".//FlexStatement")
                            if statement is not None:
                                current_xml_dates = (statement.get("fromDate"), statement.get("toDate"))
                                if last_xml_dates and current_xml_dates == last_xml_dates:
                                    logger.info(f"IB returned identical Flex Query dates {current_xml_dates} for {current_start} to {current_end}. Ignoring and stopping backward batching.")
                                    break
                                last_xml_dates = current_xml_dates
                        except Exception as e:
                            logger.warning(f"Could not parse XML for date validation: {e}")
                            
                        has_data = self._process_flex_xml(xml_data, account_id, effective_start, effective_end)
                        
                        if not has_data:
                            empty_months_count += 1
                            logger.info(f"No new execution or order data found for {current_start} to {current_end}. (Empty months: {empty_months_count})")
                            if empty_months_count >= 12:
                                logger.info("Reached 12 consecutive months with no data. Stopping backward batching.")
                                break
                        else:
                            empty_months_count = 0
                            
                        # Move backwards one month
                        current_end = current_start - timedelta(days=1)
                        current_start = current_end.replace(day=1)
                        
                    # After full backward init, set last_flex_sync_date to now
                    self.repo.update_sync_state(account_id, last_date=datetime.now())
                    
                else:
                    # Ongoing daily/incremental sync
                    if last_flex_date >= today:
                        logger.info(f"Flex data for account {account_id} is already up to date (last sync: {last_flex_date}). Skipping Flex Query.")
                    else:
                        logger.info(f"Last Flex sync was {last_flex_date}. Requesting incremental update.")
                        xml_data, effective_start, effective_end = self.flex_service.download_flex_data(token, query_id, start_date=last_flex_date, end_date=yesterday)
                        if xml_data:
                            self._process_flex_xml(xml_data, account_id, effective_start, effective_end)
                            self.repo.update_sync_state(account_id, last_date=datetime.now())
                        else:
                            logger.info(f"No new Flex Data to process for {account_id}.")
            
            # 5. API Sync for today's data
            self._sync_api_executions(account_id)

            # 6. Recalc Shadow Positions
            logger.info(f"Recalculating shadow positions for {account_id}...")
            ignored_refs = []
            self.repo.recalc_shadow_positions(account_id, ignored_order_refs=ignored_refs)
            
            return True

    @trace
    def _process_flex_xml(self, xml_data: bytes, account_id: str, start_dt, end_dt) -> bool:
        """Parses XML and saves to DB. Returns True if any useful data (executions/orders/positions) was found."""
        # Save XML payload to file
        try:
            os.makedirs("data", exist_ok=True)
            file_name = f"{account_id}-{start_dt.strftime('%Y%m%d')}-{end_dt.strftime('%Y%m%d')}.xml"
            file_path = os.path.join("data", file_name)
            with open(file_path, "wb") as f:
                f.write(xml_data)
            logger.info(f"Saved Flex XML to: {file_path}")
        except Exception as e:
            logger.error(f"Failed to save Flex XML file: {e}")

        has_data = False

        # 4a. Save Contracts (SecurityInfo)
        flex_contracts = self.flex_service.parse_contracts_from_xml(xml_data)
        for c_data in flex_contracts:
            self.repo.save_contract(c_data)
        logger.info(f"Imported/Updated {len(flex_contracts)} contracts from Flex Query.")

        # 4b. Save Executions
        executions = self.flex_service.parse_executions_from_xml(xml_data)
        logger.info(f"Parsed {len(executions)} executions from Flex Query.")
        
        count = 0
        for exec_data in executions:
            if exec_data["account_id"] == account_id:
                self.repo.save_execution(exec_data)
                if exec_data.get("con_id"):
                    self.repo.update_contract_last_seen(exec_data["con_id"])
                count += 1
                has_data = True
        
        logger.info(f"Saved {count} new/existing executions to database.")
        
        # 4c. Parse and Save Orders
        if b"<Order" in xml_data: 
             orders = self.flex_service.parse_orders_from_xml(xml_data)
             logger.info(f"Parsed {len(orders)} orders from Flex Query.")
             o_count = 0
             for o_data in orders:
                 if o_data["account_id"] == account_id:
                     self.repo.save_order(o_data)
                     if o_data.get("con_id"):
                         self.repo.update_contract_last_seen(o_data["con_id"])
                     o_count += 1
                     has_data = True
             logger.info(f"Saved {o_count} orders to database.")

        # 4d. Parse and Save Positions & Lots
        if b"<OpenPosition" in xml_data:
             pos_data = self.flex_service.parse_positions_from_xml(xml_data)
             logger.info(f"Parsed {len(pos_data['positions'])} aggregate positions and {len(pos_data['lots'])} lots from Flex Query.")
             
             p_count = 0
             for p_data in pos_data['positions']:
                 if p_data["account_id"] == account_id:
                     self.repo.save_position(p_data)
                     p_count += 1
                     has_data = True
             
             l_count = 0
             for l_data in pos_data['lots']:
                 if l_data["account_id"] == account_id:
                     self.repo.save_position_lot(l_data)
                     l_count += 1
                     has_data = True
             logger.info(f"Saved {p_count} aggregate positions and {l_count} lots to database.")

        return has_data

    @trace
    def _sync_api_executions(self, account_id: str):
        """Fetches latest executions from IB API and saves to DB."""
        if not self.ib_conn or not self.ib_conn.isConnected():
            logger.info("IBConnection not active. Skipping API sync for current data.")
            return

        logger.info(f"Starting API sync for {account_id}...")
        
        sync_state = self.repo.get_sync_state(account_id)
        # Use last API sync date. If none, start from beginning of today since Flex Query 
        # only covers up to yesterday and API only reliably provides recent executions.
        last_sync = None
        if sync_state and sync_state.last_api_sync_date:
            last_sync = sync_state.last_api_sync_date
        else:
            last_sync = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        from ibapi.execution import ExecutionFilter
        filter = ExecutionFilter()
        filter.clientId = self.ib_conn._client_id
        filter.acctCode = account_id
        
        if last_sync:
            # Format required by IB API: YYYYMMDD-hh:mm:ss
            filter.time = last_sync.strftime("%Y%m%d-%H:%M:%S")
            logger.info(f"Requesting API executions since {filter.time}")

        req_id = self.ib_conn.get_next_req_id()
        self.ib_conn.execution_events[req_id] = threading.Event()
        self.ib_conn.executions_data[req_id] = []
        
        self.ib_conn.reqExecutions(req_id, filter)
        
        logger.info("Waiting for API execution data...")
        success = self.ib_conn.execution_events[req_id].wait(timeout=10.0)
        
        if success:
            execs = self.ib_conn.executions_data.get(req_id, [])
            logger.info(f"Received {len(execs)} executions via API.")
            
            count = 0
            for data in execs:
                contract = data["contract"]
                execution = data["execution"]
                
                # Parse execution time "YYYYMMDD  hh:mm:ss" or similar
                try:
                    if " " in execution.time:
                        # Remove extra spaces between date and time
                        time_str = " ".join(execution.time.split())
                        exec_time = datetime.strptime(time_str, "%Y%m%d %H:%M:%S")
                    else:
                        exec_time = datetime.strptime(execution.time, "%Y%m%d")
                except Exception as e:
                    logger.warning(f"Failed to parse execution time '{execution.time}': {e}")
                    exec_time = datetime.now()

                exec_data = {
                    "exec_id": execution.execId,
                    "account_id": execution.acctNumber,
                    "order_ref": execution.orderRef,
                    "time": exec_time,
                    "symbol": contract.localSymbol or contract.symbol,
                    "side": execution.side,
                    "quantity": float(execution.shares),
                    "price": float(execution.price),
                    "con_id": contract.conId,
                    "perm_id": execution.permId,
                    "exchange": execution.exchange,
                    "client_id": execution.clientId,
                    "liquidation": execution.liquidation,
                    "cum_qty": float(execution.cumQty),
                    "avg_price": float(execution.avgPrice),
                    "ev_rule": execution.evRule,
                    "ev_multiplier": execution.evMultiplier,
                    "model_code": execution.modelCode,
                    "last_liquidity": execution.lastLiquidity,
                    "pending_price_revision": execution.pendingPriceRevision
                }
                
                self.repo.save_execution(exec_data)
                self.repo.save_contract({
                    "con_id": contract.conId,
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "exchange": contract.exchange,
                    "currency": contract.currency,
                    "local_symbol": contract.localSymbol,
                    "trading_class": contract.tradingClass
                })
                count += 1

            self.repo.update_sync_state(account_id, last_api_date=datetime.now())
            logger.info(f"API sync completed. Saved {count} executions.")
        else:
            logger.error("API sync timed out waiting for executions.")

        # Cleanup
        if req_id in self.ib_conn.execution_events:
            del self.ib_conn.execution_events[req_id]
        if req_id in self.ib_conn.executions_data:
            del self.ib_conn.executions_data[req_id]
