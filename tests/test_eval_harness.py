from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.eval_harness import (
    ERROR,
    FAIL,
    PASS,
    EvalCase,
    builtin_code_eval_cases,
    builtin_smoke_eval_cases,
    load_eval_cases,
    render_eval_json,
    render_eval_markdown,
    run_eval_case,
    run_eval_cases,
    score_eval_run,
)


class EvalHarnessTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent eval harness ")

    def test_load_eval_cases_from_quantagent_evals(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            eval_dir = project / ".quantagent" / "evals"
            eval_dir.mkdir(parents=True)
            (eval_dir / "cases.json").write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "hello",
                                "name": "hello case",
                                "type": "shell",
                                "command": "python3 -c 'print(\"hello\")'",
                                "weight": 3,
                                "tags": ["smoke"],
                                "env": {"DEMO": "1"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (eval_dir / "single.json").write_text(
                json.dumps({"id": "single", "command": "python3 -c 'print(1)'"}),
                encoding="utf-8",
            )

            cases = load_eval_cases(project)

            self.assertEqual([case.id for case in cases], ["hello", "single"])
            self.assertEqual(cases[0].name, "hello case")
            self.assertEqual(cases[0].weight, 3)
            self.assertEqual(cases[0].env, {"DEMO": "1"})

    def test_run_shell_case_records_output_returncode_duration_and_classification(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            result = run_eval_case(
                project,
                EvalCase(
                    id="output",
                    name="output",
                    command="python3 -c 'import sys; print(\"out\"); print(\"err\", file=sys.stderr)'",
                ),
            )

            self.assertEqual(result.classification, PASS)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.score, 1)
            self.assertIn("out", result.stdout_preview)
            self.assertIn("err", result.stderr_preview)
            self.assertGreaterEqual(result.duration_ms, 0)

    def test_run_shell_case_classifies_failed_returncode(self) -> None:
        with self.make_project() as tmp:
            result = run_eval_case(
                Path(tmp),
                EvalCase(id="bad", name="bad", command="python3 -c 'import sys; sys.exit(7)'", weight=2),
            )

            self.assertEqual(result.classification, FAIL)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.score, 0)
            self.assertEqual(result.max_score, 2)
            self.assertIn("expected returncode 0", result.message)

    def test_run_shell_case_classifies_timeout_as_error(self) -> None:
        with self.make_project() as tmp:
            result = run_eval_case(
                Path(tmp),
                EvalCase(
                    id="timeout",
                    name="timeout",
                    command="python3 -c 'import time; time.sleep(2)'",
                    timeout_seconds=0.01,
                ),
            )

            self.assertEqual(result.classification, ERROR)
            self.assertIsNone(result.returncode)
            self.assertIn("timeout", result.message)

    def test_score_and_render_markdown_and_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            run = run_eval_cases(
                project,
                [
                    EvalCase(id="pass", name="pass", command="python3 -c 'print(\"yes\")'", weight=2),
                    EvalCase(id="fail", name="fail", command="python3 -c 'import sys; sys.exit(1)'", weight=3),
                ],
            )

            summary = score_eval_run(run)
            markdown = render_eval_markdown(run)
            payload = json.loads(render_eval_json(run))

            self.assertEqual(summary["score"], 2)
            self.assertEqual(summary["max_score"], 5)
            self.assertEqual(summary["passed"], 1)
            self.assertEqual(summary["failed"], 1)
            self.assertIn("# Mako Eval Run", markdown)
            self.assertIn("[pass] pass", markdown)
            self.assertIn("[fail] fail", markdown)
            self.assertEqual(payload["summary"]["percent"], 40)
            self.assertEqual(payload["results"][0]["stdout_preview"].strip(), "yes")

    def test_builtin_smoke_cases_are_shell_cases(self) -> None:
        cases = builtin_smoke_eval_cases()

        self.assertGreaterEqual(len(cases), 2)
        self.assertTrue(all(case.type == "shell" for case in cases))
        self.assertIn("py_compile", cases[0].command)

    def test_builtin_code_cases_cover_programming_agent_surface(self) -> None:
        cases = builtin_code_eval_cases()
        ids = [case.id for case in cases]
        tags = {tag for case in cases for tag in case.tags}

        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case.type == "shell" for case in cases))
        for expected in {"code", "edit", "repair", "isolation", "apply", "context", "orchestration"}:
            self.assertIn(expected, tags)
        self.assertTrue(any("test_apply_gate" in case.command for case in cases))
        self.assertTrue(any("test_worktree_isolation" in case.command for case in cases))


if __name__ == "__main__":
    unittest.main()
