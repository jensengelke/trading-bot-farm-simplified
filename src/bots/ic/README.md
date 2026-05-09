# IC Bot - Iron Condor Trading Bot

## Overview

The IC (Iron Condor) bot creates iron condor spreads on SPX index options. An iron condor consists of:
- A bull put spread (sell put + buy lower put)
- A bear call spread (sell call + buy higher call)

This strategy profits from low volatility when the underlying stays within a range.

## Strategy

### Entry Conditions
- Scheduled execution at 9:45 AM US/Eastern on trading days
- Finds options with 14 DTE (Days To Expiration)

### Position Structure

**Put Spread (Bull Put Spread):**
- Short Put: Closest to delta -0.25 (configurable)
- Long Put: 10 points below short put (configurable offset)

**Call Spread (Bear Call Spread):**
- Short Call: Closest to delta 0.65 (configurable)
- Long Call: 5 points above short call (configurable offset)

### Example
If SPX is at 6000:
- Sell 5990 Put (delta ~-0.25)
- Buy 5980 Put (10 points lower)
- Sell 6010 Call (delta ~0.65)
- Buy 6015 Call (5 points higher)

## Configuration

### Required Fields
- `bot_name`: Unique identifier for the bot instance
- `bot_type`: Must be "ic"
- `log_level`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

### Custom Fields
- `timezone`: Timezone for scheduling (default: "America/New_York")
- `entry_time`: Time to check for entry (default: "09:45:00")
- `dte`: Days to expiration for options (default: 14)
- `put_short_delta`: Target delta for short put (default: -0.25)
- `put_width`: Points offset for long put (default: 10)
- `call_short_delta`: Target delta for short call (default: 0.65)
- `call_width`: Points offset for long call (default: 5)
- `test_mode`: Enable test mode for immediate execution (default: false)

## Configuration Example

```yaml
bot_name: "ic-1"
bot_type: "ic"
log_level: "INFO"

timezone: "America/New_York"
entry_time: "09:45:00"

dte: 14

put_short_delta: -0.25
put_width: 10

call_short_delta: 0.65
call_width: 5

test_mode: false
```

## Usage

1. Create a configuration file in `config/default/` or `config/demo/`
2. Run the bot:
   ```bash
   python main.py --config-dir config/default
   ```

## Test Mode

Enable `test_mode: true` to:
- Trigger entry check 3 seconds after bot starts
- Skip weekend date adjustments in testing

## Risk Management

The iron condor has defined risk:
- Maximum loss on put side: (put_width - premium received) × 100
- Maximum loss on call side: (call_width - premium received) × 100
- Maximum profit: Total premium received × 100

## Notes

- Uses SPX index options (SPXW trading class)
- Orders are placed as BAG contracts with all four legs
- Uses SMART routing with NonGuaranteed flag for better fills
- Limit orders are placed at mid-price adjusted to minTick