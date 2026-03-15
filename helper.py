import os
import sys
import yaml
import logging
import argparse
from datetime import datetime

# --- Configure system logging ---
logger = logging.getLogger("system")
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Ensure the local src folder is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.db.database import init_db
from src.db.repository import Repository
import src.db.database as db

def load_config(filepath=".config.yaml") -> dict:
    if not os.path.exists(filepath):
        logger.error(f"Configuration file {filepath} not found.")
        return {}
    try:
        with open(filepath, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to parse {filepath}: {e}")
        return {}

def get_timestamps(args):
    """
    Reads the last synchronization timestamp from the database.
    """
    config = load_config(args.config)
    db_url = config.get("database", {}).get("url", "sqlite:///data/trading_farm.db")
    init_db(db_url)
    repository = Repository(db.Session)
    
    conn_config = config.get("connection", {})
    selected_account = conn_config.get("selected_account", "")

    if not selected_account:
        logger.error("No 'selected_account' found in config. Cannot determine which account to check.")
        return

    sync_state = repository.get_sync_state(selected_account)

    if sync_state:
        logger.info(f"Last sync status for account {selected_account}:")
        if sync_state.last_flex_sync_date:
            logger.info(f"  Flex Query Sync: {sync_state.last_flex_sync_date.isoformat()}")
        else:
            logger.info("  Flex Query Sync: Never")
        
        if sync_state.last_api_sync_date:
            logger.info(f"  API Sync: {sync_state.last_api_sync_date.isoformat()}")
        else:
            logger.info("  API Sync: Never")
    else:
        logger.info(f"No sync state found for account {selected_account}.")


def remove_timestamps(args):
    """
    Deletes the last synchronization timestamp from the database.
    """
    config = load_config(args.config)
    db_url = config.get("database", {}).get("url", "sqlite:///data/trading_farm.db")
    init_db(db_url)
    repository = Repository(db.Session)
    
    conn_config = config.get("connection", {})
    selected_account = conn_config.get("selected_account", "")

    if not selected_account:
        logger.error("No 'selected_account' found in config. Cannot determine which account to update.")
        return

    sync_state = repository.get_sync_state(selected_account)

    if sync_state:
        sync_state.last_flex_sync_date = None
        sync_state.last_api_sync_date = None
        repository.db.add(sync_state)
        repository.db.commit()
        logger.info(f"Timestamps for account {selected_account} have been removed.")
    else:
        logger.info(f"No sync state found for account {selected_account}.")


def main():
    parser = argparse.ArgumentParser(description="Helper script for trading-bot-farm development.")
    parser.add_argument("-c", "--config", default=".config.yaml", help="Path to config file")
    
    subparsers = parser.add_subparsers(dest="command", help="Available tools")
    
    # get-timestamps command
    get_timestamps_parser = subparsers.add_parser("get-timestamps", help="Get the last sync timestamps from the database.")
    
    # remove-timestamps command
    remove_timestamps_parser = subparsers.add_parser("remove-timestamps", help="Remove the last sync timestamps from the database.")
    
    args = parser.parse_args()

    if args.command == "get-timestamps":
        get_timestamps(args)
    elif args.command == "remove-timestamps":
        remove_timestamps(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
