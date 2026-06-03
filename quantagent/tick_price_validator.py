"""
Tick Price Validator

Validates strategy trade prices against actual tick data to ensure authenticity.
Checks that entry and exit prices fall within the actual tick price ranges
for the corresponding time windows.

Usage:
    from quantagent.tick_price_validator import validate_trade_prices

    result = validate_trade_prices(
        trades_csv="realistic_t1_trades.csv",
        tick_dir="tick_data/"
    )

    print(f"Total trades: {result.total_trades}")
    print(f"Valid entries: {result.valid_entry_prices}")
    print(f"Invalid entries: {len(result.invalid_entries)}")
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InvalidPrice:
    """Represents a price that doesn't match tick data."""
    code: str
    date: str
    strategy_price: float
    tick_min: float
    tick_max: float
    deviation_pct: float
    price_type: str  # 'entry' or 'exit'
    time_window: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    """Complete price validation report."""
    total_trades: int
    valid_entry_prices: int
    valid_exit_prices: int
    invalid_entries: tuple[InvalidPrice, ...] = ()
    invalid_exits: tuple[InvalidPrice, ...] = ()
    missing_tick_data: tuple[str, ...] = ()
    validation_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "valid_entry_prices": self.valid_entry_prices,
            "valid_exit_prices": self.valid_exit_prices,
            "invalid_entries": [ie.to_dict() for ie in self.invalid_entries],
            "invalid_exits": [ie.to_dict() for ie in self.invalid_exits],
            "missing_tick_data": list(self.missing_tick_data),
            "validation_rate": self.validation_rate,
        }


def load_tick_data(tick_dir: Path, code: str, date: str) -> list[dict[str, Any]]:
    """
    Load tick data for a specific stock code and date.

    Args:
        tick_dir: Directory containing tick CSV files
        code: Stock code (e.g., '300678')
        date: Date string (e.g., '2018-03-15')

    Returns:
        List of tick records with Time, Price, Volume fields
    """
    # Try common tick file naming patterns
    date_compact = date.replace("-", "")
    patterns = [
        f"tick_trade_{code}_{date_compact}.csv",
        f"tick_{code}_{date_compact}.csv",
        f"{code}_tick_{date_compact}.csv",
        f"{code}_{date}.csv",
    ]

    for pattern in patterns:
        tick_file = tick_dir / pattern
        if tick_file.exists():
            ticks = []
            with open(tick_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ticks.append({
                        'Time': row.get('Time', ''),
                        'Price': float(row.get('Price', 0)),
                        'Volume': float(row.get('Volume', 0)),
                    })
            return ticks

    return []


def check_price_in_range(
    price: float,
    tick_data: list[dict[str, Any]],
    time_window: tuple[time, time] | None = None
) -> tuple[bool, float, float]:
    """
    Check if a price falls within the tick data range for a time window.

    Args:
        price: Strategy price to validate
        tick_data: List of tick records
        time_window: Optional (start_time, end_time) tuple to filter ticks

    Returns:
        Tuple of (is_valid, tick_min, tick_max)
    """
    if not tick_data:
        return False, 0.0, 0.0

    # Filter by time window if provided
    filtered_ticks = tick_data
    if time_window:
        start_time, end_time = time_window
        filtered_ticks = []
        for tick in tick_data:
            try:
                tick_time_str = tick['Time']
                if ' ' in tick_time_str:
                    tick_time = datetime.strptime(tick_time_str, '%Y-%m-%d %H:%M:%S').time()
                else:
                    tick_time = datetime.strptime(tick_time_str, '%H:%M:%S').time()

                if start_time <= tick_time <= end_time:
                    filtered_ticks.append(tick)
            except (ValueError, KeyError):
                continue

    if not filtered_ticks:
        return False, 0.0, 0.0

    prices = [t['Price'] for t in filtered_ticks if t['Price'] > 0]
    if not prices:
        return False, 0.0, 0.0

    tick_min = min(prices)
    tick_max = max(prices)

    # Allow small tolerance for rounding (0.01 yuan)
    tolerance = 0.01
    is_valid = (tick_min - tolerance) <= price <= (tick_max + tolerance)

    return is_valid, tick_min, tick_max


def validate_trade_prices(
    trades_csv: str | Path,
    tick_dir: str | Path,
    *,
    entry_date_col: str = "entry_date",
    exit_date_col: str = "exit_date",
    code_col: str = "code",
    entry_price_col: str = "entry_price",
    exit_price_col: str = "exit_price",
    entry_time_window: tuple[time, time] = (time(9, 25), time(9, 35)),
    max_trades: int | None = None,
) -> ValidationResult:
    """
    Validate strategy trade prices against tick data.

    Args:
        trades_csv: Path to trades CSV file
        tick_dir: Directory containing tick data files
        entry_date_col: Column name for entry date
        exit_date_col: Column name for exit date
        code_col: Column name for stock code
        entry_price_col: Column name for entry price
        exit_price_col: Column name for exit price
        entry_time_window: Time window for entry price validation (default 09:25-09:35)
        max_trades: Maximum number of trades to validate (None = all)

    Returns:
        ValidationResult with validation statistics and invalid cases
    """
    trades_path = Path(trades_csv).expanduser().resolve()
    tick_path = Path(tick_dir).expanduser().resolve()

    if not trades_path.exists():
        raise FileNotFoundError(f"Trades CSV not found: {trades_path}")
    if not tick_path.exists():
        raise FileNotFoundError(f"Tick directory not found: {tick_path}")

    invalid_entries: list[InvalidPrice] = []
    invalid_exits: list[InvalidPrice] = []
    missing_tick_data: set[str] = set()
    valid_entry_count = 0
    valid_exit_count = 0
    total_trades = 0

    with open(trades_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if max_trades and total_trades >= max_trades:
                break

            total_trades += 1
            code = row.get(code_col, '')
            entry_date = row.get(entry_date_col, '')
            exit_date = row.get(exit_date_col, '')

            try:
                entry_price = float(row.get(entry_price_col, 0))
                exit_price = float(row.get(exit_price_col, 0))
            except (ValueError, TypeError):
                continue

            # Validate entry price
            if entry_price > 0 and entry_date:
                entry_ticks = load_tick_data(tick_path, code, entry_date)
                if entry_ticks:
                    is_valid, tick_min, tick_max = check_price_in_range(
                        entry_price,
                        entry_ticks,
                        entry_time_window
                    )
                    if is_valid:
                        valid_entry_count += 1
                    else:
                        # Calculate deviation
                        if entry_price < tick_min:
                            deviation_pct = ((tick_min - entry_price) / entry_price) * 100
                        else:
                            deviation_pct = ((entry_price - tick_max) / entry_price) * 100

                        invalid_entries.append(InvalidPrice(
                            code=code,
                            date=entry_date,
                            strategy_price=entry_price,
                            tick_min=tick_min,
                            tick_max=tick_max,
                            deviation_pct=round(deviation_pct, 2),
                            price_type='entry',
                            time_window=f"{entry_time_window[0].strftime('%H:%M')}-{entry_time_window[1].strftime('%H:%M')}"
                        ))
                else:
                    missing_tick_data.add(f"{code}_{entry_date}")

            # Validate exit price
            if exit_price > 0 and exit_date:
                exit_ticks = load_tick_data(tick_path, code, exit_date)
                if exit_ticks:
                    # For exit, check entire trading day
                    is_valid, tick_min, tick_max = check_price_in_range(
                        exit_price,
                        exit_ticks,
                        None  # No time window restriction
                    )
                    if is_valid:
                        valid_exit_count += 1
                    else:
                        # Calculate deviation
                        if exit_price < tick_min:
                            deviation_pct = ((tick_min - exit_price) / exit_price) * 100
                        else:
                            deviation_pct = ((exit_price - tick_max) / exit_price) * 100

                        invalid_exits.append(InvalidPrice(
                            code=code,
                            date=exit_date,
                            strategy_price=exit_price,
                            tick_min=tick_min,
                            tick_max=tick_max,
                            deviation_pct=round(deviation_pct, 2),
                            price_type='exit',
                            time_window='full_day'
                        ))
                else:
                    missing_tick_data.add(f"{code}_{exit_date}")

    # Calculate validation rate
    total_validatable = (total_trades * 2) - len(missing_tick_data)
    if total_validatable > 0:
        validation_rate = ((valid_entry_count + valid_exit_count) / total_validatable) * 100
    else:
        validation_rate = 0.0

    return ValidationResult(
        total_trades=total_trades,
        valid_entry_prices=valid_entry_count,
        valid_exit_prices=valid_exit_count,
        invalid_entries=tuple(invalid_entries),
        invalid_exits=tuple(invalid_exits),
        missing_tick_data=tuple(sorted(missing_tick_data)),
        validation_rate=round(validation_rate, 2)
    )


def generate_validation_report(result: ValidationResult, output_path: str | Path) -> None:
    """
    Generate a markdown validation report.

    Args:
        result: ValidationResult to report
        output_path: Path to save the markdown report
    """
    output = Path(output_path).expanduser().resolve()

    lines = [
        "# Tick Price Validation Report",
        "",
        "## Summary",
        "",
        f"- **Total Trades**: {result.total_trades}",
        f"- **Valid Entry Prices**: {result.valid_entry_prices}",
        f"- **Valid Exit Prices**: {result.valid_exit_prices}",
        f"- **Invalid Entry Prices**: {len(result.invalid_entries)}",
        f"- **Invalid Exit Prices**: {len(result.invalid_exits)}",
        f"- **Missing Tick Data**: {len(result.missing_tick_data)}",
        f"- **Validation Rate**: {result.validation_rate:.2f}%",
        "",
    ]

    if result.invalid_entries:
        lines.extend([
            "## Invalid Entry Prices",
            "",
            "| Code | Date | Strategy Price | Tick Min | Tick Max | Deviation % | Time Window |",
            "|------|------|----------------|----------|----------|-------------|-------------|",
        ])
        for inv in result.invalid_entries:
            lines.append(
                f"| {inv.code} | {inv.date} | {inv.strategy_price:.2f} | "
                f"{inv.tick_min:.2f} | {inv.tick_max:.2f} | {inv.deviation_pct:.2f}% | "
                f"{inv.time_window} |"
            )
        lines.append("")

    if result.invalid_exits:
        lines.extend([
            "## Invalid Exit Prices",
            "",
            "| Code | Date | Strategy Price | Tick Min | Tick Max | Deviation % |",
            "|------|------|----------------|----------|----------|-------------|",
        ])
        for inv in result.invalid_exits:
            lines.append(
                f"| {inv.code} | {inv.date} | {inv.strategy_price:.2f} | "
                f"{inv.tick_min:.2f} | {inv.tick_max:.2f} | {inv.deviation_pct:.2f}% |"
            )
        lines.append("")

    if result.missing_tick_data:
        lines.extend([
            "## Missing Tick Data",
            "",
        ])
        for missing in result.missing_tick_data:
            lines.append(f"- {missing}")
        lines.append("")

    output.write_text('\n'.join(lines), encoding='utf-8')


def save_validation_json(result: ValidationResult, output_path: str | Path) -> None:
    """
    Save validation result as JSON.

    Args:
        result: ValidationResult to save
        output_path: Path to save the JSON file
    """
    output = Path(output_path).expanduser().resolve()
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
