import os
import yaml
import importlib
import logging
from typing import Dict, List
from src.bots.base_bot import BaseBot
from src.ib_connection import IBConnection
from src.timer_manager import TimerManager

class BotManager:
    def __init__(self, config_dir: str, ib_connection: IBConnection, logger: logging.Logger):
        self.config_dir = config_dir
        self.ib_connection = ib_connection
        self.bots: Dict[str, BaseBot] = {}
        self.logger = logger
        self.timer_manager = TimerManager()
        self.bots_started = False

    def discover_and_load_bots(self):
        self.logger.info(f"Discovering bots in {self.config_dir}...")
        for filename in os.listdir(self.config_dir):
            if filename.endswith(".yaml") and filename != ".config.yaml":
                filepath = os.path.join(self.config_dir, filename)
                self.load_bot_from_config(filepath)

    def load_bot_from_config(self, filepath: str):
        try:
            with open(filepath, "r") as f:
                config_data = yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to parse {filepath}: {e}")
            return

        bot_type = config_data.get("bot_type")
        if not bot_type:
            self.logger.error(f"bot_type not found in {filepath}")
            return

        try:
            config_module = importlib.import_module(f"src.bots.{bot_type}.config")
            bot_module = importlib.import_module(f"src.bots.{bot_type}.bot")

            config_class_name = "".join([part.capitalize() for part in bot_type.split("_")]) + "Config"
            bot_class_name = "".join([part.capitalize() for part in bot_type.split("_")]) + "Bot"
            
            ConfigClass = getattr(config_module, config_class_name)
            BotClass = getattr(bot_module, bot_class_name)

            config = ConfigClass(**config_data)
            bot_instance = BotClass(config, self.ib_connection, self.timer_manager, self.config_dir)
            
            self.bots[config.bot_name] = bot_instance
            self.logger.info(f"Loaded bot: {config.bot_name} ({bot_type})")

        except (ModuleNotFoundError, AttributeError) as e:
            self.logger.error(f"Failed to load bot '{bot_type}': {e}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while loading bot '{bot_type}': {e}")

    def start_all_bots(self):
        """
        Start all bots. This should only be called after full synchronization
        (both API and Flex Query) is complete.
        """
        if self.bots_started:
            self.logger.debug("Bots already started, skipping.")
            return
            
        self.logger.info("Starting all bots...")
        self.timer_manager.start()
        for bot in self.bots.values():
            bot.start()
        self.bots_started = True

    def stop_all_bots(self):
        self.logger.info("Stopping all bots...")
        self.timer_manager.stop()
        for bot in self.bots.values():
            bot.stop()
