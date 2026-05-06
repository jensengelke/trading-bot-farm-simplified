import os
import sys
import yaml
import logging
import argparse
from datetime import datetime
import shutil
import glob

# Ensure the local src folder is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.logging_config import setup_logging
from src.ib_connection import IBConnection
from src.db.database import Base, init_db
import src.db.database as db
from src.db.repository import Repository
from src.services.flex_query_service import FlexQueryService
from src.services.sync_manager import SyncManager
from src.bot_manager import BotManager

def load_config(config_dir="config/default", logger: logging.Logger | None = None) -> dict:
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
        # For dictionaries, preserve all keys (including 0) and only filter values
        return {k: object_to_dict(v) for k, v in obj.items() if object_to_dict(v) not in (None, "", [], {})}
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
        print(f"{title}: None")
        logger.info(f"{title}: None")
        return
    
    clean_data = object_to_dict(data)
    yaml_str = yaml.dump(clean_data, default_flow_style=False, sort_keys=False)
    output = f"\n{title}:\n{yaml_str}"
    print(output)
    logger.info(output)

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

def setup_environment(args) -> tuple:
    """Setup logging and load configuration.
    
    Returns:
        tuple: (logger, config, selected_account)
    """
    config_dir_name = os.path.basename(os.path.normpath(args.config_dir))
    log_dir = os.path.join("logs", config_dir_name)
    roll_log_files(log_dir)
    
    logger = setup_logging("system", log_dir)
    
    # Setup dedicated debug logger for order cache investigation
    from src.logging_config import setup_debug_logger
    setup_debug_logger("order_cache_debug", log_dir)
    
    config = load_config(args.config_dir, logger)
    
    if not config:
        logger.error("Failed to load configuration. Aborting.")
        sys.exit(1)
    
    selected_account = config.get("connection", {}).get("selected_account", "")
    return logger, config, selected_account


def initialize_connection(config: dict, logger: logging.Logger) -> IBConnection:
    """Initialize IB connection with config parameters.
    
    Returns:
        IBConnection: Configured IB connection instance
    """
    conn_config = config.get("connection", {})
    host = conn_config.get("host", "127.0.0.1")
    port = conn_config.get("port", 7497)
    client_id = conn_config.get("client_id", 1)
    selected_account = conn_config.get("selected_account", "")
    
    logger.info("Initializing IBConnection layer...")
    ib_conn = IBConnection(host, port, client_id, selected_account)
    ib_conn.reqMarketDataType(2)  # live frozen
    
    return ib_conn


def initialize_database(config: dict, logger: logging.Logger) -> Repository:
    """Initialize database and return repository.
    
    Returns:
        Repository: Database repository instance
    """
    logger.info("Initializing database...")
    db_url = config.get("database", {}).get("url", "sqlite:///data/trading_farm.db")
    
    try:
        init_db(db_url)
        Base.metadata.create_all(bind=db.engine)
        return Repository(db.Session())
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)


def initialize_sync_manager(repository: Repository, ib_conn: IBConnection,
                           config: dict, bot_manager: BotManager,
                           logger: logging.Logger, flex_query_start_date: str | None = None) -> SyncManager:
    """Initialize sync manager with completion callback.
    
    Args:
        flex_query_start_date: Optional forced start date for flex query (YYYY-MM-DD format)
    
    Returns:
        SyncManager: Configured sync manager instance
    """
    logger.info("Initializing Sync Manager...")
    flex_service = FlexQueryService()
    sync_manager = SyncManager(repository, flex_service, ib_conn, config=config,
                              flex_query_start_date=flex_query_start_date)
    
    # Register sync completion callback to start bots after sync
    def on_full_sync_complete():
        logger.info("Account sync complete. Starting all bots now...")
        bot_manager.start_all_bots()
    
    sync_manager.set_sync_completion_callback(on_full_sync_complete)
    return sync_manager


def perform_initial_sync(ib_conn: IBConnection, sync_manager: SyncManager,
                        selected_account: str, logger: logging.Logger) -> None:
    """Attempt connection and perform initial account sync."""
    if not selected_account:
        logger.info("No account selected. Skipping initial sync.")
        return
    
    logger.info("Attempting connection to IBKR for initial sync...")
    success = ib_conn.connect_and_start()
    if success:
        logger.info("Connected successfully.")
    else:
        logger.warning("Failed to connect. API sync will be skipped.")
        return

    logger.info(f"Performing initial sync for account {selected_account}...")
    try:
        success = sync_manager.sync_account(selected_account)
        if not success:
            logger.warning(f"Sync skipped or failed for {selected_account}")
    except Exception as e:
        logger.error(f"Error during sync: {e}")


class MenuHandler:
    """Handles CLI menu operations."""
    
    def __init__(self, ib_conn: IBConnection, bot_manager: BotManager,
                 sync_manager: SyncManager, selected_account: str,
                 logger: logging.Logger):
        self.ib_conn = ib_conn
        self.bot_manager = bot_manager
        self.sync_manager = sync_manager
        self.selected_account = selected_account
        self.logger = logger
        
        # Menu dispatch table
        self.handlers = {
            "1": self.handle_connect,
            "2": self.handle_disconnect,
            "3": self.handle_status,
            "4": self.handle_positions,
            "5": self.handle_orders,
            "6": self.handle_summary,
            "7": self.handle_exit,
        }
    
    def handle_connect(self) -> bool:
        """Handle connection request. Returns True to continue loop."""
        if not self.ib_conn.isConnected():
            self.logger.info("Attempting connection...")
            success = self.ib_conn.connect_and_start()
            if success:
                self._perform_sync()
        else:
            self.logger.info("Already connected.")
        return True
    
    def handle_disconnect(self) -> bool:
        """Handle disconnection request. Returns True to continue loop."""
        if self.ib_conn.isConnected():
            self.bot_manager.stop_all_bots()
            self.ib_conn.disconnect_and_stop()
        else:
            self.logger.info("Not currently connected.")
        return True
    
    def handle_status(self) -> bool:
        """Handle status check. Returns True to continue loop."""
        status = "Connected" if self.ib_conn.isConnected() else "Disconnected"
        message = f"Connection Status: {status}"
        print(message)
        self.logger.info(message)
        return True
    
    def handle_positions(self) -> bool:
        """Handle positions view. Returns True to continue loop."""
        positions = self.ib_conn.get_cached_positions()
        print_yaml("Cached Positions", positions, self.logger)
        return True
    
    def handle_orders(self) -> bool:
        """Handle orders view. Returns True to continue loop."""
        orders = self.ib_conn.get_orders()
        print_yaml("Open Orders", orders, self.logger)
        return True
    
    def handle_summary(self) -> bool:
        """Handle account summary view. Returns True to continue loop."""
        summary = self.ib_conn.get_cached_account_summary()
        print_yaml("Account Summary", summary, self.logger)
        return True
    
    def handle_exit(self) -> bool:
        """Handle exit request. Returns False to stop loop."""
        self.logger.info("Exiting application...")
        if self.ib_conn.isConnected():
            self.bot_manager.stop_all_bots()
            self.ib_conn.disconnect_and_stop()
        return False
    
    def _perform_sync(self) -> None:
        """Helper to perform account sync."""
        self.logger.info(f"Performing sync for account {self.selected_account}...")
        try:
            self.sync_manager.sync_account(self.selected_account)
        except Exception as e:
            self.logger.error(f"Error during sync: {e}")
    
    def process_choice(self, choice: str) -> bool:
        """Process menu choice. Returns True to continue, False to exit."""
        handler = self.handlers.get(choice)
        if handler:
            return handler()
        else:
            self.logger.info("Invalid selection.")
            return True


class ApplicationContext:
    """Context manager for application resources."""
    
    def __init__(self, ib_conn: IBConnection, bot_manager: BotManager,
                 logger: logging.Logger):
        self.ib_conn = ib_conn
        self.bot_manager = bot_manager
        self.logger = logger
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Guaranteed cleanup on exit."""
        self.logger.info("Cleaning up resources...")
        
        # Stop bots first
        try:
            self.bot_manager.stop_all_bots()
        except Exception as e:
            self.logger.error(f"Error stopping bots: {e}")
        
        # Disconnect IB
        try:
            if self.ib_conn.isConnected():
                self.ib_conn.disconnect_and_stop()
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
        
        self.logger.info("Cleanup complete.")
        return False  # Don't suppress exceptions


def run_cli_loop(menu_handler: MenuHandler) -> None:
    """Run the interactive CLI menu loop."""
    running = True
    while running:
        print_menu()
        choice = input("Select an option: ").strip()
        running = menu_handler.process_choice(choice)


def main():
    """Main entry point for Trading Bot Farm V2."""
    # Parse arguments
    parser = argparse.ArgumentParser(description="Trading Bot Farm V2")
    parser.add_argument("--config-dir", default="config/default",
                       help="Path to config directory")
    parser.add_argument("--flex-query-start-date", type=str, default=None,
                       help="Force flex query sync from this date (format: YYYY-MM-DD)")
    args = parser.parse_args()
    
    # Setup environment
    logger, config, selected_account = setup_environment(args)
    
    # Initialize components
    ib_conn = initialize_connection(config, logger)
    repository = initialize_database(config, logger)
    
    bot_manager = BotManager(args.config_dir, ib_conn, logger)
    bot_manager.discover_and_load_bots()
    
    sync_manager = initialize_sync_manager(repository, ib_conn, config,
                                          bot_manager, logger,
                                          args.flex_query_start_date)
    
    # Use context manager for guaranteed cleanup
    with ApplicationContext(ib_conn, bot_manager, logger):
        # Perform initial sync
        perform_initial_sync(ib_conn, sync_manager, selected_account, logger)
        
        # Create menu handler and run CLI loop
        menu_handler = MenuHandler(ib_conn, bot_manager, sync_manager,
                                   selected_account, logger)
        run_cli_loop(menu_handler)

if __name__ == "__main__":
    main()
