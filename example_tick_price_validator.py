#!/usr/bin/env python3
"""
Example usage of tick_price_validator module.

This script demonstrates how to validate strategy trade prices against
actual tick data to ensure price authenticity.
"""

from pathlib import Path
from quantagent.tick_price_validator import (
    validate_trade_prices,
    generate_validation_report,
    save_validation_json,
)


def example_basic_validation():
    """Basic validation example."""
    print("=" * 70)
    print("EXAMPLE 1: Basic Price Validation")
    print("=" * 70)

    # Validate trade prices against tick data
    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
        entry_date_col="entry_date",
        exit_date_col="exit_date",
        code_col="code",
        entry_price_col="entry_price",
        exit_price_col="exit_price",
    )

    print(f"Total trades: {result.total_trades}")
    print(f"Valid entry prices: {result.valid_entry_prices}")
    print(f"Valid exit prices: {result.valid_exit_prices}")
    print(f"Validation rate: {result.validation_rate:.2f}%")
    print()


def example_custom_time_window():
    """Validation with custom entry time window."""
    print("=" * 70)
    print("EXAMPLE 2: Custom Entry Time Window")
    print("=" * 70)

    from datetime import time

    # Validate with custom time window (09:30-09:40 instead of default 09:25-09:35)
    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
        entry_time_window=(time(9, 30), time(9, 40)),
    )

    print(f"Entry time window: 09:30-09:40")
    print(f"Valid entry prices: {result.valid_entry_prices}")
    print()


def example_limited_validation():
    """Validate only first N trades."""
    print("=" * 70)
    print("EXAMPLE 3: Validate First 100 Trades")
    print("=" * 70)

    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
        max_trades=100,
    )

    print(f"Trades validated: {result.total_trades}")
    print(f"Invalid entries: {len(result.invalid_entries)}")
    print(f"Invalid exits: {len(result.invalid_exits)}")
    print()


def example_report_generation():
    """Generate validation reports."""
    print("=" * 70)
    print("EXAMPLE 4: Generate Reports")
    print("=" * 70)

    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
    )

    # Save JSON report
    save_validation_json(result, "validation_report.json")
    print("JSON report saved to: validation_report.json")

    # Generate markdown report
    generate_validation_report(result, "validation_report.md")
    print("Markdown report saved to: validation_report.md")
    print()


def example_inspect_invalid_prices():
    """Inspect invalid price details."""
    print("=" * 70)
    print("EXAMPLE 5: Inspect Invalid Prices")
    print("=" * 70)

    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
    )

    if result.invalid_entries:
        print(f"Found {len(result.invalid_entries)} invalid entry prices:")
        for inv in result.invalid_entries[:5]:  # Show first 5
            print(f"  Code: {inv.code}, Date: {inv.date}")
            print(f"  Strategy Price: {inv.strategy_price:.2f}")
            print(f"  Tick Range: [{inv.tick_min:.2f}, {inv.tick_max:.2f}]")
            print(f"  Deviation: {inv.deviation_pct:.2f}%")
            print()
    else:
        print("All entry prices are valid!")
    print()


def example_check_missing_data():
    """Check for missing tick data."""
    print("=" * 70)
    print("EXAMPLE 6: Check Missing Tick Data")
    print("=" * 70)

    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
    )

    if result.missing_tick_data:
        print(f"Missing tick data for {len(result.missing_tick_data)} code-date pairs:")
        for missing in result.missing_tick_data[:10]:  # Show first 10
            print(f"  - {missing}")
    else:
        print("All tick data is available!")
    print()


def example_validation_workflow():
    """Complete validation workflow."""
    print("=" * 70)
    print("EXAMPLE 7: Complete Validation Workflow")
    print("=" * 70)

    # Step 1: Validate prices
    print("Step 1: Validating trade prices...")
    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/",
    )

    # Step 2: Check validation rate
    print(f"Step 2: Validation rate = {result.validation_rate:.2f}%")
    if result.validation_rate < 95.0:
        print("  WARNING: Validation rate below 95%!")

    # Step 3: Identify problematic trades
    print(f"Step 3: Found {len(result.invalid_entries)} invalid entry prices")
    print(f"        Found {len(result.invalid_exits)} invalid exit prices")

    # Step 4: Generate reports
    print("Step 4: Generating reports...")
    save_validation_json(result, "validation_report.json")
    generate_validation_report(result, "validation_report.md")

    # Step 5: Summary
    print("\nValidation Summary:")
    print(f"  Total trades: {result.total_trades}")
    print(f"  Valid entries: {result.valid_entry_prices}")
    print(f"  Valid exits: {result.valid_exit_prices}")
    print(f"  Missing data: {len(result.missing_tick_data)}")
    print()


def main():
    """Run all examples."""
    print("\n")
    print("*" * 70)
    print("TICK PRICE VALIDATOR - USAGE EXAMPLES")
    print("*" * 70)
    print("\n")

    # Note: These examples assume you have:
    # - realistic_t1_trades.csv with columns: code, entry_date, exit_date, entry_price, exit_price
    # - tick_data/ directory with tick CSV files

    print("NOTE: These are example code snippets.")
    print("To run them, ensure you have the required data files.\n")

    # Uncomment to run examples:
    # example_basic_validation()
    # example_custom_time_window()
    # example_limited_validation()
    # example_report_generation()
    # example_inspect_invalid_prices()
    # example_check_missing_data()
    # example_validation_workflow()


if __name__ == "__main__":
    main()
