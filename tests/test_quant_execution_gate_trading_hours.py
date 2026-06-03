from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.quant_execution_gate import (
    QuantExecutionEvidenceSpec,
    run_quant_execution_gate,
)


class QuantExecutionGateTradingHoursTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant gate ")

    def test_stock_trading_hours_09_30_to_15_00(self) -> None:
        """Stock trading hours should be 09:30-15:00."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "09:30:00,10.0,1000\n"
                "10:00:00,10.1,1100\n"
                "14:59:00,10.2,1200\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should not have trading hours warning for stock hours
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)

    def test_stock_trading_hours_warns_outside_09_30_to_15_00(self) -> None:
        """Stock data outside 09:30-15:00 should trigger warning."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "09:25:00,10.0,1000\n"  # Before market open
                "09:35:00,10.1,1100\n"
                "14:55:00,10.2,1200\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should have warning for out-of-hours data
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 1)
            self.assertIn("09:30-15:00", time_issues[0].message)
            self.assertIn("detected: stock", time_issues[0].message)

    def test_futures_day_trading_hours_09_00_to_15_15(self) -> None:
        """Futures day trading hours should be 09:00-15:15."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "09:00:00,3000.0,10\n"  # Futures start earlier
                "09:15:00,3001.0,11\n"
                "14:59:00,3002.0,12\n"
                "15:10:00,3003.0,13\n",  # Futures end later
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should auto-detect futures_day and not warn
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)

    def test_futures_night_trading_hours_21_00_to_23_00(self) -> None:
        """Futures night trading hours should be 21:00-23:00."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "21:00:00,3000.0,10\n"
                "21:30:00,3001.0,11\n"
                "22:00:00,3002.0,12\n"
                "22:59:00,3003.0,13\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should auto-detect futures_night and not warn
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)

    def test_futures_night_trading_hours_00_00_to_02_30(self) -> None:
        """Futures night trading hours should include 00:00-02:30."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "00:00:00,3000.0,10\n"
                "00:30:00,3001.0,11\n"
                "01:00:00,3002.0,12\n"
                "02:29:00,3003.0,13\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should auto-detect futures_night and not warn
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)

    def test_futures_night_auto_detection_with_mixed_data(self) -> None:
        """Mixed day and night data should auto-detect as futures_night."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            # 33% night data should trigger futures_night detection
            tick.write_text(
                "time,price,volume\n"
                "09:30:00,3000.0,10\n"
                "10:00:00,3001.0,11\n"
                "21:00:00,3004.0,14\n"  # Night session
                "22:00:00,3005.0,15\n"  # Night session
                "01:00:00,3006.0,16\n"  # Night session
                "02:00:00,3007.0,17\n",  # Night session
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should auto-detect futures_night and not warn
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)

    def test_futures_night_warns_outside_valid_hours(self) -> None:
        """Futures night data outside 21:00-23:00 and 00:00-02:30 should warn."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "time,price,volume\n"
                "21:00:00,3000.0,10\n"
                "22:00:00,3001.0,11\n"
                "03:00:00,3002.0,12\n"  # Outside night hours
                "20:00:00,3003.0,13\n",  # Outside night hours
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should warn about out-of-hours data
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 1)
            self.assertIn("futures_night", time_issues[0].message)
            self.assertIn("21:00-23:00/00:00-02:30", time_issues[0].message)

    def test_fill_evidence_also_checks_trading_hours(self) -> None:
        """Fill evidence should also check trading hours."""
        with self.make_project() as tmp:
            project = Path(tmp)
            fill = project / "fill.csv"
            # 1 out of 4 timestamps out of hours (25%) - should stay as stock and warn
            fill.write_text(
                "time,code,price,qty\n"
                "09:25:00,000001,10.0,100\n"  # Before market open
                "09:31:00,000001,10.1,200\n"
                "10:00:00,000001,10.2,300\n"
                "14:00:00,000001,10.3,400\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    fill_path=str(fill),
                    execution_source="test",
                ),
                required_evidence=("fill",),
            )

            # Should have warning for out-of-hours fill data
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 1)
            self.assertEqual(time_issues[0].evidence_type, "fill")

    def test_datetime_format_with_date_prefix(self) -> None:
        """Should handle datetime format with date prefix."""
        with self.make_project() as tmp:
            project = Path(tmp)
            tick = project / "tick.csv"
            tick.write_text(
                "datetime,price,volume\n"
                "2026-05-27 21:00:00,3000.0,10\n"
                "2026-05-27 22:00:00,3001.0,11\n",
                encoding="utf-8",
            )

            result = run_quant_execution_gate(
                project,
                QuantExecutionEvidenceSpec(
                    tick_path=str(tick),
                    execution_source="test",
                ),
                required_evidence=("tick",),
            )

            # Should auto-detect futures_night and not warn
            time_issues = [i for i in result.issues if i.code == "time_outside_trading_hours"]
            self.assertEqual(len(time_issues), 0)


if __name__ == "__main__":
    unittest.main()
