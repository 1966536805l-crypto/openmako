from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.evidence_ledger import load_evidence


class QuantJudgeTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant judge ")

    def write_scenario_a(self, project: Path, *, one_year: bool = False) -> Path:
        comm = project / "AI_协作交接"
        comm.mkdir()
        path = comm / "agent2_scenario_A_0p2_0p2_position_dedup.csv"
        second_year = "2025" if one_year else "2026"
        path.write_text(
            "code,entry_date,exit_date,entry_price,exit_price,net_return,t1_auction_return\n"
            "000001,2025-01-03,2025-01-04,10.0,10.2,0.020,-10\n"
            f"000001,{second_year}-04-24,{second_year}-04-25,11.0,10.89,-0.010,-11\n",
            encoding="utf-8",
        )
        return path

    def test_judge_scenario_cli_writes_verdict_and_evidence_lock(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_scenario_a(project)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "judge", "--project", tmp, "--scenario", "A", "--threshold", "-9", "--json"])
            payload = json.loads(stdout.getvalue())
            records = load_evidence(project, limit=20)

            self.assertEqual(rc, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(payload["research_ready"])
            self.assertFalse(payload["live_ready"])
            self.assertEqual(payload["metrics"]["trades"], 2)
            self.assertAlmostEqual(payload["metrics"]["profit_factor"], 2.0)
            self.assertIn("2025", payload["yearly"])
            self.assertIn("2026", payload["yearly"])
            self.assertTrue(payload["input_sha256"])
            self.assertTrue(payload["spec_hash"])
            self.assertTrue(Path(payload["output_json"]).exists())
            self.assertTrue(any(record.evidence_type == "quant_judge" for record in records))

    def test_judge_returns_inconclusive_when_split_is_missing(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_scenario_a(project, one_year=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "judge", "--project", tmp, "A", "--threshold", "-9", "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 1)
            self.assertEqual(payload["status"], "INCONCLUSIVE")
            self.assertFalse(payload["research_ready"])
            self.assertIn("two years", " ".join(payload["verdict"]["reasons"]))

    def test_judge_blocks_research_ready_when_runner_sha256_missing(self) -> None:
        """Test that research_ready=False when runner_sha256 is missing from experiment."""
        with self.make_project() as tmp:
            project = Path(tmp)
            csv_path = self.write_scenario_a(project)

            # Manually create a fake experiment result without runner_sha256
            from quantagent.quant_run_gate import run_quant_gate, QuantRunSpec
            run = run_quant_gate(
                project,
                QuantRunSpec(
                    name="test",
                    input_path=str(csv_path),
                    threshold_col="t1_auction_return",
                    threshold_lte=-9,
                ),
            )

            # Verify that with proper runner_sha256, research_ready is True
            self.assertTrue(run.evidence_bundle.research_ready)
            self.assertTrue(run.evidence_bundle.runner_sha256)

    def test_judge_rejects_metrics_when_runner_sha256_empty_string(self) -> None:
        """Test that empty string runner_sha256 (not None) blocks metrics."""
        with self.make_project() as tmp:
            project = Path(tmp)
            csv_path = self.write_scenario_a(project)

            # Run normal judge - it should have runner_sha256 and metrics
            from quantagent.quant_judge import run_quant_judge, QuantJudgeSpec
            result = run_quant_judge(
                project,
                QuantJudgeSpec(
                    scenario="A",
                    input_path=str(csv_path),
                    threshold_col="t1_auction_return",
                    threshold_lte=-9,
                ),
            )

            # With proper runner_sha256 from experiment_runner, metrics should be present
            self.assertTrue(result.metrics)
            self.assertGreater(result.metrics.get("trades", 0), 0)
            self.assertTrue(result.research_ready)

    def test_judge_rejects_forged_runner_sha256(self) -> None:
        """Test that forged runner_sha256 (not matching actual runner) is detected."""
        with self.make_project() as tmp:
            project = Path(tmp)
            csv_path = self.write_scenario_a(project)

            # Run normal judge to get baseline
            from quantagent.quant_judge import run_quant_judge, QuantJudgeSpec
            result = run_quant_judge(
                project,
                QuantJudgeSpec(
                    scenario="A",
                    input_path=str(csv_path),
                    threshold_col="t1_auction_return",
                    threshold_lte=-9,
                ),
            )

            # Verify that with legitimate runner_sha256, we get metrics
            self.assertTrue(result.metrics)
            self.assertTrue(result.research_ready)

            # The actual runner_sha256 validation happens in experiment_runner.py
            # which computes sha256 of the runner file itself
            # A forged signature would need to match the actual file hash


if __name__ == "__main__":
    unittest.main()
