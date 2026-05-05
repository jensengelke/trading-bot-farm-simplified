import logging
import threading
from ..db.repository import Repository
import yaml
import os
from pathlib import Path
from typing import Dict, List, Tuple, Callable, Any

def load_config(filepath=".config.yaml") -> dict:
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r") as f:
        return yaml.safe_load(f)
from ..utils import trace
from .flex_query_service import FlexQueryService
from datetime import datetime, timedelta

logger = logging.getLogger("system")

# Constants
EMPTY_MONTHS_THRESHOLD = 12
API_SYNC_TIMEOUT = 10.0

class SyncManager:
    @trace
    def __init__(self, repository: Repository, flex_service: FlexQueryService, ib_conn=None, config=None, flex_query_start_date: str | None = None):
        self.repo = repository
        self.flex_service = flex_service
        self.ib_conn = ib_conn
        self.config = config if config is not None else load_config()
        self.flex_sync_complete = False
        self.api_sync_complete = False
        self.sync_completion_callback = None
        self.callback_invoked = False
        self.flex_query_start_date = flex_query_start_date

    @trace
    def set_sync_completion_callback(self, callback):
        """
        Register a callback to be invoked when BOTH flex query and API sync complete.
        """
        self.sync_completion_callback = callback
        logger.info("Sync completion callback registered")
    
    @trace
    def _check_and_invoke_completion_callback(self):
        """
        Check if both flex and API sync are complete, and invoke callback if so.
        """
        if self.flex_sync_complete and self.api_sync_complete and not self.callback_invoked:
            if self.sync_completion_callback:
                logger.info("Both Flex Query and API sync complete. Invoking completion callback...")
                self.callback_invoked = True
                try:
                    threading.Thread(target=self.sync_completion_callback, daemon=True).start()
                except Exception as e:
                    logger.error(f"Error in sync completion callback: {e}")
    
    @trace
    def _validate_flex_config(self, account_id: str) -> tuple[str, str] | None:
        """
        Validates flex configuration for the account.
        Returns: (token, query_id) if valid, None otherwise
        """
        flex_conf = self.config.get("flex", {})
        token = flex_conf.get("flex_token")
        query_id = flex_conf.get("flex_query_id")
        
        if not token or not query_id:
            logger.warning(f"Missing flex_token or flex_query_id for account {account_id}. Skipping Flex Query.")
            return None
        
        return token, query_id
    
    @trace
    def _initialize_flex_sync(self, account_id: str, token: str, query_id: str, yesterday, now: datetime) -> bool:
        """
        Performs initial backward-batching sync for a new account.
        Returns True if initialization completed successfully.
        """
        logger.info("Initializing database for the first time. Batching Flex Query backward by month...")
        current_end = yesterday
        current_start = current_end.replace(day=1)
        
        last_xml_dates = None
        empty_months_count = 0
        
        while True:
            xml_data, effective_start, effective_end = self.flex_service.download_flex_data(
                token, query_id, start_date=current_start, end_date=current_end
            )
            
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
                if empty_months_count >= EMPTY_MONTHS_THRESHOLD:
                    logger.info(f"Reached {EMPTY_MONTHS_THRESHOLD} consecutive months with no data. Stopping backward batching.")
                    break
            else:
                empty_months_count = 0
                
            # Move backwards one month
            current_end = current_start - timedelta(days=1)
            current_start = current_end.replace(day=1)
            
        # After full backward init, set last_flex_sync_date to now
        self.repo.update_sync_state(account_id, last_date=now)
        return True
    
    @trace
    @trace
    def _perform_incremental_flex_sync(self, account_id: str, token: str, query_id: str,
                                       last_flex_date, yesterday) -> bool:
        """
        Performs incremental sync from last sync date to yesterday.
        Returns True if sync completed successfully.
        """
        # Use forced start date if provided
        if self.flex_query_start_date:
            try:
                forced_start = datetime.strptime(self.flex_query_start_date, "%Y-%m-%d").date()
                logger.info(f"Using forced flex query start date: {forced_start} (ignoring last sync date: {last_flex_date})")
                start_date = forced_start
            except ValueError as e:
                logger.error(f"Invalid flex query start date format '{self.flex_query_start_date}': {e}. Expected format: YYYY-MM-DD")
                return False
        else:
            # Check if already up to date
            if last_flex_date >= yesterday:
                logger.info(f"Flex data for account {account_id} is already up to date (last sync: {last_flex_date}). Skipping Flex Query.")
                return True
            start_date = last_flex_date
        
        # Request incremental update
        logger.info(f"Last Flex sync was {last_flex_date}. Requesting incremental update from {start_date} to {yesterday}.")
        xml_data, effective_start, effective_end = self.flex_service.download_flex_data(
            token, query_id, start_date=start_date, end_date=yesterday
        )
        
        if xml_data:
            self._process_flex_xml(xml_data, account_id, effective_start, effective_end)
            # Update to the last date of the requested block (as a datetime at midnight to match column type)
            new_last_date = datetime.combine(effective_end if effective_end else yesterday, datetime.min.time())
            self.repo.update_sync_state(account_id, last_date=new_last_date)
            return True
        else:
            logger.info(f"No new Flex Data to process for {account_id}. Not advancing sync date.")
            return False
    
    @trace
    def sync_account(self, account_id: str) -> bool:
        """
        Performs a full sync for the given account:
        1. Validates config for token/query_id
        2. Retrieves last sync date from DB
        3. Downloads Flex Data (initialization or incremental)
        4. Parses and saves executions
        5. Performs API Sync for executions since last Flex Sync
        6. Recalculates Shadow Positions
        
        Returns True if sync completed successfully, False otherwise.
        """
        logger.info(f"Starting sync for account {account_id}...")
        
        # Cache timestamps for consistency
        now = datetime.utcnow()
        today = now.date()
        yesterday = today - timedelta(days=1)
        
        # 1. Validate flex configuration
        config_result = self._validate_flex_config(account_id)
        
        if not config_result:
            logger.error(f"Invalid flex configuration for account {account_id}. Sync failed.")
            return False
        
        token, query_id = config_result
        
        # 2. Get last sync state from DB
        sync_state = self.repo.get_sync_state(account_id)
        last_flex_date = (sync_state.last_flex_sync_date.date()
                         if sync_state and sync_state.last_flex_sync_date
                         else None)
        
        # 3. Perform Flex Query sync (initialization or incremental)
        if not last_flex_date:
            self.flex_sync_complete = self._initialize_flex_sync(account_id, token, query_id, yesterday, now)
        else:
            self.flex_sync_complete = self._perform_incremental_flex_sync(
                account_id, token, query_id, last_flex_date, yesterday
            )
        
        # Log flex sync status
        if self.flex_sync_complete:
            logger.info("Flex Query sync completed successfully.")
        else:
            logger.error("Flex Query sync failed. Stopping sync process.")
            return False
        
        # 4. API Sync for today's data
        self.api_sync_complete = self._sync_api_executions(account_id)
        
        # Log API sync status
        if self.api_sync_complete:
            logger.info("API sync completed successfully.")
        else:
            logger.error("API sync failed. Stopping sync process.")
            return False
        
        # 5. Recalculate Shadow Positions
        logger.info(f"Recalculating shadow positions for {account_id}...")
        ignored_refs = []
        self.repo.recalc_shadow_positions(account_id, ignored_order_refs=ignored_refs)
        
        logger.info(f"Sync completed successfully for {account_id}")
        
        # 6. Check if both syncs are complete and invoke callback
        self._check_and_invoke_completion_callback()
        
        return True

    def _save_flex_xml_file(self, xml_data: bytes, account_id: str, start_dt: datetime, end_dt: datetime) -> None:
        """Save XML payload to file system."""
        try:
            file_name = f"{account_id}-{start_dt.strftime('%Y%m%d')}-{end_dt.strftime('%Y%m%d')}.xml"
            file_path = Path("data") / file_name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(xml_data)
            logger.info(f"Saved Flex XML to: {file_path}")
        except Exception as e:
            logger.error(f"Failed to save Flex XML file: {e}")

    def _update_contract_if_present(self, item_data: Dict) -> None:
        """Update contract last_seen timestamp if con_id exists in item."""
        if item_data.get("con_id"):
            self.repo.update_contract_last_seen(item_data["con_id"])

    def _xml_contains_section(self, xml_data: bytes, tag: str) -> bool:
        """Check if XML contains a specific tag."""
        return f"<{tag}".encode() in xml_data

    def _process_and_save_items(
        self,
        items: List[Dict],
        account_id: str,
        save_func: Callable[[Dict], Any],
        item_type: str,
        update_contract: bool = True
    ) -> Tuple[int, bool]:
        """
        Generic processor for filtering and saving items by account_id.
        
        Args:
            items: List of item dictionaries to process
            account_id: Account ID to filter by
            save_func: Repository save function (e.g., self.repo.save_execution)
            item_type: Type name for logging (e.g., "executions")
            update_contract: Whether to update contract last_seen timestamp
            
        Returns:
            Tuple of (count, has_data)
        """
        count = 0
        has_data = False
        
        for item_data in items:
            if item_data["account_id"] == account_id:
                save_func(item_data)
                if update_contract:
                    self._update_contract_if_present(item_data)
                count += 1
                has_data = True
        
        logger.info(f"Saved {count} {item_type} to database.")
        return count, has_data

    def _process_contracts(self, xml_data: bytes) -> bool:
        """Process and save contracts from XML. Returns True if any contracts found."""
        flex_contracts = self.flex_service.parse_contracts_from_xml(xml_data)
        for c_data in flex_contracts:
            self.repo.save_contract(c_data)
        logger.info(f"Imported/Updated {len(flex_contracts)} contracts from Flex Query.")
        return len(flex_contracts) > 0

    def _process_executions(self, xml_data: bytes, account_id: str) -> Tuple[int, bool]:
        """Process and save executions from XML. Returns (count, has_data)."""
        executions = self.flex_service.parse_executions_from_xml(xml_data)
        logger.info(f"Parsed {len(executions)} executions from Flex Query.")
        
        count, has_data = self._process_and_save_items(
            executions, account_id, self.repo.save_execution, "new/existing executions"
        )
        return count, has_data

    def _process_orders(self, xml_data: bytes, account_id: str) -> Tuple[int, bool]:
        """Process and save orders from XML. Returns (count, has_data)."""
        orders = self.flex_service.parse_orders_from_xml(xml_data)
        logger.info(f"Parsed {len(orders)} orders from Flex Query.")
        
        count, has_data = self._process_and_save_items(
            orders, account_id, self.repo.save_order, "orders"
        )
        return count, has_data

    def _process_positions_and_lots(self, xml_data: bytes, account_id: str) -> bool:
        """Process and save positions and lots from XML. Returns True if any data found."""
        pos_data = self.flex_service.parse_positions_from_xml(xml_data)
        logger.info(
            f"Parsed {len(pos_data['positions'])} aggregate positions and "
            f"{len(pos_data['lots'])} lots from Flex Query."
        )
        
        # Process positions
        p_count, p_has_data = self._process_and_save_items(
            pos_data['positions'], account_id, self.repo.save_position,
            "aggregate positions", update_contract=False
        )
        
        # Process lots
        l_count, l_has_data = self._process_and_save_items(
            pos_data['lots'], account_id, self.repo.save_position_lot,
            "lots", update_contract=False
        )
        
        return p_has_data or l_has_data

    @trace
    def _process_flex_xml(self, xml_data: bytes, account_id: str, start_dt: datetime, end_dt: datetime) -> bool:
        """Parses XML and saves to DB. Returns True if any useful data (executions/orders/positions) was found."""
        
        # 1. Save XML file
        self._save_flex_xml_file(xml_data, account_id, start_dt, end_dt)
        
        has_data = False
        
        # 2. Process contracts (no filtering needed)
        has_data |= self._process_contracts(xml_data)
        
        # 3. Process executions
        _, found_data = self._process_executions(xml_data, account_id)
        has_data |= found_data
        
        # 4. Process orders (if present)
        if self._xml_contains_section(xml_data, "Order"):
            _, found_data = self._process_orders(xml_data, account_id)
            has_data |= found_data
        
        # 5. Process positions and lots (if present)
        if self._xml_contains_section(xml_data, "OpenPosition"):
            has_data |= self._process_positions_and_lots(xml_data, account_id)
        
        return has_data

    @trace
    def _sync_api_executions(self, account_id: str) -> bool:
        """Fetches latest executions from IB API and saves to DB. Returns True if sync was successful."""
        if not self.ib_conn or not self.ib_conn.isConnected():
            logger.info("IBConnection not active. Skipping API sync for current data.")
            return False

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
        success = self.ib_conn.execution_events[req_id].wait(timeout=API_SYNC_TIMEOUT)
        
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
            
            # Cleanup
            if req_id in self.ib_conn.execution_events:
                del self.ib_conn.execution_events[req_id]
            if req_id in self.ib_conn.executions_data:
                del self.ib_conn.executions_data[req_id]
            
            return True
        else:
            logger.error("API sync timed out waiting for executions.")
            
            # Cleanup
            if req_id in self.ib_conn.execution_events:
                del self.ib_conn.execution_events[req_id]
            if req_id in self.ib_conn.executions_data:
                del self.ib_conn.executions_data[req_id]
            
            return False
