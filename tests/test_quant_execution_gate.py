import csv
import tempfile
import unittest
from pathlib import Path

from quantagent.quant_execution_gate import (
    QuantExecutionEvidenceSpec,
    run_quant_execution_gate,
)


class TestQuantExecutionGateCapacityBoundaries(unittest.TestCase):
    """Test capacity evidence boundary conditions."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_path = Path(self.temp_dir)

    def _create_capacity_csv(self, filename: str, rows: int, notional_per_row: float = 10000.0) -> Path:
        """Helper to create capacity CSV with specified rows and notional values."""
        path = self.project_path / filename
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["capacity", "symbol", "date"])
            for i in range(rows):
                writer.writerow([notional_per_row, f"SYM{i:04d}", "2024-01-01"])
        return path

    def _create_minimal_evidence_files(self) -> dict:
        """Create minimal required evidence files for gate to pass."""
        tick_path = self.project_path / "tick.csv"
        with tick_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "price", "volume"])
            writer.writerow(["09:30:00", "100.0", "1000"])

        fill_path = self.project_path / "fill.csv"
        with fill_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "code", "price", "qty"])
            writer.writerow(["09:30:00", "SYM0001", "100.0", "100"])

        broker_path = self.project_path / "broker.csv"
        with broker_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["broker", "account"])
            writer.writerow(["test_broker", "test_account"])

        slippage_path = self.project_path / "slippage.csv"
        with slippage_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["slippage"])
            writer.writerow(["0.0001"])

        return {
            "tick_path": str(tick_path),
            "fill_path": str(fill_path),
            "broker_path": str(broker_path),
            "slippage_path": str(slippage_path),
        }

    def test_capacity_exactly_100_rows_should_pass(self):
        """Test capacity file with exactly 100 rows - should pass without warning."""
        evidence = self._create_minimal_evidence_files()
        capacity_path = self._create_capacity_csv("capacity_100.csv", rows=100, notional_per_row=10000.0)
        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should not have capacity_insufficient_sample_size warning
        capacity_sample_issues = [
            issue for issue in result.issues
            if issue.code == "capacity_insufficient_sample_size"
        ]
        self.assertEqual(len(capacity_sample_issues), 0, "Should not warn for exactly 100 rows")

    def test_capacity_99_rows_should_warn(self):
        """Test capacity file with 99 rows - should trigger WARN."""
        evidence = self._create_minimal_evidence_files()
        capacity_path = self._create_capacity_csv("capacity_99.csv", rows=99, notional_per_row=10000.0)
        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have capacity_insufficient_sample_size warning
        capacity_sample_issues = [
            issue for issue in result.issues
            if issue.code == "capacity_insufficient_sample_size"
        ]
        self.assertEqual(len(capacity_sample_issues), 1, "Should warn for 99 rows")
        self.assertEqual(capacity_sample_issues[0].level, "warn")
        self.assertIn("99 rows", capacity_sample_issues[0].message)

    def test_capacity_exactly_1000000_notional_should_pass(self):
        """Test capacity file with exactly 1,000,000 total notional - should pass without warning."""
        evidence = self._create_minimal_evidence_files()
        # 100 rows * 10,000 = 1,000,000
        capacity_path = self._create_capacity_csv("capacity_1m.csv", rows=100, notional_per_row=10000.0)
        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should not have capacity_insufficient_notional warning
        capacity_notional_issues = [
            issue for issue in result.issues
            if issue.code == "capacity_insufficient_notional"
        ]
        self.assertEqual(len(capacity_notional_issues), 0, "Should not warn for exactly 1,000,000 notional")

    def test_capacity_999999_notional_should_warn(self):
        """Test capacity file with 999,999 total notional - should trigger WARN."""
        evidence = self._create_minimal_evidence_files()
        # 100 rows * 9,999.99 = 999,999
        capacity_path = self._create_capacity_csv("capacity_999999.csv", rows=100, notional_per_row=9999.99)
        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have capacity_insufficient_notional warning
        capacity_notional_issues = [
            issue for issue in result.issues
            if issue.code == "capacity_insufficient_notional"
        ]
        self.assertEqual(len(capacity_notional_issues), 1, "Should warn for 999,999 notional")
        self.assertEqual(capacity_notional_issues[0].level, "warn")
        self.assertIn("999999", capacity_notional_issues[0].message)

    def test_capacity_empty_file_should_error(self):
        """Test empty capacity file - should trigger ERROR."""
        evidence = self._create_minimal_evidence_files()
        capacity_path = self.project_path / "capacity_empty.csv"
        capacity_path.touch()  # Create empty file
        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have empty_file error
        empty_file_issues = [
            issue for issue in result.issues
            if issue.code == "empty_file" and issue.evidence_type == "capacity"
        ]
        self.assertEqual(len(empty_file_issues), 1, "Should error for empty file")
        self.assertEqual(empty_file_issues[0].level, "block")

    def test_capacity_missing_column_should_warn(self):
        """Test capacity file missing capacity column - should trigger WARN."""
        evidence = self._create_minimal_evidence_files()
        capacity_path = self.project_path / "capacity_no_col.csv"

        # Create CSV without capacity column
        with capacity_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol", "date"])  # Missing capacity column
            for i in range(100):
                writer.writerow([f"SYM{i:04d}", "2024-01-01"])

        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have missing_required_column_group error
        missing_col_issues = [
            issue for issue in result.issues
            if issue.code == "missing_required_column_group" and issue.evidence_type == "capacity"
        ]
        self.assertEqual(len(missing_col_issues), 1, "Should error for missing capacity column")
        self.assertEqual(missing_col_issues[0].level, "block")
        self.assertIn("capacity", missing_col_issues[0].message)

    def test_capacity_header_only_should_error(self):
        """Test capacity file with header but no data rows - should trigger ERROR."""
        evidence = self._create_minimal_evidence_files()
        capacity_path = self.project_path / "capacity_header_only.csv"

        with capacity_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["capacity", "symbol", "date"])
            # No data rows

        evidence["capacity_path"] = str(capacity_path)

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have empty_csv_rows error
        empty_rows_issues = [
            issue for issue in result.issues
            if issue.code == "empty_csv_rows" and issue.evidence_type == "capacity"
        ]
        self.assertEqual(len(empty_rows_issues), 1, "Should error for no data rows")
        self.assertEqual(empty_rows_issues[0].level, "block")


class TestQuantExecutionGateTradingHoursBoundaries(unittest.TestCase):
    """Test trading hours boundary conditions for tick/fill evidence."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_path = Path(self.temp_dir)

    def _create_tick_csv(self, filename: str, timestamps: list[str]) -> Path:
        """Helper to create tick CSV with specified timestamps."""
        path = self.project_path / filename
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "price", "volume"])
            for ts in timestamps:
                writer.writerow([ts, "100.0", "1000"])
        return path

    def _create_fill_csv(self, filename: str, timestamps: list[str]) -> Path:
        """Helper to create fill CSV with specified timestamps."""
        path = self.project_path / filename
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "code", "price", "qty"])
            for ts in timestamps:
                writer.writerow([ts, "SYM0001", "100.0", "100"])
        return path

    def _create_minimal_evidence_files(self, tick_path: str = None, fill_path: str = None) -> dict:
        """Create minimal required evidence files for gate to pass."""
        if not tick_path:
            tick_file = self.project_path / "tick.csv"
            with tick_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time", "price", "volume"])
                writer.writerow(["09:30:00", "100.0", "1000"])
            tick_path = str(tick_file)

        if not fill_path:
            fill_file = self.project_path / "fill.csv"
            with fill_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time", "code", "price", "qty"])
                writer.writerow(["09:30:00", "SYM0001", "100.0", "100"])
            fill_path = str(fill_file)

        broker_path = self.project_path / "broker.csv"
        with broker_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["broker", "account"])
            writer.writerow(["test_broker", "test_account"])

        slippage_path = self.project_path / "slippage.csv"
        with slippage_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["slippage"])
            writer.writerow(["0.0001"])

        capacity_path = self.project_path / "capacity.csv"
        with capacity_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["capacity"])
            writer.writerow(["1000000"])

        return {
            "tick_path": tick_path,
            "fill_path": fill_path,
            "broker_path": str(broker_path),
            "slippage_path": str(slippage_path),
            "capacity_path": str(capacity_path),
        }

    def test_tick_09_29_59_should_warn(self):
        """Test tick at 09:29:59 - should trigger WARN (before market open)."""
        # Mix with valid stock hours to prevent futures classification
        timestamps = ["09:29:59"] * 2 + ["10:00:00"] * 8
        tick_path = self._create_tick_csv("tick_092959.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for 09:29:59")
        self.assertEqual(time_issues[0].level, "warn")
        self.assertIn("2/10", time_issues[0].message)
        self.assertIn("trading hours", time_issues[0].message)

    def test_tick_09_30_00_should_pass(self):
        """Test tick at 09:30:00 - should pass (market open)."""
        # Use multiple rows to ensure detection
        tick_path = self._create_tick_csv("tick_093000.csv", ["09:30:00"] * 10)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should NOT have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 0, "Should not warn for 09:30:00")

    def test_tick_15_00_00_should_pass(self):
        """Test tick at 15:00:00 - should pass (last valid second)."""
        # Use multiple rows to ensure detection
        tick_path = self._create_tick_csv("tick_150000.csv", ["15:00:00"] * 10)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should NOT have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 0, "Should not warn for 15:00:00")

    def test_tick_15_00_01_should_warn(self):
        """Test tick at 15:00:01 - should trigger WARN (after market close)."""
        # Mix with valid stock hours to prevent futures classification
        timestamps = ["15:00:01"] * 2 + ["10:00:00"] * 8
        tick_path = self._create_tick_csv("tick_150001.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for 15:00:01")
        self.assertEqual(time_issues[0].level, "warn")
        self.assertIn("2/10", time_issues[0].message)
        self.assertIn("trading hours", time_issues[0].message)

    def test_tick_mixed_50_percent_out_of_hours(self):
        """Test tick with 50% in-hours, 50% out-hours - should trigger WARN."""
        timestamps = [
            "09:30:00",  # in-hours
            "09:29:59",  # out-hours
            "14:59:59",  # in-hours
            "15:00:01",  # out-hours
        ]
        tick_path = self._create_tick_csv("tick_mixed.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for mixed hours")
        self.assertEqual(time_issues[0].level, "warn")
        self.assertIn("2/4", time_issues[0].message)
        self.assertIn("50.0%", time_issues[0].message)

    def test_fill_09_29_59_should_warn(self):
        """Test fill at 09:29:59 - should trigger WARN (before market open)."""
        # Mix with valid stock hours to prevent futures classification
        timestamps = ["09:29:59"] * 2 + ["10:00:00"] * 8
        fill_path = self._create_fill_csv("fill_092959.csv", timestamps)
        evidence = self._create_minimal_evidence_files(fill_path=str(fill_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "fill"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for fill at 09:29:59")
        self.assertEqual(time_issues[0].level, "warn")
        self.assertIn("2/10", time_issues[0].message)

    def test_fill_15_00_01_should_warn(self):
        """Test fill at 15:00:01 - should trigger WARN (after market close)."""
        # Mix with valid stock hours to prevent futures classification
        timestamps = ["15:00:01"] * 2 + ["10:00:00"] * 8
        fill_path = self._create_fill_csv("fill_150001.csv", timestamps)
        evidence = self._create_minimal_evidence_files(fill_path=str(fill_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "fill"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for fill at 15:00:01")
        self.assertEqual(time_issues[0].level, "warn")
        self.assertIn("2/10", time_issues[0].message)

    def test_tick_with_date_prefix_should_parse_correctly(self):
        """Test tick with full datetime format - should parse time correctly."""
        timestamps = [
            "2024-01-15 09:29:59",  # out-hours
            "2024-01-15 09:30:00",  # in-hours
            "2024-01-15 15:00:00",  # in-hours
            "2024-01-15 15:00:01",  # out-hours
        ]
        tick_path = self._create_tick_csv("tick_datetime.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for datetime format")
        self.assertIn("2/4", time_issues[0].message)
        self.assertIn("50.0%", time_issues[0].message)

    def test_tick_night_session_21_00_00_should_pass(self):
        """Test tick at 21:00:00 - should pass (night session start)."""
        timestamps = ["21:00:00"] * 10  # Need multiple to trigger night session detection
        tick_path = self._create_tick_csv("tick_210000.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should NOT have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 0, "Should not warn for 21:00:00 in night session")

    def test_tick_night_session_20_59_59_should_warn(self):
        """Test tick at 20:59:59 - should trigger WARN (before night session)."""
        timestamps = ["21:00:00"] * 9 + ["20:59:59"]  # Mix to trigger night session detection
        tick_path = self._create_tick_csv("tick_205959.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for 20:59:59")
        self.assertEqual(time_issues[0].level, "warn")

    def test_tick_night_session_23_00_00_should_warn(self):
        """Test tick at 23:00:00 - should trigger WARN (after night session end)."""
        timestamps = ["21:00:00"] * 9 + ["23:00:00"]  # Mix to trigger night session detection
        tick_path = self._create_tick_csv("tick_230000.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 1, "Should warn for 23:00:00")
        self.assertEqual(time_issues[0].level, "warn")

    def test_tick_night_session_22_59_59_should_pass(self):
        """Test tick at 22:59:59 - should pass (last valid second of night session)."""
        timestamps = ["21:00:00"] * 9 + ["22:59:59"]  # Mix to trigger night session detection
        tick_path = self._create_tick_csv("tick_225959.csv", timestamps)
        evidence = self._create_minimal_evidence_files(tick_path=str(tick_path))

        spec = QuantExecutionEvidenceSpec(
            execution_source="test_source",
            **evidence,
        )

        result = run_quant_execution_gate(self.project_path, spec)

        # Should NOT have time_outside_trading_hours warning
        time_issues = [
            issue for issue in result.issues
            if issue.code == "time_outside_trading_hours" and issue.evidence_type == "tick"
        ]
        self.assertEqual(len(time_issues), 0, "Should not warn for 22:59:59 in night session")


if __name__ == "__main__":
    unittest.main()
