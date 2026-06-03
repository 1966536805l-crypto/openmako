from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from quantagent.cli import main
from quantagent.edit_loop import create_patch_plan
from quantagent.model_client import ModelResponse
from quantagent.swarm import run_repair_swarm, run_swarm


class SwarmTest(unittest.TestCase):
    def test_swarm_runs_isolated_workers_and_writes_battle_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent swarm ") as tmp:
            project = Path(tmp)
            (project / "demo.py").write_text("VALUE = 0\n", encoding="utf-8")

            result = run_swarm(
                project,
                "change demo value",
                workers=2,
                worker_command=(
                    "python3 -c 'from pathlib import Path; "
                    'Path(\"demo.py\").write_text(\"VALUE = {worker_index}\", encoding=\"utf-8\")\''
                ),
                test_command="python3 -m py_compile demo.py",
                sandbox_backend="worktree",
                allow_risky_worker=True,
                allow_risky_test=True,
                use_default_worker=False,
            )

            self.assertTrue(result.ok)
            self.assertEqual(len(result.workers), 2)
            self.assertTrue(result.winner_worker_id)
            self.assertTrue(result.winner_review_id)
            self.assertTrue(Path(result.battle_report_path).exists())
            self.assertEqual((project / "demo.py").read_text(encoding="utf-8"), "VALUE = 0\n")
            self.assertEqual(len(list(Path(result.run_dir).glob("worker-*_bundle.json"))), 2)
            self.assertIn("OpenMako Swarm Battle Report", Path(result.battle_report_path).read_text(encoding="utf-8"))

    def test_swarm_cli_runs_without_default_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent swarm cli ") as tmp:
            project = Path(tmp)
            (project / "demo.py").write_text("VALUE = 0\n", encoding="utf-8")

            with redirect_stdout(StringIO()):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "swarm",
                        "--project",
                        str(project),
                        "--task",
                        "change demo value",
                        "--workers",
                        "1",
                        "--worker-command",
                        "python3 -c 'from pathlib import Path; Path(\"demo.py\").write_text(\"VALUE = 9\", encoding=\"utf-8\")'",
                        "--no-default-worker",
                        "--test",
                        "python3 -m py_compile demo.py",
                        "--sandbox-backend",
                        "worktree",
                        "--allow-risky-worker",
                        "--allow-risky-test",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual((project / "demo.py").read_text(encoding="utf-8"), "VALUE = 0\n")
            reports = list((project / ".quantagent" / "quantagent_swarms").glob("swarm-*/battle_report.md"))
            self.assertEqual(len(reports), 1)

    def test_repair_swarm_runs_parent_ranked_isolated_repair_loops(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with tempfile.TemporaryDirectory(prefix="quantagent repair swarm ") as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_repair_swarm(
                project,
                plan,
                "AssertionError",
                workers=2,
                max_rounds=1,
                model="fake-model",
                client_factory=lambda _worker_id: FakeClient(),
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.mode, "repair_loop")
            self.assertEqual(len(result.workers), 2)
            self.assertTrue(result.winner_worker_id)
            self.assertTrue(result.winner_review_id)
            self.assertTrue(result.arbitration.apply_gate_ready)
            self.assertTrue(Path(result.scheduler_result_path).exists())
            self.assertTrue(Path(result.arbitration_path).exists())
            self.assertEqual(len(list(Path(result.run_dir).glob("worker-*_bundle.json"))), 2)
            self.assertTrue(all(worker.preview_id for worker in result.workers))
            self.assertTrue(all(worker.rounds >= 1 for worker in result.workers))
            self.assertEqual((project / "a.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            report = Path(result.battle_report_path).read_text(encoding="utf-8")
            self.assertIn("mode: repair_loop", report)
            self.assertIn("Parent Arbitration", report)


if __name__ == "__main__":
    unittest.main()
