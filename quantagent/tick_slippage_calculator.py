"""
Tick-level slippage calculator.

Compares theoretical signal prices against actual executable prices from tick data
to measure real-world slippage.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .exception_audit import audit_suppressed_exception


@dataclass(frozen=True)
class SlippageCase:
    """Single trade slippage case."""

    trade_id: int
    code: str
    signal_time: str
    signal_price: float
    executable_price: float
    direction: str  # 'buy' or 'sell'
    volume: float
    slippage_bps: float
    slippage_pct: float
    tick_delay_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlippageDistribution:
    """Slippage distribution statistics."""

    range_0_10bps: int = 0  # 0-0.1%
    range_10_20bps: int = 0  # 0.1-0.2%
    range_20_50bps: int = 0  # 0.2-0.5%
    range_50_100bps: int = 0  # 0.5-1.0%
    range_over_100bps: int = 0  # >1.0%

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlippageReport:
    """Complete slippage analysis report."""

    total_trades: int
    average_slippage_bps: float
    median_slippage_bps: float
    std_slippage_bps: float
    min_slippage_bps: float
    max_slippage_bps: float
    distribution: SlippageDistribution
    worst_cases: tuple[SlippageCase, ...] = ()
    best_cases: tuple[SlippageCase, ...] = ()
    assumed_slippage_bps: float = 20.0  # default 0.2%
    slippage_underestimated: bool = False
    slippage_overestimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "average_slippage_bps": self.average_slippage_bps,
            "median_slippage_bps": self.median_slippage_bps,
            "std_slippage_bps": self.std_slippage_bps,
            "min_slippage_bps": self.min_slippage_bps,
            "max_slippage_bps": self.max_slippage_bps,
            "distribution": self.distribution.to_dict(),
            "worst_cases": [c.to_dict() for c in self.worst_cases],
            "best_cases": [c.to_dict() for c in self.best_cases],
            "assumed_slippage_bps": self.assumed_slippage_bps,
            "slippage_underestimated": self.slippage_underestimated,
            "slippage_overestimated": self.slippage_overestimated,
        }


def find_executable_price(
    tick_data: pd.DataFrame,
    signal_time: datetime,
    direction: str,
    volume: float = 0,
) -> tuple[float, int]:
    """
    Find the actual executable price from tick data after signal time.

    Args:
        tick_data: DataFrame with columns [Time, Price, Volume, Type]
        signal_time: Signal generation time
        direction: 'buy' or 'sell'
        volume: Desired trade volume (currently unused, for future enhancement)

    Returns:
        (executable_price, delay_ms): Price and delay in milliseconds
    """
    if tick_data.empty:
        return 0.0, 0

    # Ensure Time column is datetime
    if not pd.api.types.is_datetime64_any_dtype(tick_data['Time']):
        tick_data = tick_data.copy()
        tick_data['Time'] = pd.to_datetime(tick_data['Time'])

    # Find ticks after signal time
    future_ticks = tick_data[tick_data['Time'] >= signal_time]

    if future_ticks.empty:
        # No future ticks, use last available price
        return float(tick_data.iloc[-1]['Price']), 0

    # For buy: look for sell orders (Type='S') or any executed price
    # For sell: look for buy orders (Type='B') or any executed price
    if direction == 'buy':
        # Buyer takes the ask price (seller's price)
        # In tick data, Type='S' means seller initiated, which is what buyer gets
        matching_ticks = future_ticks[future_ticks['Type'] == 'S'] if 'Type' in future_ticks.columns else future_ticks
    else:
        # Seller takes the bid price (buyer's price)
        # Type='B' means buyer initiated, which is what seller gets
        matching_ticks = future_ticks[future_ticks['Type'] == 'B'] if 'Type' in future_ticks.columns else future_ticks

    if matching_ticks.empty:
        # No matching type, use first available tick
        matching_ticks = future_ticks

    # Take the first matching tick
    first_tick = matching_ticks.iloc[0]
    executable_price = float(first_tick['Price'])

    # Calculate delay
    delay_ms = int((first_tick['Time'] - signal_time).total_seconds() * 1000)

    return executable_price, delay_ms


def calculate_slippage(
    trades_csv: str | Path,
    tick_dir: str | Path,
    signal_col: str = "t1_auction_return",
    date_col: str = "entry_date",
    code_col: str = "code",
    direction_col: str = "direction",
    volume_col: str = "volume",
    price_col: str = "entry_price",
    assumed_slippage_bps: float = 20.0,
) -> SlippageReport:
    """
    Calculate real slippage from trades and tick data.

    Args:
        trades_csv: Path to trades CSV with signal information
        tick_dir: Directory containing tick data CSVs (named like tick_trade_{code}_{date}.csv)
        signal_col: Column name for signal return (e.g., t1_auction_return)
        date_col: Column name for entry date
        code_col: Column name for stock code
        direction_col: Column name for trade direction (1=buy, -1=sell)
        volume_col: Column name for trade volume
        price_col: Column name for theoretical entry price
        assumed_slippage_bps: Assumed slippage in basis points for comparison

    Returns:
        SlippageReport with detailed analysis
    """
    trades_path = Path(trades_csv)
    tick_path = Path(tick_dir)

    if not trades_path.exists():
        raise FileNotFoundError(f"Trades file not found: {trades_path}")

    if not tick_path.exists():
        raise FileNotFoundError(f"Tick directory not found: {tick_path}")

    # Load trades
    trades_df = pd.read_csv(trades_path)

    # Validate required columns
    required_cols = [date_col, code_col, price_col]
    missing_cols = [col for col in required_cols if col not in trades_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in trades CSV: {missing_cols}")

    # Infer direction if not provided
    if direction_col not in trades_df.columns:
        # Assume buy if signal_col > 0, sell if < 0
        if signal_col in trades_df.columns:
            trades_df['direction'] = trades_df[signal_col].apply(lambda x: 1 if x > 0 else -1)
            direction_col = 'direction'
        else:
            # Default to buy
            trades_df['direction'] = 1
            direction_col = 'direction'

    # Infer volume if not provided
    if volume_col not in trades_df.columns:
        trades_df['volume'] = 100  # Default volume
        volume_col = 'volume'

    slippage_cases = []

    for idx, row in trades_df.iterrows():
        code = str(row[code_col])
        date_str = str(row[date_col])
        signal_price = float(row[price_col])
        direction = int(row[direction_col])
        volume = float(row[volume_col]) if volume_col in trades_df.columns else 100

        # Parse date
        try:
            if '-' in date_str:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            else:
                date_obj = datetime.strptime(date_str, '%Y%m%d')
        except ValueError:
            continue

        date_formatted = date_obj.strftime('%Y%m%d')

        # Find tick file
        tick_file = tick_path / f"tick_trade_{code}_{date_formatted}.csv"

        if not tick_file.exists():
            # Try alternative naming
            tick_file = tick_path / f"tick_{code}_{date_formatted}.csv"

        if not tick_file.exists():
            continue

        # Load tick data
        try:
            tick_df = pd.read_csv(tick_file)
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:load_tick_data", exc, data={"path": str(tick_file)})
            continue

        if tick_df.empty:
            continue

        # Assume signal time is at market open (09:30:00)
        signal_time = datetime.strptime(f"{date_obj.strftime('%Y-%m-%d')} 09:30:00", '%Y-%m-%d %H:%M:%S')

        # Find executable price
        direction_str = 'buy' if direction > 0 else 'sell'
        executable_price, delay_ms = find_executable_price(
            tick_df, signal_time, direction_str, volume
        )

        if executable_price == 0:
            continue

        # Calculate slippage
        # For buy: slippage = (executable - signal) / signal
        # For sell: slippage = (signal - executable) / signal
        if direction > 0:
            slippage_pct = (executable_price - signal_price) / signal_price
        else:
            slippage_pct = (signal_price - executable_price) / signal_price

        slippage_bps = slippage_pct * 10000

        case = SlippageCase(
            trade_id=int(idx),
            code=code,
            signal_time=signal_time.strftime('%Y-%m-%d %H:%M:%S'),
            signal_price=signal_price,
            executable_price=executable_price,
            direction=direction_str,
            volume=volume,
            slippage_bps=slippage_bps,
            slippage_pct=slippage_pct,
            tick_delay_ms=delay_ms,
        )

        slippage_cases.append(case)

    if not slippage_cases:
        return SlippageReport(
            total_trades=0,
            average_slippage_bps=0.0,
            median_slippage_bps=0.0,
            std_slippage_bps=0.0,
            min_slippage_bps=0.0,
            max_slippage_bps=0.0,
            distribution=SlippageDistribution(),
            assumed_slippage_bps=assumed_slippage_bps,
        )

    # Calculate statistics
    slippages = [c.slippage_bps for c in slippage_cases]
    avg_slippage = sum(slippages) / len(slippages)
    median_slippage = sorted(slippages)[len(slippages) // 2]
    std_slippage = (sum((s - avg_slippage) ** 2 for s in slippages) / len(slippages)) ** 0.5
    min_slippage = min(slippages)
    max_slippage = max(slippages)

    # Distribution
    dist_counts = {
        'range_0_10bps': 0,
        'range_10_20bps': 0,
        'range_20_50bps': 0,
        'range_50_100bps': 0,
        'range_over_100bps': 0,
    }

    for s in slippages:
        abs_s = abs(s)
        if abs_s < 10:
            dist_counts['range_0_10bps'] += 1
        elif abs_s < 20:
            dist_counts['range_10_20bps'] += 1
        elif abs_s < 50:
            dist_counts['range_20_50bps'] += 1
        elif abs_s < 100:
            dist_counts['range_50_100bps'] += 1
        else:
            dist_counts['range_over_100bps'] += 1

    distribution = SlippageDistribution(**dist_counts)

    # Worst and best cases
    sorted_cases = sorted(slippage_cases, key=lambda c: c.slippage_bps, reverse=True)
    worst_cases = tuple(sorted_cases[:10])
    best_cases = tuple(sorted_cases[-10:])

    # Compare with assumed slippage
    slippage_underestimated = avg_slippage > assumed_slippage_bps
    slippage_overestimated = avg_slippage < assumed_slippage_bps * 0.5

    return SlippageReport(
        total_trades=len(slippage_cases),
        average_slippage_bps=avg_slippage,
        median_slippage_bps=median_slippage,
        std_slippage_bps=std_slippage,
        min_slippage_bps=min_slippage,
        max_slippage_bps=max_slippage,
        distribution=distribution,
        worst_cases=worst_cases,
        best_cases=best_cases,
        assumed_slippage_bps=assumed_slippage_bps,
        slippage_underestimated=slippage_underestimated,
        slippage_overestimated=slippage_overestimated,
    )


def save_slippage_report(report: SlippageReport, output_path: str | Path) -> None:
    """Save slippage report to JSON file."""
    import json

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)


def print_slippage_summary(report: SlippageReport) -> None:
    """Print human-readable slippage summary."""
    print(f"\n{'='*60}")
    print("SLIPPAGE ANALYSIS REPORT")
    print(f"{'='*60}\n")

    print(f"Total Trades: {report.total_trades}")
    print(f"Average Slippage: {report.average_slippage_bps:.2f} bps ({report.average_slippage_bps/100:.3f}%)")
    print(f"Median Slippage: {report.median_slippage_bps:.2f} bps")
    print(f"Std Dev: {report.std_slippage_bps:.2f} bps")
    print(f"Min Slippage: {report.min_slippage_bps:.2f} bps")
    print(f"Max Slippage: {report.max_slippage_bps:.2f} bps")

    print(f"\nAssumed Slippage: {report.assumed_slippage_bps:.2f} bps")
    if report.slippage_underestimated:
        print(f"⚠️  WARNING: Real slippage exceeds assumption!")
    elif report.slippage_overestimated:
        print(f"✓ Real slippage is significantly lower than assumption")

    print(f"\nDistribution:")
    dist = report.distribution
    print(f"  0-10 bps (0-0.1%):    {dist.range_0_10bps:4d} trades")
    print(f"  10-20 bps (0.1-0.2%): {dist.range_10_20bps:4d} trades")
    print(f"  20-50 bps (0.2-0.5%): {dist.range_20_50bps:4d} trades")
    print(f"  50-100 bps (0.5-1%):  {dist.range_50_100bps:4d} trades")
    print(f"  >100 bps (>1%):       {dist.range_over_100bps:4d} trades")

    if report.worst_cases:
        print(f"\nWorst 3 Cases:")
        for i, case in enumerate(report.worst_cases[:3], 1):
            print(f"  {i}. {case.code} {case.signal_time}: {case.slippage_bps:.2f} bps "
                  f"({case.direction}, signal={case.signal_price:.2f}, exec={case.executable_price:.2f})")

    print(f"\n{'='*60}\n")
