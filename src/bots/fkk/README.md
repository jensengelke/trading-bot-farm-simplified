# FKKBot - Für kleine Konten
Bull put spread on SPX, default: - entry time: 14:15 Eastern
5 points width, 35 delta

# Config
Implemented in src\bots\fkk\config.py
Configured in e.g. config\default\fkk-2015-5.yaml
```yaml
bot_name: "fkk-2015-5"
bot_type: "fkk"
log_level: "INFO"
timezone: "America/New_York"
entry_time: "14:15"
delta: 35
width: 5
```

# Implementation
Implemented in src\bots\fkk\bot.py  

## Phases
- Start
- Confirm Entry Conditions
- Entry

## State variables
- underlying_contract: Contract
- underlying_contract_resolution_status: ContractResolutionStatus

### Phase "Start"
Implemented as a lifecycle method of BaseBot: start()
- Schedule `confirm_entry_conditions` based on config. Timer needs to be for today or tomorrow depending on current time relative to entry_time

### Phase "Confirm Entry Conditions"
Implemented as a method `on_confirm_entry_conditions()` called by `on_timer()` upon receiving the `confirm_entry_conditions` timer event
- determine if today is a trading day: 
    - Resolve underlying SPX contract and check `tradingHours` and `liquidHours` fields of the returned contract object. Resolving a contract is an async operation, so this method only invokes BaseBot.resolve_contracts() and returns immediately. The result is handled in the callback method `on_confirm_entry_conditions_on_underlying_contract_resolved()`.
    - `confirm_entry_conditions_on_underlying_contract_resolved()` receives ContractDetails with tradingHours and liquidHours strings follow a specific format: YYYYMMDD:START-END;YYYYMMDD:START-END... Example: 20260410:0930-1600 means on April 10, 2026, the market is open from 9:30 AM to 4:00 PM in the exchange's local timezone. 
    Closed: If a day is a holiday or weekend, it will say 20260411:CLOSED.


How often is historicalDataUpdate() callback called?
When keepUpToDate is active, Interactive Brokers sends updates for the current, unfinished bar approximately every 5 seconds.

Even if you have requested 1-hour bars or 1-day bars, the API will not wait for the hour or day to finish before talking to you. Instead, it sends the "in-progress" version of that bar every 5 seconds.

SPX > SMA 5
Intraday Move Up >=0.3%



- Resolve underlying SPX
- Subscribe to SPX market data
- Unsubscribe from SPX market data
- Resolve option chain for SPX
- Select strikes
- Subscribe to option market data
- Unsubscribe from option market data
- Place entry order
- Verify entry order