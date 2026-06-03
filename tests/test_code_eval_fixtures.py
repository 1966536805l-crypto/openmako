from __future__ import annotations

import json
import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from quantagent.code_eval_fixtures import (
    FAIL,
    PASS,
    apply_oracle_edits,
    builtin_code_eval_fixtures,
    materialize_code_eval_fixture,
    render_code_eval_fixture_list,
    render_code_eval_json,
    render_code_eval_markdown,
    render_code_eval_solve_json,
    run_code_eval_fixture,
    run_code_eval_pack,
    run_code_eval_solve_pack,
    select_code_eval_fixtures,
)
from quantagent.cli import main
from quantagent.model_client import ModelResponse


class CodeEvalFixturesTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent code eval ")

    def test_builtin_fixtures_are_unique_and_issue_to_patch_shaped(self) -> None:
        fixtures = builtin_code_eval_fixtures()
        ids = [fixture.id for fixture in fixtures]
        multi_file = [fixture for fixture in fixtures if "multi-file" in fixture.tags]
        multi_edit = [fixture for fixture in fixtures if len(fixture.oracle_edits) >= 2]

        self.assertGreaterEqual(len(fixtures), 13)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(fixture.issue for fixture in fixtures))
        self.assertTrue(all(fixture.files for fixture in fixtures))
        self.assertTrue(all(fixture.oracle_edits for fixture in fixtures))
        self.assertTrue(all("issue-to-patch" in fixture.tags for fixture in fixtures))
        self.assertGreaterEqual(len(multi_file), 3)
        self.assertGreaterEqual(len(multi_edit), 1)
        self.assertIn("add-regression", render_code_eval_fixture_list(fixtures))

    def test_materialized_fixture_fails_then_oracle_passes(self) -> None:
        fixture = select_code_eval_fixtures(["add-regression"])[0]
        with self.make_project() as tmp:
            workspace = materialize_code_eval_fixture(fixture, Path(tmp) / "workspace")

            initial = run_code_eval_fixture(Path(tmp), fixture, run_root=Path(tmp) / "run", apply_oracle=False)
            error = apply_oracle_edits(workspace, fixture)

        self.assertEqual(initial.initial.status, FAIL)
        self.assertTrue(initial.ok)
        self.assertEqual(error, "")

    def test_full_pack_proves_all_fixtures_red_to_green(self) -> None:
        with self.make_project() as tmp:
            run = run_code_eval_pack(Path(tmp), keep_workspaces=False)
            markdown = render_code_eval_markdown(run)
            payload = json.loads(render_code_eval_json(run))

        self.assertEqual(run.summary["failed"], 0)
        self.assertEqual(run.summary["passed"], len(builtin_code_eval_fixtures()))
        self.assertEqual(run.summary["engineering_level"], "L4.5")
        self.assertGreaterEqual(run.summary["multi_file_fixtures"], 3)
        self.assertGreaterEqual(run.summary["multi_edit_fixtures"], 1)
        self.assertIn("# Mako Code Eval Fixtures", markdown)
        self.assertIn("engineering_level: L4.5", markdown)
        self.assertEqual(payload["summary"]["percent"], 100)
        self.assertEqual(payload["summary"]["engineering_level"], "L4.5")
        self.assertTrue(all(item.initial.status == FAIL and item.oracle and item.oracle.status == PASS for item in run.results))

    def test_unknown_fixture_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            select_code_eval_fixtures(["missing"])

    def test_solve_pack_uses_repair_loop_without_oracle_apply(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self, fixture_id: str) -> None:
                self.fixture_id = fixture_id

            def complete(self, request):
                fixture = select_code_eval_fixtures([self.fixture_id])[0]
                edits = [
                    {
                        "path": edit.path,
                        "old": edit.old,
                        "new": edit.new,
                        "expected_count": edit.expected_count,
                    }
                    for edit in fixture.oracle_edits
                ]
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text=json.dumps({"candidates": [{"name": "minimal repair", "summary": "fix source", "edits": edits}]}),
                    provider="fake",
                )

        with self.make_project() as tmp:
            run = run_code_eval_solve_pack(
                Path(tmp),
                fixture_ids=["add-regression"],
                model="fake-model",
                client_factory=lambda fixture: FakeClient(fixture.id),
                keep_workspaces=False,
            )
            payload = json.loads(render_code_eval_solve_json(run))

        self.assertEqual(run.summary["passed"], 1)
        self.assertEqual(run.results[0].initial.status, FAIL)
        self.assertTrue(run.results[0].solver_ok)
        self.assertIn("calc.py", run.results[0].changed_paths)
        self.assertEqual(payload["summary"]["percent"], 100)

    def test_solve_pack_fails_fast_without_model_credentials(self) -> None:
        with self.make_project() as tmp, patch.dict(os.environ, {"QUANTAGENT_OPENAI_API_KEY": "", "OPENAI_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "model API key is not configured"):
                run_code_eval_solve_pack(Path(tmp), fixture_ids=["add-regression"], keep_workspaces=False)

    def test_code_eval_cli_list_and_run_json(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                list_code = main(["--no-trust-prompt", "code-eval", "--project", tmp, "list", "--fixture", "add-regression", "--json"])
                run_code = main(["--no-trust-prompt", "code-eval", "--project", tmp, "run", "--fixture", "add-regression", "--json", "--clean"])

        self.assertEqual(list_code, 0)
        self.assertEqual(run_code, 0)
        self.assertIn("add-regression", stdout.getvalue())

    def test_comma_separated_fixture_ids_are_expanded(self) -> None:
        # Simulate CLI behavior: --fixture "id1,id2,id3"
        raw_input = ["add-regression,email-normalization", "comma-int-parser"]
        expanded = []
        for item in raw_input:
            expanded.extend(f.strip() for f in item.split(',') if f.strip())

        fixtures = select_code_eval_fixtures(expanded)
        ids = [f.id for f in fixtures]

        self.assertEqual(len(fixtures), 3)
        self.assertIn("add-regression", ids)
        self.assertIn("email-normalization", ids)
        self.assertIn("comma-int-parser", ids)

    def test_unknown_fixture_error_includes_hint(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "code-eval", "--project", tmp, "list", "--fixture", "unknown-fixture-id"])

        self.assertEqual(code, 2)
        output = stdout.getvalue()
        self.assertIn("unknown code eval fixture(s): unknown-fixture-id", output)
        self.assertIn("Available fixtures:", output)
        self.assertIn("mako code-eval list", output)

    def test_list_fixtures_json_output(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "code-eval", "--project", tmp, "list", "--json"])

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        payload = json.loads(output)
        self.assertIsInstance(payload, list)
        self.assertGreaterEqual(len(payload), 13)
        self.assertTrue(all("id" in item for item in payload))
        self.assertTrue(all("issue" in item for item in payload))
        self.assertTrue(all("tags" in item for item in payload))

    def test_run_all_fixtures_flag(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "code-eval", "--project", tmp, "run", "--all", "--json", "--clean"])

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        payload = json.loads(output)
        self.assertIn("summary", payload)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertGreaterEqual(payload["summary"]["passed"], 13)


if __name__ == "__main__":
    unittest.main()
