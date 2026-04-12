import os
import sys
import yaml
import time
import signal
import threading
import logging
import argparse
from datetime import datetime
import shutil
import glob

# Ensure the local src folder is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.ib_connection import IBConnection
from src.db.database import Base, init_db
import src.db.database as db
from src.db.repository import Repository
from src.services.flex_query_service import FlexQueryService
from src.services.sync_manager import SyncManager
from src.bot_manager import BotManager

class WorkerThread(threading.Thread):
    def __init__(self, ib_connection: IBConnection, logger: logging.Logger):
        super().__init__(daemon=True)
        self.ib_connection = ib_connection
        self.running = False
        self.logger = logger

    def run(self):
        self.running = True
        self.logger.info("Worker thread started. Monitoring connection state...")
        while self.running:
            time.sleep(1)

    def stop(self):
        self.logger.info("Stopping worker thread...")
        self.running = False

def load_config(config_dir="config/default", logger: logging.Logger = None) -> dict:
    filepath = os.path.join(config_dir, ".config.yaml")
    if not os.path.exists(filepath):
        if logger:
            logger.error(f"Configuration file {filepath} not found.")
        return {}
    try:
        with open(filepath, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse {filepath}: {e}")
        return {}

def object_to_dict(obj):
    """Recursively convert objects to dictionaries for YAML serialization."""
    from decimal import Decimal
    if isinstance(obj, dict):
        return {k: object_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [object_to_dict(v) for v in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '__dict__'):
        return {k: object_to_dict(v) for k, v in vars(obj).items() if not k.startswith('_') and v is not None and v != "" and v != 0 and v != 0.0 and v != False and v != [] and object_to_dict(v) != {}}
    elif hasattr(obj, '__slots__'):
        return {k: object_to_dict(getattr(obj, k)) for k in obj.__slots__ if hasattr(obj, k) and getattr(obj, k) is not None}
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)

def print_yaml(title, data, logger: logging.Logger):
    if not data:
        logger.info(f"{title}: None")
        return
    
    clean_data = object_to_dict(data)
    yaml_str = yaml.dump(clean_data, default_flow_style=False, sort_keys=False)
    logger.info(f"\n{title}:\n{yaml_str}")

def print_menu():
    print("\n" + "="*40)
    print(" V2 Farm API Interface")
    print("="*40)
    print("  1. Connect to IBKR")
    print("  2. Disconnect")
    print("  3. Check Status")
    print("  4. View Cached Positions")
    print("  5. View Open Orders")
    print("  6. View Account Summary")
    print("  7. Exit")
    print("="*40)

def roll_log_files(log_dir):
    """
    Moves existing .log files in log_dir to a timestamped sub-directory.
    """
    if not os.path.isdir(log_dir):
        return
    
    now = datetime.now()
    timestamp_dir_name = now.strftime("%Y-%m-%d-%H-%M-%S")
    timestamp_dir_path = os.path.join(log_dir, timestamp_dir_name)
    
    try:
        # Find log files before creating the new directory
        log_files = glob.glob(os.path.join(log_dir, '*.log'))

        if log_files:
            os.makedirs(timestamp_dir_path, exist_ok=True)
            
            for log_file in log_files:
                # Check if the destination file already exists (unlikely)
                # and if so, don't move it.
                base_name = os.path.basename(log_file)
                if not os.path.exists(os.path.join(timestamp_dir_path, base_name)):
                    shutil.move(log_file, timestamp_dir_path)
                else:
                    print(f"Log file {base_name} already exists in {timestamp_dir_path}, skipping.")

    except Exception as e:
        # If logging is not yet configured, just print to console.
        print(f"Error rolling log files: {e}")

def main():
    parser = argparse.ArgumentParser(description="Trading Bot Farm V2")
    parser.add_argument("--config-dir", default="config/default", help="Path to config directory")
    args = parser.parse_args()

    # --- Log rolling ---
    config_dir_name = os.path.basename(os.path.normpath(args.config_dir))
    log_dir = os.path.join("logs", config_dir_name)
    roll_log_files(log_dir)

    # --- Configure system logging according to specification ---
    logger = logging.getLogger("system")
    logger.setLevel(logging.DEBUG)
    
    # Console handler for end user (INFO level and up)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler for system log (DEBUG level for tracing)
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(log_dir, "system.log"), mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(file_formatter)
    
    logger.addHandler(file_handler)

    config = load_config(args.config_dir, logger)
    conn_config = config.get("connection", {})
    
    # Extract config properties
    host = conn_config.get("host", "127.0.0.1")
    port = conn_config.get("port", 7497)
    client_id = conn_config.get("client_id", 1)
    selected_account = conn_config.get("selected_account", "")

    logger.info("Initializing IBConnection layer...")
    ib_conn = IBConnection(host, port, client_id, selected_account)
    # live frozen     
    ib_conn.reqMarketDataType(2)
    
    logger.info("Initializing database...")
    db_url = config.get("database", {}).get("url", "sqlite:///data/trading_farm.db")
    init_db(db_url)
    Base.metadata.create_all(bind=db.engine)
    repository = Repository(db.Session)

    logger.info("Initializing Sync Manager...")
    flex_service = FlexQueryService()
    sync_manager = SyncManager(repository, flex_service, ib_conn, config=config)

    # Initialize Bot Manager
    bot_manager = BotManager(args.config_dir, ib_conn, logger)
    bot_manager.discover_and_load_bots()
    # TODO: add back when implementing listeners for account events
    # for bot in bot_manager.bots.values():
    #    ib_conn.register_listener(bot)

    # Automatically attempt connection before syncing so we can fetch API data
    if selected_account:
        logger.info("Attempting connection to IBKR for initial sync...")
        success = ib_conn.connect_and_start()
        if success:
            logger.info("Connected successfully.")
        else:
            logger.warning("Failed to connect. API sync will be skipped.")

        logger.info(f"Performing initial sync for account {selected_account}...")
        try:
            success = sync_manager.sync_account(selected_account)
            if success:
                logger.info(f"Sync completed for {selected_account}")
            else:
                logger.warning(f"Sync skipped or failed for {selected_account}")
        except Exception as e:
            logger.error(f"Error during sync: {e}")

    # Setup Worker Thread
    worker = WorkerThread(ib_conn, logger)
    if ib_conn.isConnected() and not worker.is_alive():
        worker.start()
        bot_manager.start_all_bots()

    # CLI Loop
    running = True
    while running:
        print_menu()
        choice = input("Select an option: ").strip()

        if choice == "1":
            if not ib_conn.isConnected():
                logger.info("Attempting connection...")
                success = ib_conn.connect_and_start()
                if success and not worker.is_alive():
                    worker.start()
                    bot_manager.start_all_bots()
            else:
                logger.info("Already connected.")
                
        elif choice == "2":
            if ib_conn.isConnected():
                bot_manager.stop_all_bots()
                ib_conn.disconnect_and_stop()
                if worker.is_alive():
                    worker.stop()
                    worker.join(timeout=2)
            else:
                logger.info("Not currently connected.")
                
        elif choice == "3":
            status = "Connected" if ib_conn.isConnected() else "Disconnected"
            logger.info(f"Connection Status: {status}")
            
        elif choice == "4":
            positions = ib_conn.get_cached_positions()
            print_yaml("Cached Positions", positions, logger)
            
        elif choice == "5":
            orders = ib_conn.get_orders()
            print_yaml("Open Orders", orders, logger)
            
        elif choice == "6":
            summary = ib_conn.get_cached_account_summary()
            print_yaml("Account Summary", summary, logger)
            
        elif choice == "7":
            logger.info("Exiting application...")
            if ib_conn.isConnected():
                bot_manager.stop_all_bots()
                ib_conn.disconnect_and_stop()
            worker.stop()
            running = False
            
        else:
            logger.info("Invalid selection.")

if __name__ == "__main__":
    main()
