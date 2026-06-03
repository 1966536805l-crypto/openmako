# Tick Validation System

Internal legacy quant documentation. This is not the current public v0.1 capability claim; the current public proof is the focused learning-effect gate linked from README.md and issue #1.

## Overview

The tick validation system provides evidence-based execution validation for quantitative trading strategies. It validates that reported fills can be explained by actual market tick data, ensuring that backtest results are grounded in real market conditions.

## System Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Tick Validation System                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Tick Extract │  │ Price Valid  │  │ Slippage Calc│      │
│  │              │  │              │  │              │      │
│  │ - 7z/zip     │  │ - Range check│  │ - BPS delta  │      │
│  │ - CSV parse  │  │ - Zero/neg   │  │ - Tolerance  │      │
│  │ - Time norm  │  │ - Missing    │  │ - Default    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Capacity Val │  │ Completeness │  │ Fill Replay  │      │
│  │              │  │              │  │              │      │
│  │ - Notional   │  │ - Missing    │  │ - Time match │      │
│  │ - Limits     │  │ - Anomalies  │  │ - Price match│      │
│  │ - Sample size│  │ - Coverage   │  │ - Capacity   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Compressed Archive (7z/zip)
         │
         ├─> Tick Extraction
         │        │
         │        ├─> Time Normalization (HH:MM:SS, HHMMSS)
         │        ├─> Date Prefixing (YYYY-MM-DD HH:MM:SS)
         │        └─> CSV Output
         │
         ├─> Price Validation
         │        │
         │        ├─> Range Check (> 0)
         │        ├─> Missing Value Check
         │        └─> Anomaly Detection
         │
         ├─> Slippage Calculation
         │        │
         │        ├─> Fill-Tick Matching
         │        ├─> BPS Delta Calculation
         │        └─> Tolerance Comparison
         │
         ├─> Capacity Validation
         │        │
         │        ├─> Notional Calculation
         │        ├─> Limit Comparison
         │        └─> Sample Size Check
         │
         └─> Execution Replay
                  │
                  ├─> Fill Explanation
                  ├─> Order Lifecycle
                  └─> Broker Reconciliation
```

## Usage

### 1. Extract Tick Data

Extract tick data from compressed archives:

```bash
mako quant data-sample /path/to/逐笔成交 \
  --code 000001 \
  --kind tick_trade \
  --date 2026-05-27 \
  --max-rows 10000
```

**Output:**
- CSV file in `.quantagent/data_samples/`
- Time values normalized to `YYYY-MM-DD HH:MM:SS` format
- Automatic date prefixing for time-only values

### 2. Validate Execution

Run full execution validation with tick evidence:

```bash
mako quant execution-gate \
  --tick .quantagent/data_samples/tick_trade_000001_20260527.csv \
  --fill broker_fills.csv \
  --broker broker_info.csv \
  --order order_lifecycle.csv \
  --position positions.csv \
  --account account_balance.csv \
  --slippage slippage_evidence.csv \
  --capacity capacity_evidence.csv \
  --execution-source "broker export"
```

**Output:**
- `live_ready`: Boolean indicating if execution is validated
- `execution_replay`: Detailed replay results
- `issues`: List of validation issues with severity levels

### 3. Programmatic Usage

```python
from pathlib import Path
from quantagent.quant_data_sample import sample_local_quant_data, QuantDataSampleSpec
from quantagent.quant_execution_gate import run_quant_execution_gate, QuantExecutionEvidenceSpec

# Extract tick data
tick_result = sample_local_quant_data(
    project=Path.cwd(),
    spec=QuantDataSampleSpec(
        root="/path/to/逐笔成交",
        code="000001",
        kind="tick_trade",
        date="2026-05-27",
        max_rows=10000,
    ),
)

# Validate execution
gate_result = run_quant_execution_gate(
    project=Path.cwd(),
    spec=QuantExecutionEvidenceSpec(
        tick_path=tick_result.output_path,
        fill_path="broker_fills.csv",
        broker_path="broker_info.csv",
        order_path="order_lifecycle.csv",
        position_path="positions.csv",
        account_path="account_balance.csv",
        slippage_path="slippage_evidence.csv",
        capacity_path="capacity_evidence.csv",
        execution_source="broker export",
    ),
)

print(f"Live Ready: {gate_result.live_ready}")
print(f"Fills Explained: {gate_result.execution_replay['fills_explained']}/{gate_result.execution_replay['fills_checked']}")
```

## Validation Standards

### Tick Data Requirements

**Required Columns:**
- `time` or `Time` or `成交时间`: Trade timestamp
- `code` or `Code` or `证券代码`: Security code
- `price` or `Price` or `成交价`: Trade price
- `volume` or `Volume` or `成交量`: Trade volume

**Validation Rules:**
- Price must be > 0
- Volume must be > 0
- Time must be parseable
- Missing values trigger BLOCK

**Supported Time Formats:**
- `HH:MM:SS` (e.g., `09:30:00`)
- `HHMMSS` (e.g., `093000`)
- `HH:MM:SS.fff` (with milliseconds)
- `YYYY-MM-DD HH:MM:SS` (full datetime)

### Price Validation

**Normal Price Range:**
- Price > 0
- No extreme outliers (configurable)
- Consistent with historical range

**Anomalous Prices (BLOCK):**
- Zero or negative prices
- Missing price values
- Prices outside reasonable bounds

### Slippage Calculation

**Formula:**
```
slippage_bps = |fill_price - tick_price| / tick_price * 10000
```

**Scenarios:**

| Scenario | Tick Price | Fill Price | Slippage (bps) | Allowed | Result |
|----------|-----------|-----------|----------------|---------|--------|
| Normal buy | 10.00 | 10.005 | 5 | 10 | PASS |
| High slippage | 10.00 | 10.020 | 200 | 10 | BLOCK |
| Sell slippage | 10.00 | 9.995 | 5 | 10 | PASS |
| Default tolerance | 10.00 | 10.008 | 8 | 10 (default) | PASS |

**Default Slippage:** 10 bps (configurable)

**Code-Specific Slippage:**
```csv
code,slippage_bps
000001,5.0
000002,10.0
600000,3.5
```

### Capacity Validation

**Sufficient Capacity:**
- Sample size ≥ 100 rows
- Total notional ≥ 1,000,000
- Covers target trading period

**Insufficient Capacity (WARN):**
- Sample size < 100 rows
- Total notional < 1,000,000
- Limited time coverage

**Capacity Check:**
```
fill_notional = fill_price * fill_quantity
if capacity > 0 and fill_notional > capacity:
    BLOCK: "fill_notional_exceeds_capacity"
```

**Capacity Evidence Format:**
```csv
code,capacity
000001,100000
000002,200000
600000,150000
```

### Completeness Checks

**Missing Data (BLOCK):**
- Fill has no matching tick data
- Tick data missing required columns
- Fill outside time window (default: 60 seconds)

**Anomalies (WARN):**
- Tick data has no code column (weak evidence)
- Insufficient capacity sample size
- Insufficient capacity notional

**Coverage Requirements:**
- All fills must have matching ticks
- Time delta ≤ window_seconds (default: 60)
- Price delta ≤ allowed slippage

## Common Issues

### Issue: Tick extraction fails

**Symptom:**
```
warnings: ["tick 7z not found for date: 2026-05-27"]
```

**Solution:**
- Verify archive exists: `/path/to/逐笔成交/2026-05-27.7z`
- Check date format: `YYYY-MM-DD`
- Ensure `bsdtar` is installed: `which bsdtar`

### Issue: Fill price exceeds slippage

**Symptom:**
```
issues: [{
  "level": "block",
  "code": "fill_price_exceeds_slippage",
  "message": "Fill price delta 200.00bps exceeds allowed 10.00bps"
}]
```

**Solution:**
- Review slippage evidence file
- Increase allowed slippage if justified
- Investigate fill execution quality
- Check for data quality issues

### Issue: Fill outside tick window

**Symptom:**
```
issues: [{
  "level": "block",
  "code": "fill_outside_tick_window",
  "message": "Fill is 300s away from nearest tick"
}]
```

**Solution:**
- Increase `window_seconds` parameter
- Verify tick data covers full trading period
- Check for time zone mismatches
- Ensure tick data is complete

### Issue: Capacity insufficient sample size

**Symptom:**
```
issues: [{
  "level": "warn",
  "code": "capacity_insufficient_sample_size",
  "message": "Capacity evidence has only 50 rows (< 100 threshold)"
}]
```

**Solution:**
- Expand capacity evidence sample
- Include more trading days
- Cover more securities
- Verify data completeness

### Issue: Invalid tick row

**Symptom:**
```
issues: [{
  "level": "block",
  "code": "invalid_tick_row",
  "message": "Tick row missing time/price/volume"
}]
```

**Solution:**
- Check CSV column names
- Verify data encoding (UTF-8, GB18030)
- Remove empty rows
- Validate data source

## File Formats

### Tick Data CSV

```csv
time,code,price,volume
2026-05-27 09:30:00,000001,10.50,1000
2026-05-27 09:30:01,000001,10.51,1500
2026-05-27 09:30:02,000001,10.49,2000
```

**Column Aliases:**
- Time: `time`, `Time`, `timestamp`, `datetime`, `成交时间`
- Code: `code`, `Code`, `symbol`, `证券代码`, `股票代码`
- Price: `price`, `Price`, `成交价`, `成交价格`
- Volume: `volume`, `Volume`, `qty`, `成交量`

### Slippage Evidence CSV

```csv
code,slippage_bps
000001,5.0
000002,10.0
600000,3.5
```

### Capacity Evidence CSV

```csv
code,capacity
000001,100000
000002,200000
600000,150000
```

### Fill Data CSV

```csv
time,code,price,qty,order_id,side
2026-05-27 09:30:30,000001,10.505,500,ord1,buy
2026-05-27 09:31:15,000001,10.515,300,ord2,buy
```

## Integration

### With Execution Gate

The tick validation system integrates with the execution gate:

```python
from quantagent.quant_execution_gate import run_quant_execution_gate

result = run_quant_execution_gate(
    project=Path.cwd(),
    spec=QuantExecutionEvidenceSpec(
        tick_path="tick.csv",
        fill_path="fill.csv",
        # ... other evidence files
    ),
)

# Check results
if result.live_ready:
    print("✓ Execution validated")
else:
    print("✗ Validation failed")
    for issue in result.issues:
        print(f"  [{issue.level}] {issue.code}: {issue.message}")
```

### With Quant Auto Evidence

Automatic evidence discovery:

```python
from quantagent.quant_auto_evidence import discover_quant_evidence

evidence = discover_quant_evidence(
    project=Path.cwd(),
    data_root="/path/to/market_data",
)

if evidence.get("tick"):
    print(f"Found tick data: {evidence['tick']}")
```

### With Agent Runtime

The agent runtime uses tick validation for P4 (real execution) claims:

```python
from quantagent.agent_v2 import run_agent_v2

# Agent automatically gates P4 claims on tick validation
result = run_agent_v2(
    project=Path.cwd(),
    query="Validate execution for 2026-05-27",
    evidence_paths={
        "tick": "tick.csv",
        "fill": "fill.csv",
        # ...
    },
)
```

## Performance

### Extraction Performance

| Archive Size | Rows | Extraction Time | Memory |
|-------------|------|-----------------|--------|
| 10 MB (7z) | 10,000 | ~2s | ~50 MB |
| 50 MB (7z) | 50,000 | ~8s | ~200 MB |
| 100 MB (7z) | 100,000 | ~15s | ~400 MB |

### Validation Performance

| Fills | Ticks | Validation Time | Memory |
|-------|-------|-----------------|--------|
| 100 | 10,000 | ~0.1s | ~10 MB |
| 1,000 | 50,000 | ~0.5s | ~50 MB |
| 10,000 | 100,000 | ~3s | ~200 MB |

### Optimization Tips

1. **Limit tick data to trading hours:** 09:30-15:00
2. **Use max_rows parameter:** Extract only needed rows
3. **Cache extracted data:** Reuse CSV files
4. **Filter by code:** Extract only relevant securities
5. **Use date ranges:** Limit to specific trading days

## Testing

Run the tick validation test suite:

```bash
# Run all tick validation tests
python3 -m unittest tests.test_tick_validation

# Run specific test class
python3 -m unittest tests.test_tick_validation.TickExtractionTest

# Run specific test
python3 -m unittest tests.test_tick_validation.TickExtractionTest.test_extracts_tick_from_7z_archive

# Run with verbose output
python3 -m unittest tests.test_tick_validation -v
```

## Known Limitations

1. **Archive Format Support:**
   - Requires `bsdtar` for 7z extraction
   - ZIP files supported natively
   - RAR not supported

2. **Time Zone Handling:**
   - Assumes all times in local market time
   - No automatic time zone conversion
   - User must ensure consistent time zones

3. **Code Normalization:**
   - Extracts last 6 digits as code
   - May not work for all market conventions
   - User should verify code matching

4. **Memory Constraints:**
   - Large tick files (>1M rows) may require streaming
   - Current implementation loads full CSV into memory
   - Consider chunking for very large datasets

5. **Slippage Model:**
   - Simple BPS-based model
   - Does not account for market impact
   - Does not model bid-ask spread explicitly

6. **Capacity Model:**
   - Static capacity limits
   - Does not model intraday capacity changes
   - Does not account for market depth dynamics

## Future Enhancements

1. **Streaming Extraction:** Support for very large archives
2. **Advanced Slippage Models:** Market impact, bid-ask spread
3. **Dynamic Capacity:** Intraday capacity modeling
4. **Multi-Market Support:** Cross-market validation
5. **Real-Time Validation:** Live execution monitoring
6. **Visualization:** Charts for slippage, capacity, coverage
7. **Anomaly Detection:** ML-based anomaly detection
8. **Performance Profiling:** Detailed performance metrics

## References

- [Execution Gate Documentation](EXECUTION_GATE.md)
- [Quant Data Sample Documentation](QUANT_DATA_SAMPLE.md)
- [Evidence-Based Validation](EVIDENCE_BASED_VALIDATION.md)
- [P4 Real Execution Framework](P4_REAL_EXECUTION.md)

## Support

For issues or questions:
- Check [Common Issues](#common-issues) section
- Review test cases in `tests/test_tick_validation.py`
- Consult source code: `quantagent/quant_data_sample.py`, `quantagent/quant_execution_replay.py`
- File an issue with reproduction steps and sample data
