import requests
import time
import xml.etree.ElementTree as ET
import logging
import os
import re
from ..utils import trace
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("system")

DEFAULT_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

class FlexQueryService:
    @trace
    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url

    @trace
    def _get_last_to_date(self, account_id: str) -> Optional[date]:
        """
        Scans data/ directory for {account_id}.xml and finds the toDate 
        from the FlexStatement element.
        """
        file_path = os.path.join("data", f"{account_id}.xml")
        if not os.path.exists(file_path):
            return None
        
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # Find the FlexStatement element
            statement = root.find(".//FlexStatement")
            if statement is not None:
                to_date_str = statement.get("toDate")
                if to_date_str:
                    logger.info(f"Found last toDate for account {account_id}: {to_date_str}")
                    return datetime.strptime(to_date_str, "%Y-%m-%d").date()
        except Exception as e:
            logger.debug(f"Error reading {file_path} for last toDate: {e}")
            
        return None

    @trace
    def _adjust_start_date(self, dt: date) -> date:
        """Adjusts start date to the next weekday if it's a weekend."""
        if dt.weekday() >= 5:  # Saturday or Sunday
            adjusted_date = dt + timedelta(days=7 - dt.weekday())
            logger.info(f"Adjusted start date from {dt} (weekend) to {adjusted_date} (weekday).")
            return adjusted_date
        return dt

    @trace
    def _adjust_end_date(self, dt: date) -> date:
        """Adjusts end date to the previous weekday if it's a weekend."""
        if dt.weekday() >= 5:  # Saturday or Sunday
            adjusted_date = dt - timedelta(days=dt.weekday() - 4)
            logger.info(f"Adjusted end date from {dt} (weekend) to {adjusted_date} (weekday).")
            return adjusted_date
        return dt

    @trace
    def download_flex_data(self, token: str, query_id: str, start_date: date, end_date: date) -> (Optional[bytes], Optional[date], Optional[date]):
        """
        Downloads Flex Query data (XML) using the two-step process, with retry logic for invalid date ranges.
        Returns the raw XML bytes and the effective dates used, or (None, None, None) if failed.
        """
        original_start_date = start_date
        original_end_date = end_date

        current_start_date = self._adjust_start_date(start_date)
        current_end_date = self._adjust_end_date(end_date)
        
        max_date_shift = 3
        
        for day_shift in range(max_date_shift + 1):
            
            if day_shift > 0:
                logger.info(f"Date adjustment iteration {day_shift}/{max_date_shift}...")

            # Primary attempt with current dates
            xml_content = self._send_flex_request(token, query_id, current_start_date, current_end_date)
            if xml_content:
                return xml_content, current_start_date, current_end_date

            # After 3 failures, try adjusting start_date, then end_date
            if day_shift < max_date_shift:
                
                # Adjust start_date forward
                logger.info("Adapting start date due to persistent failures...")
                current_start_date += timedelta(days=1)
                current_start_date = self._adjust_start_date(current_start_date)
                
                xml_content = self._send_flex_request(token, query_id, current_start_date, current_end_date)
                if xml_content:
                    return xml_content, current_start_date, current_end_date
                
                # Adjust end_date backward
                logger.info("Adapting end date due to persistent failures...")
                current_end_date -= timedelta(days=1)
                current_end_date = self._adjust_end_date(current_end_date)

                xml_content = self._send_flex_request(token, query_id, current_start_date, current_end_date)
                if xml_content:
                    return xml_content, current_start_date, current_end_date

        logger.error(f"Flex Query failed definitively after moving start date to {current_start_date} and end date to {current_end_date}. Aborting.")
        return None, None, None

    def _send_flex_request(self, token: str, query_id: str, start_date: date, end_date: date) -> Optional[bytes]:
        """
        Internal method to handle a single Flex Query request sequence for a given date range.
        """
        send_path = "/SendRequest"
        payload = {
            "t": token, 
            "q": query_id, 
            "v": 3,
            "fd": start_date.strftime("%Y%m%d"),
            "td": end_date.strftime("%Y%m%d")
        }
        
        logger.info(f"Initiating Flex Query {query_id} for period {start_date.strftime('%Y%m%d')} to {end_date.strftime('%Y%m%d')}...")
        logger.info(f"Flex Query SOAP payload: {payload}")
        
        max_send_retries = 3
        ref_code = None
        
        for attempt in range(max_send_retries):
            try:
                resp = requests.get(f"{self.base_url}{send_path}", params=payload)
                resp.raise_for_status()
                
                root = ET.fromstring(resp.content)
                status_elem = root.find("Status")
                
                if status_elem is not None and status_elem.text == "Success":
                    ref_code_elem = root.find("ReferenceCode")
                    if ref_code_elem is not None:
                        ref_code = ref_code_elem.text
                        logger.info(f"Flex Query requested. Reference Code: {ref_code}")
                        break
                    else:
                        logger.error("No ReferenceCode found in successful Flex response.")
                        return None # Fatal error for this attempt, but might be retried with new dates
                else:
                    err_code = root.find("ErrorCode").text if root.find("ErrorCode") is not None else ""
                    err_msg = root.find("ErrorMessage").text if root.find("ErrorMessage") is not None else "Unknown Error"
                    
                    # Specific handling for rate limiting
                    if err_code in ("1001", "1018", "1019"):
                        wait_time = 60
                        logger.warning(f"Flex Query SendRequest rate limited (Code: {err_code}, Msg: {err_msg}). Waiting {wait_time}s before retry (Attempt {attempt+1}/{max_send_retries})...")
                        time.sleep(wait_time)
                        continue
                    # Check for invalid date range error message and stop retrying for this date range
                    elif "invalid" in err_msg.lower() and "date" in err_msg.lower():
                        logger.warning(f"Flex Query failed due to invalid date range: {err_msg}. No more retries for this range.")
                        return None
                    else:
                        logger.error(f"Flex Query request failed. Status: {status_elem.text if status_elem is not None else 'None'}. Error: {err_msg}")
                        # Don't retry on other fatal errors for this date range
                        return None
            except Exception as e:
                logger.error(f"Flex Query SendRequest failed with exception: {e} on attempt {attempt+1}/{max_send_retries}")
                time.sleep(10)
                
        if not ref_code:
            logger.error(f"Failed to get ReferenceCode after {max_send_retries} attempts for dates {start_date} to {end_date}.")
            return None

        # Step 2: Wait and Get Statement
        time.sleep(5)
        
        receive_path = "/GetStatement"
        receive_params = {"t": token, "q": ref_code, "v": 3}
        
        max_retries = 10
        for i in range(max_retries):
            logger.info(f"Polling for Flex Statement (Attempt {i+1}/{max_retries})...")
            try:
                resp = requests.get(f"{self.base_url}{receive_path}", params=receive_params)
                resp.raise_for_status()
                
                try:
                    snippet = resp.content[:200]
                    logger.debug(f"Flex Statement response snippet: {snippet}")
                    if b"<Status>Success</Status>" in snippet or b"FlexStatements" in snippet:
                        logger.info("Flex Statement request successful.")
                        logger.info(f"Flex XML Content (first 500 chars): {resp.content[:500]}")
                        return resp.content
                    elif b"<Status>Warn</Status>" in snippet or b"<Status>Fail</Status>" in snippet:
                         logger.info("Flex Statement status returned Warn or Fail.")
                         root = ET.fromstring(resp.content)
                         code = root.find("ErrorCode")
                         if code is not None and code.text == "1019": # Statement generation in progress
                             logger.info("Statement generation in progress. Waiting...")
                             time.sleep(5)
                             continue
                         else:
                             msg = root.find("ErrorMessage").text if root.find("ErrorMessage") is not None else "Unknown"
                             logger.error(f"GetStatement returned error: {msg}")
                             return None # Fatal error
                except Exception as e:
                    logger.exception(f"Error parsing Flex response status: {e}")
                    return resp.content
                
                logger.info("Flex Statement request failed. Retrying...")
                time.sleep(5)

            except Exception as e:
                logger.warning(f"GetStatement request error: {e}. Retrying...")
                time.sleep(5)
        
        logger.error("Timed out waiting for Flex Statement.")
        return None


    @trace
    def parse_executions_from_xml(self, xml_content: bytes) -> List[Dict[str, Any]]:
        """
        Parses the Flex XML and extracts execution data from 'Trade' elements.
        """
        executions = []
        try:
            root = ET.fromstring(xml_content)
            
            # Navigate to Trades -> Trade
            # Structure: FlexQueryResponse -> FlexStatements -> FlexStatement -> Trades -> Trade
            
            # Using iter to find all Trade tags anywhere (simpler)
            for trade in root.iter("Trade"):
                # We interpret transactionType="ExchTrade" as standard execution
                # Check filters if needed
                
                # Extract fields
                # Mapping XML attributes to our model fields
                
                # Check Transaction Type
                trans_type = trade.get("transactionType")
                if trans_type != "ExchTrade":
                    continue # Skip "BookTrade" or others if not relevant for raw executions
                    
                exec_id = trade.get("ibExecID")
                # Fallback to tradeID if ibExecID missing (unlikely for ExchTrade)
                if not exec_id:
                    exec_id = trade.get("tradeID")

                if not exec_id:
                    continue

                # Parse date
                date_str = trade.get("dateTime") # e.g. "2026-01-02 100726"
                try:
                    # Adjust format based on sample. Sample: "2026-01-02 100726" (YYYY-MM-DD HHMMSS)
                    # We might need flexible parsing.
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H%M%S")
                except ValueError:
                     # Fallback or log
                     logger.warning(f"Could not parse date: {date_str}")
                     dt = datetime.now() # Should not happen often
                
                # Symbol
                symbol = trade.get("symbol")
                
                # Side
                side = trade.get("buySell") # BUY/SELL
                
                # Quantity
                try:
                    qty = float(trade.get("quantity", 0))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse quantity from trade: {e}")
                    qty = 0.0
                    
                # Price
                try:
                    price = float(trade.get("tradePrice", 0))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse tradePrice from trade: {e}")
                    price = 0.0
                    
                # Order Ref
                order_ref = trade.get("orderReference")
                
                # ConID and PermID
                con_id_str = trade.get("conid")
                con_id = int(con_id_str) if con_id_str else None
                
                perm_id_str = trade.get("ibOrderID")
                perm_id = int(perm_id_str) if perm_id_str else None

                # Account
                account_id = trade.get("accountId")
                
                executions.append({
                    "exec_id": exec_id,
                    "account_id": account_id,
                    "order_ref": order_ref,
                    "time": dt,
                    "symbol": symbol,
                    "side": side,
                    "quantity": qty,
                    "price": price,
                    "con_id": con_id,
                    "perm_id": perm_id,
                    "exchange": trade.get("listingExchange"),
                    "commission": float(trade.get("ibCommission", 0)) if trade.get("ibCommission") else 0.0,
                    "commission_currency": trade.get("ibCommissionCurrency"),
                    "model_code": trade.get("model"),
                    "submitter": trade.get("traderID")
                })
                
        except ET.ParseError as e:
            logger.error(f"XML Parse Error: {e}")
            
        return executions

    @trace
    def parse_orders_from_xml(self, xml_content: bytes) -> List[Dict[str, Any]]:
        """
        Parses the Flex XML and extracts order data from 'Order' elements.
        """
        orders = []
        try:
            root = ET.fromstring(xml_content)
            
            # Navigate to FlexStatements -> FlexStatement -> Orders -> Order
            for order_elem in root.iter("Order"):
                try:
                    perm_id_str = order_elem.get("ibOrderID")
                    if not perm_id_str:
                         continue
                    perm_id = int(perm_id_str)
                    
                    account_id = order_elem.get("accountId")
                    order_ref = order_elem.get("orderReference")
                    
                    con_id_str = order_elem.get("conid")
                    con_id = int(con_id_str) if con_id_str else 0
                    
                    symbol = order_elem.get("symbol")
                    sec_type = order_elem.get("assetCategory")
                    exchange = order_elem.get("listingExchange")
                                        
                    # Handle BAG/Combo symbols
                    if sec_type == "BAG":
                        logger.info(f"Found BAG order: {order_elem}")
                        legs = []
                        for leg in order_elem.iter("OrderComboLeg"):
                             l_sym = leg.get("symbol") or leg.get("conid")
                             l_qty = leg.get("quantity", "1")
                             
                             # Some Flex reports Might use ratio instead of quantity
                             if not l_qty or l_qty == "0":
                                 l_qty = leg.get("ratio", "1")
                                 
                             if l_sym:
                                 legs.append(f"{l_qty} x {l_sym}")
                        
                        if legs:
                            symbol = " + ".join(legs)
                    
                    action = order_elem.get("buySell")
                    order_type = order_elem.get("orderType")
                    
                    try:
                        total_quantity = float(order_elem.get("quantity", 0))
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse order quantity: {e}")
                        total_quantity = 0.0

                    try:
                        lmt_price = float(order_elem.get("orderPrice", 0)) # Verify field name from XML spec if possible, usually orderPrice or limitPrice
                        # Fallback if 0 for Limit orders might be tradePrice?
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse order price: {e}")
                        lmt_price = 0.0
                        
                    try:
                        aux_price = float(order_elem.get("auxPrice", 0))
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse aux price: {e}")
                        aux_price = 0.0

                    # Status might be inferred
                    status = "Unknown" # Flex queries often are historical, so might be 'Filled' or 'Cancelled' but explicit status field varies
                    
                    # Parsing timestamps
                    order_time_str = order_elem.get("orderTime")
                    order_time = None
                    if order_time_str:
                        try:
                             # Format: YYYY-MM-DD HHMMSS
                             order_time = datetime.strptime(order_time_str, "%Y-%m-%d %H%M%S")
                        except ValueError as e:
                             logger.warning(f"Failed to parse order time '{order_time_str}': {e}")
                    
                    orders.append({
                        "perm_id": perm_id,
                        # "client_order_id": ... # Not in Flex usually
                        "account_id": account_id,
                        "order_ref": order_ref,
                        "con_id": con_id,
                        "symbol": symbol,
                        "sec_type": sec_type,
                        "exchange": exchange,
                        "action": action,
                        "order_type": order_type,
                        "total_quantity": total_quantity,
                        "lmt_price": lmt_price,
                        "aux_price": aux_price,
                        "status": status,
                        "order_time": order_time,
                        "last_update_time": datetime.now()
                    })
                    
                except Exception as e:
                    logger.warning(f"Error parsing order element: {e}")
                    continue
                    
        except ET.ParseError as e:
             logger.error(f"XML Parse Error in parse_orders_from_xml: {e}")
             
        return orders

    @trace
    def parse_contracts_from_xml(self, xml_content: bytes) -> List[Dict[str, Any]]:
        """
        Parses the Flex XML and extracts contract metadata from 'SecurityInfo' elements.
        """
        contracts = []
        try:
            root = ET.fromstring(xml_content)
            
            for info in root.iter("SecurityInfo"):
                try:
                    con_id_str = info.get("conid")
                    if not con_id_str:
                         continue
                    con_id = int(con_id_str)
                    
                    symbol = info.get("symbol")
                    sec_type = info.get("assetCategory")
                    
                    # Map other fields if available
                    # Note: Flex XML field names often differ slightly from IB API Contract object or our DB model.
                    # We'll map what we can.
                    
                    contract_data = {
                        "con_id": con_id,
                        "symbol": symbol,
                        "sec_type": sec_type,
                        "exchange": info.get("listingExchange"),
                        "currency": info.get("currency"),
                        "local_symbol": info.get("symbol"), # Usually matches symbol in Flex for many types
                        "trading_class": info.get("tradingClass"),
                        "long_name": info.get("description"),
                        "last_update_time": datetime.now(),
                        "last_seen": datetime.now()
                    }
                    
                    # Handle specific types like Options/Futures if fields exist
                    expiry = info.get("expiry")
                    if expiry:
                        contract_data["last_trade_date_or_contract_month"] = expiry
                        
                    strike = info.get("strike")
                    if strike:
                        try:
                            contract_data["strike"] = float(strike)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to parse strike price '{strike}': {e}")
                            
                    right = info.get("putCall")
                    if right:
                        contract_data["right"] = "C" if right == "Call" else "P" if right == "Put" else right
                        
                    multiplier = info.get("multiplier")
                    if multiplier:
                        contract_data["multiplier"] = multiplier

                    contracts.append(contract_data)
                    
                except Exception as e:
                    logger.warning(f"Error parsing SecurityInfo element: {e}")
                    continue
                    
        except ET.ParseError as e:
             logger.error(f"XML Parse Error in parse_contracts_from_xml: {e}")
             
        return contracts


    @trace
    def parse_positions_from_xml(self, xml_content: bytes) -> Dict[str, Any]:
        """
        Parses the Flex XML and extracts position and lot data from 'OpenPosition' elements.
        Returns a dictionary with 'positions' and 'lots'.
        """
        positions = []
        lots = []
        try:
            root = ET.fromstring(xml_content)
            
            for op_elem in root.iter("OpenPosition"):
                try:
                    account_id = op_elem.get("accountId")
                    con_id_str = op_elem.get("conid")
                    if not con_id_str:
                        continue
                    con_id = int(con_id_str)
                    
                    lod = op_elem.get("levelOfDetail")
                    
                    if lod == "SUMMARY":
                        positions.append({
                            "account_id": account_id,
                            "con_id": con_id,
                            "symbol": op_elem.get("symbol"),
                            "underlying": op_elem.get("underlyingSymbol"),
                            "sec_type": op_elem.get("assetCategory"),
                            "currency": op_elem.get("currency"),
                            "position": float(op_elem.get("position", 0)),
                            "avg_cost": float(op_elem.get("costBasisPrice", 0)),
                            "mkt_price": float(op_elem.get("markPrice", 0)),
                            "mkt_value": float(op_elem.get("positionValue", 0)),
                            "unrealized_pnl": float(op_elem.get("fifoPnlUnrealized", 0)),
                            "last_update_time": datetime.now()
                        })
                    elif lod == "LOT":
                        open_date_str = op_elem.get("openDateTime")
                        open_date = None
                        if open_date_str:
                            try:
                                # Flex openDateTime format can vary, but usually YYYY-MM-DD HHMMSS or YYYY-MM-DD
                                if len(open_date_str) > 10:
                                    open_date = datetime.strptime(open_date_str, "%Y-%m-%d %H%M%S")
                                else:
                                    open_date = datetime.strptime(open_date_str, "%Y-%m-%d")
                            except ValueError as e:
                                logger.warning(f"Failed to parse open date '{open_date_str}': {e}")
                        
                        lots.append({
                            "lot_id": op_elem.get("originatingTransactionID") or f"lot-{account_id}-{con_id}-{len(lots)}",
                            "account_id": account_id,
                            "con_id": con_id,
                            "quantity": float(op_elem.get("position", 0)),
                            "avg_price": float(op_elem.get("openPrice", 0)),
                            "open_date_time": open_date
                        })
                except Exception as e:
                    logger.warning(f"Error parsing OpenPosition element: {e}")
                    continue
                    
        except ET.ParseError as e:
            logger.error(f"XML Parse Error in parse_positions_from_xml: {e}")
            
        return {"positions": positions, "lots": lots}
