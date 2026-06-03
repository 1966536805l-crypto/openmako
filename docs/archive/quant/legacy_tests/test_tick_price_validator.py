#!/usr/bin/env python3
"""
Test script for tick_price_validator.

Archived quant demo script. This is not part of the focused OpenMako v0.1
public evidence gate.

Usage:
    python3 test_tick_price_validator.py
"""

import csv
from pathlib import Path
from quantagent.tick_price_validator import (
    validate_trade_prices,
    generate_validation_report,
    save_validation_json,
)


def main():
    project_root = Path(__file__).parent

    # Sample tick directory
    tick_dir = project_root / "AI_协作交接/quant_auto_evidence/qauto-1779695281986/data_samples"

    # Create a sample trades CSV for testing
    trades_csv = project_root / "test_realistic_t1_trades.csv"

    # Create sample trades CSV if it doesn't exist
    if not trades_csv.exists():
        with open(trades_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'code', 'entry_date', 'exit_date', 'entry_price', 'exit_price',
                't1_auction_return', 'direction'
            ])

            # Valid entry price: 59.05 is within tick range (09:25:00 ticks show 59.05)
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.20', '0.02', '1'])

            # Invalid entry price: 60.00 is outside tick range
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '60.00', '59.15', '-0.01', '-1'])

            # Valid entry price: 59.05 again
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.10', '0.01', '1'])

            # Invalid entry price: 58.00 is below tick range
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '58.00', '59.00', '0.015', '1'])

            # Valid entry price
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.25', '0.03', '1'])

            # Add more test cases
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.30', '0.025', '1'])
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.18', '0.018', '1'])
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.22', '0.022', '1'])
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.12', '0.012', '1'])
            writer.writerow(['300678', '2018-03-15', '2018-03-16', '59.05', '59.28', '0.028', '1'])

        print(f"Created sample trades CSV: {trades_csv}")

    if not tick_dir.exists():
        print(f"ERROR: Tick directory not found: {tick_dir}")
        print("Please ensure the quant_auto_evidence data samples exist.")
        return

    print("Running tick price validation...")
    print(f"Trades CSV: {trades_csv}")
    print(f"Tick directory: {tick_dir}")
    print()

    try:
        # Validate first 10 trades
        result = validate_trade_prices(
            trades_csv=trades_csv,
            tick_dir=tick_dir,
            entry_date_col="entry_date",
            exit_date_col="exit_date",
            code_col="code",
            entry_price_col="entry_price",
            exit_price_col="exit_price",
            max_trades=10,
        )

        # Print summary
        print("=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        print(f"Total trades validated: {result.total_trades}")
        print(f"Valid entry prices: {result.valid_entry_prices}")
        print(f"Valid exit prices: {result.valid_exit_prices}")
        print(f"Invalid entry prices: {len(result.invalid_entries)}")
        print(f"Invalid exit prices: {len(result.invalid_exits)}")
        print(f"Missing tick data: {len(result.missing_tick_data)}")
        print(f"Validation rate: {result.validation_rate:.2f}%")
        print()

        if result.invalid_entries:
            print("INVALID ENTRY PRICES:")
            print("-" * 60)
            for inv in result.invalid_entries:
                print(f"  Code: {inv.code}, Date: {inv.date}")
                print(f"  Strategy Price: {inv.strategy_price:.2f}")
                print(f"  Tick Range: [{inv.tick_min:.2f}, {inv.tick_max:.2f}]")
                print(f"  Deviation: {inv.deviation_pct:.2f}%")
                print(f"  Time Window: {inv.time_window}")
                print()

        if result.invalid_exits:
            print("INVALID EXIT PRICES:")
            print("-" * 60)
            for inv in result.invalid_exits:
                print(f"  Code: {inv.code}, Date: {inv.date}")
                print(f"  Strategy Price: {inv.strategy_price:.2f}")
                print(f"  Tick Range: [{inv.tick_min:.2f}, {inv.tick_max:.2f}]")
                print(f"  Deviation: {inv.deviation_pct:.2f}%")
                print()

        if result.missing_tick_data:
            print("MISSING TICK DATA:")
            print("-" * 60)
            for missing in result.missing_tick_data:
                print(f"  {missing}")
            print()

        # Save reports
        json_output = project_root / "tick_price_validation.json"
        save_validation_json(result, json_output)
        print(f"JSON report saved to: {json_output}")

        md_output = project_root / "tick_price_validation.md"
        generate_validation_report(result, md_output)
        print(f"Markdown report saved to: {md_output}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
