from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from quantagent.quant_data_sample import (
    QuantDataSampleSpec,
    _extract_7z_csv_rows,
    _find_tick_7z,
    _normalize_tick_time_value,
    _prefix_tick_time_with_date,
    sample_local_quant_data,
)
from quantagent.quant_execution_replay import (
    BLOCK,
    PASS,
    WARN,
    CapacityEvidence,
    SlippageEvidence,
    TickTrade,
    _load_capacity,
    _load_slippage,
    _load_ticks,
    _replay_fills,
)
from quantagent.broker_gateway import BrokerFill


class TickExtractionTest(unittest.TestCase):
    """Test tick data extraction from compressed archives."""

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako tick validation ")

    def test_extracts_tick_from_7z_archive(self) -> None:
        """Test extracting tick data from 7z compressed file."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick_root = project / "逐笔成交"
            tick_root.mkdir()

            # Create a mock 7z file using bsdtar (if available)
            csv_content = "Time,Code,Price,Volume\n09:30:00,000001,10.50,1000\n09:31:00,000001,10.51,1500\n"
            csv_file = project / "000001.csv"
            csv_file.write_text(csv_content, encoding="utf-8")

            archive_path = tick_root / "2026-05-27.7z"
            try:
                subprocess.run(
                    ["bsdtar", "-a", "-cf", str(archive_path), "-C", str(project), "000001.csv"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self.skipTest("bsdtar not available or failed")

            # Test finding the 7z file
            found = _find_tick_7z(tick_root, "2026-05-27")
            self.assertIsNotNone(found)
            self.assertEqual(found, archive_path)

            # Test extracting rows
            rows, columns, warning = _extract_7z_csv_rows(archive_path, "000001.csv", max_rows=100)
            self.assertEqual(len(rows), 2)
            self.assertIn("Time", columns)
            self.assertIn("Price", columns)
            self.assertEqual(warning, "")

    def test_samples_tick_trade_with_date_prefix(self) -> None:
        """Test tick trade sampling with automatic date prefixing."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick_root = project / "逐笔成交"
            tick_root.mkdir()

            csv_content = "Time,Code,Price,Volume\n09:30:00,000001,10.50,1000\n09:31:00,000001,10.51,1500\n"
            csv_file = project / "000001.csv"
            csv_file.write_text(csv_content, encoding="utf-8")

            archive_path = tick_root / "2026-05-27.7z"
            try:
                subprocess.run(
                    ["bsdtar", "-a", "-cf", str(archive_path), "-C", str(project), "000001.csv"],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self.skipTest("bsdtar not available")

            result = sample_local_quant_data(
                project,
                QuantDataSampleSpec(
                    root=str(tick_root),
                    code="000001",
                    kind="tick_trade",
                    date="2026-05-27",
                    max_rows=100,
                ),
            )

            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(result.rows_written, 2)
            self.assertEqual(result.expectation_kind, "tick_trade_csv")

            # Verify date was prefixed
            output = Path(result.output_path).read_text(encoding="utf-8")
            self.assertIn("2026-05-27 09:30:00", output)
            self.assertIn("2026-05-27 09:31:00", output)

    def test_normalizes_tick_time_formats(self) -> None:
        """Test normalization of various tick time formats."""
        self.assertEqual(_normalize_tick_time_value("093000"), "09:30:00")
        self.assertEqual(_normalize_tick_time_value("093000.500"), "09:30:00.500")
        self.assertEqual(_normalize_tick_time_value("09:30:00"), "09:30:00")
        self.assertEqual(_normalize_tick_time_value("09:30:00.123"), "09:30:00.123")

    def test_prefix_tick_time_with_date(self) -> None:
        """Test prefixing time-only values with date."""
        rows = [
            {"Time": "09:30:00", "Price": "10.50"},
            {"Time": "093100", "Price": "10.51"},
            {"Time": "2026-05-27 09:32:00", "Price": "10.52"},  # Already has date
        ]

        result = _prefix_tick_time_with_date(rows, ["Time", "Price"], "2026-05-27")

        self.assertEqual(result[0]["Time"], "2026-05-27 09:30:00")
        self.assertEqual(result[1]["Time"], "2026-05-27 09:31:00")
        self.assertEqual(result[2]["Time"], "2026-05-27 09:32:00")  # Unchanged


class PriceValidationTest(unittest.TestCase):
    """Test price validation and slippage calculation."""

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako price validation ")

    def test_loads_tick_data_with_valid_prices(self) -> None:
        """Test loading tick data with valid price values."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick_file = project / "tick.csv"
            tick_file.write_text(
                "time,code,price,volume\n"
                "09:30:00,000001,10.50,1000\n"
                "09:31:00,000001,10.51,1500\n"
                "09:32:00,000001,10.49,2000\n",
                encoding="utf-8",
            )

            ticks, issues = _load_ticks(project, str(tick_file))

            self.assertEqual(len(ticks), 3)
            self.assertEqual(len(issues), 0)
            self.assertEqual(ticks[0].price, 10.50)
            self.assertEqual(ticks[1].price, 10.51)
            self.assertEqual(ticks[2].price, 10.49)

    def test_blocks_invalid_tick_prices(self) -> None:
        """Test blocking of invalid tick prices (zero, negative, missing)."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick_file = project / "tick.csv"
            tick_file.write_text(
                "time,code,price,volume\n"
                "09:30:00,000001,10.50,1000\n"
                "09:31:00,000001,0,1500\n"  # Zero price
                "09:32:00,000001,-10.49,2000\n"  # Negative price
                "09:33:00,000001,,1000\n",  # Missing price
                encoding="utf-8",
            )

            ticks, issues = _load_ticks(project, str(tick_file))

            self.assertEqual(len(ticks), 1)  # Only first row is valid
            self.assertEqual(len(issues), 3)  # Three invalid rows
            self.assertTrue(all(issue.level == BLOCK for issue in issues))
            self.assertTrue(all(issue.code == "invalid_tick_row" for issue in issues))

    def test_loads_slippage_evidence(self) -> None:
        """Test loading slippage evidence from CSV."""
        with self.make_project() as tmp:
            project = Path(tmp)
            slippage_file = project / "slippage.csv"
            slippage_file.write_text(
                "code,slippage_bps\n"
                "000001,5.0\n"
                "000002,10.0\n"
                "600000,3.5\n",
                encoding="utf-8",
            )

            slippage, issues = _load_slippage(project, str(slippage_file))

            self.assertEqual(len(slippage), 3)
            self.assertEqual(len(issues), 0)
            self.assertEqual(slippage["000001"].slippage_bps, 5.0)
            self.assertEqual(slippage["000002"].slippage_bps, 10.0)
            self.assertEqual(slippage["600000"].slippage_bps, 3.5)

    def test_blocks_invalid_slippage_values(self) -> None:
        """Test blocking of invalid slippage values."""
        with self.make_project() as tmp:
            project = Path(tmp)
            slippage_file = project / "slippage.csv"
            slippage_file.write_text(
                "code,slippage_bps\n"
                "000001,5.0\n"
                "000002,-10.0\n"  # Negative slippage
                ",3.5\n"  # Missing code
                "000003,\n",  # Missing slippage
                encoding="utf-8",
            )

            slippage, issues = _load_slippage(project, str(slippage_file))

            self.assertEqual(len(slippage), 1)  # Only first row is valid
            self.assertEqual(len(issues), 3)
            self.assertTrue(all(issue.level == BLOCK for issue in issues))


class SlippageCalculationTest(unittest.TestCase):
    """Test slippage calculation in different scenarios."""

    def test_calculates_slippage_within_tolerance(self) -> None:
        """Test fill replay with slippage within allowed tolerance."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=1000, source_row=1),
            TickTrade(code="000001", time="09:31:00", price=10.01, volume=1500, source_row=2),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.005,  # 5 bps slippage
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {"000001": SlippageEvidence(code="000001", slippage_bps=10.0, source_row=1)}
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].ok)
        self.assertLess(checks[0].price_delta_bps, 10.0)
        self.assertEqual(len(issues), 0)

    def test_blocks_slippage_exceeding_tolerance(self) -> None:
        """Test blocking when slippage exceeds allowed tolerance."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=1000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.20,  # 200 bps slippage
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {"000001": SlippageEvidence(code="000001", slippage_bps=10.0, source_row=1)}
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0].ok)
        self.assertGreater(checks[0].price_delta_bps, 10.0)
        self.assertTrue(any(issue.code == "fill_price_exceeds_slippage" for issue in issues))
        self.assertTrue(any(issue.level == BLOCK for issue in issues))

    def test_uses_default_slippage_when_not_specified(self) -> None:
        """Test using default slippage when code-specific slippage not provided."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=1000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.008,  # 8 bps slippage
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}  # No code-specific slippage
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].ok)
        self.assertEqual(checks[0].allowed_slippage_bps, 10.0)  # Used default


class CapacityValidationTest(unittest.TestCase):
    """Test capacity validation for sufficient and insufficient scenarios."""

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako capacity validation ")

    def test_loads_capacity_evidence(self) -> None:
        """Test loading capacity evidence from CSV."""
        with self.make_project() as tmp:
            project = Path(tmp)
            capacity_file = project / "capacity.csv"
            capacity_file.write_text(
                "code,capacity\n"
                "000001,100000\n"
                "000002,200000\n"
                "600000,150000\n",
                encoding="utf-8",
            )

            capacity, issues = _load_capacity(project, str(capacity_file))

            self.assertEqual(len(capacity), 3)
            self.assertEqual(len(issues), 0)
            self.assertEqual(capacity["000001"].capacity, 100000)
            self.assertEqual(capacity["000002"].capacity, 200000)
            self.assertEqual(capacity["600000"].capacity, 150000)

    def test_validates_fill_within_capacity(self) -> None:
        """Test fill validation when notional is within capacity."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=10000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.00,
                quantity=5000,  # Notional = 50,000
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {"000001": CapacityEvidence(code="000001", capacity=100000, source_row=1)}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].ok)
        self.assertEqual(checks[0].capacity, 100000)
        self.assertEqual(len(issues), 0)

    def test_blocks_fill_exceeding_capacity(self) -> None:
        """Test blocking when fill notional exceeds capacity."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=10000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.00,
                quantity=15000,  # Notional = 150,000 > capacity
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {"000001": CapacityEvidence(code="000001", capacity=100000, source_row=1)}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0].ok)
        self.assertTrue(any(issue.code == "fill_notional_exceeds_capacity" for issue in issues))
        self.assertTrue(any(issue.level == BLOCK for issue in issues))

    def test_skips_capacity_check_when_not_provided(self) -> None:
        """Test that capacity check is skipped when capacity is not provided."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=10000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.00,
                quantity=15000,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {}  # No capacity evidence

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].ok)  # Should pass without capacity check
        self.assertEqual(checks[0].capacity, 0.0)


class CompletenessCheckTest(unittest.TestCase):
    """Test completeness checks for missing or anomalous data."""

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako completeness check ")

    def test_blocks_fill_without_matching_tick(self) -> None:
        """Test blocking when fill has no matching tick data."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=1000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000002",  # Different code, no tick match
                time="09:30:30",
                price=20.00,
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 0)  # No check created
        self.assertTrue(any(issue.code == "fill_has_no_tick_match" for issue in issues))
        self.assertTrue(any(issue.level == BLOCK for issue in issues))

    def test_blocks_fill_outside_time_window(self) -> None:
        """Test blocking when fill is outside the time window of nearest tick."""
        ticks = [
            TickTrade(code="000001", time="09:30:00", price=10.00, volume=1000, source_row=1),
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:35:00",  # 5 minutes = 300 seconds away
                price=10.00,
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0].ok)
        self.assertGreater(checks[0].time_delta_seconds, 60)
        self.assertTrue(any(issue.code == "fill_outside_tick_window" for issue in issues))

    def test_warns_when_tick_has_no_code_column(self) -> None:
        """Test warning when tick data has no code column."""
        ticks = [
            TickTrade(code="", time="09:30:00", price=10.00, volume=1000, source_row=1),  # No code
        ]
        fills = [
            BrokerFill(
                code="000001",
                time="09:30:30",
                price=10.00,
                quantity=500,
                side="buy",
                order_id="ord1",
                source_row=1,
            ),
        ]
        slippage = {}
        capacity = {}

        checks, issues = _replay_fills(fills, ticks, slippage, capacity, window_seconds=60, default_slippage_bps=10.0)

        self.assertTrue(any(issue.code == "weak_tick_replay_no_code" for issue in issues))
        self.assertTrue(any(issue.level == WARN for issue in issues))

    def test_blocks_invalid_capacity_values(self) -> None:
        """Test blocking of invalid capacity values."""
        with self.make_project() as tmp:
            project = Path(tmp)
            capacity_file = project / "capacity.csv"
            capacity_file.write_text(
                "code,capacity\n"
                "000001,100000\n"
                "000002,-50000\n"  # Negative capacity
                ",100000\n"  # Missing code
                "000003,\n",  # Missing capacity
                encoding="utf-8",
            )

            capacity, issues = _load_capacity(project, str(capacity_file))

            self.assertEqual(len(capacity), 1)  # Only first row is valid
            self.assertEqual(len(issues), 3)
            self.assertTrue(all(issue.level == BLOCK for issue in issues))
            self.assertTrue(all(issue.code == "invalid_capacity_row" for issue in issues))


if __name__ == "__main__":
    unittest.main()
