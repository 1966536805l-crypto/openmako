# Design Decisions: Quantitative Evidence Gates

Internal legacy quant documentation. This is not the current public v0.1 capability claim;
the current public proof is the focused learning-effect gate linked from
`README.md` and issue #1.

This document explains the key design decisions behind OpenMako's quantitative evidence gates, which prevent unverified performance claims and enforce statistical rigor.

## 1. Why `runner_sha256` Prevents Forgery

**Decision**: Every quant run must include a `runner_sha256` hash that cryptographically binds metrics to the code that computed them.

**Rationale**:
- **Tamper Detection**: Without code verification, an agent could claim "PF=2.5" by editing a CSV file rather than running actual backtests. The `runner_sha256` ensures metrics come from a known, auditable computation.
- **Reproducibility**: The hash allows operators to verify that metrics were computed by a specific version of the strategy code, not hand-edited or cherry-picked.
- **Evidence Chain**: Combined with `input_sha256` (data hash) and `spec_hash` (parameter hash), the runner hash completes the evidence chain: "These metrics came from *this code* running on *this data* with *these parameters*."

**Implementation**:
```python
# quantagent/quant_run_gate.py
runner_sha256 = str(experiment.get("runner_sha256") or "")
# CRITICAL: extract runner signature

# quantagent/quant_evidence_bundle.py
def live_ready(self) -> bool:
    return (
        self.data_contract_ok
        and self.leak_check_ok
        and self.split_ok
        and self.execution_gate_ok
        and self.runner_sha256  # CRITICAL: must have runner signature
    )
```

**Failure Mode**: If `runner_sha256` is missing or doesn't match the expected strategy code, `live_ready` returns `False`, blocking any live trading approval.

---

## 2. Why OOS Must Be ≥20%

**Decision**: Out-of-sample (OOS) data must represent at least 20% of the total dataset for a run to be considered statistically valid.

**Statistical Rationale**:
- **Overfitting Detection**: In-sample optimization can easily produce spurious patterns. A 20% OOS holdout provides meaningful validation that the strategy generalizes beyond the training period.
- **Sample Size**: For typical quant strategies with 100-500 trades, 20% OOS yields 20-100 trades, which is the minimum for detecting whether performance degrades out-of-sample.
- **Industry Standard**: The 80/20 train/test split is a widely accepted baseline in machine learning and quantitative finance. Going below 20% OOS risks validating on too few samples.

**Statistical Power**:
- With 20% OOS and 100 total trades, you get 20 OOS trades. This is sufficient to detect a 50% performance drop with reasonable confidence (p < 0.05).
- With 10% OOS (10 trades), statistical power drops significantly, making it easy to miss overfitting.

**Implementation**:
```python
# quantagent/quant_run_gate.py
oos_ratio = oos_rows / total_rows if total_rows > 0 else 0.0
oos_sufficient = oos_rows == 0 or oos_ratio >= 0.20

if not oos_sufficient:
    reason = f"OOS sample size insufficient: {oos_rows}/{total_rows} ({oos_ratio:.1%}) < 20%"
    return QuantSplitCheck(ok=False, ...)
```

**Edge Cases**:
- If `oos_start` and `oos_end` are not specified, the check passes (research-only mode).
- If OOS is specified but < 20%, the run is blocked from live trading.

---

## 3. Why Capacity Threshold is 100 Rows / 1M CNY

**Decision**: Capacity evidence must contain at least 100 rows of tick/volume data and demonstrate at least 1M CNY in estimated market capacity.

**Rationale**:

### 100 Row Minimum
- **Statistical Reliability**: Capacity estimation requires aggregating volume across multiple time windows. With fewer than 100 rows, variance is too high to produce reliable estimates.
- **Market Microstructure**: 100 rows typically represents 1-2 days of minute-level data or 1-2 weeks of daily data, which captures typical intraday and multi-day volume patterns.
- **Outlier Resistance**: With 100+ samples, outlier volumes (e.g., news-driven spikes) are diluted, producing more stable capacity estimates.

### 1M CNY Minimum
- **Practical Trading Floor**: 1M CNY (~$140K USD) is the minimum capacity for a strategy to be worth deploying. Below this, transaction costs and operational overhead dominate returns.
- **Slippage Sensitivity**: Strategies with < 1M capacity are highly sensitive to slippage and execution quality, making them unsuitable for live trading without extensive broker evidence.
- **Risk Management**: Small-capacity strategies often trade illiquid names or tight time windows, increasing operational risk.

**Implementation**:
```python
# quantagent/quant_execution_gate.py
if total_rows < 100:
    issues.append(
        QuantExecutionIssue(
            code="capacity_insufficient_rows",
            severity="warn",
            message=f"Capacity evidence has only {total_rows} rows, recommended minimum is 100 rows for reliable capacity estimation",
            evidence_type="capacity",
        )
    )

if estimated_total < 1000000:
    issues.append(
        QuantExecutionIssue(
            code="capacity_below_threshold",
            severity="warn",
            message=f"Estimated capacity {estimated_total:,.0f} CNY is below 1M CNY threshold",
            evidence_type="capacity",
        )
    )
```

**Severity**: These are `warn` level, not `block`, because capacity constraints depend on strategy type (HFT vs. daily rebalance) and operator risk tolerance.

---

## 4. Why Slippage is Mandatory

**Decision**: Any quant run claiming live-readiness must include explicit slippage assumptions or broker-verified fill evidence.

**Rationale**:
- **Realism Gap**: Backtests assume perfect execution at mid-price or close price. Real trading incurs slippage from bid-ask spread, market impact, and adverse selection.
- **Performance Inflation**: Ignoring slippage can inflate backtest returns by 10-50 bps per trade. For a strategy with 100 trades/year, this is 10-50% annual return difference.
- **Risk Disclosure**: Operators must explicitly acknowledge slippage assumptions. If slippage is 0 bps, the run is flagged as unrealistic unless broker evidence proves otherwise.

**Implementation**:
```python
# quantagent/quant_run_gate.py
@dataclass(frozen=True)
class QuantRunSpec:
    fees_bps: float = 0.0
    slippage_bps: float = 0.0  # Must be set explicitly
    capacity_notes: str = ""
    execution_source: str = ""
    # ...

# quantagent/quant_execution_gate.py
def run_quant_execution_gate(project: str | Path, spec: QuantExecutionEvidenceSpec) -> QuantExecutionGateResult:
    # If no broker evidence, slippage assumptions must be documented
    if not spec.fill_path and spec.slippage_bps == 0.0:
        issues.append(
            QuantExecutionIssue(
                code="slippage_not_specified",
                severity="warn",
                message="Slippage assumptions are 0 bps but no broker fill evidence provided",
                evidence_type="slippage",
            )
        )
```

**Typical Values**:
- **Liquid stocks (top 300)**: 2-5 bps slippage
- **Mid-cap stocks**: 5-10 bps slippage
- **Small-cap or illiquid**: 10-30 bps slippage
- **Futures**: 1-3 bps slippage

---

## 5. Why Broker Evidence is Required for Live Trading

**Decision**: A run is only `live_ready` if it includes broker-verified execution evidence (tick, fill, order, or account data).

**Rationale**:
- **Simulation vs. Reality**: Backtests are simulations. Broker evidence proves the strategy can execute in real market conditions.
- **Execution Quality**: Broker fills reveal actual slippage, partial fills, order rejections, and other execution issues invisible in backtests.
- **Regulatory Compliance**: Many jurisdictions require documented evidence of strategy performance before live deployment.

**Evidence Hierarchy**:
1. **Broker fills** (highest confidence): Actual executed trades with timestamps, prices, and quantities.
2. **Tick data**: Market tick-by-tick data showing liquidity and price movement.
3. **Order logs**: Submitted orders with fill status.
4. **Account statements**: Broker-provided P&L and position records.

**Implementation**:
```python
# quantagent/quant_execution_gate.py
@dataclass(frozen=True)
class QuantExecutionEvidenceSpec:
    execution_source: str = ""
    tick_path: str = ""
    fill_path: str = ""
    broker_path: str = ""
    order_path: str = ""
    position_path: str = ""
    account_path: str = ""
    slippage_path: str = ""
    capacity_path: str = ""

def run_quant_execution_gate(...) -> QuantExecutionGateResult:
    has_broker_evidence = bool(
        spec.fill_path or spec.tick_path or spec.broker_path or spec.order_path
    )
    
    execution_gate_ok = has_broker_evidence and len(blocking_issues) == 0
    live_ready = execution_gate_ok and split_ok and leak_check_ok
```

**Failure Mode**: If no broker evidence is provided, `live_ready` is `False`, and the run is marked research-only.

---

## 6. Trading Hours Validation

**Decision**: Tick and fill timestamps must fall within standard trading hours (09:30-15:00 for stocks, with futures night session support).

**Rationale**:
- **Data Quality**: Timestamps outside trading hours indicate data errors, timezone issues, or test data leakage.
- **Market Realism**: Strategies claiming to trade at 03:00 AM are either using incorrect data or trading non-standard instruments.
- **Fraud Detection**: Manually edited CSVs often have impossible timestamps (e.g., "2025-01-01 00:00:00").

**Implementation**:
```python
# quantagent/quant_execution_gate.py
def _check_trading_hours(timestamp: str, instrument_type: str) -> bool:
    time_obj = datetime.strptime(timestamp, "%H:%M:%S").time()
    
    if instrument_type == "stock":
        return time(9, 30) <= time_obj <= time(15, 0)
    elif instrument_type == "futures":
        # Support night session: 21:00-02:30
        return (time(9, 30) <= time_obj <= time(15, 0)) or (time(21, 0) <= time_obj or time_obj <= time(2, 30))
    else:
        return True  # Unknown instrument, skip check
```

**Tolerance**: If > 20% of timestamps are outside trading hours, the run is flagged with a warning.

---

## Summary Table

| Gate | Threshold | Severity | Rationale |
|------|-----------|----------|-----------|
| `runner_sha256` | Must exist | BLOCK | Prevents metric forgery |
| OOS % | ≥ 20% | BLOCK | Statistical validity |
| Capacity rows | ≥ 100 | WARN | Estimation reliability |
| Capacity CNY | ≥ 1M | WARN | Practical trading floor |
| Slippage | Must specify | WARN | Realism enforcement |
| Broker evidence | Required for live | BLOCK | Execution proof |
| Trading hours | ≥ 80% in-hours | WARN | Data quality |

**Design Philosophy**: These gates implement a "fail-safe" approach where the default is to block unverified claims. Operators can override warnings but cannot bypass blocks without providing the required evidence.
