# Bot Framework Implementation Plan

## 1. Directory Structure & Configuration Updates
- Create a new directory structure `config/default/`.
- Move the existing `.config.yaml` to `config/default/.config.yaml` to act as the primary system/connection configuration.
- Modify `main.py` to accept `--config-dir` (defaulting to `config/default`).
- Update `main.py` logic to load system config from the provided directory, treating this directory as the parent for all related configurations for this instance.

## 2. Core Bot Framework Classes
- **ConfigBase**: Create `src/bots/config_base.py` using `pydantic`. It will define the base fields every bot needs:
  - `bot_name` (str)
  - `bot_type` (str)
  - `log_level` (Enum)
- **BaseBot**: Create `src/bots/base_bot.py`. 
  - Will take a `ConfigBase` instance and a reference to the central `IBConnection` (or a proxy router) upon initialization.
  - Define empty callback methods (e.g., `tick_price(self, reqId, tickType, price, attrib): pass`) which subclasses can override.
  - Define proxy methods to interact with IB, allowing the central manager to aggregate identical requests (e.g., market data for the same symbol).

## 3. Bot Dispatcher / Manager
- Create a manager class (e.g., `BotManager`) responsible for:
  - Scanning all `*.yaml` files in the `--config-dir` (excluding `.config.yaml`).
  - Reading the `bot_type` from each file to dynamically import the correct `Bot` and `Config` classes (e.g., loading from `src.bots.<bot_type>.bot`).
  - Validating the YAML against the specific `ConfigBase` subclass.
  - Instantiating the bots.
  - Acting as the intermediary listener for `IBConnection` callbacks and routing them to the appropriate bots based on `reqId` or symbol.

## 4. Sample Implementation: Double Calendar
- Create `src/bots/double_calendar/__init__.py`
- Create `src/bots/double_calendar/config.py` defining `DoubleCalendarBotConfig(ConfigBase)`.
- Create `src/bots/double_calendar/bot.py` defining `DoubleCalendarBot(BaseBot)`.
- Create an example bot config: `config/default/double-calendar-DC57.yaml`.

## 5. Main Loop Integration
- Hook the new bot dispatcher into `main.py`, likely managing the `WorkerThread` so that events are successfully dispatched to all active bots while the system is connected.