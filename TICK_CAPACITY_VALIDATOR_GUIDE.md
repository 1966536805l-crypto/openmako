# Tick Capacity Validator - Usage Guide

## Overview

The `tick_capacity_validator` module validates that strategy trade volumes are within acceptable market capacity limits by comparing against actual tick-level market liquidity data.

## Key Features

- **Conservative threshold**: Strategy volume ≤ 10% of market volume
- **Aggressive threshold**: Strategy volume ≤ 20% of market volume
- **Time-window based**: Calculates market liquidity within a configurable time window (default 5 minutes)
- **Per-trade validation**: Validates each trade individually against market conditions at that time
- **Detailed reporting**: Provides comprehensive reports with violation details

## Installation

The module is located at:
```
quantagent/tick_capacity_validator.py
```

## Basic Usage

```python
from quantagent.tick_capacity_validator import validate_capacity

# Validate trades against tick data
report = validate_capacity(
    trades_csv="path/to/trades.csv",
    tick_dir="path/to/tick_data",
    threshold=0.1,  # 10% conservative
    time_window_minutes=5
)

# Check results
print(f"Total trades: {report.total_trades}")
print(f"Conservative OK: {report.capacity_ok_conservative}")
print(f"Aggressive OK: {report.capacity_ok_aggressive}")

# Review violations
for issue in report.insufficient_capacity_conservative:
    print(f"{issue.code} {issue.date} {issue.time}: "
          f"{issue.ratio:.2%} exceeds {issue.threshold:.0%}")
```

## Command Line Usage

```bash
# Run validation from command line
python3 -m quantagent.tick_capacity_validator trades.csv tick_data_dir/

# Run comprehensive demo
python3 demo_capacity_comprehensive.py
```

## Input Data Formats

### Trades CSV Format

Required fields:
- `code`: Stock code (e.g., "300678")
- `date` or `time`: Trade date/datetime
- `volume`: Trade volume in shares

Optional fields:
- `price`: Trade price
- `amount`: Trade amount

Example:
```csv
code,date,time,volume,price,amount
300678,2018-03-15,2018-03-15 09:30:00,500,59.05,29525.00
300678,2018-03-15,2018-03-15 10:00:00,800,59.20,47360.00
```

### Tick Data CSV Format

Required fields:
- `Time`: Timestamp (YYYY-MM-DD HH:MM:SS)
- `Volume`: Trade volume
- `Price`: Trade price

Example:
```csv
Time,Volume,Price
2018-03-15 09:25:00,200,59.05
2018-03-15 09:25:30,100,59.06
```

### Tick File Naming

The validator searches for tick files using these patterns:
- `tick_trade_{code}_{YYYYMMDD}.csv`
- `{code}_{YYYYMMDD}_tick.csv`
- `{code}_tick_{YYYYMMDD}.csv`
- Any file containing both code and date

## Output Report Structure

```python
@dataclass
class CapacityReport:
    total_trades: int
    capacity_ok_conservative: int  # Trades ≤ 10% of market
    capacity_ok_aggressive: int    # Trades ≤ 20% of market
    insufficient_capacity_conservative: tuple[CapacityIssue, ...]
    insufficient_capacity_aggressive: tuple[CapacityIssue, ...]
    conservative_threshold: float = 0.1
    aggressive_threshold: float = 0.2
```

Each `CapacityIssue` contains:
- `code`: Stock code
- `date`: Trade date
- `time`: Trade time
- `strategy_volume`: Strategy trade volume
- `market_volume`: Market volume in time window
- `ratio`: strategy_volume / market_volume
- `threshold`: The threshold that was exceeded

## Functions

### `validate_capacity(trades_csv, tick_dir, threshold=0.1, time_window_minutes=5)`

Main validation function.

**Parameters:**
- `trades_csv`: Path to strategy trades CSV
- `tick_dir`: Directory containing tick data files
- `threshold`: Primary threshold (default 0.1 for 10%)
- `time_window_minutes`: Time window for liquidity calculation (default 5)

**Returns:** `CapacityReport`

### `calculate_market_liquidity(tick_data, target_time, time_window_minutes=5)`

Calculate market liquidity within a time window.

**Parameters:**
- `tick_data`: List of tick records
- `target_time`: Target trade time
- `time_window_minutes`: Window size in minutes

**Returns:** `MarketLiquidity` with total_volume, total_amount, trade_count, avg_trade_volume

## Testing

Run the test suite:
```bash
python3 -m unittest tests.test_tick_capacity_validator -v
```

All 12 tests should pass:
- 4 tests for market liquidity calculation
- 3 tests for tick file finding
- 5 tests for capacity validation scenarios

## Demo Scripts

### `demo_capacity_comprehensive.py`

Creates synthetic tick data and demonstrates validation with various scenarios:
- Small trades within capacity
- Medium trades exceeding conservative but not aggressive
- Large trades exceeding both thresholds

Run with:
```bash
python3 demo_capacity_comprehensive.py
```

Output includes:
- Synthetic tick data in `demo_data/ticks/`
- Test trades in `demo_data/test_trades.csv`
- JSON report in `demo_data/capacity_report.json`

## Integration with Quant Workflow

The validator integrates with the existing quant evidence framework:

```python
from quantagent.tick_capacity_validator import validate_capacity
from quantagent.quant_execution_gate import QuantExecutionEvidenceSpec

# Include capacity validation in execution gate
spec = QuantExecutionEvidenceSpec(
    tick_path="path/to/ticks",
    capacity_path="path/to/capacity_report.json",
    # ... other evidence paths
)

# Run capacity validation
capacity_report = validate_capacity(
    trades_csv="strategy_trades.csv",
    tick_dir=spec.tick_path
)

# Save report for evidence
import json
with open(spec.capacity_path, 'w') as f:
    json.dump(capacity_report.to_dict(), f, indent=2)
```

## Interpretation Guidelines

### Conservative Threshold (10%)

- **Pass**: Strategy is safe for live trading with standard risk management
- **Fail**: Strategy may cause market impact; consider reducing position sizes

### Aggressive Threshold (20%)

- **Pass**: Strategy may work but requires careful monitoring
- **Fail**: Strategy will likely cause significant market impact; needs redesign

### Common Issues

1. **No tick data found**: Check file naming patterns and date formats
2. **Zero market volume**: Time window may not contain any trades; adjust window size
3. **All trades fail**: Strategy position sizes may be too large for the market

## Performance Considerations

- Tick data is loaded once per file
- Time window calculation is O(n) where n = number of ticks
- Typical validation of 100 trades with 10,000 ticks takes < 1 second

## Future Enhancements

Potential improvements:
- Amount-based validation (trade amount vs market turnover)
- Intraday liquidity patterns (higher liquidity at open/close)
- Multi-day aggregation for longer-term strategies
- Real-time capacity monitoring during live trading
