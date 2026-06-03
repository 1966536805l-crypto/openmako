"""
Tests for tick_integrity_checker module.
"""

import csv
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from quantagent.tick_integrity_checker import (
    AbnormalJump,
    IntegrityReport,
    MissingTick,
    TimestampError,
    check_tick_integrity,
    detect_abnormal_jumps,
    detect_missing_ticks,
    detect_timestamp_errors,
)


class TestDetectMissingTicks(unittest.TestCase):
    """Test missing tick detection."""

    def test_no_missing_ticks(self):
        """Normal tick sequence with no gaps."""
        base_time = datetime(2024, 1, 15, 9, 30, 0)
        tick_data = [
            {"Time": (base_time + timedelta(seconds=i * 3)).strftime("%Y-%m-%d %H:%M:%S"), "Code": "600000"}
            for i in range(10)
        ]

        missing = detect_missing_ticks(tick_data, max_gap_seconds=60)
        self.assertEqual(len(missing), 0)

    def test_detect_large_gap(self):
        """Detect gap larger than threshold."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Code": "600000"},
            {"Time": "2024-01-15 09:30:10", "Code": "600000"},
            {"Time": "2024-01-15 09:32:00", "Code": "600000"},  # 110 second gap
        ]

        missing = detect_missing_ticks(tick_data, max_gap_seconds=60)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].code, "600000")
        self.assertEqual(missing[0].gap_start, "09:30:10")
        self.assertEqual(missing[0].gap_end, "09:32:00")
        self.assertEqual(missing[0].duration_seconds, 110)

    def test_empty_data(self):
        """Handle empty tick data."""
        missing = detect_missing_ticks([])
        self.assertEqual(len(missing), 0)

    def test_single_tick(self):
        """Handle single tick."""
        tick_data = [{"Time": "2024-01-15 09:30:00", "Code": "600000"}]
        missing = detect_missing_ticks(tick_data)
        self.assertEqual(len(missing), 0)


class TestDetectAbnormalJumps(unittest.TestCase):
    """Test abnormal price jump detection."""

    def test_no_abnormal_jumps(self):
        """Normal price movements."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Price": "10.00", "Code": "600000"},
            {"Time": "2024-01-15 09:30:03", "Price": "10.05", "Code": "600000"},
            {"Time": "2024-01-15 09:30:06", "Price": "10.02", "Code": "600000"},
        ]

        jumps = detect_abnormal_jumps(tick_data, max_change_pct=0.1)
        self.assertEqual(len(jumps), 0)

    def test_detect_large_jump(self):
        """Detect price jump > 10%."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Price": "10.00", "Code": "600000"},
            {"Time": "2024-01-15 09:30:03", "Price": "11.50", "Code": "600000"},  # 15% jump
        ]

        jumps = detect_abnormal_jumps(tick_data, max_change_pct=0.1)
        self.assertEqual(len(jumps), 1)
        self.assertEqual(jumps[0].code, "600000")
        self.assertAlmostEqual(jumps[0].price_before, 10.0)
        self.assertAlmostEqual(jumps[0].price_after, 11.5)
        self.assertAlmostEqual(jumps[0].change_pct, 0.15)

    def test_ignore_zero_price(self):
        """Ignore ticks with zero price."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Price": "0", "Code": "600000"},
            {"Time": "2024-01-15 09:30:03", "Price": "10.00", "Code": "600000"},
        ]

        jumps = detect_abnormal_jumps(tick_data)
        self.assertEqual(len(jumps), 0)

    def test_empty_data(self):
        """Handle empty tick data."""
        jumps = detect_abnormal_jumps([])
        self.assertEqual(len(jumps), 0)


class TestDetectTimestampErrors(unittest.TestCase):
    """Test timestamp error detection."""

    def test_monotonic_timestamps(self):
        """Normal monotonic timestamps."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Volume": "100", "Code": "600000"},
            {"Time": "2024-01-15 09:30:03", "Volume": "200", "Code": "600000"},
            {"Time": "2024-01-15 09:30:06", "Volume": "150", "Code": "600000"},
        ]

        errors, zero_volume = detect_timestamp_errors(tick_data)
        # Filter out trading hours errors for this test
        non_trading_errors = [e for e in errors if e.error_type != "out_of_trading_hours"]
        self.assertEqual(len(non_trading_errors), 0)
        self.assertEqual(zero_volume, 0)

    def test_non_monotonic_timestamps(self):
        """Detect non-monotonic timestamps."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Volume": "100", "Code": "600000"},
            {"Time": "2024-01-15 09:30:10", "Volume": "200", "Code": "600000"},
            {"Time": "2024-01-15 09:30:05", "Volume": "150", "Code": "600000"},  # Goes back
        ]

        errors, _ = detect_timestamp_errors(tick_data)
        non_monotonic = [e for e in errors if e.error_type == "non_monotonic"]
        self.assertGreater(len(non_monotonic), 0)

    def test_out_of_trading_hours(self):
        """Detect timestamps outside trading hours."""
        tick_data = [
            {"Time": "2024-01-15 08:00:00", "Volume": "100", "Code": "600000"},  # Before market open
            {"Time": "2024-01-15 09:30:00", "Volume": "200", "Code": "600000"},  # Valid
            {"Time": "2024-01-15 16:00:00", "Volume": "150", "Code": "600000"},  # After market close
        ]

        errors, _ = detect_timestamp_errors(tick_data)
        out_of_hours = [e for e in errors if e.error_type == "out_of_trading_hours"]
        self.assertEqual(len(out_of_hours), 2)

    def test_zero_volume_count(self):
        """Count zero volume ticks."""
        tick_data = [
            {"Time": "2024-01-15 09:30:00", "Volume": "100", "Code": "600000"},
            {"Time": "2024-01-15 09:30:03", "Volume": "0", "Code": "600000"},
            {"Time": "2024-01-15 09:30:06", "Volume": "0", "Code": "600000"},
            {"Time": "2024-01-15 09:30:09", "Volume": "200", "Code": "600000"},
        ]

        _, zero_volume = detect_timestamp_errors(tick_data)
        self.assertEqual(zero_volume, 2)

    def test_invalid_timestamp(self):
        """Detect invalid timestamp format."""
        tick_data = [
            {"Time": "invalid-time", "Volume": "100", "Code": "600000"},
            {"Time": "2024-01-15 09:30:00", "Volume": "200", "Code": "600000"},
        ]

        errors, _ = detect_timestamp_errors(tick_data)
        invalid = [e for e in errors if e.error_type == "invalid_timestamp"]
        self.assertEqual(len(invalid), 1)


class TestCheckTickIntegrity(unittest.TestCase):
    """Test complete integrity check."""

    def test_check_empty_directory(self):
        """Handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = check_tick_integrity(tmpdir)
            self.assertEqual(report.files_checked, 0)
            self.assertEqual(report.total_ticks, 0)

    def test_check_nonexistent_directory(self):
        """Handle nonexistent directory."""
        report = check_tick_integrity("/nonexistent/path")
        self.assertEqual(report.files_checked, 0)

    def test_check_valid_tick_file(self):
        """Check valid tick file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tick_file = Path(tmpdir) / "tick_trade_600000_20240115.csv"

            # Create sample tick data
            with open(tick_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["Time", "Price", "Volume"])
                writer.writeheader()
                base_time = datetime(2024, 1, 15, 9, 30, 0)
                for i in range(10):
                    writer.writerow({
                        "Time": (base_time + timedelta(seconds=i * 3)).strftime("%Y-%m-%d %H:%M:%S"),
                        "Price": f"{10.0 + i * 0.01:.2f}",
                        "Volume": "100"
                    })

            report = check_tick_integrity(tmpdir)
            self.assertEqual(report.files_checked, 1)
            self.assertEqual(report.total_ticks, 10)
            self.assertEqual(len(report.missing_ticks), 0)
            self.assertEqual(len(report.abnormal_jumps), 0)

    def test_check_file_with_issues(self):
        """Check file with multiple issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tick_file = Path(tmpdir) / "tick_600000_20240115.csv"

            # Create tick data with issues
            with open(tick_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["Time", "Price", "Volume"])
                writer.writeheader()
                writer.writerow({"Time": "2024-01-15 09:30:00", "Price": "10.00", "Volume": "100"})
                writer.writerow({"Time": "2024-01-15 09:32:00", "Price": "10.05", "Volume": "0"})  # Gap + zero volume
                writer.writerow({"Time": "2024-01-15 09:32:03", "Price": "12.00", "Volume": "100"})  # Price jump

            report = check_tick_integrity(tmpdir)
            self.assertEqual(report.files_checked, 1)
            self.assertGreater(len(report.missing_ticks), 0)
            self.assertGreater(len(report.abnormal_jumps), 0)
            self.assertGreater(report.zero_volume_count, 0)

    def test_report_to_dict(self):
        """Test report serialization."""
        report = IntegrityReport(
            files_checked=1,
            total_ticks=100,
            missing_ticks=(
                MissingTick("600000", "2024-01-15", "09:30:00", "09:32:00", 120),
            ),
            abnormal_jumps=(
                AbnormalJump("600000", "2024-01-15", "09:32:00", 10.0, 12.0, 0.2),
            ),
            timestamp_errors=(
                TimestampError("600000", "2024-01-15", "non_monotonic", "details"),
            ),
            zero_volume_count=5
        )

        report_dict = report.to_dict()
        self.assertEqual(report_dict["files_checked"], 1)
        self.assertEqual(report_dict["total_ticks"], 100)
        self.assertEqual(len(report_dict["missing_ticks"]), 1)
        self.assertEqual(len(report_dict["abnormal_jumps"]), 1)
        self.assertEqual(len(report_dict["timestamp_errors"]), 1)
        self.assertEqual(report_dict["zero_volume_count"], 5)


if __name__ == "__main__":
    unittest.main()
