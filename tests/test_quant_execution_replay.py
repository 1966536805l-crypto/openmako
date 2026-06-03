from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.quant_execution_gate import QuantExecutionEvidenceSpec, run_quant_execution_gate


class QuantExecutionReplayTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant execution replay ")

    def write_execution_replay_files(self, project: Path, *, tick_price: float = 10.10, fill_price: float = 10.10) -> dict[str, Path]:
        files = {
            "tick": project / "tick.csv",
            "fill": project / "fill.csv",
            "broker": project / "broker.csv",
            "order": project / "order.csv",
            "position": project / "position.csv",
            "account": project / "account.csv",
            "slippage": project / "slippage.csv",
            "capacity": project / "capacity.csv",
        }
        files["tick"].write_text(f"time,code,price,volume\n09:31:00,000001,{tick_price},1000\n", encoding="utf-8")
        files["fill"].write_text(f"time,code,price,qty,order_id,side\n09:31:00,000001,{fill_price},500,ord1,buy\n", encoding="utf-8")
        files["broker"].write_text("broker,account\nlocal_broker,acct1\n", encoding="utf-8")
        files["order"].write_text("time,code,order_id,price,qty,traded,status\n09:30:59,000001,ord1,10.10,500,500,filled\n", encoding="utf-8")
        files["position"].write_text("code,quantity\n000001,500\n", encoding="utf-8")
        files["account"].write_text("broker,account,balance,available\nlocal_broker,acct1,100000,94950\n", encoding="utf-8")
        files["slippage"].write_text("code,slippage_bps\n000001,5\n", encoding="utf-8")
        files["capacity"].write_text("code,capacity\n000001,100000\n", encoding="utf-8")
        return files

    def run_gate(self, project: Path, files: dict[str, Path]):
        return run_quant_execution_gate(
            project,
            QuantExecutionEvidenceSpec(
                tick_path=str(files["tick"]),
                fill_path=str(files["fill"]),
                broker_path=str(files["broker"]),
                order_path=str(files["order"]),
                position_path=str(files["position"]),
                account_path=str(files["account"]),
                slippage_path=str(files["slippage"]),
                capacity_path=str(files["capacity"]),
                execution_source="broker export",
            ),
        )

    def test_execution_gate_explains_fill_order_and_position(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_replay_files(project)

            result = self.run_gate(project, files)

            self.assertTrue(result.live_ready)
            self.assertTrue(result.execution_replay["ok"])
            self.assertEqual(result.execution_replay["fills_checked"], 1)
            self.assertEqual(result.execution_replay["fills_explained"], 1)
            self.assertTrue(result.execution_replay["order_lifecycle_ok"])
            self.assertTrue(result.execution_replay["broker_reconciliation_ok"])

    def test_execution_gate_blocks_unexplained_fill_price(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_replay_files(project, tick_price=10.0, fill_price=10.5)

            result = self.run_gate(project, files)

            self.assertFalse(result.live_ready)
            self.assertFalse(result.execution_replay["ok"])
            self.assertTrue(any(issue.code == "execution_replay_fill_price_exceeds_slippage" for issue in result.issues))

    def test_capacity_insufficient_sample_size_warns(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_replay_files(project)

            # Write capacity file with only 50 rows (< 100 threshold)
            capacity_lines = ["code,capacity\n"]
            for i in range(50):
                capacity_lines.append(f"00000{i % 10},50000\n")
            files["capacity"].write_text("".join(capacity_lines), encoding="utf-8")

            result = self.run_gate(project, files)

            # Should still be live_ready (WARN not BLOCK), but should have warning
            self.assertTrue(result.live_ready)
            capacity_issues = [issue for issue in result.issues if issue.evidence_type == "capacity"]
            self.assertTrue(any(issue.code == "capacity_insufficient_sample_size" for issue in capacity_issues))
            self.assertTrue(any(issue.level == "warn" for issue in capacity_issues))

    def test_capacity_insufficient_notional_warns(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_replay_files(project)

            # Write capacity file with sufficient rows but low total notional (< 1,000,000)
            # Use 6000 per row to avoid blocking the fill (fill notional is ~5050)
            capacity_lines = ["code,capacity\n"]
            for i in range(150):
                capacity_lines.append(f"00000{i % 10},6000\n")  # 150 * 6000 = 900,000 < 1,000,000
            files["capacity"].write_text("".join(capacity_lines), encoding="utf-8")

            result = self.run_gate(project, files)

            # Should still be live_ready (WARN not BLOCK), but should have warning
            self.assertTrue(result.live_ready)
            capacity_issues = [issue for issue in result.issues if issue.evidence_type == "capacity"]
            self.assertTrue(any(issue.code == "capacity_insufficient_notional" for issue in capacity_issues))
            self.assertTrue(any(issue.level == "warn" for issue in capacity_issues))

    def test_capacity_sufficient_sample_passes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            files = self.write_execution_replay_files(project)

            # Write capacity file with sufficient rows and notional
            capacity_lines = ["code,capacity\n"]
            for i in range(150):
                capacity_lines.append(f"00000{i % 10},10000\n")  # 150 * 10000 = 1,500,000 > 1,000,000
            files["capacity"].write_text("".join(capacity_lines), encoding="utf-8")

            result = self.run_gate(project, files)

            # Should be live_ready with no capacity warnings
            self.assertTrue(result.live_ready)
            capacity_issues = [issue for issue in result.issues if issue.evidence_type == "capacity"]
            self.assertFalse(any(issue.code == "capacity_insufficient_sample_size" for issue in capacity_issues))
            self.assertFalse(any(issue.code == "capacity_insufficient_notional" for issue in capacity_issues))


if __name__ == "__main__":
    unittest.main()
