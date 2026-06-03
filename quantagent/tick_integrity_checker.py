"""
Tick Integrity Checker

Validates tick data quality by detecting:
- Missing ticks: time gaps > 60 seconds
- Abnormal price jumps: price changes > 10%
- Timestamp errors: non-monotonic or out-of-trading-hours
- Zero volume: consecutive zero-volume ticks

Usage:
    from quantagent.tick_integrity_checker import check_tick_integrity

    report = check_tick_integrity("path/to/tick_data_dir")

    print(f"Files checked: {report.files_checked}")
    print(f"Missing ticks: {len(report.missing_ticks)}")
    print(f"Abnormal jumps: {len(report.abnormal_jumps)}")
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from .exception_audit import audit_suppressed_exception


@dataclass(frozen=True)
class MissingTick:
    """Represents a gap in tick data."""
    code: str
    date: str
    gap_start: str
    gap_end: str
    duration_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AbnormalJump:
    """Represents an abnormal price jump."""
    code: str
    date: str
    time: str
    price_before: float
    price_after: float
    change_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TimestampError:
    """Represents a timestamp error."""
    code: str
    date: str
    error_type: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntegrityReport:
    """Complete tick integrity report."""
    files_checked: int
    total_ticks: int
    missing_ticks: tuple[MissingTick, ...] = ()
    abnormal_jumps: tuple[AbnormalJump, ...] = ()
    timestamp_errors: tuple[TimestampError, ...] = ()
    zero_volume_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_checked": self.files_checked,
            "total_ticks": self.total_ticks,
            "missing_ticks": [mt.to_dict() for mt in self.missing_ticks],
            "abnormal_jumps": [aj.to_dict() for aj in self.abnormal_jumps],
            "timestamp_errors": [te.to_dict() for te in self.timestamp_errors],
            "zero_volume_count": self.zero_volume_count,
        }


def detect_missing_ticks(
    tick_data: list[dict[str, Any]],
    max_gap_seconds: int = 60
) -> list[MissingTick]:
    """
    Detect missing ticks based on time gaps.

    Args:
        tick_data: List of tick records with Time field
        max_gap_seconds: Maximum acceptable gap in seconds (default 60)

    Returns:
        List of MissingTick objects
    """
    missing = []

    if len(tick_data) < 2:
        return missing

    for i in range(1, len(tick_data)):
        prev_tick = tick_data[i - 1]
        curr_tick = tick_data[i]

        try:
            prev_time = _parse_tick_time(prev_tick.get("Time", ""))
            curr_time = _parse_tick_time(curr_tick.get("Time", ""))

            if prev_time is None or curr_time is None:
                continue

            gap = (curr_time - prev_time).total_seconds()

            if gap > max_gap_seconds:
                code = curr_tick.get("Code", prev_tick.get("Code", ""))
                date = curr_time.strftime("%Y-%m-%d")

                missing.append(
                    MissingTick(
                        code=code,
                        date=date,
                        gap_start=prev_time.strftime("%H:%M:%S"),
                        gap_end=curr_time.strftime("%H:%M:%S"),
                        duration_seconds=int(gap)
                    )
                )
        except (ValueError, TypeError):
            continue

    return missing


def detect_abnormal_jumps(
    tick_data: list[dict[str, Any]],
    max_change_pct: float = 0.1
) -> list[AbnormalJump]:
    """
    Detect abnormal price jumps.

    Args:
        tick_data: List of tick records with Time and Price fields
        max_change_pct: Maximum acceptable price change (default 0.1 = 10%)

    Returns:
        List of AbnormalJump objects
    """
    jumps = []

    if len(tick_data) < 2:
        return jumps

    for i in range(1, len(tick_data)):
        prev_tick = tick_data[i - 1]
        curr_tick = tick_data[i]

        try:
            prev_price = float(prev_tick.get("Price", 0))
            curr_price = float(curr_tick.get("Price", 0))

            if prev_price <= 0 or curr_price <= 0:
                continue

            change_pct = abs(curr_price - prev_price) / prev_price

            if change_pct > max_change_pct:
                curr_time = _parse_tick_time(curr_tick.get("Time", ""))
                if curr_time is None:
                    continue

                code = curr_tick.get("Code", prev_tick.get("Code", ""))
                date = curr_time.strftime("%Y-%m-%d")

                jumps.append(
                    AbnormalJump(
                        code=code,
                        date=date,
                        time=curr_time.strftime("%H:%M:%S"),
                        price_before=prev_price,
                        price_after=curr_price,
                        change_pct=change_pct
                    )
                )
        except (ValueError, TypeError):
            continue

    return jumps


def detect_timestamp_errors(
    tick_data: list[dict[str, Any]]
) -> tuple[list[TimestampError], int]:
    """
    Detect timestamp errors and zero volume ticks.

    Args:
        tick_data: List of tick records with Time and Volume fields

    Returns:
        Tuple of (timestamp_errors, zero_volume_count)
    """
    errors = []
    zero_volume_count = 0
    prev_time = None

    # Trading hours: 09:30 - 11:30, 13:00 - 15:00 (China A-share market)
    morning_start = time(9, 30)
    morning_end = time(11, 30)
    afternoon_start = time(13, 0)
    afternoon_end = time(15, 0)

    for i, tick in enumerate(tick_data):
        try:
            curr_time = _parse_tick_time(tick.get("Time", ""))
            if curr_time is None:
                code = tick.get("Code", "")
                date = tick.get("Time", "")[:10] if tick.get("Time") else ""
                errors.append(
                    TimestampError(
                        code=code,
                        date=date,
                        error_type="invalid_timestamp",
                        details=f"Row {i}: cannot parse timestamp '{tick.get('Time', '')}'"
                    )
                )
                continue

            # Check non-monotonic timestamps
            if prev_time is not None and curr_time < prev_time:
                code = tick.get("Code", "")
                date = curr_time.strftime("%Y-%m-%d")
                errors.append(
                    TimestampError(
                        code=code,
                        date=date,
                        error_type="non_monotonic",
                        details=f"Row {i}: {curr_time.strftime('%H:%M:%S')} < {prev_time.strftime('%H:%M:%S')}"
                    )
                )

            # Check trading hours
            tick_time = curr_time.time()
            in_morning = morning_start <= tick_time <= morning_end
            in_afternoon = afternoon_start <= tick_time <= afternoon_end

            if not (in_morning or in_afternoon):
                code = tick.get("Code", "")
                date = curr_time.strftime("%Y-%m-%d")
                errors.append(
                    TimestampError(
                        code=code,
                        date=date,
                        error_type="out_of_trading_hours",
                        details=f"Row {i}: {curr_time.strftime('%H:%M:%S')} outside 09:30-11:30, 13:00-15:00"
                    )
                )

            # Check zero volume
            volume = float(tick.get("Volume", 0))
            if volume == 0:
                zero_volume_count += 1

            prev_time = curr_time

        except (ValueError, TypeError):
            continue

    return errors, zero_volume_count


def check_tick_integrity(tick_dir: str | Path) -> IntegrityReport:
    """
    Check tick data integrity for all files in directory.

    Args:
        tick_dir: Directory containing tick CSV files

    Returns:
        IntegrityReport with all detected issues

    Expected tick CSV format:
        - Time: timestamp (YYYY-MM-DD HH:MM:SS)
        - Price: trade price
        - Volume: trade volume
        - Code: stock code (optional)
    """
    tick_dir_path = Path(tick_dir).expanduser().resolve()

    if not tick_dir_path.exists() or not tick_dir_path.is_dir():
        return IntegrityReport(
            files_checked=0,
            total_ticks=0
        )

    all_missing = []
    all_jumps = []
    all_timestamp_errors = []
    total_zero_volume = 0
    files_checked = 0
    total_ticks = 0

    # Process all CSV files in directory
    for tick_file in sorted(tick_dir_path.glob("*.csv")):
        try:
            tick_data = _load_tick_file(tick_file)

            if not tick_data:
                continue

            files_checked += 1
            total_ticks += len(tick_data)

            # Extract code and date from filename or data
            code, date = _extract_code_date(tick_file, tick_data)

            # Add code and date to each tick record
            for tick in tick_data:
                if "Code" not in tick or not tick["Code"]:
                    tick["Code"] = code

            # Detect issues
            missing = detect_missing_ticks(tick_data)
            all_missing.extend(missing)

            jumps = detect_abnormal_jumps(tick_data)
            all_jumps.extend(jumps)

            timestamp_errors, zero_volume = detect_timestamp_errors(tick_data)
            all_timestamp_errors.extend(timestamp_errors)
            total_zero_volume += zero_volume

        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:check_tick_integrity", exc, data={"path": str(tick_file)})
            continue

    return IntegrityReport(
        files_checked=files_checked,
        total_ticks=total_ticks,
        missing_ticks=tuple(all_missing),
        abnormal_jumps=tuple(all_jumps),
        timestamp_errors=tuple(all_timestamp_errors),
        zero_volume_count=total_zero_volume
    )


def _load_tick_file(tick_path: Path) -> list[dict[str, Any]]:
    """Load tick data from CSV file."""
    tick_data = []

    try:
        with open(tick_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tick_data.append(row)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:_load_tick_file", exc, data={"path": str(tick_path)})

    return tick_data


def _parse_tick_time(time_str: str) -> datetime | None:
    """Parse tick timestamp string."""
    if not time_str:
        return None

    # Try common formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y%m%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue

    return None


def _extract_code_date(tick_file: Path, tick_data: list[dict[str, Any]]) -> tuple[str, str]:
    """Extract stock code and date from filename or data."""
    code = ""
    date = ""

    # Try to extract from filename
    # Expected patterns: tick_trade_600000_20240101.csv, 600000_20240101_tick.csv
    filename = tick_file.stem
    parts = filename.split("_")

    for part in parts:
        # Check if it's a stock code (6 digits)
        if len(part) == 6 and part.isdigit():
            code = part
        # Check if it's a date (8 digits)
        elif len(part) == 8 and part.isdigit():
            try:
                parsed = datetime.strptime(part, "%Y%m%d")
                date = parsed.strftime("%Y-%m-%d")
            except ValueError:
                pass

    # Fallback: extract from first tick record
    if tick_data:
        first_tick = tick_data[0]
        if not code and "Code" in first_tick:
            code = first_tick["Code"]
        if not date and "Time" in first_tick:
            time_str = first_tick["Time"]
            if time_str:
                date = time_str[:10]

    return code, date


def main():
    """CLI entry point for testing."""
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python -m quantagent.tick_integrity_checker <tick_dir>")
        sys.exit(1)

    tick_dir = sys.argv[1]
    report = check_tick_integrity(tick_dir)

    print("=" * 60)
    print("Tick Integrity Report")
    print("=" * 60)
    print(f"Files checked: {report.files_checked}")
    print(f"Total ticks: {report.total_ticks}")
    print(f"Zero volume ticks: {report.zero_volume_count}")
    print()

    if report.missing_ticks:
        print(f"Missing ticks: {len(report.missing_ticks)}")
        for mt in list(report.missing_ticks)[:5]:
            print(f"  {mt.code} {mt.date} {mt.gap_start} -> {mt.gap_end} "
                  f"({mt.duration_seconds}s)")
        if len(report.missing_ticks) > 5:
            print(f"  ... and {len(report.missing_ticks) - 5} more")
        print()

    if report.abnormal_jumps:
        print(f"Abnormal jumps: {len(report.abnormal_jumps)}")
        for aj in list(report.abnormal_jumps)[:5]:
            print(f"  {aj.code} {aj.date} {aj.time}: "
                  f"{aj.price_before:.2f} -> {aj.price_after:.2f} "
                  f"({aj.change_pct:.2%})")
        if len(report.abnormal_jumps) > 5:
            print(f"  ... and {len(report.abnormal_jumps) - 5} more")
        print()

    if report.timestamp_errors:
        print(f"Timestamp errors: {len(report.timestamp_errors)}")
        for te in list(report.timestamp_errors)[:5]:
            print(f"  {te.code} {te.date} [{te.error_type}]: {te.details}")
        if len(report.timestamp_errors) > 5:
            print(f"  ... and {len(report.timestamp_errors) - 5} more")
        print()

    # Output JSON for programmatic use
    if "--json" in sys.argv:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
