from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.doctor import run_doctor
from quantagent.quant_bench import (
    latest_quant_bench,
    quant_bench_dir,
    render_quant_bench,
    render_quant_bench_json,
    run_quant_bench,
    score_quant_bench,
)


class QuantBenchTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant bench ")

    def test_quant_bench_runs_all_cases_and_writes_artifacts(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            run = run_quant_bench(project)
            summary = score_quant_bench(run)
            latest = latest_quant_bench(project)

            self.assertEqual(summary["total"], 17)
            self.assertEqual(summary["score"], summary["max_score"])
            self.assertEqual(summary["percent"], 100)
            self.assertTrue((quant_bench_dir(project) / f"{run.run_id}.json").exists())
            self.assertTrue((quant_bench_dir(project) / f"{run.run_id}.md").exists())
            self.assertIsNotNone(latest)
            self.assertEqual(latest.run_id, run.run_id)

    def test_render_markdown_and_json_include_summary(self) -> None:
        with self.make_project() as tmp:
            run = run_quant_bench(Path(tmp))

            markdown = render_quant_bench(run)
            payload = json.loads(render_quant_bench_json(run))

            self.assertIn("# QuantBench", markdown)
            self.assertIn("contract_valid_trade_csv", markdown)
            self.assertEqual(payload["summary"]["percent"], 100)
            self.assertEqual(payload["summary"]["passed"], 17)

    def test_quant_bench_cli_markdown_and_json(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "quant", "--project", tmp, "bench"])
            markdown = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                json_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "bench", "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertIn("# QuantBench", markdown)
            self.assertEqual(json_rc, 0)
            self.assertEqual(payload["summary"]["percent"], 100)

    def test_doctor_reports_quant_bench(self) -> None:
        with self.make_project() as tmp:
            checks = run_doctor(Path(tmp))
            quant_bench = next(check for check in checks if check.name == "quant_bench")

            self.assertTrue(quant_bench.ok)
            self.assertEqual(quant_bench.category, "quant")
            self.assertIn("quant benchmark cases", quant_bench.detail)


if __name__ == "__main__":
    unittest.main()
