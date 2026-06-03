from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.eval_harness import EvalCase, build_eval_gap_report, eval_ledger_path, run_eval_cases


class Phase6ProductAcceptanceTest(unittest.TestCase):
    def test_eval_once_writes_ledger_gap_report_and_scorecard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6 eval once ") as tmp:
            project = Path(tmp)
            eval_dir = project / ".quantagent" / "evals"
            eval_dir.mkdir(parents=True)
            (eval_dir / "cases.json").write_text(
                json.dumps({"cases": [{"id": "ok", "command": "python3 -c 'print(42)'"}]}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "eval", "--project", tmp, "once"])

            output = stdout.getvalue()
            ledger = eval_ledger_path(project.resolve(strict=False))
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 1)
        self.assertIn("# Eval Gap Report", output)
        self.assertIn("# Eval Scorecard", output)
        self.assertIn("benchmark:pass", output)
        self.assertEqual(rows[0]["summary"]["score"], rows[0]["summary"]["max_score"])

    def test_eval_scorecard_is_derived_from_latest_ledger_row(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6 scorecard ") as tmp:
            project = Path(tmp)
            eval_dir = project / ".quantagent" / "evals"
            eval_dir.mkdir(parents=True)
            (eval_dir / "cases.json").write_text(
                json.dumps({"cases": [{"id": "ok", "command": "python3 -c 'print(42)'"}]}),
                encoding="utf-8",
            )
            self.assertEqual(main(["--no-trust-prompt", "eval", "--project", tmp, "once", "--json"]), 0)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "eval", "--project", tmp, "scorecard", "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["source"], "ledger")
        self.assertEqual(payload["badge"], f"benchmark:{payload['status']} {payload['score']}/{payload['max_score']} ({payload['percent']}/100)")
        self.assertTrue(payload["benchmark_id"])

    def test_gap_report_next_action_uses_failed_case_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6 next step ") as tmp:
            run = run_eval_cases(
                Path(tmp),
                [
                    EvalCase(
                        id="fails-with-evidence",
                        name="fails with evidence",
                        command="python3 -c 'import sys; print(\"AUTOPSY_EVIDENCE: missing import\", file=sys.stderr); sys.exit(2)'",
                    )
                ],
            )
            report = build_eval_gap_report(run)

        self.assertEqual(report["status"], "gap")
        self.assertIn("fails-with-evidence", report["next_action"])
        self.assertIn("AUTOPSY_EVIDENCE", report["next_action"])

    def test_doctor_outputs_short_blocking_issues_and_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase6 doctor ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "bad"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text('{"id":', encoding="utf-8")

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = main(["--no-trust-prompt", "doctor", "--project", tmp])
            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = main(["--no-trust-prompt", "doctor", "--project", tmp, "--json"])
            payload = json.loads(json_stdout.getvalue())

        self.assertEqual(text_code, 1)
        self.assertEqual(json_code, 1)
        self.assertIn("## Blocking Issues", text_stdout.getvalue())
        self.assertNotIn("Highest-Value Next Upgrades", text_stdout.getvalue())
        self.assertTrue(any(item["name"] == "plugin_registry" for item in payload["blocking_issues"]))


if __name__ == "__main__":
    unittest.main()
