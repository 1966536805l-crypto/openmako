#!/usr/bin/env python3
"""
Test script for tick_slippage_calculator.

Usage:
    python3 test_slippage_calculator.py
"""

from pathlib import Path
from quantagent.tick_slippage_calculator import (
    calculate_slippage,
    print_slippage_summary,
    save_slippage_report,
)


def main():
    # Use the sample data from quant_auto_evidence
    project_root = Path(__file__).parent

    # Sample tick directory
    tick_dir = project_root / "AI_协作交接/quant_auto_evidence/qauto-1779695281986/data_samples"

    # For testing, we'll create a minimal trades CSV
    # In real usage, this would be realistic_t1_trades.csv or similar
    trades_csv = project_root / "test_trades_sample.csv"

    # Create a sample trades CSV if it doesn't exist
    if not trades_csv.exists():
        import csv
        with open(trades_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['code', 'entry_date', 'entry_price', 't1_auction_return', 'direction', 'volume'])
            # Sample trade: code 300678, date 2018-03-15, entry at 59.05
            writer.writerow(['300678', '2018-03-15', '59.05', '0.02', '1', '100'])
            writer.writerow(['300678', '2018-03-15', '59.10', '-0.01', '-1', '200'])
        print(f"Created sample trades CSV: {trades_csv}")

    if not tick_dir.exists():
        print(f"ERROR: Tick directory not found: {tick_dir}")
        print("Please ensure the quant_auto_evidence data samples exist.")
        return

    print("Running slippage calculation...")
    print(f"Trades CSV: {trades_csv}")
    print(f"Tick directory: {tick_dir}")

    try:
        report = calculate_slippage(
            trades_csv=trades_csv,
            tick_dir=tick_dir,
            signal_col="t1_auction_return",
            date_col="entry_date",
            code_col="code",
            direction_col="direction",
            volume_col="volume",
            price_col="entry_price",
            assumed_slippage_bps=20.0,  # 0.2% assumption
        )

        # Print summary
        print_slippage_summary(report)

        # Save report
        output_json = project_root / "slippage_report.json"
        save_slippage_report(report, output_json)
        print(f"Report saved to: {output_json}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
