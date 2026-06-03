"""
Tick Capacity Validator

Validates that strategy trade volumes are within acceptable market capacity limits
by comparing against actual tick-level market liquidity data.

Key validations:
- Conservative threshold: strategy volume <= 10% of market volume
- Aggressive threshold: strategy volume <= 20% of market volume
- Time-window based liquidity calculation
- Per-trade capacity verification

Usage:
    from quantagent.tick_capacity_validator import validate_capacity

    report = validate_capacity(
        trades_csv="path/to/trades.csv",
        tick_dir="path/to/tick_data",
        threshold=0.1  # 10% conservative
    )

    print(f"Total trades: {report.total_trades}")
    print(f"Capacity OK (conservative): {report.capacity_ok_conservative}")
    print(f"Capacity OK (aggressive): {report.capacity_ok_aggressive}")
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .exception_audit import audit_suppressed_exception


@dataclass(frozen=True)
class CapacityIssue:
    """Represents a single capacity violation."""
    code: str
    date: str
    time: str
    strategy_volume: float
    market_volume: float
    ratio: float
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketLiquidity:
    """Market liquidity statistics for a time window."""
    total_volume: float
    total_amount: float
    trade_count: int
    avg_trade_volume: float
    time_window_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapacityReport:
    """Complete capacity validation report."""
    total_trades: int
    capacity_ok_conservative: int
    capacity_ok_aggressive: int
    insufficient_capacity_conservative: tuple[CapacityIssue, ...] = ()
    insufficient_capacity_aggressive: tuple[CapacityIssue, ...] = ()
    conservative_threshold: float = 0.1
    aggressive_threshold: float = 0.2

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "capacity_ok_conservative": self.capacity_ok_conservative,
            "capacity_ok_aggressive": self.capacity_ok_aggressive,
            "insufficient_capacity_conservative": [
                issue.to_dict() for issue in self.insufficient_capacity_conservative
            ],
            "insufficient_capacity_aggressive": [
                issue.to_dict() for issue in self.insufficient_capacity_aggressive
            ],
            "conservative_threshold": self.conservative_threshold,
            "aggressive_threshold": self.aggressive_threshold,
        }


def calculate_market_liquidity(
    tick_data: list[dict[str, Any]],
    target_time: datetime,
    time_window_minutes: int = 5
) -> MarketLiquidity:
    """
    Calculate market liquidity within a time window around target time.

    Args:
        tick_data: List of tick records with Time, Volume, Price fields
        target_time: The target trade time
        time_window_minutes: Window size in minutes (default 5)

    Returns:
        MarketLiquidity object with aggregated statistics
    """
    window_start = target_time - timedelta(minutes=time_window_minutes // 2)
    window_end = target_time + timedelta(minutes=time_window_minutes // 2)

    total_volume = 0.0
    total_amount = 0.0
    trade_count = 0

    for tick in tick_data:
        try:
            tick_time = datetime.strptime(tick["Time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError):
            continue

        if window_start <= tick_time <= window_end:
            try:
                volume = float(tick.get("Volume", 0))
                price = float(tick.get("Price", 0))
                total_volume += volume
                total_amount += volume * price
                trade_count += 1
            except (ValueError, TypeError):
                continue

    avg_trade_volume = total_volume / trade_count if trade_count > 0 else 0.0

    return MarketLiquidity(
        total_volume=total_volume,
        total_amount=total_amount,
        trade_count=trade_count,
        avg_trade_volume=avg_trade_volume,
        time_window_minutes=time_window_minutes
    )


def load_tick_data(tick_path: Path) -> list[dict[str, Any]]:
    """Load tick data from CSV file."""
    tick_data = []

    if not tick_path.exists():
        return tick_data

    try:
        with open(tick_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tick_data.append(row)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:load_tick_data", exc, data={"path": str(tick_path)})

    return tick_data


def load_trades(trades_csv: Path) -> list[dict[str, Any]]:
    """Load strategy trades from CSV file."""
    trades = []

    if not trades_csv.exists():
        return trades

    try:
        with open(trades_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:load_trades", exc, data={"path": str(trades_csv)})

    return trades


def find_tick_file(tick_dir: Path, code: str, date: str) -> Path | None:
    """
    Find tick data file for given stock code and date.

    Expected naming patterns:
    - tick_trade_{code}_{date}.csv
    - {code}_{date}_tick.csv
    - {code}_tick_{date}.csv
    """
    date_clean = date.replace("-", "")

    patterns = [
        f"tick_trade_{code}_{date_clean}.csv",
        f"{code}_{date_clean}_tick.csv",
        f"{code}_tick_{date_clean}.csv",
        f"tick_{code}_{date_clean}.csv",
    ]

    for pattern in patterns:
        tick_path = tick_dir / pattern
        if tick_path.exists():
            return tick_path

    # Fallback: search for any file containing code and date
    for tick_file in tick_dir.glob("*.csv"):
        if code in tick_file.name and date_clean in tick_file.name:
            return tick_file

    return None


def validate_capacity(
    trades_csv: str | Path,
    tick_dir: str | Path,
    threshold: float = 0.1,
    time_window_minutes: int = 5
) -> CapacityReport:
    """
    Validate trading capacity against market liquidity.

    Args:
        trades_csv: Path to strategy trades CSV file
        tick_dir: Directory containing tick data files
        threshold: Primary threshold (default 0.1 for 10%)
        time_window_minutes: Time window for liquidity calculation (default 5)

    Returns:
        CapacityReport with validation results

    Expected trades CSV format:
        - code: stock code
        - date or time: trade date/datetime
        - volume: trade volume (shares)
        - amount: trade amount (optional, for amount-based validation)

    Expected tick CSV format:
        - Time: timestamp (YYYY-MM-DD HH:MM:SS)
        - Volume: trade volume
        - Price: trade price
    """
    trades_path = Path(trades_csv).expanduser().resolve()
    tick_dir_path = Path(tick_dir).expanduser().resolve()

    if not trades_path.exists():
        return CapacityReport(
            total_trades=0,
            capacity_ok_conservative=0,
            capacity_ok_aggressive=0
        )

    if not tick_dir_path.exists() or not tick_dir_path.is_dir():
        return CapacityReport(
            total_trades=0,
            capacity_ok_conservative=0,
            capacity_ok_aggressive=0
        )

    trades = load_trades(trades_path)

    if not trades:
        return CapacityReport(
            total_trades=0,
            capacity_ok_conservative=0,
            capacity_ok_aggressive=0
        )

    conservative_threshold = 0.1
    aggressive_threshold = 0.2

    conservative_ok = 0
    aggressive_ok = 0
    conservative_issues = []
    aggressive_issues = []

    for trade in trades:
        try:
            code = trade.get("code", "")

            # Try multiple date field names - check for non-empty values
            date_str = (
                (trade.get("time") or "").strip() or
                (trade.get("date") or "").strip() or
                (trade.get("datetime") or "").strip()
            )

            if not code or not date_str:
                continue

            # Parse trade time
            if " " in date_str:
                try:
                    trade_time = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Try alternative format
                    trade_time = datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S")
                date_only = date_str.split()[0]
            else:
                try:
                    trade_time = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    trade_time = datetime.strptime(date_str, "%Y/%m/%d")
                date_only = date_str

            # Get strategy volume
            strategy_volume = float(trade.get("volume", 0))
            if strategy_volume <= 0:
                continue

            # Find and load tick data
            tick_file = find_tick_file(tick_dir_path, code, date_only)
            if not tick_file:
                # No tick data available, cannot validate
                continue

            tick_data = load_tick_data(tick_file)
            if not tick_data:
                continue

            # Calculate market liquidity
            liquidity = calculate_market_liquidity(
                tick_data,
                trade_time,
                time_window_minutes
            )

            if liquidity.total_volume <= 0:
                # No market volume in window, cannot validate
                continue

            # Calculate ratio
            ratio = strategy_volume / liquidity.total_volume

            # Check conservative threshold (10%)
            if ratio <= conservative_threshold:
                conservative_ok += 1
            else:
                conservative_issues.append(
                    CapacityIssue(
                        code=code,
                        date=date_only,
                        time=trade_time.strftime("%H:%M:%S"),
                        strategy_volume=strategy_volume,
                        market_volume=liquidity.total_volume,
                        ratio=ratio,
                        threshold=conservative_threshold
                    )
                )

            # Check aggressive threshold (20%)
            if ratio <= aggressive_threshold:
                aggressive_ok += 1
            else:
                aggressive_issues.append(
                    CapacityIssue(
                        code=code,
                        date=date_only,
                        time=trade_time.strftime("%H:%M:%S"),
                        strategy_volume=strategy_volume,
                        market_volume=liquidity.total_volume,
                        ratio=ratio,
                        threshold=aggressive_threshold
                    )
                )

        except (ValueError, KeyError, TypeError):
            continue

    return CapacityReport(
        total_trades=len(trades),
        capacity_ok_conservative=conservative_ok,
        capacity_ok_aggressive=aggressive_ok,
        insufficient_capacity_conservative=tuple(conservative_issues),
        insufficient_capacity_aggressive=tuple(aggressive_issues),
        conservative_threshold=conservative_threshold,
        aggressive_threshold=aggressive_threshold
    )


def main():
    """CLI entry point for testing."""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python -m quantagent.tick_capacity_validator <trades_csv> <tick_dir>")
        sys.exit(1)

    trades_csv = sys.argv[1]
    tick_dir = sys.argv[2]

    report = validate_capacity(trades_csv, tick_dir)

    print("=" * 60)
    print("Tick Capacity Validation Report")
    print("=" * 60)
    print(f"Total trades: {report.total_trades}")
    print(f"Conservative (10%) OK: {report.capacity_ok_conservative}")
    print(f"Aggressive (20%) OK: {report.capacity_ok_aggressive}")
    print()

    if report.insufficient_capacity_conservative:
        print(f"Conservative violations: {len(report.insufficient_capacity_conservative)}")
        for issue in report.insufficient_capacity_conservative[:5]:
            print(f"  {issue.code} {issue.date} {issue.time}: "
                  f"{issue.strategy_volume:.0f} / {issue.market_volume:.0f} "
                  f"= {issue.ratio:.2%}")
        if len(report.insufficient_capacity_conservative) > 5:
            print(f"  ... and {len(report.insufficient_capacity_conservative) - 5} more")

    print()

    if report.insufficient_capacity_aggressive:
        print(f"Aggressive violations: {len(report.insufficient_capacity_aggressive)}")
        for issue in report.insufficient_capacity_aggressive[:5]:
            print(f"  {issue.code} {issue.date} {issue.time}: "
                  f"{issue.strategy_volume:.0f} / {issue.market_volume:.0f} "
                  f"= {issue.ratio:.2%}")
        if len(report.insufficient_capacity_aggressive) > 5:
            print(f"  ... and {len(report.insufficient_capacity_aggressive) - 5} more")


if __name__ == "__main__":
    main()
