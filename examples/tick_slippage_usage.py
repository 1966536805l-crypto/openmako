"""
Tick Slippage Calculator - Usage Examples

This module calculates real slippage by comparing theoretical signal prices
against actual executable prices from tick-level data.
"""

from pathlib import Path
from quantagent.tick_slippage_calculator import (
    calculate_slippage,
    print_slippage_summary,
    save_slippage_report,
)


# Example 1: Basic usage with default parameters
def example_basic():
    """Calculate slippage with default parameters."""
    report = calculate_slippage(
        trades_csv="path/to/realistic_t1_trades.csv",
        tick_dir="path/to/tick_data_directory",
        assumed_slippage_bps=20.0  # Compare against 0.2% assumption
    )

    print_slippage_summary(report)
    save_slippage_report(report, "slippage_report.json")


# Example 2: Custom column names
def example_custom_columns():
    """Calculate slippage with custom CSV column names."""
    report = calculate_slippage(
        trades_csv="path/to/trades.csv",
        tick_dir="path/to/tick_data",
        signal_col="t1_auction_return",  # Signal return column
        date_col="entry_date",           # Date column
        code_col="stock_code",           # Stock code column
        direction_col="side",            # Direction: 1=buy, -1=sell
        volume_col="shares",             # Volume column
        price_col="signal_price",        # Theoretical price column
        assumed_slippage_bps=20.0
    )

    return report


# Example 3: Analyze slippage distribution
def example_analyze_distribution():
    """Analyze slippage distribution and identify worst cases."""
    report = calculate_slippage(
        trades_csv="path/to/trades.csv",
        tick_dir="path/to/tick_data",
        assumed_slippage_bps=20.0
    )

    # Check if slippage assumption is reasonable
    if report.slippage_underestimated:
        print(f"⚠️  WARNING: Real slippage ({report.average_slippage_bps:.2f} bps) "
              f"exceeds assumption ({report.assumed_slippage_bps:.2f} bps)")
        print("Strategy performance may be overstated!")

    # Analyze distribution
    dist = report.distribution
    total = report.total_trades
    print(f"\nSlippage Distribution:")
    print(f"  Low slippage (0-10 bps):     {dist.range_0_10bps/total*100:.1f}%")
    print(f"  Medium slippage (10-20 bps): {dist.range_10_20bps/total*100:.1f}%")
    print(f"  High slippage (20-50 bps):   {dist.range_20_50bps/total*100:.1f}%")
    print(f"  Very high (50-100 bps):      {dist.range_50_100bps/total*100:.1f}%")
    print(f"  Extreme (>100 bps):          {dist.range_over_100bps/total*100:.1f}%")

    # Examine worst cases
    print(f"\nWorst 5 Slippage Cases:")
    for i, case in enumerate(report.worst_cases[:5], 1):
        print(f"  {i}. {case.code} on {case.signal_time}")
        print(f"     Signal: {case.signal_price:.2f}, Exec: {case.executable_price:.2f}")
        print(f"     Slippage: {case.slippage_bps:.2f} bps ({case.slippage_pct*100:.3f}%)")
        print(f"     Direction: {case.direction}, Volume: {case.volume:.0f}")

    return report


# Example 4: Compare multiple strategies
def example_compare_strategies():
    """Compare slippage across multiple strategies."""
    strategies = [
        ("Strategy A", "path/to/strategy_a_trades.csv", 20.0),
        ("Strategy B", "path/to/strategy_b_trades.csv", 15.0),
        ("Strategy C", "path/to/strategy_c_trades.csv", 25.0),
    ]

    results = []
    for name, trades_csv, assumed_bps in strategies:
        report = calculate_slippage(
            trades_csv=trades_csv,
            tick_dir="path/to/tick_data",
            assumed_slippage_bps=assumed_bps
        )
        results.append((name, report))

    # Print comparison
    print(f"\n{'Strategy':<15} {'Avg Slippage':<15} {'Assumed':<10} {'Status':<20}")
    print("-" * 60)
    for name, report in results:
        status = "⚠️ UNDERESTIMATED" if report.slippage_underestimated else "✓ OK"
        print(f"{name:<15} {report.average_slippage_bps:>6.2f} bps     "
              f"{report.assumed_slippage_bps:>6.2f} bps  {status}")

    return results


# Example 5: Integration with quant_full_audit
def example_integration_with_audit():
    """
    Integrate slippage calculation with quant_full_audit workflow.

    This shows how to use tick_slippage_calculator as part of the
    evidence-gated audit process.
    """
    from quantagent.quant_full_audit import QuantFullAuditSpec, run_quant_full_audit

    # Step 1: Run full audit to get tick data samples
    audit_spec = QuantFullAuditSpec(
        scenario="A",
        input_path="path/to/trades.csv",
        name="strategy_name",
        return_col="net_return",
        threshold_col="t1_auction_return",
        auto_evidence=True,  # This generates tick samples
    )

    audit_result = run_quant_full_audit(audit_spec)

    # Step 2: Use the tick samples for slippage calculation
    if audit_result.ok and audit_result.auto_evidence_result:
        tick_dir = Path(audit_result.auto_evidence_result.get('output_dir', '')) / 'data_samples'

        report = calculate_slippage(
            trades_csv=audit_spec.input_path,
            tick_dir=tick_dir,
            assumed_slippage_bps=20.0
        )

        print_slippage_summary(report)

        # Step 3: Update audit with slippage findings
        if report.slippage_underestimated:
            print("⚠️  AUDIT FINDING: Slippage assumption is too optimistic")
            print("    Strategy performance may be overstated")
            print("    Recommend increasing slippage assumption or improving execution")

    return audit_result, report


# Example 6: Tick data format requirements
def example_tick_data_format():
    """
    Document the expected tick data format.

    Tick CSV files should be named: tick_trade_{code}_{YYYYMMDD}.csv

    Required columns:
    - Time: Timestamp in format 'YYYY-MM-DD HH:MM:SS'
    - Price: Execution price (float)
    - Volume: Trade volume (int)
    - Type: 'B' for buyer-initiated, 'S' for seller-initiated

    Example:
        Time,Price,Volume,Type
        2018-03-15 09:25:00,59.05,200,B
        2018-03-15 09:25:01,59.06,100,S
        2018-03-15 09:25:02,59.05,150,B

    The calculator will:
    - For buy orders: find the first 'S' (sell) tick after signal time
    - For sell orders: find the first 'B' (buy) tick after signal time
    - Calculate slippage as (actual - theoretical) / theoretical
    """
    pass


if __name__ == "__main__":
    # Run examples (with placeholder paths)
    print("Tick Slippage Calculator - Usage Examples")
    print("=" * 60)
    print("\nSee function docstrings for detailed usage patterns.")
    print("\nKey functions:")
    print("  - calculate_slippage(): Main calculation function")
    print("  - find_executable_price(): Find actual execution price from ticks")
    print("  - print_slippage_summary(): Display human-readable summary")
    print("  - save_slippage_report(): Save JSON report")
