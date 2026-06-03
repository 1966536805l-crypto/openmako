#!/usr/bin/env python3
"""
Comprehensive demo for tick capacity validation.

This creates synthetic but realistic tick data and demonstrates
capacity validation with various scenarios.
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from quantagent.tick_capacity_validator import validate_capacity


def create_synthetic_tick_data(output_dir: Path):
    """Create synthetic tick data for demonstration."""
    output_dir.mkdir(parents=True, exist_ok=True)

    tick_file = output_dir / "tick_trade_300678_20180315.csv"

    # Generate realistic tick data throughout the trading day
    ticks = []
    base_price = 59.0

    # Morning session: 09:30 - 11:30
    current_time = datetime(2018, 3, 15, 9, 30, 0)
    end_morning = datetime(2018, 3, 15, 11, 30, 0)

    while current_time < end_morning:
        # Simulate varying volumes and prices
        volume = 100 + (hash(str(current_time)) % 200)
        price_offset = (hash(str(current_time)) % 100) / 100.0
        price = base_price + price_offset

        ticks.append({
            "Time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Volume": str(volume),
            "Price": f"{price:.2f}"
        })

        # Add tick every 30 seconds on average
        current_time += timedelta(seconds=30)

    # Afternoon session: 13:00 - 15:00
    current_time = datetime(2018, 3, 15, 13, 0, 0)
    end_afternoon = datetime(2018, 3, 15, 15, 0, 0)

    while current_time < end_afternoon:
        volume = 100 + (hash(str(current_time)) % 200)
        price_offset = (hash(str(current_time)) % 100) / 100.0
        price = base_price + price_offset

        ticks.append({
            "Time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Volume": str(volume),
            "Price": f"{price:.2f}"
        })

        current_time += timedelta(seconds=30)

    # Write tick data
    with open(tick_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Time", "Volume", "Price"])
        writer.writeheader()
        writer.writerows(ticks)

    print(f"Created {len(ticks)} synthetic ticks in {tick_file}")
    return tick_file


def create_test_scenarios(output_file: Path):
    """Create trades with different capacity scenarios."""
    trades = [
        # Scenario 1: Small trade, well within capacity (should pass both)
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 10:00:00",
            "volume": "500",
            "price": "59.05",
            "amount": "29525.00",
            "scenario": "small_safe"
        },
        # Scenario 2: Medium trade, within aggressive but not conservative
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 10:30:00",
            "volume": "3000",
            "price": "59.20",
            "amount": "177600.00",
            "scenario": "medium_aggressive_ok"
        },
        # Scenario 3: Large trade, exceeds both thresholds
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 11:00:00",
            "volume": "8000",
            "price": "59.10",
            "amount": "472800.00",
            "scenario": "large_exceeds"
        },
        # Scenario 4: Another small safe trade
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 13:30:00",
            "volume": "600",
            "price": "58.95",
            "amount": "35370.00",
            "scenario": "small_safe"
        },
        # Scenario 5: Medium trade in afternoon
        {
            "code": "300678",
            "date": "2018-03-15",
            "time": "2018-03-15 14:00:00",
            "volume": "2500",
            "price": "59.00",
            "amount": "147500.00",
            "scenario": "medium_aggressive_ok"
        },
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "date", "time", "volume", "price", "amount", "scenario"])
        writer.writeheader()
        writer.writerows(trades)

    print(f"Created {len(trades)} test trades in {output_file}")
    return output_file


def main():
    print("=" * 70)
    print("Tick Capacity Validation - Comprehensive Demo")
    print("=" * 70)
    print()

    # Setup
    demo_dir = Path("demo_data")
    tick_dir = demo_dir / "ticks"

    # Create synthetic data
    print("Step 1: Creating synthetic tick data...")
    create_synthetic_tick_data(tick_dir)
    print()

    print("Step 2: Creating test trade scenarios...")
    trades_file = demo_dir / "test_trades.csv"
    create_test_scenarios(trades_file)
    print()

    # Run validation
    print("Step 3: Running capacity validation...")
    print("-" * 70)
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

    # Conservative violations
    if report.insufficient_capacity_conservative:
        print(f"CONSERVATIVE VIOLATIONS ({len(report.insufficient_capacity_conservative)} trades):")
        print("-" * 70)
        for issue in report.insufficient_capacity_conservative:
            print(f"  Code: {issue.code}")
            print(f"  Time: {issue.date} {issue.time}")
            print(f"  Strategy volume: {issue.strategy_volume:,.0f} shares")
            print(f"  Market volume (5-min): {issue.market_volume:,.0f} shares")
            print(f"  Ratio: {issue.ratio:.2%} > {issue.threshold:.0%} threshold")
            print(f"  Impact: EXCEEDS conservative capacity")
            print()
    else:
        print("✓ No conservative violations")
        print()

    # Aggressive violations
    if report.insufficient_capacity_aggressive:
        print(f"AGGRESSIVE VIOLATIONS ({len(report.insufficient_capacity_aggressive)} trades):")
        print("-" * 70)
        for issue in report.insufficient_capacity_aggressive:
            print(f"  Code: {issue.code}")
            print(f"  Time: {issue.date} {issue.time}")
            print(f"  Strategy volume: {issue.strategy_volume:,.0f} shares")
            print(f"  Market volume (5-min): {issue.market_volume:,.0f} shares")
            print(f"  Ratio: {issue.ratio:.2%} > {issue.threshold:.0%} threshold")
            print(f"  Impact: EXCEEDS aggressive capacity")
            print()
    else:
        print("✓ No aggressive violations")
        print()

    # Save report
    report_file = demo_dir / "capacity_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"Full report saved to: {report_file}")
    print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if report.capacity_ok_conservative == report.total_trades:
        print("✓ All trades pass conservative capacity check (10%)")
        print("  Strategy is safe for live trading with conservative risk management")
    elif report.capacity_ok_aggressive == report.total_trades:
        print("⚠ All trades pass aggressive capacity check (20%)")
        print("  Strategy may work but requires careful position sizing")
    else:
        print("✗ Some trades exceed market capacity limits")
        print("  Strategy needs adjustment before live trading")
        print(f"  - {len(report.insufficient_capacity_aggressive)} trades exceed 20% of market volume")

    print()
    print("Demo complete. Check the demo_data/ directory for generated files.")


if __name__ == "__main__":
    main()
