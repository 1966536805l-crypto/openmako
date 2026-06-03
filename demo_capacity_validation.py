#!/usr/bin/env python3
"""
Demo script for tick capacity validation.

This demonstrates validating strategy trades against real market tick data
to ensure the strategy doesn't exceed realistic market capacity.
"""

import csv
import json
from pathlib import Path

from quantagent.tick_capacity_validator import validate_capacity


def create_demo_trades():
    """Create realistic demo trades based on actual tick data."""
    trades_file = Path("realistic_t1_trades.csv")

    # These trades are timed to match the available tick data
    trades = [
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 09:30:00",
            "volume": "500",
            "price": "59.05",
            "amount": "29525.00"
        },
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 10:00:00",
            "volume": "800",
            "price": "59.20",
            "amount": "47360.00"
        },
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 11:00:00",
            "volume": "300",
            "price": "59.10",
            "amount": "17730.00"
        },
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 13:30:00",
            "volume": "1200",
            "price": "58.95",
            "amount": "70740.00"
        },
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 14:00:00",
            "volume": "600",
            "price": "59.00",
            "amount": "35400.00"
        },
    ]

    with open(trades_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "date", "time", "volume", "price", "amount"])
        writer.writeheader()
        writer.writerows(trades)

    return trades_file


def main():
    print("=" * 70)
    print("Tick Capacity Validation Demo")
    print("=" * 70)
    print()

    # Create demo trades
    trades_file = create_demo_trades()
    print(f"Created demo trades: {trades_file}")

    # Path to tick data
    tick_dir = Path("AI_协作交接/quant_auto_evidence/qauto-1779695281986/data_samples")

    if not tick_dir.exists():
        print(f"ERROR: Tick data directory not found: {tick_dir}")
        return

    print(f"Using tick data from: {tick_dir}")
    print()

    # Run validation
    print("Running capacity validation...")
    report = validate_capacity(trades_file, tick_dir, threshold=0.1, time_window_minutes=5)

    # Display results
    print()
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"Total trades analyzed: {report.total_trades}")
    print(f"Conservative threshold (10%): {report.capacity_ok_conservative} trades OK")
    print(f"Aggressive threshold (20%): {report.capacity_ok_aggressive} trades OK")
    print()

    if report.insufficient_capacity_conservative:
        print(f"Conservative violations: {len(report.insufficient_capacity_conservative)}")
        print("-" * 70)
        for issue in report.insufficient_capacity_conservative:
            print(f"  Code: {issue.code}")
            print(f"  Date: {issue.date} {issue.time}")
            print(f"  Strategy volume: {issue.strategy_volume:,.0f} shares")
            print(f"  Market volume (5-min window): {issue.market_volume:,.0f} shares")
            print(f"  Ratio: {issue.ratio:.2%} (threshold: {issue.threshold:.0%})")
            print(f"  Status: EXCEEDS conservative capacity")
            print()

    if report.insufficient_capacity_aggressive:
        print(f"Aggressive violations: {len(report.insufficient_capacity_aggressive)}")
        print("-" * 70)
        for issue in report.insufficient_capacity_aggressive:
            print(f"  Code: {issue.code}")
            print(f"  Date: {issue.date} {issue.time}")
            print(f"  Strategy volume: {issue.strategy_volume:,.0f} shares")
            print(f"  Market volume (5-min window): {issue.market_volume:,.0f} shares")
            print(f"  Ratio: {issue.ratio:.2%} (threshold: {issue.threshold:.0%})")
            print(f"  Status: EXCEEDS aggressive capacity")
            print()

    # Save report as JSON
    report_file = Path("capacity_validation_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"Full report saved to: {report_file}")
    print()

    # Summary
    if report.capacity_ok_conservative == report.total_trades:
        print("✓ All trades pass conservative capacity check (10%)")
    elif report.capacity_ok_aggressive == report.total_trades:
        print("⚠ All trades pass aggressive capacity check (20%) but not conservative")
    else:
        print("✗ Some trades exceed market capacity limits")


if __name__ == "__main__":
    main()
