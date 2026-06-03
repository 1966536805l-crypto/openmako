from __future__ import annotations

import json
import shlex
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from quantagent.agent_loop_core import run_agent_loop
from quantagent.coding_bench import run_coding_bench, run_coding_bench_stability
from quantagent.learning_effect_coding_bench import run_learning_effect_coding_bench
from quantagent.skill_pipeline import (
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    propose_file_bundle_repair_skill_from_trajectory,
    run_skill_eval_command,
)


class ExternalBenchmarkMultimoduleRegressionTest(unittest.TestCase):
    def test_openclaw_selected_js_no_seed_repair_changes_only_target_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-js-repair-benchmark-") as tmp:
            project = Path(tmp) / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_PARSE_FINITE_NUMBER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            task_file = project / "openclaw_js_tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "openclaw_parse_strict_integer_js_no_seed",
                                "instruction": "Fix the failing JavaScript tests without editing tests.",
                                "files": {
                                    "package.json": "{\"type\":\"module\"}\n",
                                    OPENCLAW_PARSE_FINITE_NUMBER_TARGET: _broken_openclaw_parse_strict_integer_source(source),
                                    "tests/test_parse_finite_number.mjs": _openclaw_parse_strict_integer_tests(),
                                },
                                "test_command": "node tests/test_parse_finite_number.mjs",
                                "max_iterations": 1,
                                "timeout_seconds": 30,
                                "tags": ["openclaw", "javascript", "external-held-out", "no-seed"],
                            }
                        ]
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            command = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                "--mode repair --json --max-steps 12 --learning-context off {instruction}"
            )
            run = run_coding_bench(project, agent_command=command, task_file=task_file, keep_workspaces=True)

        summary = run.summary()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["solved"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["cheated"], 0)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["invalid"], 0)
        result = run.results[0]
        self.assertEqual(result.status, "solved", result.to_dict())
        self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_PARSE_FINITE_NUMBER_TARGET,))
        self.assertEqual(result.patch_metrics.out_of_scope_files, ())
        self.assertEqual(result.patch_metrics.workspace_added_files, ())
        self.assertEqual(result.patch_metrics.workspace_deleted_files, ())

    def test_openclaw_selected_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_PARSE_FINITE_NUMBER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_parse_strict_integer_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_js_workspace(stage1, broken_source, _openclaw_parse_strict_integer_tests())
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_PARSE_FINITE_NUMBER_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-parse-finite-number-js-repair",
                description="Learned OpenClaw selected JavaScript parse-finite-number repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-parse-finite-number-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_PARSE_FINITE_NUMBER_TARGET,))
            self.assertIn("parseStrictInteger", hint["functions"])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_parse_finite_number.mjs",
                summary="stage1 OpenClaw JS parse-finite-number repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_parse_finite_number.mjs")),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-parse-finite-number"), proposal),
            )

            task_file = root / "openclaw_js_learning_tasks.json"
            _write_openclaw_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-parse-finite-number-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden js failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_parse_strict_integer_js_hidden_bounds",
            "openclaw_parse_strict_integer_js_hidden_safe_range",
        }
        self.assertEqual(benchmark_fingerprint, "c6c033cf723b912e9a5f5ee141957b84bde8bffe05ea217554f4b2b62d095eb8")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_PARSE_FINITE_NUMBER_TARGET,))
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_parse_timeout_package_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-parse-timeout-package-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_PARSE_TIMEOUT_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_parse_timeout_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_parse_timeout_package_workspace(stage1, broken_source, _openclaw_parse_timeout_package_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_parse_timeout.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "entry": (stage1 / "src" / "timeout.js").read_text(encoding="utf-8"),
                "readme": (stage1 / "README.md").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript parse-timeout tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "src" / "timeout.js").read_text(encoding="utf-8"), before["entry"])
            self.assertEqual((stage1 / "README.md").read_text(encoding="utf-8"), before["readme"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_PARSE_TIMEOUT_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-parse-timeout-package-js-repair",
                description="Learned OpenClaw selected JavaScript parse-timeout package-entry repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-parse-timeout-package-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_PARSE_TIMEOUT_TARGET,))
            self.assertIn("parseTimeoutMs", hint["functions"])
            self.assertIn("parseTimeoutMsWithFallback", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 OpenClaw JS parse-timeout package-entry repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-parse-timeout-package"), proposal),
            )

            task_file = root / "openclaw_parse_timeout_package_js_learning_tasks.json"
            _write_openclaw_parse_timeout_package_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-parse-timeout-package-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_parse_timeout_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('parse-timeout failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_parse_timeout_package_js_hidden_invalid_values",
            "openclaw_parse_timeout_package_js_hidden_type_edges",
        }
        expected_patch_scope = (OPENCLAW_PARSE_TIMEOUT_TARGET,)
        forbidden_files = {
            "package.json",
            "src/timeout.js",
            "README.md",
        }
        self.assertEqual(benchmark_fingerprint, "ef3b88a6931c342bc3f306786a8fb907aab765db059e2c35d516b1aff1a1117f")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_arg_split_package_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-arg-split-package-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_ARG_SPLIT_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_arg_split_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_arg_split_package_workspace(stage1, broken_source, _openclaw_arg_split_package_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_arg_split.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "entry": (stage1 / "src" / "args.js").read_text(encoding="utf-8"),
                "readme": (stage1 / "README.md").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript arg-split tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "src" / "args.js").read_text(encoding="utf-8"), before["entry"])
            self.assertEqual((stage1 / "README.md").read_text(encoding="utf-8"), before["readme"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_ARG_SPLIT_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-arg-split-package-js-repair",
                description="Learned OpenClaw selected JavaScript arg-split package-entry repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-arg-split-package-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_ARG_SPLIT_TARGET,))
            self.assertIn("splitArgsPreservingQuotes", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 OpenClaw JS arg-split package-entry repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-arg-split-package"), proposal),
            )

            task_file = root / "openclaw_arg_split_package_js_learning_tasks.json"
            _write_openclaw_arg_split_package_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-arg-split-package-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_arg_split_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('arg-split failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_arg_split_package_js_hidden_backslash_quotes",
            "openclaw_arg_split_package_js_hidden_quote_start",
        }
        expected_patch_scope = (OPENCLAW_ARG_SPLIT_TARGET,)
        forbidden_files = {
            "package.json",
            "src/args.js",
            "README.md",
        }
        self.assertEqual(benchmark_fingerprint, "3888323d7b5bc9b9844fe47b48c20431182bbcdac07390f1d8791cd0c75cebc4")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_selected_balanced_json_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-balanced-json-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_BALANCED_JSON_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_balanced_json_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_balanced_json_workspace(stage1, broken_source, _openclaw_balanced_json_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_balanced_json.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript balanced-json tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_BALANCED_JSON_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-balanced-json-js-repair",
                description="Learned OpenClaw selected JavaScript balanced-json repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-balanced-json-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_BALANCED_JSON_TARGET,))
            self.assertIn("extractBalancedJsonPrefix", hint["functions"])
            self.assertIn("extractBalancedJsonFragments", hint["functions"])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_balanced_json.mjs",
                summary="stage1 OpenClaw JS balanced-json repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-balanced-json"), proposal),
            )

            task_file = root / "openclaw_balanced_json_js_learning_tasks.json"
            _write_openclaw_balanced_json_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-balanced-json-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_balanced_json_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden balanced-json failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_balanced_json_js_hidden_strings",
            "openclaw_balanced_json_js_hidden_fragments",
        }
        self.assertEqual(benchmark_fingerprint, "bb0565237829fb4e88c0b06e2e6f935f7d6a970266687320dc2ebe908d094dcb")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_BALANCED_JSON_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_selected_json_pointer_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-json-pointer-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_JSON_POINTER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_json_pointer_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_json_pointer_workspace(stage1, broken_source, _openclaw_json_pointer_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_json_pointer.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript json-pointer tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_JSON_POINTER_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-json-pointer-js-repair",
                description="Learned OpenClaw selected JavaScript json-pointer repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-json-pointer-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_JSON_POINTER_TARGET,))
            self.assertIn("readJsonPointer", hint["functions"])
            self.assertIn("encodeJsonPointerToken", hint["functions"])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_json_pointer.mjs",
                summary="stage1 OpenClaw JS json-pointer repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-json-pointer"), proposal),
            )

            task_file = root / "openclaw_json_pointer_js_learning_tasks.json"
            _write_openclaw_json_pointer_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-json-pointer-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_json_pointer_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden json-pointer failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_json_pointer_js_hidden_escaped_tokens",
            "openclaw_json_pointer_js_hidden_missing_modes",
        }
        self.assertEqual(benchmark_fingerprint, "d3c5ffdc9f891cf6ae9fa1008ebe6e9219595bd00268ba2539370afe117975b8")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_JSON_POINTER_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_selected_command_poll_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-command-poll-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_COMMAND_POLL_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_command_poll_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_command_poll_workspace(stage1, broken_source, _openclaw_command_poll_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_command_poll_backoff.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript command-poll backoff tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_COMMAND_POLL_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-command-poll-js-repair",
                description="Learned OpenClaw selected JavaScript command-poll backoff repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-command-poll-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_COMMAND_POLL_TARGET,))
            self.assertIn("recordCommandPoll", hint["functions"])
            self.assertIn("resetCommandPollCount", hint["functions"])
            self.assertIn("pruneStaleCommandPolls", hint["functions"])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_command_poll_backoff.mjs",
                summary="stage1 OpenClaw JS command-poll repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-command-poll"), proposal),
            )

            task_file = root / "openclaw_command_poll_js_learning_tasks.json"
            _write_openclaw_command_poll_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-command-poll-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_command_poll_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden command-poll failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_command_poll_js_hidden_reset_isolated",
            "openclaw_command_poll_js_hidden_prune_boundaries",
        }
        expected_stability_counts = {task_id: 3 for task_id in expected_task_ids}
        self.assertEqual(benchmark_fingerprint, "e96460f8bbb7cfde4b7c78190a82187ab0c3a9e6c7104c0f255895787ea6b7e6")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), expected_stability_counts)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["total"], 2)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.approved_learning_run.summary()["errors"], 0)
        self.assertEqual(report.approved_learning_run.summary()["invalid"], 0)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["failed"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        self.assertEqual(cheat_summary["errors"], 0)
        self.assertEqual(cheat_summary["invalid"], 0)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_COMMAND_POLL_TARGET,))
            self.assertEqual(result.patch_metrics.workspace_modified_files, (OPENCLAW_COMMAND_POLL_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_package_level_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="package-level-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_labels_source()

            stage1 = root / "stage1_workspace"
            _write_mako_js_labels_workspace(stage1, broken_source, _mako_js_labels_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_labels.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level JavaScript labels tests without editing tests or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_LABELS_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="mako-js-labels-repair",
                description="Learned package-level JavaScript labels repair from a successful stage1 run.",
                triggers=("opaque-mako-js-labels-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_LABELS_TARGET,))
            self.assertIn("compactLabel", hint["functions"])
            self.assertIn("labelKey", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 package-level JS labels repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-level-js-labels"), proposal),
            )

            task_file = root / "package_level_js_learning_tasks.json"
            _write_mako_js_labels_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-mako-js-labels-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_package_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden package js failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "package_level_js_labels_hidden_unicode_spacing",
            "package_level_js_labels_hidden_empty_edges",
        }
        self.assertEqual(benchmark_fingerprint, "fef9aeb1ea11d7583855530c3c1393c51af82b7bc09efb3212ed45c0db1196a9")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (MAKO_JS_LABELS_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_package_level_async_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="package-level-async-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_async_records_source()

            stage1 = root / "stage1_workspace"
            _write_mako_js_async_records_workspace(stage1, broken_source, _mako_js_async_records_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_async_records.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            index_before = (stage1 / "mako_js" / "index.js").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level async JavaScript records tests without editing tests or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_ASYNC_RECORDS_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="mako-js-async-records-repair",
                description="Learned package-level async JavaScript records repair from a successful stage1 run.",
                triggers=("opaque-mako-js-async-records-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_ASYNC_RECORDS_TARGET,))
            self.assertIn("loadUserSummaries", hint["functions"])
            self.assertIn("normalizeUserId", hint["functions"])
            self.assertIn("summarizeUser", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 package-level async JS records repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-level-async-js-records"), proposal),
            )

            task_file = root / "package_level_async_js_learning_tasks.json"
            _write_mako_js_async_records_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-mako-js-async-records-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_package_async_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden async js failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "package_level_async_js_records_hidden_dedupe_errors",
            "package_level_async_js_records_hidden_roles_invalid",
        }
        self.assertEqual(benchmark_fingerprint, "5c4020e5f0cc1d572049dcceee2c706618478e302f6c9e647420e7a2c56ecf6a")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["total"], 2)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.approved_learning_run.summary()["errors"], 0)
        self.assertEqual(report.approved_learning_run.summary()["invalid"], 0)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["failed"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        self.assertEqual(cheat_summary["errors"], 0)
        self.assertEqual(cheat_summary["invalid"], 0)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (MAKO_JS_ASYNC_RECORDS_TARGET,))
            self.assertEqual(result.patch_metrics.workspace_modified_files, (MAKO_JS_ASYNC_RECORDS_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_package_level_io_boundary_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="package-level-io-boundary-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_io_boundary_source()

            stage1 = root / "stage1_workspace"
            _write_mako_js_io_boundary_workspace(stage1, broken_source, _mako_js_io_boundary_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_io_boundary.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "index": (stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"),
                "labels": (stage1 / "mako_js" / "labels.js").read_text(encoding="utf-8"),
                "async_records": (stage1 / "mako_js" / "async_records.js").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level JavaScript mocked I/O boundary tests without editing tests, sibling modules, index, or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"), before["index"])
            self.assertEqual((stage1 / "mako_js" / "labels.js").read_text(encoding="utf-8"), before["labels"])
            self.assertEqual((stage1 / "mako_js" / "async_records.js").read_text(encoding="utf-8"), before["async_records"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_IO_BOUNDARY_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="mako-js-io-boundary-repair",
                description="Learned package-level JavaScript mocked I/O boundary repair from a successful stage1 run.",
                triggers=("opaque-mako-js-io-boundary-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_IO_BOUNDARY_TARGET,))
            self.assertIn("scanWorkspaceManifest", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 package-level JS mocked I/O boundary repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-level-js-io-boundary"), proposal),
            )

            task_file = root / "package_level_io_boundary_js_learning_tasks.json"
            _write_mako_js_io_boundary_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-mako-js-io-boundary-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_package_io_boundary_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden io-boundary js failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "package_level_io_boundary_js_hidden_dynamic_errors",
            "package_level_io_boundary_js_hidden_hardcoded_constants",
        }
        expected_patch_scope = (MAKO_JS_IO_BOUNDARY_TARGET,)
        forbidden_files = {
            "package.json",
            "mako_js/index.js",
            "mako_js/labels.js",
            "mako_js/async_records.js",
        }
        self.assertEqual(benchmark_fingerprint, "a89ce9519ea682ed1171bb4bec3865e2c9e135f1a960885e31198b132abb6900")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["total"], 2)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.approved_learning_run.summary()["errors"], 0)
        self.assertEqual(report.approved_learning_run.summary()["invalid"], 0)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["failed"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        self.assertEqual(cheat_summary["errors"], 0)
        self.assertEqual(cheat_summary["invalid"], 0)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_package_level_fs_manifest_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="package-level-fs-manifest-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_fs_manifest_source()

            stage1 = root / "stage1_workspace"
            _write_mako_js_fs_manifest_workspace(stage1, broken_source, _mako_js_fs_manifest_stage1_tests(), _mako_js_fs_manifest_stage1_fixture_files())
            stage1_test_path = stage1 / "tests" / "test_fs_manifest.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "lock": (stage1 / "package-lock.json").read_text(encoding="utf-8"),
                "index": (stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"),
                "helper": (stage1 / "fixtures" / "local-helper" / "package.json").read_text(encoding="utf-8"),
                "fixture": (stage1 / "fixtures" / "workspace" / "package.json").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level JavaScript real fs manifest tests without editing tests, fixtures, entrypoints, package-lock, or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "package-lock.json").read_text(encoding="utf-8"), before["lock"])
            self.assertEqual((stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"), before["index"])
            self.assertEqual((stage1 / "fixtures" / "local-helper" / "package.json").read_text(encoding="utf-8"), before["helper"])
            self.assertEqual((stage1 / "fixtures" / "workspace" / "package.json").read_text(encoding="utf-8"), before["fixture"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_FS_MANIFEST_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="mako-js-fs-manifest-repair",
                description="Learned package-level JavaScript real fs manifest repair from a successful npm lifecycle stage1 run.",
                triggers=("opaque-mako-js-fs-manifest-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_FS_MANIFEST_TARGET,))
            self.assertIn("scanFsPackageManifest", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 package-level JS real fs manifest repair verifies through npm pretest lifecycle and tests",
                evidence=(result.trajectory_path, str(stage1_test_path), str(stage1 / "package-lock.json")),
                timeout_seconds=45,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-level-js-fs-manifest"), proposal),
            )

            task_file = root / "package_level_fs_manifest_js_learning_tasks.json"
            _write_mako_js_fs_manifest_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-mako-js-fs-manifest-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_package_fs_manifest_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('fs manifest failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "package_level_fs_manifest_js_hidden_lock_and_missing",
            "package_level_fs_manifest_js_hidden_depth_and_invalid",
        }
        expected_patch_scope = (MAKO_JS_FS_MANIFEST_TARGET,)
        forbidden_files = {
            "package.json",
            "package-lock.json",
            "mako_js/index.js",
            "fixtures/local-helper/package.json",
            "fixtures/workspace/package.json",
        }
        self.assertEqual(benchmark_fingerprint, "1ab60de09c402c4b6baf71b731cbb36503b371a5fb0cebdaf356879fee7cd50c")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="package-level-http-manifest-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_http_manifest_source()

            stage1 = root / "stage1_workspace"
            _write_mako_js_http_manifest_workspace(stage1, broken_source, _mako_js_http_manifest_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_http_manifest.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "index": (stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level JavaScript real fetch metadata tests without editing tests, entrypoints, or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "mako_js" / "index.js").read_text(encoding="utf-8"), before["index"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_HTTP_MANIFEST_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="mako-js-http-manifest-repair",
                description="Learned package-level JavaScript real fetch metadata repair from a successful local HTTP stage1 run.",
                triggers=("opaque-mako-js-http-manifest-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_HTTP_MANIFEST_TARGET,))
            self.assertIn("fetchPackageMetadata", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 package-level JS real fetch metadata repair verifies through local HTTP server tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=45,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-level-js-http-manifest"), proposal),
            )

            task_file = root / "package_level_http_manifest_js_learning_tasks.json"
            _write_mako_js_http_manifest_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-mako-js-http-manifest-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_package_http_manifest_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('http manifest failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "package_level_http_manifest_js_hidden_encoded_and_missing",
            "package_level_http_manifest_js_hidden_invalid_and_errors",
        }
        expected_patch_scope = (MAKO_JS_HTTP_MANIFEST_TARGET,)
        forbidden_files = {
            "package.json",
            "mako_js/index.js",
        }
        self.assertEqual(benchmark_fingerprint, "cee4ed1d12e22b9a5032f675386259f586d7e4663753ac14fbabbfdd500a1aef")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_less_pinned_package_io_boundary_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="less-pinned-io-boundary-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_io_boundary_source()

            stage1 = root / "stage1_workspace"
            _write_less_pinned_mako_js_io_boundary_workspace(stage1, broken_source, _less_pinned_io_boundary_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_io_boundary.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "entry": (stage1 / "src" / "runtime" / "index.js").read_text(encoding="utf-8"),
                "cli": (stage1 / "src" / "cli.js").read_text(encoding="utf-8"),
                "labels": (stage1 / "mako_js" / "labels.js").read_text(encoding="utf-8"),
                "async_records": (stage1 / "mako_js" / "async_records.js").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing package-level JavaScript mocked I/O boundary tests without editing tests, src entrypoints, sibling modules, or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), before["entry"])
            self.assertEqual((stage1 / "src" / "cli.js").read_text(encoding="utf-8"), before["cli"])
            self.assertEqual((stage1 / "mako_js" / "labels.js").read_text(encoding="utf-8"), before["labels"])
            self.assertEqual((stage1 / "mako_js" / "async_records.js").read_text(encoding="utf-8"), before["async_records"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_IO_BOUNDARY_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="less-pinned-mako-js-io-boundary-repair",
                description="Learned less-pinned package JavaScript mocked I/O boundary repair from a successful stage1 run.",
                triggers=("opaque-less-pinned-mako-js-io-boundary-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_IO_BOUNDARY_TARGET,))
            self.assertIn("scanWorkspaceManifest", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 less-pinned package JS mocked I/O boundary repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("less-pinned-package-js-io-boundary"), proposal),
            )

            task_file = root / "less_pinned_package_io_boundary_js_learning_tasks.json"
            _write_less_pinned_mako_js_io_boundary_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-less-pinned-mako-js-io-boundary-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_less_pinned_io_boundary_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('less-pinned io-boundary failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "less_pinned_io_boundary_js_hidden_dynamic_errors",
            "less_pinned_io_boundary_js_hidden_hardcoded_constants",
        }
        expected_patch_scope = (MAKO_JS_IO_BOUNDARY_TARGET,)
        forbidden_files = {
            "package.json",
            "src/runtime/index.js",
            "src/cli.js",
            "mako_js/labels.js",
            "mako_js/async_records.js",
        }
        self.assertEqual(benchmark_fingerprint, "9ffb8c2eca0fd7c5186548045ce648a15f58e5571c7b9b637d608fa042849563")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_multi_package_io_boundary_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="multi-package-io-boundary-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            broken_source = _broken_mako_js_io_boundary_source()

            stage1 = root / "stage1_workspace"
            _write_multi_package_mako_js_io_boundary_workspace(stage1, broken_source, _multi_package_io_boundary_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_io_boundary.mjs"
            before = {
                "test": stage1_test_path.read_text(encoding="utf-8"),
                "package": (stage1 / "package.json").read_text(encoding="utf-8"),
                "app_entry": (stage1 / "apps" / "cli" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"),
                "core_entry": (stage1 / "packages" / "core" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"),
                "labels": (stage1 / "packages" / "core" / "mako_js" / "labels.js").read_text(encoding="utf-8"),
                "async_records": (stage1 / "packages" / "core" / "mako_js" / "async_records.js").read_text(encoding="utf-8"),
                "tools": (stage1 / "packages" / "tools" / "index.js").read_text(encoding="utf-8"),
            }
            result = run_agent_loop(
                stage1,
                "Fix the failing multi-package JavaScript workspace mocked I/O boundary tests without editing tests, app entrypoints, package entrypoints, sibling packages, or package config.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), before["test"])
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), before["package"])
            self.assertEqual((stage1 / "apps" / "cli" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), before["app_entry"])
            self.assertEqual((stage1 / "packages" / "core" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), before["core_entry"])
            self.assertEqual((stage1 / "packages" / "core" / "mako_js" / "labels.js").read_text(encoding="utf-8"), before["labels"])
            self.assertEqual((stage1 / "packages" / "core" / "mako_js" / "async_records.js").read_text(encoding="utf-8"), before["async_records"])
            self.assertEqual((stage1 / "packages" / "tools" / "index.js").read_text(encoding="utf-8"), before["tools"])
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="multi-package-mako-js-io-boundary-repair",
                description="Learned multi-package JavaScript mocked I/O boundary repair from a successful stage1 run.",
                triggers=("opaque-multi-package-mako-js-io-boundary-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET,))
            self.assertIn("scanWorkspaceManifest", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && npm test",
                summary="stage1 multi-package JS mocked I/O boundary repair verifies through npm test",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("multi-package-js-io-boundary"), proposal),
            )

            task_file = root / "multi_package_io_boundary_js_learning_tasks.json"
            _write_multi_package_mako_js_io_boundary_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-multi-package-mako-js-io-boundary-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_multi_package_io_boundary_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('multi-package io-boundary failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "multi_package_io_boundary_js_hidden_dynamic_errors",
            "multi_package_io_boundary_js_hidden_hardcoded_constants",
        }
        expected_patch_scope = (MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET,)
        forbidden_files = {
            "package.json",
            "apps/cli/src/runtime/index.js",
            "packages/core/src/runtime/index.js",
            "packages/core/mako_js/labels.js",
            "packages/core/mako_js/async_records.js",
            "packages/tools/package.json",
            "packages/tools/index.js",
            "README.md",
        }
        self.assertEqual(benchmark_fingerprint, "714fa87140ca9f1187e37ea55e7d37ff26beaef41cfebcc42ea745bab7a8bee8")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), {task_id: 3 for task_id in expected_task_ids})
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.workspace_modified_files, expected_patch_scope)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
            for path in forbidden_files:
                self.assertNotIn(path, result.patch_metrics.changed_files)
                self.assertNotIn(path, result.patch_metrics.workspace_modified_files)
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_selected_async_lock_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-async-lock-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            source = OPENCLAW_ASYNC_LOCK_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _broken_openclaw_async_lock_source(source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_async_lock_workspace(stage1, broken_source, _openclaw_async_lock_stage1_tests())
            stage1_test_path = stage1 / "tests" / "test_async_lock.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript async-lock tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [OPENCLAW_ASYNC_LOCK_TARGET])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-async-lock-js-repair",
                description="Learned OpenClaw selected JavaScript async-lock repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-async-lock-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_ASYNC_LOCK_TARGET,))
            self.assertIn("createAsyncLock", hint["functions"])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_async_lock.mjs",
                summary="stage1 OpenClaw JS async-lock repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-async-lock"), proposal),
            )

            task_file = root / "openclaw_async_lock_js_learning_tasks.json"
            _write_openclaw_async_lock_js_learning_task_file(
                task_file,
                broken_source,
                trigger="opaque-openclaw-js-async-lock-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_async_lock_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden async-lock failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_async_lock_js_hidden_serial_order",
            "openclaw_async_lock_js_hidden_parallel_and_rejection",
        }
        expected_stability_counts = {task_id: 3 for task_id in expected_task_ids}
        self.assertEqual(benchmark_fingerprint, "7bee8b80a8e2d632aa482a4a792219b503817c085dc6036ac7135f48fd26bac2")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(Counter(result.task_id for result in stability_results), expected_stability_counts)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, (OPENCLAW_ASYNC_LOCK_TARGET,))
            self.assertEqual(result.patch_metrics.workspace_modified_files, (OPENCLAW_ASYNC_LOCK_TARGET,))
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") and path.endswith(".mjs") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_openclaw_selected_combined_js_trajectory_skill_reuses_on_hidden_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-combined-js-learning-effect-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir(parents=True)
            balanced_source = OPENCLAW_BALANCED_JSON_SOURCE.read_text(encoding="utf-8")
            json_pointer_source = OPENCLAW_JSON_POINTER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(balanced_source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            self.assertIn(_sha256(json_pointer_source), OPENCLAW_MANIFEST.read_text(encoding="utf-8"))
            broken_balanced_source = _broken_openclaw_balanced_json_source(balanced_source)
            broken_json_pointer_source = _broken_openclaw_json_pointer_source(json_pointer_source)

            stage1 = root / "stage1_workspace"
            _write_openclaw_combined_js_workspace(
                stage1,
                balanced_source=broken_balanced_source,
                json_pointer_source=broken_json_pointer_source,
                test_source=_openclaw_combined_js_stage1_tests(),
            )
            stage1_test_path = stage1 / "tests" / "test_combined_openclaw_js.mjs"
            stage1_test_before = stage1_test_path.read_text(encoding="utf-8")
            package_before = (stage1 / "package.json").read_text(encoding="utf-8")
            result = run_agent_loop(
                stage1,
                "Fix the failing JavaScript OpenClaw combined tests without editing tests.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(stage1_test_path.read_text(encoding="utf-8"), stage1_test_before)
            self.assertEqual((stage1 / "package.json").read_text(encoding="utf-8"), package_before)
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(
                tuple(implementation.data["files_touched"]),
                (OPENCLAW_BALANCED_JSON_TARGET, OPENCLAW_JSON_POINTER_TARGET),
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="openclaw-combined-js-repair",
                description="Learned OpenClaw selected JavaScript multi-file repair from a successful stage1 run.",
                triggers=("opaque-openclaw-js-combined-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            self.assertIn("JavaScript", proposal.body)
            self.assertEqual(hint["target"], "js_file_bundle")
            self.assertEqual(tuple(hint["files"]), (OPENCLAW_BALANCED_JSON_TARGET, OPENCLAW_JSON_POINTER_TARGET))
            self.assertIn("extractBalancedJsonPrefix", hint["functions"])
            self.assertIn("readJsonPointer", hint["functions"])
            self.assertNotIn("package.json", hint["files"])
            self.assertFalse(any(path.startswith("tests/") for path in hint["files"]))

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && node tests/test_combined_openclaw_js.mjs",
                summary="stage1 OpenClaw combined JS repair verifies against Node tests",
                evidence=(result.trajectory_path, str(stage1_test_path)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("openclaw-js-combined"), proposal),
            )

            task_file = root / "openclaw_combined_js_learning_tasks.json"
            _write_openclaw_combined_js_learning_task_file(
                task_file,
                balanced_source=broken_balanced_source,
                json_pointer_source=broken_json_pointer_source,
                trigger="opaque-openclaw-js-combined-1",
            )
            benchmark_fingerprint = _sha256(task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --mode repair --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                keep_workspaces=True,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=3,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_combined_js_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.mjs'):\n"
                "    test_file.write_text(\"import assert from 'node:assert/strict';\\nassert.equal(1, 1);\\n\", encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden combined js failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            no_learning_results = report.no_learning_run.results
            approved_results = report.approved_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        expected_task_ids = {
            "openclaw_combined_js_hidden_escaped_pointer",
            "openclaw_combined_js_hidden_fragments_missing",
        }
        expected_patch_scope = (OPENCLAW_BALANCED_JSON_TARGET, OPENCLAW_JSON_POINTER_TARGET)
        self.assertEqual(benchmark_fingerprint, "d06fa61c5cd237810869535590ff6bc90cbaf93f0115d861ccc529c6e21d26ce")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
        self.assertTrue(all(result.status == "failed" for result in no_learning_results))
        self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
        self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.no_learning_run.summary()["failed"], 2)
        self.assertEqual(report.no_learning_run.summary()["cheated"], 0)
        self.assertEqual(report.no_learning_run.summary()["errors"], 0)
        self.assertEqual(report.no_learning_run.summary()["invalid"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        self.assertEqual(stability.summary()["solved"], 6)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        self.assertEqual(cheat_summary["total"], 2)
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], 2)
        for result in (*approved_results, *stability_results):
            self.assertEqual(result.status, "solved", result.to_dict())
            self.assertEqual(result.patch_metrics.changed_files, expected_patch_scope)
            self.assertEqual(tuple(sorted(result.patch_metrics.workspace_modified_files)), expected_patch_scope)
            self.assertNotIn("package.json", result.patch_metrics.changed_files)
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(result.patch_metrics.workspace_added_files, ())
            self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        for result in cheat_results:
            self.assertEqual(result.status, "cheated")
            self.assertFalse(result.solved)
            self.assertEqual(result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", result.patch_metrics.workspace_added_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in result.patch_metrics.out_of_scope_files),
                result.to_dict(),
            )

    def test_no_seed_double_module_opaque_learning_contract_regression(self) -> None:
        with tempfile.TemporaryDirectory(prefix="external-benchmark-multimodule-") as tmp:
            project = Path(tmp) / "learning_project"
            project.mkdir(parents=True)
            task_file = project / "external_multimodule_tasks.json"
            tasks: list[dict[str, Any]] = []
            expected_by_task: dict[str, tuple[str, ...]] = {}

            for family in _families():
                expected_files = tuple(sorted(family["modules"]))
                stage1 = project / f"stage1_{family['id']}"
                _write_workspace(stage1, family, family["stage1_tests"])
                result = run_agent_loop(
                    stage1,
                    "Fix the failing package tests without editing tests.",
                    explicit_mode="repair",
                    include_validation=True,
                    learning_context="off",
                    max_steps=12,
                )
                self.assertTrue(result.ok, result.to_dict())
                implementation = next(item for item in result.observations if item.name == "implement")
                self.assertEqual(tuple(sorted(implementation.data["files_touched"])), expected_files)

                proposal = propose_file_bundle_repair_skill_from_trajectory(
                    project,
                    result.trajectory_path,
                    workspace=stage1,
                    name=f"{family['id'].replace('_', '-')}-opaque-multimodule-repair",
                    description="Opaque-trigger package multi-module repair learned from a benchmark-style stage1 run.",
                    triggers=(family["trigger"],),
                )
                eval_result = run_skill_eval_command(
                    project,
                    f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                    summary=f"stage1 {family['id']} verifies against package tests",
                    evidence=(result.trajectory_path, str(stage1 / "tests" / f"test_{family['id']}.py")),
                    timeout_seconds=30,
                )
                self.assertTrue(eval_result.passed, eval_result.to_dict())
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=_with_learning_report(eval_result, _stage1_learning_report(family["id"]), proposal),
                )

                for index, test_source in enumerate(family["stage2_tests"], start=1):
                    task_id = f"{family['id']}_hidden_{index}"
                    expected_by_task[task_id] = expected_files
                    tasks.append(
                        {
                            "id": task_id,
                            "instruction": f"Fix the failing package tests using approved learning contract {family['trigger']}.",
                            "files": _task_files(family, test_source),
                            "test_command": "{python} -m unittest discover -s tests -q",
                            "max_iterations": 1,
                            "timeout_seconds": 30,
                            "tags": ["external-style", "opaque-trigger", "multi-module", "package-file-bundle"],
                        }
                    )

            task_file.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
            )
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=2,
            )

        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": len(tasks)})
        self.assertEqual(stability.summary()["solved"], len(tasks) * 2)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        for result in (*report.approved_learning_run.results, *(item for run in stability.runs for item in run.results)):
            self.assertEqual(result.status, "solved")
            self.assertEqual(tuple(sorted(result.patch_metrics.changed_files)), expected_by_task[result.task_id])
            self.assertEqual(result.patch_metrics.out_of_scope_files, ())


def _families() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "telemetry_names",
            "trigger": "opaque-regression-01",
            "modules": {
                "northstar/events/cleaning.py": "def canonical_event_name(value):\n    return str(value)\n",
                "northstar/events/fields.py": "def normalize_field_name(value):\n    return str(value)\n",
            },
            "stage1_tests": """
import unittest
from northstar.events.cleaning import canonical_event_name
from northstar.events.fields import normalize_field_name

class TestTelemetryNames(unittest.TestCase):
    def test_event_ids(self):
        self.assertEqual(canonical_event_name('  User Login!!  '), 'user-login')
        self.assertEqual(canonical_event_name('PAYMENT__Captured'), 'payment-captured')
    def test_field_names(self):
        self.assertEqual(normalize_field_name('  User ID  '), 'user id')
        self.assertEqual(normalize_field_name(' STATUS '), 'status')
""",
            "stage2_tests": (
                """
import unittest
from northstar.events.cleaning import canonical_event_name
from northstar.events.fields import normalize_field_name

class TestTelemetryNamesHiddenA(unittest.TestCase):
    def test_hidden_events(self):
        self.assertEqual(canonical_event_name('  Cart Add+++Item  '), 'cart-add-item')
        self.assertEqual(normalize_field_name('  Session Key '), 'session key')
""",
                """
import unittest
from northstar.events.cleaning import canonical_event_name
from northstar.events.fields import normalize_field_name

class TestTelemetryNamesHiddenB(unittest.TestCase):
    def test_hidden_events(self):
        self.assertEqual(canonical_event_name('MOBILE__Checkout Complete'), 'mobile-checkout-complete')
        self.assertEqual(normalize_field_name(' DEVICE TYPE '), 'device type')
""",
            ),
        },
        {
            "id": "ledger_math",
            "trigger": "opaque-regression-02",
            "modules": {
                "ledger/rules/totals.py": "def merge_total(a, b):\n    return a - b\n",
                "ledger/rules/weights.py": "def scale_units(a, b):\n    return a + b\n",
            },
            "stage1_tests": """
import unittest
from ledger.rules.totals import merge_total
from ledger.rules.weights import scale_units

class TestLedgerMath(unittest.TestCase):
    def test_totals(self):
        self.assertEqual(merge_total(8, 5), 13)
        self.assertEqual(merge_total(-2, 7), 5)
    def test_weights(self):
        self.assertEqual(scale_units(3, 4), 12)
        self.assertEqual(scale_units(6, 5), 30)
""",
            "stage2_tests": (
                """
import unittest
from ledger.rules.totals import merge_total
from ledger.rules.weights import scale_units

class TestLedgerMathHiddenA(unittest.TestCase):
    def test_hidden_math(self):
        self.assertEqual(merge_total(21, -4), 17)
        self.assertEqual(scale_units(7, 8), 56)
""",
                """
import unittest
from ledger.rules.totals import merge_total
from ledger.rules.weights import scale_units

class TestLedgerMathHiddenB(unittest.TestCase):
    def test_hidden_math(self):
        self.assertEqual(merge_total(0, 19), 19)
        self.assertEqual(scale_units(-3, 9), -27)
""",
            ),
        },
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_PARSE_FINITE_NUMBER_TARGET = "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js"
OPENCLAW_PARSE_FINITE_NUMBER_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "parse-finite-number-C3Woj8eC.js"
OPENCLAW_PARSE_TIMEOUT_TARGET = "third_party/openclaw/selected/parse-timeout-91AFhn8L.js"
OPENCLAW_PARSE_TIMEOUT_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "parse-timeout-91AFhn8L.js"
OPENCLAW_ARG_SPLIT_TARGET = "third_party/openclaw/selected/arg-split-DM7vx6uc.js"
OPENCLAW_ARG_SPLIT_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "arg-split-DM7vx6uc.js"
OPENCLAW_BALANCED_JSON_TARGET = "third_party/openclaw/selected/balanced-json-YUc2rvlg.js"
OPENCLAW_BALANCED_JSON_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "balanced-json-YUc2rvlg.js"
OPENCLAW_JSON_POINTER_TARGET = "third_party/openclaw/selected/json-pointer-BRH9eAOA.js"
OPENCLAW_JSON_POINTER_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "json-pointer-BRH9eAOA.js"
OPENCLAW_COMMAND_POLL_TARGET = "third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"
OPENCLAW_COMMAND_POLL_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "command-poll-backoff-DmjJeZIx.js"
OPENCLAW_ASYNC_LOCK_TARGET = "third_party/openclaw/selected/async-lock-BcLS4KOc.js"
OPENCLAW_ASYNC_LOCK_SOURCE = REPO_ROOT / "third_party" / "openclaw" / "selected" / "async-lock-BcLS4KOc.js"
MAKO_JS_LABELS_TARGET = "mako_js/labels.js"
MAKO_JS_ASYNC_RECORDS_TARGET = "mako_js/async_records.js"
MAKO_JS_IO_BOUNDARY_TARGET = "mako_js/io_boundary.js"
MAKO_JS_FS_MANIFEST_TARGET = "mako_js/fs_manifest.js"
MAKO_JS_HTTP_MANIFEST_TARGET = "mako_js/http_manifest.js"
MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET = "packages/core/mako_js/io_boundary.js"
OPENCLAW_MANIFEST = REPO_ROOT / "third_party" / "openclaw" / "MANIFEST.sha256"


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _openmako_repair_hint(body: str) -> dict[str, Any]:
    marker = "```openmako-repair"
    start = body.index(marker) + len(marker)
    end = body.index("```", start)
    return json.loads(body[start:end].strip())


def _broken_openclaw_parse_strict_integer_source(source: str) -> str:
    original = (
        "function parseStrictInteger(value) {\n"
        "\tif (typeof value === \"number\") return Number.isSafeInteger(value) ? value : void 0;\n"
        "\tif (typeof value !== \"string\") return;\n"
        "\tconst normalized = normalizeNumericString(value);\n"
        "\tif (!normalized || !/^[+-]?\\d+$/.test(normalized)) return;\n"
        "\tconst parsed = Number(normalized);\n"
        "\treturn Number.isSafeInteger(parsed) ? parsed : void 0;\n"
        "}"
    )
    broken = (
        "function parseStrictInteger(value) {\n"
        "\tif (typeof value === \"number\") return value;\n"
        "\tif (typeof value === \"string\") return Number.parseInt(value, 10);\n"
        "}"
    )
    if original not in source:
        raise AssertionError("OpenClaw parseStrictInteger source fingerprint changed")
    return source.replace(original, broken)


def _openclaw_parse_strict_integer_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as parseStrictInteger, i as parseStrictPositiveInteger, r as parseStrictNonNegativeInteger } from '../third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js';\n\n"
        "assert.equal(parseStrictInteger(' 42 '), 42);\n"
        "assert.equal(parseStrictInteger('+17'), 17);\n"
        "assert.equal(parseStrictInteger('-8'), -8);\n"
        "assert.equal(parseStrictInteger('42px'), undefined);\n"
        "assert.equal(parseStrictInteger('4.2'), undefined);\n"
        "assert.equal(parseStrictInteger(Number.MAX_SAFE_INTEGER + 1), undefined);\n"
        "assert.equal(parseStrictPositiveInteger('7'), 7);\n"
        "assert.equal(parseStrictPositiveInteger('0'), undefined);\n"
        "assert.equal(parseStrictNonNegativeInteger('0'), 0);\n"
    )


def _openclaw_parse_strict_integer_hidden_bounds_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as parseStrictInteger, i as parseStrictPositiveInteger, r as parseStrictNonNegativeInteger } from '../third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js';\n\n"
        "assert.equal(parseStrictInteger('0008'), 8);\n"
        "assert.equal(parseStrictInteger('-0008'), -8);\n"
        "assert.equal(parseStrictInteger('8.0'), undefined);\n"
        "assert.equal(parseStrictInteger('1e3'), undefined);\n"
        "assert.equal(parseStrictInteger(''), undefined);\n"
        "assert.equal(parseStrictPositiveInteger('12'), 12);\n"
        "assert.equal(parseStrictPositiveInteger('-1'), undefined);\n"
        "assert.equal(parseStrictNonNegativeInteger('+0'), 0);\n"
    )


def _openclaw_parse_strict_integer_hidden_safe_range_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as parseStrictInteger, i as parseStrictPositiveInteger, r as parseStrictNonNegativeInteger } from '../third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js';\n\n"
        "assert.equal(parseStrictInteger(Number.MAX_SAFE_INTEGER), Number.MAX_SAFE_INTEGER);\n"
        "assert.equal(parseStrictInteger(Number.MIN_SAFE_INTEGER), Number.MIN_SAFE_INTEGER);\n"
        "assert.equal(parseStrictInteger(Number.MAX_SAFE_INTEGER + 2), undefined);\n"
        "assert.equal(parseStrictInteger('9007199254740992'), undefined);\n"
        "assert.equal(parseStrictInteger('  -17  '), -17);\n"
        "assert.equal(parseStrictPositiveInteger('+23'), 23);\n"
        "assert.equal(parseStrictPositiveInteger(Number.MIN_SAFE_INTEGER), undefined);\n"
        "assert.equal(parseStrictNonNegativeInteger('000'), 0);\n"
    )


def _broken_openclaw_parse_timeout_source(source: str) -> str:
    original_parse = (
        "function parseTimeoutMs(raw) {\n"
        "\tif (raw === void 0 || raw === null) return;\n"
        "\tlet value = NaN;\n"
        "\tif (typeof raw === \"number\") value = raw;\n"
        "\telse if (typeof raw === \"bigint\") value = Number(raw);\n"
        "\telse if (typeof raw === \"string\") {\n"
        "\t\tconst trimmed = raw.trim();\n"
        "\t\tif (!trimmed) return;\n"
        "\t\tvalue = Number.parseInt(trimmed, 10);\n"
        "\t}\n"
        "\treturn Number.isFinite(value) ? value : void 0;\n"
        "}"
    )
    broken_parse = (
        "function parseTimeoutMs(raw) {\n"
        "\treturn Number.parseInt(raw, 10) || 0;\n"
        "}"
    )
    original_fallback = (
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {}) {\n"
        "\tif (raw === void 0 || raw === null) return fallbackMs;\n"
        "\tconst value = typeof raw === \"string\" ? raw.trim() : typeof raw === \"number\" || typeof raw === \"bigint\" ? String(raw) : null;\n"
        "\tif (value === null) {\n"
        "\t\tif (options.invalidType === \"error\") throw invalidTimeout();\n"
        "\t\treturn fallbackMs;\n"
        "\t}\n"
        "\tif (!value) return fallbackMs;\n"
        "\tconst parsed = Number.parseInt(value, 10);\n"
        "\tif (!Number.isFinite(parsed) || parsed <= 0) throw invalidTimeout(value);\n"
        "\treturn parsed;\n"
        "}"
    )
    broken_fallback = (
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {}) {\n"
        "\tconst parsed = Number.parseInt(raw, 10);\n"
        "\treturn Number.isFinite(parsed) ? parsed : fallbackMs;\n"
        "}"
    )
    if original_parse not in source or original_fallback not in source:
        raise AssertionError("OpenClaw parse-timeout source fingerprint changed")
    return source.replace(original_parse, broken_parse).replace(original_fallback, broken_fallback)


def _openclaw_parse_timeout_package_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { parseTimeoutMs, parseTimeoutMsWithFallback } from '../src/timeout.js';\n\n"
        "assert.equal(parseTimeoutMs(' 2500ms '), 2500);\n"
        "assert.equal(parseTimeoutMs(15n), 15);\n"
        "assert.equal(parseTimeoutMs({ value: 1 }), undefined);\n"
        "assert.equal(parseTimeoutMsWithFallback(undefined, 30000), 30000);\n"
        "assert.equal(parseTimeoutMsWithFallback(' 1200 ', 30000), 1200);\n"
        "assert.throws(() => parseTimeoutMsWithFallback('0', 30000), /Invalid --timeout/);\n"
        "assert.throws(() => parseTimeoutMsWithFallback({}, 30000, { invalidType: 'error' }), /Invalid --timeout/);\n"
    )


def _openclaw_parse_timeout_hidden_invalid_values_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { parseTimeoutMs, parseTimeoutMsWithFallback } from '../src/timeout.js';\n\n"
        "assert.equal(parseTimeoutMs(''), undefined);\n"
        "assert.equal(parseTimeoutMs(null), undefined);\n"
        "assert.equal(parseTimeoutMs('30 seconds'), 30);\n"
        "assert.equal(parseTimeoutMsWithFallback('', 5000), 5000);\n"
        "assert.equal(parseTimeoutMsWithFallback(null, 5000), 5000);\n"
        "assert.throws(() => parseTimeoutMsWithFallback('-1', 5000), /Invalid --timeout/);\n"
        "assert.throws(() => parseTimeoutMsWithFallback('NaN', 5000), /Invalid --timeout/);\n"
    )


def _openclaw_parse_timeout_hidden_type_edges_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { parseTimeoutMs, parseTimeoutMsWithFallback } from '../src/timeout.js';\n\n"
        "assert.equal(parseTimeoutMs(42), 42);\n"
        "assert.equal(parseTimeoutMs(42n), 42);\n"
        "assert.equal(parseTimeoutMs(Symbol.for('timeout')), undefined);\n"
        "assert.equal(parseTimeoutMsWithFallback(42n, 1000), 42);\n"
        "assert.equal(parseTimeoutMsWithFallback(false, 1000), 1000);\n"
        "assert.throws(() => parseTimeoutMsWithFallback(false, 1000, { invalidType: 'error' }), /Invalid --timeout/);\n"
        "assert.throws(() => parseTimeoutMsWithFallback(0, 1000), /Invalid --timeout/);\n"
    )


def _broken_openclaw_arg_split_source(source: str) -> str:
    return _replace_javascript_function_source(
        source,
        "splitArgsPreservingQuotes",
        "function splitArgsPreservingQuotes(value, options) {\n"
        "\treturn value.trim() ? value.trim().split(/\\s+/) : [];\n"
        "}",
    )


def _openclaw_arg_split_package_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { splitArgsPreservingQuotes } from '../src/args.js';\n\n"
        "assert.deepEqual(splitArgsPreservingQuotes('run \"hello world\" now'), ['run', 'hello world', 'now']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('cmd a\\\\ b \"c d\"', { escapeMode: 'backslash' }), ['cmd', 'a b', 'c d']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes(\"deploy 'west zone'\", { quoteChars: [\"'\"] }), ['deploy', 'west zone']);\n"
    )


def _openclaw_arg_split_hidden_backslash_quotes_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { splitArgsPreservingQuotes } from '../src/args.js';\n\n"
        "assert.deepEqual(splitArgsPreservingQuotes('alpha \"two words\" beta'), ['alpha', 'two words', 'beta']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('path foo\\\\ bar baz'), ['path', 'foo\\\\', 'bar', 'baz']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('say \\\\\"hello world\\\\\" now', { escapeMode: 'backslash-quote-only' }), ['say', '\"hello', 'world\"', 'now']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('path foo\\\\ bar baz', { escapeMode: 'backslash-quote-only' }), ['path', 'foo\\\\', 'bar', 'baz']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('path foo\\\\ bar baz', { escapeMode: 'backslash' }), ['path', 'foo bar', 'baz']);\n"
    )


def _openclaw_arg_split_hidden_quote_start_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { splitArgsPreservingQuotes } from '../src/args.js';\n\n"
        "assert.deepEqual(splitArgsPreservingQuotes('a\"b c\" d', { quoteStart: 'start' }), ['a\"b', 'c\"', 'd']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes('\"b c\" d', { quoteStart: 'start' }), ['b c', 'd']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes(\"cmd 'two words' tail\", { quoteChars: [\"'\"] }), ['cmd', 'two words', 'tail']);\n"
        "assert.deepEqual(splitArgsPreservingQuotes(\"cmd \\\"two words\\\" 'three four'\", { quoteChars: [\"'\", '\"'] }), ['cmd', 'two words', 'three four']);\n"
    )


def _broken_openclaw_balanced_json_source(source: str) -> str:
    broken = _replace_javascript_function_source(
        source,
        "extractBalancedJsonPrefix",
        "function extractBalancedJsonPrefix(raw, opts = {}) {\n"
        "\treturn null;\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "extractBalancedJsonFragments",
        "function extractBalancedJsonFragments(raw, opts = {}) {\n"
        "\treturn [];\n"
        "}",
    )
    if broken == source:
        raise AssertionError("OpenClaw balanced-json source replacement did not change source")
    return broken


def _javascript_function_body_start_source(source: str, function_name: str) -> tuple[int, int]:
    marker = f"function {function_name}("
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"JavaScript function not found: {function_name}")
    paren_start = start + len(marker) - 1
    depth = 0
    in_string = ""
    escaped = False
    paren_end = -1
    for index in range(paren_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {"'", '"', "`"}:
            in_string = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                paren_end = index
                break
    if paren_end < 0:
        raise AssertionError(f"JavaScript function signature did not terminate: {function_name}")
    brace_start = paren_end + 1
    while brace_start < len(source) and source[brace_start].isspace():
        brace_start += 1
    if brace_start >= len(source) or source[brace_start] != "{":
        raise AssertionError(f"JavaScript function has no body: {function_name}")
    return start, brace_start


def _replace_javascript_function_source(source: str, function_name: str, replacement: str) -> str:
    start, brace_start = _javascript_function_body_start_source(source, function_name)
    depth = 0
    in_string = ""
    escaped = False
    for index in range(brace_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {"'", '"', "`"}:
            in_string = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement + source[index + 1 :]
    raise AssertionError(f"JavaScript function did not terminate: {function_name}")


def _openclaw_balanced_json_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n\n"
        "assert.deepEqual(extractBalancedJsonPrefix('xx {\"a\":[1,{\"b\":\"}\"}]} tail'), { json: '{\"a\":[1,{\"b\":\"}\"}]}', startIndex: 3, endIndex: 21 });\n"
        "assert.deepEqual(extractBalancedJsonPrefix('skip [1,{\"x\":\"[\"}] rest', { openers: ['['] }), { json: '[1,{\"x\":\"[\"}]', startIndex: 5, endIndex: 17 });\n"
        "assert.deepEqual(extractBalancedJsonFragments('a {\"a\":1} b [2,{\"c\":3}]'), [\n"
        "  { json: '{\"a\":1}', startIndex: 2, endIndex: 8 },\n"
        "  { json: '[2,{\"c\":3}]', startIndex: 12, endIndex: 22 },\n"
        "]);\n"
    )


def _openclaw_balanced_json_hidden_strings_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n\n"
        "const escapedQuote = String.raw`pre {\"quote\":\"he said \\\"hi\\\"\",\"arr\":[1]} tail`;\n"
        "assert.deepEqual(extractBalancedJsonPrefix(escapedQuote), { json: String.raw`{\"quote\":\"he said \\\"hi\\\"\",\"arr\":[1]}`, startIndex: 4, endIndex: 39 });\n"
        "assert.deepEqual(extractBalancedJsonPrefix('prefix {\"msg\":\"brace } in text\",\"list\":[1]} suffix'), { json: '{\"msg\":\"brace } in text\",\"list\":[1]}', startIndex: 7, endIndex: 42 });\n"
        "assert.deepEqual(extractBalancedJsonPrefix('noise [\"}\", {\"k\": [1,2]}] end'), { json: '[\"}\", {\"k\": [1,2]}]', startIndex: 6, endIndex: 24 });\n"
        "assert.equal(extractBalancedJsonPrefix('skip {\"x\":1}', { openers: ['['] }), null);\n"
    )


def _openclaw_balanced_json_hidden_fragments_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n\n"
        "assert.deepEqual(extractBalancedJsonPrefix('lead [1,{\"nested\":[2,3]}] tail', { openers: ['['] }), { json: '[1,{\"nested\":[2,3]}]', startIndex: 5, endIndex: 24 });\n"
        "assert.deepEqual(extractBalancedJsonFragments('one [1] two {\"b\":2} three [3,{\"c\":\"}\"}]'), [\n"
        "  { json: '[1]', startIndex: 4, endIndex: 6 },\n"
        "  { json: '{\"b\":2}', startIndex: 12, endIndex: 18 },\n"
        "  { json: '[3,{\"c\":\"}\"}]', startIndex: 26, endIndex: 38 },\n"
        "]);\n"
    )


def _broken_openclaw_json_pointer_source(source: str) -> str:
    broken = _replace_javascript_function_source(
        source,
        "decodeJsonPointerToken",
        "function decodeJsonPointerToken(token) {\n"
        "\treturn token;\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "encodeJsonPointerToken",
        "function encodeJsonPointerToken(token) {\n"
        "\treturn token;\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "readJsonPointer",
        "function readJsonPointer(root, pointer, options = {}) {\n"
        "\tif (!pointer.startsWith(\"/\")) return undefined;\n"
        "\treturn root[pointer];\n"
        "}",
    )
    if broken == source:
        raise AssertionError("OpenClaw json-pointer source replacement did not change source")
    return broken


def _openclaw_json_pointer_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "const root = {\n"
        "  providers: { openai: { 'api/key': 'sk-live', 'tilde~name': 'escaped' } },\n"
        "  list: [{ name: 'zero' }, { name: 'one' }]\n"
        "};\n"
        "assert.equal(readJsonPointer(root, '/providers/openai/api~1key'), 'sk-live');\n"
        "assert.equal(readJsonPointer(root, '/providers/openai/tilde~0name'), 'escaped');\n"
        "assert.deepEqual(readJsonPointer(root, '/list/1'), { name: 'one' });\n"
        "assert.equal(readJsonPointer(root, '/list/5', { onMissing: 'undefined' }), undefined);\n"
        "assert.equal(readJsonPointer(root, 'providers/openai', { onMissing: 'undefined' }), undefined);\n"
        "assert.equal(encodeJsonPointerToken('api/key~prod'), 'api~1key~0prod');\n"
    )


def _openclaw_json_pointer_hidden_escaped_tokens_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "const root = { 'a/b': { 'tilde~': ['zero', { 'x/y~z': 7 }] } };\n"
        "assert.equal(readJsonPointer(root, '/a~1b/tilde~0/1/x~1y~0z'), 7);\n"
        "assert.equal(encodeJsonPointerToken('x/y~z'), 'x~1y~0z');\n"
        "assert.deepEqual(readJsonPointer(root, '/a~1b/tilde~0/0'), 'zero');\n"
    )


def _openclaw_json_pointer_hidden_missing_modes_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "const root = { list: [{ value: 'a' }], object: { child: 3 }, scalar: 'leaf' };\n"
        "assert.equal(readJsonPointer(root, '/list/1/value', { onMissing: 'undefined' }), undefined);\n"
        "assert.equal(readJsonPointer(root, '/scalar/child', { onMissing: 'undefined' }), undefined);\n"
        "assert.equal(readJsonPointer(root, 'object/child', { onMissing: 'undefined' }), undefined);\n"
        "assert.throws(() => readJsonPointer(root, '/object/missing'), /does not exist/);\n"
        "assert.equal(encodeJsonPointerToken('plain'), 'plain');\n"
    )


def _broken_openclaw_command_poll_source(source: str) -> str:
    broken = _replace_javascript_function_source(
        source,
        "calculateBackoffMs",
        "function calculateBackoffMs(consecutiveNoOutputPolls) {\n"
        "\treturn 0;\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "recordCommandPoll",
        "function recordCommandPoll(state, commandId, hasNewOutput) {\n"
        "\tif (!state.commandPollCounts) state.commandPollCounts = new Map();\n"
        "\tstate.commandPollCounts.set(commandId, { count: 0, lastPollAt: Date.now() });\n"
        "\treturn 0;\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "resetCommandPollCount",
        "function resetCommandPollCount(state, commandId) {\n"
        "\tstate.commandPollCounts = new Map();\n"
        "}",
    )
    broken = _replace_javascript_function_source(
        broken,
        "pruneStaleCommandPolls",
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5) {\n"
        "\treturn;\n"
        "}",
    )
    if broken == source:
        raise AssertionError("OpenClaw command-poll source replacement did not change source")
    return broken


def _openclaw_command_poll_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as recordCommandPoll, r as resetCommandPollCount, t as pruneStaleCommandPolls } from '../third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js';\n\n"
        "const originalNow = Date.now;\n"
        "Date.now = () => 1000;\n"
        "try {\n"
        "  const state = {};\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 5000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 10000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 30000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 60000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 60000);\n"
        "  assert.equal(state.commandPollCounts.get('cmd-a').count, 4);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', true), 5000);\n"
        "  assert.equal(state.commandPollCounts.get('cmd-a').count, 0);\n"
        "  resetCommandPollCount(state, 'cmd-a');\n"
        "  assert.equal(state.commandPollCounts.has('cmd-a'), false);\n"
        "  state.commandPollCounts.set('old', { count: 3, lastPollAt: 0 });\n"
        "  state.commandPollCounts.set('fresh', { count: 1, lastPollAt: 999 });\n"
        "  pruneStaleCommandPolls(state, 500);\n"
        "  assert.equal(state.commandPollCounts.has('old'), false);\n"
        "  assert.equal(state.commandPollCounts.has('fresh'), true);\n"
        "} finally {\n"
        "  Date.now = originalNow;\n"
        "}\n"
    )


def _openclaw_command_poll_hidden_reset_isolated_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as recordCommandPoll, r as resetCommandPollCount, t as pruneStaleCommandPolls } from '../third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js';\n\n"
        "const originalNow = Date.now;\n"
        "Date.now = () => 2000;\n"
        "try {\n"
        "  const state = {};\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 5000);\n"
        "  assert.equal(state.commandPollCounts instanceof Map, true);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-b', false), 5000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 10000);\n"
        "  resetCommandPollCount(state, 'cmd-a');\n"
        "  assert.equal(state.commandPollCounts.has('cmd-a'), false);\n"
        "  assert.equal(state.commandPollCounts.get('cmd-b').count, 0);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 5000);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-b', false), 10000);\n"
        "  pruneStaleCommandPolls(state, 100000);\n"
        "  assert.equal(state.commandPollCounts.has('cmd-a'), true);\n"
        "  assert.equal(state.commandPollCounts.has('cmd-b'), true);\n"
        "  const empty = {};\n"
        "  resetCommandPollCount(empty, 'missing');\n"
        "  pruneStaleCommandPolls(empty, 1);\n"
        "  assert.equal(empty.commandPollCounts, undefined);\n"
        "} finally {\n"
        "  Date.now = originalNow;\n"
        "}\n"
    )


def _openclaw_command_poll_hidden_prune_boundaries_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as recordCommandPoll, r as resetCommandPollCount, t as pruneStaleCommandPolls } from '../third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js';\n\n"
        "const originalNow = Date.now;\n"
        "let now = 10000;\n"
        "Date.now = () => now;\n"
        "try {\n"
        "  const state = {};\n"
        "  for (let index = 0; index < 8; index += 1) recordCommandPoll(state, 'cmd-long', false);\n"
        "  assert.equal(recordCommandPoll(state, 'cmd-long', false), 60000);\n"
        "  assert.equal(state.commandPollCounts.get('cmd-long').count, 8);\n"
        "  state.commandPollCounts.set('boundary', { count: 2, lastPollAt: 9000 });\n"
        "  state.commandPollCounts.set('stale', { count: 2, lastPollAt: 8999 });\n"
        "  pruneStaleCommandPolls(state, 1000);\n"
        "  assert.equal(state.commandPollCounts.has('boundary'), true);\n"
        "  assert.equal(state.commandPollCounts.has('stale'), false);\n"
        "  assert.equal(recordCommandPoll(state, 'boundary', false), 60000);\n"
        "  assert.equal(state.commandPollCounts.get('boundary').count, 3);\n"
        "  resetCommandPollCount(state, 'missing');\n"
        "  assert.equal(state.commandPollCounts.has('cmd-long'), true);\n"
        "} finally {\n"
        "  Date.now = originalNow;\n"
        "}\n"
    )


def _broken_openclaw_async_lock_source(source: str) -> str:
    broken = _replace_javascript_function_source(
        source,
        "createAsyncLock",
        "function createAsyncLock() {\n"
        "\treturn async function withLock(fn) {\n"
        "\t\treturn await fn();\n"
        "\t};\n"
        "}",
    )
    if broken == source:
        raise AssertionError("OpenClaw async-lock source replacement did not change source")
    return broken


def _openclaw_async_lock_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { t as createAsyncLock } from '../third_party/openclaw/selected/async-lock-BcLS4KOc.js';\n\n"
        "function deferred() {\n"
        "  let resolve;\n"
        "  const promise = new Promise((done) => { resolve = done; });\n"
        "  return { promise, resolve };\n"
        "}\n\n"
        "const lock = createAsyncLock();\n"
        "const releaseFirst = deferred();\n"
        "const events = [];\n"
        "let active = 0;\n"
        "let maxActive = 0;\n"
        "const first = lock(async () => {\n"
        "  active += 1;\n"
        "  maxActive = Math.max(maxActive, active);\n"
        "  events.push('first-start');\n"
        "  await releaseFirst.promise;\n"
        "  events.push('first-end');\n"
        "  active -= 1;\n"
        "  return 'first';\n"
        "});\n"
        "let secondStarted = false;\n"
        "const second = lock(async () => {\n"
        "  secondStarted = true;\n"
        "  active += 1;\n"
        "  maxActive = Math.max(maxActive, active);\n"
        "  events.push('second-start');\n"
        "  active -= 1;\n"
        "  return 'second';\n"
        "});\n"
        "await Promise.resolve();\n"
        "await Promise.resolve();\n"
        "assert.equal(secondStarted, false);\n"
        "releaseFirst.resolve();\n"
        "assert.deepEqual(await Promise.all([first, second]), ['first', 'second']);\n"
        "assert.equal(maxActive, 1);\n"
        "assert.deepEqual(events, ['first-start', 'first-end', 'second-start']);\n"
        "await assert.rejects(lock(async () => { throw new Error('boom'); }), /boom/);\n"
        "assert.equal(await lock(async () => 'after'), 'after');\n"
    )


def _openclaw_async_lock_hidden_serial_order_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { t as createAsyncLock } from '../third_party/openclaw/selected/async-lock-BcLS4KOc.js';\n\n"
        "function deferred() {\n"
        "  let resolve;\n"
        "  const promise = new Promise((done) => { resolve = done; });\n"
        "  return { promise, resolve };\n"
        "}\n\n"
        "const lock = createAsyncLock();\n"
        "const releaseA = deferred();\n"
        "const events = [];\n"
        "const a = lock(async () => {\n"
        "  events.push('a:start');\n"
        "  await releaseA.promise;\n"
        "  events.push('a:end');\n"
        "  return 'a';\n"
        "});\n"
        "let bStarted = false;\n"
        "let cStarted = false;\n"
        "const b = lock(async () => { bStarted = true; events.push('b'); return 'b'; });\n"
        "const c = lock(async () => { cStarted = true; events.push('c'); return 'c'; });\n"
        "await Promise.resolve();\n"
        "await Promise.resolve();\n"
        "assert.equal(bStarted, false);\n"
        "assert.equal(cStarted, false);\n"
        "releaseA.resolve();\n"
        "assert.deepEqual(await Promise.all([a, b, c]), ['a', 'b', 'c']);\n"
        "assert.deepEqual(events, ['a:start', 'a:end', 'b', 'c']);\n"
    )


def _openclaw_async_lock_hidden_parallel_and_rejection_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { t as createAsyncLock } from '../third_party/openclaw/selected/async-lock-BcLS4KOc.js';\n\n"
        "function deferred() {\n"
        "  let resolve;\n"
        "  const promise = new Promise((done) => { resolve = done; });\n"
        "  return { promise, resolve };\n"
        "}\n\n"
        "const serial = createAsyncLock();\n"
        "const releaseSerial = deferred();\n"
        "let queuedStarted = false;\n"
        "const serialFirst = serial(async () => { await releaseSerial.promise; return 'serial-first'; });\n"
        "const serialSecond = serial(async () => { queuedStarted = true; return 'serial-second'; });\n"
        "await Promise.resolve();\n"
        "await Promise.resolve();\n"
        "assert.equal(queuedStarted, false);\n"
        "releaseSerial.resolve();\n"
        "assert.deepEqual(await Promise.all([serialFirst, serialSecond]), ['serial-first', 'serial-second']);\n"
        "const left = createAsyncLock();\n"
        "const right = createAsyncLock();\n"
        "const releaseLeft = deferred();\n"
        "const releaseRight = deferred();\n"
        "const events = [];\n"
        "const leftRun = left(async () => { events.push('left:start'); await releaseLeft.promise; events.push('left:end'); return 'left'; });\n"
        "const rightRun = right(async () => { events.push('right:start'); await releaseRight.promise; events.push('right:end'); return 'right'; });\n"
        "await Promise.resolve();\n"
        "await Promise.resolve();\n"
        "assert.deepEqual(events, ['left:start', 'right:start']);\n"
        "releaseRight.resolve();\n"
        "assert.equal(await rightRun, 'right');\n"
        "assert.deepEqual(events, ['left:start', 'right:start', 'right:end']);\n"
        "releaseLeft.resolve();\n"
        "assert.equal(await leftRun, 'left');\n"
        "const lock = createAsyncLock();\n"
        "await assert.rejects(lock(async () => { throw new Error('first failed'); }), /first failed/);\n"
        "assert.equal(await lock(async () => 'released'), 'released');\n"
    )


def _mako_js_labels_source() -> str:
    return (
        "function compactLabel(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn normalized.replace(/[^a-z0-9]+/g, \"-\").replace(/^-+|-+$/g, \"\");\n"
        "}\n"
        "function labelKey(value) {\n"
        "\tconst compacted = compactLabel(value);\n"
        "\treturn compacted ? `label:${compacted}` : \"label\";\n"
        "}\n"
        "export { compactLabel, labelKey };\n"
    )


def _broken_mako_js_labels_source() -> str:
    return (
        "function compactLabel(value) {\n"
        "\treturn String(value);\n"
        "}\n"
        "function labelKey(value) {\n"
        "\treturn compactLabel(value);\n"
        "}\n"
        "export { compactLabel, labelKey };\n"
    )


def _mako_js_async_records_source() -> str:
    return (
        "function normalizeUserId(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn /^[a-z0-9_-]+$/.test(normalized) ? normalized : \"\";\n"
        "}\n"
        "function summarizeUser(record) {\n"
        "\tif (!record || typeof record !== \"object\") return null;\n"
        "\tconst id = normalizeUserId(record.id);\n"
        "\tif (!id) return null;\n"
        "\tconst name = String(record.name ?? \"\").trim() || id;\n"
        "\tconst roles = Array.isArray(record.roles) ? record.roles.map((role) => String(role ?? \"\").trim().toLowerCase()).filter(Boolean).sort() : [];\n"
        "\treturn { id, name, roles };\n"
        "}\n"
        "async function loadUserSummaries(client, userIds, options = {}) {\n"
        "\tconst concurrency = Math.max(1, Math.min(Number(options.concurrency ?? 2) || 2, 5));\n"
        "\tconst ids = [...new Set(userIds.map((id) => normalizeUserId(id)).filter(Boolean))];\n"
        "\tconst users = [];\n"
        "\tconst errors = [];\n"
        "\tfor (let index = 0; index < ids.length; index += concurrency) {\n"
        "\t\tconst batch = ids.slice(index, index + concurrency);\n"
        "\t\tconst settled = await Promise.all(batch.map(async (id) => {\n"
        "\t\t\ttry {\n"
        "\t\t\t\treturn { id, record: await client.fetchUser(id) };\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\treturn { id, error };\n"
        "\t\t\t}\n"
        "\t\t}));\n"
        "\t\tfor (const item of settled) {\n"
        "\t\t\tif (item.error) {\n"
        "\t\t\t\terrors.push({ id: item.id, message: String(item.error?.message ?? item.error) });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tconst summary = summarizeUser(item.record);\n"
        "\t\t\tif (summary) users.push(summary);\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { users, errors };\n"
        "}\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser };\n"
    )


def _broken_mako_js_async_records_source() -> str:
    return (
        "function normalizeUserId(value) {\n"
        "\treturn String(value);\n"
        "}\n"
        "function summarizeUser(record) {\n"
        "\treturn record;\n"
        "}\n"
        "async function loadUserSummaries(client, userIds, options = {}) {\n"
        "\treturn { users: [], errors: [] };\n"
        "}\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser };\n"
    )


def _mako_js_io_boundary_source() -> str:
    return (
        "async function scanWorkspaceManifest(readText, root, candidateFiles) {\n"
        "\tconst normalizeRoot = (value) => {\n"
        "\t\tconst normalized = String(value ?? \"\").trim().replace(/\\\\+/g, \"/\").replace(/\\/+$/g, \"\");\n"
        "\t\treturn normalized || \".\";\n"
        "\t};\n"
        "\tconst cleanCandidate = (value) => {\n"
        "\t\tconst normalized = String(value ?? \"\").trim().replace(/\\\\+/g, \"/\").replace(/^\\/+/, \"\");\n"
        "\t\tconst parts = normalized.split(\"/\").filter(Boolean);\n"
        "\t\tif (!parts.length || parts.some((part) => part === \".\" || part === \"..\" || part.startsWith(\".\"))) return \"\";\n"
        "\t\treturn parts.join(\"/\");\n"
        "\t};\n"
        "\tconst compactName = (value) => String(value ?? \"\").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, \"-\").replace(/^-+|-+$/g, \"\");\n"
        "\tconst summarize = (path, data) => {\n"
        "\t\tif (path.endsWith(\"/package.json\")) {\n"
        "\t\t\treturn { path, kind: \"package\", name: compactName(data?.name), version: String(data?.version ?? \"\"), private: Boolean(data?.private) };\n"
        "\t\t}\n"
        "\t\tif (path.endsWith(\"mako.json\")) {\n"
        "\t\t\treturn { path, kind: \"mako\", owner: compactName(data?.owner), taskCount: Array.isArray(data?.tasks) ? data.tasks.length : 0 };\n"
        "\t\t}\n"
        "\t\treturn { path, kind: \"json\", keyCount: data && typeof data === \"object\" && !Array.isArray(data) ? Object.keys(data).length : 0 };\n"
        "\t};\n"
        "\tconst safeRoot = normalizeRoot(root);\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tfor (const candidate of candidateFiles) {\n"
        "\t\tconst clean = cleanCandidate(candidate);\n"
        "\t\tif (!clean) continue;\n"
        "\t\tconst path = `${safeRoot}/${clean}`;\n"
        "\t\ttry {\n"
        "\t\t\tconst text = await readText(path);\n"
        "\t\t\tlet data;\n"
        "\t\t\ttry {\n"
        "\t\t\t\tdata = JSON.parse(String(text ?? \"\"));\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\tinvalid.push({ path, reason: \"json\" });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tfound.push(summarize(path, data));\n"
        "\t\t} catch (error) {\n"
        "\t\t\tconst code = String(error?.code ?? \"\");\n"
        "\t\t\tif (code === \"ENOENT\") {\n"
        "\t\t\t\tmissing.push(path);\n"
        "\t\t\t} else {\n"
        "\t\t\t\terrors.push({ path, code: code || \"ERROR\" });\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { root: safeRoot, found, missing, invalid, errors };\n"
        "}\n"
        "export { scanWorkspaceManifest };\n"
    )


def _broken_mako_js_io_boundary_source() -> str:
    return (
        "async function scanWorkspaceManifest(readText, root, candidateFiles) {\n"
        "\treturn { root, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { scanWorkspaceManifest };\n"
    )


def _mako_js_fs_manifest_source() -> str:
    return (
        "import { readdir, readFile, stat } from \"node:fs/promises\";\n"
        "import path from \"node:path\";\n\n"
        "async function scanFsPackageManifest(root, options = {}) {\n"
        "\tconst rootPath = path.resolve(String(root ?? \".\"));\n"
        "\tconst maxDepth = Math.max(0, Math.min(Number(options.maxDepth ?? 2) || 2, 5));\n"
        "\tconst required = Array.isArray(options.required) ? options.required : [];\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tconst candidates = new Set(required.map((item) => String(item ?? \"\").replace(/\\\\+/g, \"/\").replace(/^\\/+/, \"\")).filter(Boolean));\n"
        "\tconst visit = async (dir, depth) => {\n"
        "\t\tif (depth > maxDepth) return;\n"
        "\t\tlet entries;\n"
        "\t\ttry {\n"
        "\t\t\tentries = await readdir(dir, { withFileTypes: true });\n"
        "\t\t} catch (error) {\n"
        "\t\t\terrors.push({ path: dir, code: String(error?.code ?? \"ERROR\") });\n"
        "\t\t\treturn;\n"
        "\t\t}\n"
        "\t\tentries.sort((left, right) => left.name.localeCompare(right.name));\n"
        "\t\tfor (const entry of entries) {\n"
        "\t\t\tif (entry.name === \"node_modules\" || entry.name.startsWith(\".\")) continue;\n"
        "\t\t\tconst fullPath = path.join(dir, entry.name);\n"
        "\t\t\tconst relative = path.relative(rootPath, fullPath).replace(/\\\\+/g, \"/\");\n"
        "\t\t\tif (entry.isDirectory()) {\n"
        "\t\t\t\tawait visit(fullPath, depth + 1);\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tif (entry.name === \"package.json\" || entry.name === \"package-lock.json\" || entry.name.endsWith(\".mako.json\")) {\n"
        "\t\t\t\tcandidates.add(relative);\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t};\n"
        "\tconst summarize = (relative, data) => {\n"
        "\t\tif (relative.endsWith(\"package-lock.json\")) {\n"
        "\t\t\tconst packages = data && typeof data === \"object\" && data.packages && typeof data.packages === \"object\" ? Object.keys(data.packages).length : 0;\n"
        "\t\t\treturn { path: relative, kind: \"package-lock\", lockfileVersion: Number(data?.lockfileVersion ?? 0), packageCount: packages };\n"
        "\t\t}\n"
        "\t\tif (relative.endsWith(\"package.json\")) {\n"
        "\t\t\tconst deps = data && typeof data === \"object\" && data.dependencies && typeof data.dependencies === \"object\" ? Object.values(data.dependencies) : [];\n"
        "\t\t\treturn { path: relative, kind: \"package\", name: String(data?.name ?? \"\"), version: String(data?.version ?? \"\"), dependencyCount: deps.length, localDependencyCount: deps.filter((value) => String(value).startsWith(\"file:\")).length };\n"
        "\t\t}\n"
        "\t\tif (relative.endsWith(\".mako.json\")) {\n"
        "\t\t\treturn { path: relative, kind: \"mako\", owner: String(data?.owner ?? \"\").trim().toLowerCase(), taskCount: Array.isArray(data?.tasks) ? data.tasks.length : 0 };\n"
        "\t\t}\n"
        "\t\treturn { path: relative, kind: \"json\" };\n"
        "\t};\n"
        "\tawait visit(rootPath, 0);\n"
        "\tfor (const relative of [...candidates].sort()) {\n"
        "\t\tif (relative.split(\"/\").some((part) => !part || part === \".\" || part === \"..\" || part.startsWith(\".\"))) continue;\n"
        "\t\ttry {\n"
        "\t\t\tconst filePath = path.join(rootPath, relative);\n"
        "\t\t\tconst info = await stat(filePath);\n"
        "\t\t\tif (!info.isFile()) continue;\n"
        "\t\t\tconst text = await readFile(filePath, \"utf8\");\n"
        "\t\t\tlet data;\n"
        "\t\t\ttry {\n"
        "\t\t\t\tdata = JSON.parse(text);\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\tinvalid.push({ path: relative, reason: \"json\" });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tfound.push(summarize(relative, data));\n"
        "\t\t} catch (error) {\n"
        "\t\t\tconst code = String(error?.code ?? \"ERROR\");\n"
        "\t\t\tif (code === \"ENOENT\") missing.push(relative);\n"
        "\t\t\telse errors.push({ path: relative, code });\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { root: rootPath, found, missing, invalid, errors };\n"
        "}\n"
        "export { scanFsPackageManifest };\n"
    )


def _broken_mako_js_fs_manifest_source() -> str:
    return (
        "import { readdir, readFile, stat } from \"node:fs/promises\";\n"
        "import path from \"node:path\";\n\n"
        "async function scanFsPackageManifest(root, options = {}) {\n"
        "\treturn { root, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { scanFsPackageManifest };\n"
    )


def _mako_js_fs_manifest_package_json() -> str:
    return (
        json.dumps(
            {
                "name": "@openmako/fs-manifest-fixture",
                "type": "module",
                "dependencies": {"@openmako/local-helper": "file:fixtures/local-helper"},
                "scripts": {
                    "pretest": "npm install --package-lock-only --ignore-scripts",
                    "test": "node tests/test_fs_manifest.mjs",
                },
            },
            sort_keys=True,
        )
        + "\n"
    )


def _mako_js_fs_manifest_package_lock() -> str:
    return (
        "{\n"
        "  \"name\": \"@openmako/fs-manifest-fixture\",\n"
        "  \"lockfileVersion\": 3,\n"
        "  \"requires\": true,\n"
        "  \"packages\": {\n"
        "    \"\": {\n"
        "      \"name\": \"@openmako/fs-manifest-fixture\",\n"
        "      \"dependencies\": {\n"
        "        \"@openmako/local-helper\": \"file:fixtures/local-helper\"\n"
        "      }\n"
        "    },\n"
        "    \"fixtures/local-helper\": {\n"
        "      \"name\": \"@openmako/local-helper\",\n"
        "      \"version\": \"1.0.0\"\n"
        "    },\n"
        "    \"node_modules/@openmako/local-helper\": {\n"
        "      \"resolved\": \"fixtures/local-helper\",\n"
        "      \"link\": true\n"
        "    }\n"
        "  }\n"
        "}\n"
    )


def _mako_js_fs_manifest_base_files(module_source: str, test_source: str, fixture_files: Mapping[str, str]) -> dict[str, str]:
    files = {
        "package.json": _mako_js_fs_manifest_package_json(),
        "package-lock.json": _mako_js_fs_manifest_package_lock(),
        "mako_js/index.js": "export { scanFsPackageManifest } from \"./fs_manifest.js\";\n",
        MAKO_JS_FS_MANIFEST_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "fixtures/local-helper/package.json": "{\"name\":\"@openmako/local-helper\",\"version\":\"1.0.0\",\"type\":\"module\"}\n",
        "tests/test_fs_manifest.mjs": test_source,
    }
    files.update(fixture_files)
    return files


def _mako_js_fs_manifest_stage1_fixture_files() -> dict[str, str]:
    return {
        "fixtures/workspace/package.json": json.dumps(
            {"name": " Stage Fs ", "version": "1.2.3", "dependencies": {"local": "file:../local-helper"}},
            sort_keys=True,
        )
        + "\n",
        "fixtures/workspace/team.mako.json": json.dumps({"owner": " Ops ", "tasks": ["scan", "test"]}, sort_keys=True) + "\n",
        "fixtures/workspace/packages/core/package.json": json.dumps({"name": "@openmako/core", "version": "2.0.0"}, sort_keys=True) + "\n",
        "fixtures/workspace/broken.json": "{broken json\n",
    }


def _mako_js_fs_manifest_hidden_lock_fixture_files() -> dict[str, str]:
    return {
        "fixtures/workspace/package.json": json.dumps(
            {"name": " Hidden Root ", "version": "9.0.0", "dependencies": {"tool": "file:packages/tool"}},
            sort_keys=True,
        )
        + "\n",
        "fixtures/workspace/package-lock.json": json.dumps(
            {"lockfileVersion": 3, "packages": {"": {}, "packages/tool": {}}},
            sort_keys=True,
        )
        + "\n",
        "fixtures/workspace/api.mako.json": json.dumps({"owner": " Platform ", "tasks": ["deploy"]}, sort_keys=True) + "\n",
        "fixtures/workspace/packages/tool/package.json": json.dumps({"name": "@openmako/tool", "version": "0.2.0"}, sort_keys=True) + "\n",
    }


def _mako_js_fs_manifest_hidden_depth_fixture_files() -> dict[str, str]:
    return {
        "fixtures/workspace/package.json": json.dumps({"name": "Depth Root", "version": "1.0.0"}, sort_keys=True) + "\n",
        "fixtures/workspace/ops.mako.json": json.dumps({"owner": " Release ", "tasks": []}, sort_keys=True) + "\n",
        "fixtures/workspace/packages/deep/package.json": json.dumps({"name": "@openmako/deep", "version": "9.9.9"}, sort_keys=True) + "\n",
        "fixtures/workspace/bad.mako.json": "{\"owner\":",
    }


def _mako_js_fs_manifest_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { readFile } from 'node:fs/promises';\n"
        "import { fileURLToPath } from 'node:url';\n"
        "import path from 'node:path';\n"
        "import { scanFsPackageManifest } from '../mako_js/index.js';\n\n"
        "const workspaceRoot = fileURLToPath(new URL('../fixtures/workspace', import.meta.url));\n"
        "const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));\n"
        "assert.equal(lock.packages[''].dependencies['@openmako/local-helper'], 'file:fixtures/local-helper');\n"
        "const report = await scanFsPackageManifest(workspaceRoot, { required: ['missing.json', 'broken.json'], maxDepth: 3 });\n"
        "assert.equal(report.root, path.resolve(workspaceRoot));\n"
        "assert.deepEqual(report.found, [\n"
        "  { path: 'package.json', kind: 'package', name: ' Stage Fs ', version: '1.2.3', dependencyCount: 1, localDependencyCount: 1 },\n"
        "  { path: 'packages/core/package.json', kind: 'package', name: '@openmako/core', version: '2.0.0', dependencyCount: 0, localDependencyCount: 0 },\n"
        "  { path: 'team.mako.json', kind: 'mako', owner: 'ops', taskCount: 2 },\n"
        "]);\n"
        "assert.deepEqual(report.missing, ['missing.json']);\n"
        "assert.deepEqual(report.invalid, [{ path: 'broken.json', reason: 'json' }]);\n"
        "assert.deepEqual(report.errors, []);\n"
    )


def _mako_js_fs_manifest_hidden_lock_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { readFile } from 'node:fs/promises';\n"
        "import { fileURLToPath } from 'node:url';\n"
        "import path from 'node:path';\n"
        "import { scanFsPackageManifest } from '../mako_js/index.js';\n\n"
        "const workspaceRoot = fileURLToPath(new URL('../fixtures/workspace', import.meta.url));\n"
        "const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));\n"
        "assert.equal(lock.lockfileVersion, 3);\n"
        "const report = await scanFsPackageManifest(workspaceRoot, { required: ['absent.json'], maxDepth: 4 });\n"
        "assert.equal(report.root, path.resolve(workspaceRoot));\n"
        "assert.deepEqual(report.found, [\n"
        "  { path: 'api.mako.json', kind: 'mako', owner: 'platform', taskCount: 1 },\n"
        "  { path: 'package-lock.json', kind: 'package-lock', lockfileVersion: 3, packageCount: 2 },\n"
        "  { path: 'package.json', kind: 'package', name: ' Hidden Root ', version: '9.0.0', dependencyCount: 1, localDependencyCount: 1 },\n"
        "  { path: 'packages/tool/package.json', kind: 'package', name: '@openmako/tool', version: '0.2.0', dependencyCount: 0, localDependencyCount: 0 },\n"
        "]);\n"
        "assert.deepEqual(report.missing, ['absent.json']);\n"
        "assert.deepEqual(report.invalid, []);\n"
        "assert.deepEqual(report.errors, []);\n"
    )


def _mako_js_fs_manifest_hidden_depth_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { fileURLToPath } from 'node:url';\n"
        "import { scanFsPackageManifest } from '../mako_js/index.js';\n\n"
        "const workspaceRoot = fileURLToPath(new URL('../fixtures/workspace', import.meta.url));\n"
        "const report = await scanFsPackageManifest(workspaceRoot, { required: ['bad.mako.json', 'missing.mako.json'], maxDepth: 1 });\n"
        "assert.deepEqual(report.found, [\n"
        "  { path: 'ops.mako.json', kind: 'mako', owner: 'release', taskCount: 0 },\n"
        "  { path: 'package.json', kind: 'package', name: 'Depth Root', version: '1.0.0', dependencyCount: 0, localDependencyCount: 0 },\n"
        "]);\n"
        "assert.deepEqual(report.missing, ['missing.mako.json']);\n"
        "assert.deepEqual(report.invalid, [{ path: 'bad.mako.json', reason: 'json' }]);\n"
        "assert.deepEqual(report.errors, []);\n"
        "assert.equal(report.found.some((item) => item.path === 'packages/deep/package.json'), false);\n"
    )


def _mako_js_http_manifest_source() -> str:
    return (
        "function normalizePackageName(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn /^[a-z0-9@/_-]+$/.test(normalized) ? normalized : \"\";\n"
        "}\n"
        "function packageUrl(baseUrl, name) {\n"
        "\tconst base = String(baseUrl ?? \"\").replace(/\\/+$/, \"\");\n"
        "\treturn `${base}/packages/${encodeURIComponent(name)}.json`;\n"
        "}\n"
        "function summarizePackage(name, data) {\n"
        "\tconst dependencies = data && typeof data === \"object\" && data.dependencies && typeof data.dependencies === \"object\" ? Object.keys(data.dependencies).sort() : [];\n"
        "\tconst tags = Array.isArray(data?.tags) ? data.tags.map((tag) => String(tag ?? \"\").trim().toLowerCase()).filter(Boolean).sort() : [];\n"
        "\treturn { name, version: String(data?.version ?? \"\"), dependencyCount: dependencies.length, tags };\n"
        "}\n"
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {}) {\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tconst seen = new Set();\n"
        "\tfor (const rawName of packageNames) {\n"
        "\t\tconst name = normalizePackageName(rawName);\n"
        "\t\tif (!name || seen.has(name)) continue;\n"
        "\t\tseen.add(name);\n"
        "\t\tconst url = packageUrl(baseUrl, name);\n"
        "\t\tlet response;\n"
        "\t\ttry {\n"
        "\t\t\tresponse = await fetch(url, { headers: { \"accept\": \"application/json\", ...(options.headers ?? {}) } });\n"
        "\t\t} catch (error) {\n"
        "\t\t\terrors.push({ name, code: \"NETWORK\", message: String(error?.message ?? error) });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (response.status === 404) {\n"
        "\t\t\tmissing.push(name);\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (!response.ok) {\n"
        "\t\t\terrors.push({ name, code: `HTTP_${response.status}` });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tlet data;\n"
        "\t\ttry {\n"
        "\t\t\tdata = await response.json();\n"
        "\t\t} catch (error) {\n"
        "\t\t\tinvalid.push({ name, reason: \"json\" });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tfound.push(summarizePackage(name, data));\n"
        "\t}\n"
        "\treturn { baseUrl: String(baseUrl ?? \"\").replace(/\\/+$/, \"\"), found, missing, invalid, errors };\n"
        "}\n"
        "export { fetchPackageMetadata };\n"
    )


def _broken_mako_js_http_manifest_source() -> str:
    return (
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {}) {\n"
        "\treturn { baseUrl, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { fetchPackageMetadata };\n"
    )


def _mako_js_http_manifest_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "name": "@openmako/http-manifest-fixture",
                "type": "module",
                "scripts": {"test": "node tests/test_http_manifest.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        "mako_js/index.js": "export { fetchPackageMetadata } from \"./http_manifest.js\";\n",
        MAKO_JS_HTTP_MANIFEST_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_http_manifest.mjs": test_source,
    }


def _mako_js_http_manifest_test_harness(routes: str, body: str) -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { createServer } from 'node:http';\n"
        "import { fetchPackageMetadata } from '../mako_js/index.js';\n\n"
        "async function withServer(routes, fn) {\n"
        "  const server = createServer((request, response) => {\n"
        "    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;\n"
        "    const route = routes.get(pathname);\n"
        "    if (!route) { response.writeHead(404, { 'content-type': 'application/json' }); response.end('{\"error\":\"missing\"}'); return; }\n"
        "    response.writeHead(route.status ?? 200, { 'content-type': route.type ?? 'application/json' });\n"
        "    response.end(route.body);\n"
        "  });\n"
        "  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));\n"
        "  try { return await fn(`http://127.0.0.1:${server.address().port}/`); }\n"
        "  finally { await new Promise((resolve) => server.close(resolve)); }\n"
        "}\n\n"
        f"await withServer(new Map([\n{routes}\n]), async (baseUrl) => {{\n{body}\n}});\n"
    )


def _mako_js_http_manifest_stage1_tests() -> str:
    return _mako_js_http_manifest_test_harness(
        "  ['/packages/alpha.json', { body: JSON.stringify({ version: '1.0.0', dependencies: { zed: '^1', beta: '^2' }, tags: ['CLI', 'Tool'] }) }],\n"
        "  ['/packages/%40scope%2Ftool.json', { body: JSON.stringify({ version: '2.5.0', dependencies: {}, tags: ['SDK'] }) }],\n"
        "  ['/packages/broken.json', { body: '{not json' }],\n"
        "  ['/packages/crash.json', { status: 500, body: JSON.stringify({ error: 'boom' }) }],",
        "  const report = await fetchPackageMetadata(baseUrl, [' Alpha ', '@scope/tool', 'missing', 'broken', 'crash', 'alpha', '../bad']);\n"
        "  assert.deepEqual(report, {\n"
        "    baseUrl: baseUrl.replace(/\\/+$/, ''),\n"
        "    found: [\n"
        "      { name: 'alpha', version: '1.0.0', dependencyCount: 2, tags: ['cli', 'tool'] },\n"
        "      { name: '@scope/tool', version: '2.5.0', dependencyCount: 0, tags: ['sdk'] },\n"
        "    ],\n"
        "    missing: ['missing'],\n"
        "    invalid: [{ name: 'broken', reason: 'json' }],\n"
        "    errors: [{ name: 'crash', code: 'HTTP_500' }],\n"
        "  });",
    )


def _mako_js_http_manifest_hidden_encoded_tests() -> str:
    return _mako_js_http_manifest_test_harness(
        "  ['/packages/%40org%2Fencoded-tool.json', { body: JSON.stringify({ version: '3.1.4', dependencies: { left: '^1' }, tags: ['Agent', 'Fetch'] }) }],\n"
        "  ['/packages/plain_name.json', { body: JSON.stringify({ version: 7, dependencies: {}, tags: [] }) }],",
        "  const report = await fetchPackageMetadata(baseUrl + '/', ['@ORG/Encoded-Tool', 'plain_name', 'absent', 'plain_name', 'bad name!'], { headers: { 'x-openmako-test': 'encoded' } });\n"
        "  assert.deepEqual(report, {\n"
        "    baseUrl: baseUrl.replace(/\\/+$/, ''),\n"
        "    found: [\n"
        "      { name: '@org/encoded-tool', version: '3.1.4', dependencyCount: 1, tags: ['agent', 'fetch'] },\n"
        "      { name: 'plain_name', version: '7', dependencyCount: 0, tags: [] },\n"
        "    ],\n"
        "    missing: ['absent'],\n"
        "    invalid: [],\n"
        "    errors: [],\n"
        "  });",
    )


def _mako_js_http_manifest_hidden_invalid_errors_tests() -> str:
    return _mako_js_http_manifest_test_harness(
        "  ['/packages/invalid.json', { body: '[broken' }],\n"
        "  ['/packages/ratelimited.json', { status: 429, body: JSON.stringify({ retry: true }) }],\n"
        "  ['/packages/empty.json', { body: JSON.stringify({}) }],",
        "  const report = await fetchPackageMetadata(baseUrl, ['invalid', 'ratelimited', 'empty', 'unknown']);\n"
        "  assert.deepEqual(report, {\n"
        "    baseUrl: baseUrl.replace(/\\/+$/, ''),\n"
        "    found: [{ name: 'empty', version: '', dependencyCount: 0, tags: [] }],\n"
        "    missing: ['unknown'],\n"
        "    invalid: [{ name: 'invalid', reason: 'json' }],\n"
        "    errors: [{ name: 'ratelimited', code: 'HTTP_429' }],\n"
        "  });",
    )


def _mako_js_labels_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { compactLabel, labelKey } from '../mako_js/index.js';\n\n"
        "assert.equal(compactLabel('  Alpha Beta!!  '), 'alpha-beta');\n"
        "assert.equal(compactLabel('READY__Now'), 'ready-now');\n"
        "assert.equal(compactLabel(null), '');\n"
        "assert.equal(labelKey('  Alpha Beta!!  '), 'label:alpha-beta');\n"
        "assert.equal(labelKey(' !!! '), 'label');\n"
    )


def _mako_js_labels_hidden_unicode_spacing_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { compactLabel, labelKey } from '../mako_js/index.js';\n\n"
        "assert.equal(compactLabel('\\tNorth__Star  v2!!'), 'north-star-v2');\n"
        "assert.equal(compactLabel('MIXED.case/value'), 'mixed-case-value');\n"
        "assert.equal(compactLabel(' café 42 '), 'caf-42');\n"
        "assert.equal(labelKey('MIXED.case/value'), 'label:mixed-case-value');\n"
        "assert.equal(labelKey('\\nNorth Star\\n'), 'label:north-star');\n"
    )


def _mako_js_labels_hidden_empty_edges_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { compactLabel, labelKey } from '../mako_js/index.js';\n\n"
        "assert.equal(compactLabel(undefined), '');\n"
        "assert.equal(compactLabel('---'), '');\n"
        "assert.equal(compactLabel('  007  '), '007');\n"
        "assert.equal(labelKey(undefined), 'label');\n"
        "assert.equal(labelKey('  007  '), 'label:007');\n"
    )


def _mako_js_async_records_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { loadUserSummaries, normalizeUserId, summarizeUser } from '../mako_js/index.js';\n\n"
        "const calls = [];\n"
        "const client = {\n"
        "  async fetchUser(id) {\n"
        "    calls.push(id);\n"
        "    if (id === 'missing') throw new Error('not found');\n"
        "    return { id, name: id === 'ada' ? ' Ada Lovelace ' : '', roles: ['Admin', '', 'user'] };\n"
        "  }\n"
        "};\n"
        "const report = await loadUserSummaries(client, [' Ada ', 'bad id!', 'ADA', 'missing'], { concurrency: 2 });\n"
        "assert.deepEqual(calls, ['ada', 'missing']);\n"
        "assert.deepEqual(report.users, [{ id: 'ada', name: 'Ada Lovelace', roles: ['admin', 'user'] }]);\n"
        "assert.deepEqual(report.errors, [{ id: 'missing', message: 'not found' }]);\n"
        "assert.equal(normalizeUserId(' Team_01 '), 'team_01');\n"
        "assert.deepEqual(summarizeUser({ id: ' Bob ', roles: ['Viewer'] }), { id: 'bob', name: 'bob', roles: ['viewer'] });\n"
    )


def _mako_js_async_records_hidden_dedupe_errors_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { loadUserSummaries } from '../mako_js/index.js';\n\n"
        "const calls = [];\n"
        "const client = {\n"
        "  async fetchUser(id) {\n"
        "    calls.push(id);\n"
        "    if (id === 'offline') throw new Error('offline user');\n"
        "    return { id, name: id.toUpperCase(), roles: ['writer', 'Reader'] };\n"
        "  }\n"
        "};\n"
        "const report = await loadUserSummaries(client, ['SAM', 'sam', 'offline', '../bad', 'zoe'], { concurrency: 1 });\n"
        "assert.deepEqual(calls, ['sam', 'offline', 'zoe']);\n"
        "assert.deepEqual(report.users, [\n"
        "  { id: 'sam', name: 'SAM', roles: ['reader', 'writer'] },\n"
        "  { id: 'zoe', name: 'ZOE', roles: ['reader', 'writer'] },\n"
        "]);\n"
        "assert.deepEqual(report.errors, [{ id: 'offline', message: 'offline user' }]);\n"
    )


def _mako_js_async_records_hidden_roles_invalid_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { loadUserSummaries, normalizeUserId, summarizeUser } from '../mako_js/index.js';\n\n"
        "assert.equal(normalizeUserId(' invalid space '), '');\n"
        "assert.equal(normalizeUserId('Ops-Team_2'), 'ops-team_2');\n"
        "assert.equal(summarizeUser(null), null);\n"
        "assert.equal(summarizeUser({ id: 'bad id' }), null);\n"
        "assert.deepEqual(summarizeUser({ id: 'root', name: '', roles: ['Admin', null, 'viewer'] }), { id: 'root', name: 'root', roles: ['admin', 'viewer'] });\n"
        "const client = { async fetchUser(id) { return id === 'ghost' ? null : { id, roles: [] }; } };\n"
        "const report = await loadUserSummaries(client, ['ghost', 'root'], { concurrency: 9 });\n"
        "assert.deepEqual(report, { users: [{ id: 'root', name: 'root', roles: [] }], errors: [] });\n"
    )


def _mako_js_io_boundary_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { scanWorkspaceManifest } from '../mako_js/index.js';\n\n"
        "const files = new Map([\n"
        "  ['/repo/package.json', JSON.stringify({ name: ' Stage-One ', version: '1.2.3', private: true })],\n"
        "  ['/repo/mako.json', JSON.stringify({ owner: ' Team-A ', tasks: ['lint', 'test'] })],\n"
        "  ['/repo/bad.json', '{broken json'],\n"
        "]);\n"
        "const calls = [];\n"
        "async function readText(path) {\n"
        "  calls.push(path);\n"
        "  if (files.has(path)) return files.get(path);\n"
        "  const error = new Error(`missing ${path}`);\n"
        "  error.code = 'ENOENT';\n"
        "  throw error;\n"
        "}\n"
        "assert.deepEqual(await scanWorkspaceManifest(readText, '/repo', ['package.json', 'mako.json', 'missing.json', 'bad.json']), {\n"
        "  root: '/repo',\n"
        "  found: [\n"
        "    { path: '/repo/package.json', kind: 'package', name: 'stage-one', version: '1.2.3', private: true },\n"
        "    { path: '/repo/mako.json', kind: 'mako', owner: 'team-a', taskCount: 2 },\n"
        "  ],\n"
        "  missing: ['/repo/missing.json'],\n"
        "  invalid: [{ path: '/repo/bad.json', reason: 'json' }],\n"
        "  errors: [],\n"
        "});\n"
        "assert.deepEqual(calls, ['/repo/package.json', '/repo/mako.json', '/repo/missing.json', '/repo/bad.json']);\n"
    )


def _mako_js_io_boundary_hidden_dynamic_errors_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { scanWorkspaceManifest } from '../mako_js/index.js';\n\n"
        "const files = new Map([\n"
        "  ['/srv/app/package.json', JSON.stringify({ name: ' Hidden_App ', version: 42 })],\n"
        "  ['/srv/app/team.mako.json', JSON.stringify({ owner: ' Ops ', tasks: ['ship'] })],\n"
        "  ['/srv/app/config.json', JSON.stringify({ z: 1, a: 2, mode: 'prod' })],\n"
        "  ['/srv/app/corrupt.json', '{\"x\":'],\n"
        "]);\n"
        "const calls = [];\n"
        "async function readText(path) {\n"
        "  calls.push(path);\n"
        "  await new Promise((resolve) => setTimeout(resolve, path.includes('config') ? 2 : 1));\n"
        "  if (path.endsWith('secret.json')) {\n"
        "    const error = new Error('permission denied');\n"
        "    error.code = 'EACCES';\n"
        "    throw error;\n"
        "  }\n"
        "  if (files.has(path)) return files.get(path);\n"
        "  const error = new Error('not found');\n"
        "  error.code = 'ENOENT';\n"
        "  throw error;\n"
        "}\n"
        "assert.deepEqual(await scanWorkspaceManifest(readText, '/srv/app', [\n"
        "  'package.json', 'team.mako.json', 'config.json', 'absent.json', 'corrupt.json', 'secret.json'\n"
        "]), {\n"
        "  root: '/srv/app',\n"
        "  found: [\n"
        "    { path: '/srv/app/package.json', kind: 'package', name: 'hidden_app', version: '42', private: false },\n"
        "    { path: '/srv/app/team.mako.json', kind: 'mako', owner: 'ops', taskCount: 1 },\n"
        "    { path: '/srv/app/config.json', kind: 'json', keyCount: 3 },\n"
        "  ],\n"
        "  missing: ['/srv/app/absent.json'],\n"
        "  invalid: [{ path: '/srv/app/corrupt.json', reason: 'json' }],\n"
        "  errors: [{ path: '/srv/app/secret.json', code: 'EACCES' }],\n"
        "});\n"
        "assert.deepEqual(calls, [\n"
        "  '/srv/app/package.json', '/srv/app/team.mako.json', '/srv/app/config.json',\n"
        "  '/srv/app/absent.json', '/srv/app/corrupt.json', '/srv/app/secret.json'\n"
        "]);\n"
    )


def _mako_js_io_boundary_hidden_hardcoded_constants_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { scanWorkspaceManifest } from '../mako_js/index.js';\n\n"
        "const files = new Map([\n"
        "  ['/tmp/ws/pkg.json', JSON.stringify({ alpha: 1, beta: 2 })],\n"
        "  ['/tmp/ws/release.mako.json', JSON.stringify({ owner: ' Release ', tasks: [] })],\n"
        "]);\n"
        "async function readText(path) {\n"
        "  if (files.has(path)) return files.get(path);\n"
        "  const error = new Error(`unexpected path ${path}`);\n"
        "  error.code = 'ENOENT';\n"
        "  throw error;\n"
        "}\n"
        "assert.deepEqual(await scanWorkspaceManifest(readText, '/tmp/ws', ['pkg.json', 'release.mako.json', 'package.json']), {\n"
        "  root: '/tmp/ws',\n"
        "  found: [\n"
        "    { path: '/tmp/ws/pkg.json', kind: 'json', keyCount: 2 },\n"
        "    { path: '/tmp/ws/release.mako.json', kind: 'mako', owner: 'release', taskCount: 0 },\n"
        "  ],\n"
        "  missing: ['/tmp/ws/package.json'],\n"
        "  invalid: [],\n"
        "  errors: [],\n"
        "});\n"
    )


def _less_pinned_io_boundary_stage1_tests() -> str:
    return _mako_js_io_boundary_stage1_tests().replace("../mako_js/index.js", "../src/runtime/index.js")


def _less_pinned_io_boundary_hidden_dynamic_errors_tests() -> str:
    return _mako_js_io_boundary_hidden_dynamic_errors_tests().replace("../mako_js/index.js", "../src/runtime/index.js")


def _less_pinned_io_boundary_hidden_hardcoded_constants_tests() -> str:
    return _mako_js_io_boundary_hidden_hardcoded_constants_tests().replace("../mako_js/index.js", "../src/runtime/index.js")


def _multi_package_io_boundary_stage1_tests() -> str:
    return _mako_js_io_boundary_stage1_tests().replace("../mako_js/index.js", "../apps/cli/src/runtime/index.js")


def _multi_package_io_boundary_hidden_dynamic_errors_tests() -> str:
    return _mako_js_io_boundary_hidden_dynamic_errors_tests().replace(
        "../mako_js/index.js",
        "../apps/cli/src/runtime/index.js",
    )


def _multi_package_io_boundary_hidden_hardcoded_constants_tests() -> str:
    return _mako_js_io_boundary_hidden_hardcoded_constants_tests().replace(
        "../mako_js/index.js",
        "../apps/cli/src/runtime/index.js",
    )


def _openclaw_combined_js_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "assert.deepEqual(extractBalancedJsonPrefix('xx {\"a\":[1,{\"b\":\"}\"}]} tail'), { json: '{\"a\":[1,{\"b\":\"}\"}]}', startIndex: 3, endIndex: 21 });\n"
        "assert.deepEqual(extractBalancedJsonFragments('a {\"a\":1} b [2,{\"c\":3}]'), [\n"
        "  { json: '{\"a\":1}', startIndex: 2, endIndex: 8 },\n"
        "  { json: '[2,{\"c\":3}]', startIndex: 12, endIndex: 22 },\n"
        "]);\n"
        "const root = { providers: { openai: { 'api/key': 'sk-live', 'tilde~name': 'escaped' } } };\n"
        "assert.equal(readJsonPointer(root, '/providers/openai/api~1key'), 'sk-live');\n"
        "assert.equal(readJsonPointer(root, '/providers/openai/tilde~0name'), 'escaped');\n"
        "assert.equal(encodeJsonPointerToken('api/key~prod'), 'api~1key~0prod');\n"
    )


def _openclaw_combined_js_hidden_escaped_pointer_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "assert.deepEqual(extractBalancedJsonPrefix('prefix {\"msg\":\"brace } in text\",\"list\":[1]} suffix'), { json: '{\"msg\":\"brace } in text\",\"list\":[1]}', startIndex: 7, endIndex: 42 });\n"
        "assert.deepEqual(extractBalancedJsonFragments('one [1] two {\"b\":2}'), [\n"
        "  { json: '[1]', startIndex: 4, endIndex: 6 },\n"
        "  { json: '{\"b\":2}', startIndex: 12, endIndex: 18 },\n"
        "]);\n"
        "const root = { 'a/b': { 'tilde~': ['zero', { 'x/y~z': 7 }] } };\n"
        "assert.equal(readJsonPointer(root, '/a~1b/tilde~0/1/x~1y~0z'), 7);\n"
        "assert.equal(encodeJsonPointerToken('x/y~z'), 'x~1y~0z');\n"
    )


def _openclaw_combined_js_hidden_fragments_missing_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n"
        "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
        "assert.deepEqual(extractBalancedJsonPrefix('lead [1,{\"nested\":[2,3]}] tail', { openers: ['['] }), { json: '[1,{\"nested\":[2,3]}]', startIndex: 5, endIndex: 24 });\n"
        "assert.deepEqual(extractBalancedJsonFragments('one [1] two {\"b\":2} three [3,{\"c\":\"}\"}]'), [\n"
        "  { json: '[1]', startIndex: 4, endIndex: 6 },\n"
        "  { json: '{\"b\":2}', startIndex: 12, endIndex: 18 },\n"
        "  { json: '[3,{\"c\":\"}\"}]', startIndex: 26, endIndex: 38 },\n"
        "]);\n"
        "const root = { list: [{ value: 'a' }], object: { child: 3 }, scalar: 'leaf' };\n"
        "assert.equal(readJsonPointer(root, '/list/1/value', { onMissing: 'undefined' }), undefined);\n"
        "assert.equal(readJsonPointer(root, '/scalar/child', { onMissing: 'undefined' }), undefined);\n"
        "assert.throws(() => readJsonPointer(root, '/object/missing'), /does not exist/);\n"
    )


def _write_openclaw_js_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    target = workspace / OPENCLAW_PARSE_FINITE_NUMBER_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_parse_finite_number.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_parse_timeout_package_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        json.dumps(
            {
                "name": "@openmako/openclaw-timeout-fixture",
                "type": "module",
                "exports": {"./timeout": "./src/timeout.js"},
                "scripts": {"test": "node tests/test_parse_timeout.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "src").mkdir()
    (workspace / "src" / "timeout.js").write_text(
        "export { n as parseTimeoutMsWithFallback, t as parseTimeoutMs } from \"../third_party/openclaw/selected/parse-timeout-91AFhn8L.js\";\n",
        encoding="utf-8",
    )
    target = workspace / OPENCLAW_PARSE_TIMEOUT_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "README.md").write_text("# OpenClaw timeout package fixture\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_parse_timeout.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_arg_split_package_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        json.dumps(
            {
                "name": "@openmako/openclaw-arg-split-fixture",
                "type": "module",
                "exports": {"./args": "./src/args.js"},
                "scripts": {"test": "node tests/test_arg_split.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "src").mkdir()
    (workspace / "src" / "args.js").write_text(
        "export { t as splitArgsPreservingQuotes } from \"../third_party/openclaw/selected/arg-split-DM7vx6uc.js\";\n",
        encoding="utf-8",
    )
    target = workspace / OPENCLAW_ARG_SPLIT_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "README.md").write_text("# OpenClaw arg-split package fixture\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_arg_split.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_balanced_json_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    target = workspace / OPENCLAW_BALANCED_JSON_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_balanced_json.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_json_pointer_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    target = workspace / OPENCLAW_JSON_POINTER_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_json_pointer.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_command_poll_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    target = workspace / OPENCLAW_COMMAND_POLL_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_command_poll_backoff.mjs").write_text(test_source, encoding="utf-8")


def _write_openclaw_async_lock_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    target = workspace / OPENCLAW_ASYNC_LOCK_TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_async_lock.mjs").write_text(test_source, encoding="utf-8")


def _write_mako_js_labels_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_labels.mjs\"}}\n",
        encoding="utf-8",
    )
    module_dir = workspace / "mako_js"
    module_dir.mkdir()
    (module_dir / "index.js").write_text(
        "export { compactLabel, labelKey } from \"./labels.js\";\n",
        encoding="utf-8",
    )
    target = workspace / MAKO_JS_LABELS_TARGET
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_labels.mjs").write_text(test_source, encoding="utf-8")


def _write_mako_js_async_records_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_async_records.mjs\"}}\n",
        encoding="utf-8",
    )
    module_dir = workspace / "mako_js"
    module_dir.mkdir()
    (module_dir / "index.js").write_text(
        "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n",
        encoding="utf-8",
    )
    target = workspace / MAKO_JS_ASYNC_RECORDS_TARGET
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_async_records.mjs").write_text(test_source, encoding="utf-8")


def _write_mako_js_io_boundary_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_io_boundary.mjs\"}}\n",
        encoding="utf-8",
    )
    module_dir = workspace / "mako_js"
    module_dir.mkdir()
    (module_dir / "index.js").write_text(
        "export { compactLabel, labelKey } from \"./labels.js\";\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n"
        "export { scanWorkspaceManifest } from \"./io_boundary.js\";\n",
        encoding="utf-8",
    )
    (module_dir / "labels.js").write_text(_mako_js_labels_source(), encoding="utf-8")
    (module_dir / "async_records.js").write_text(_mako_js_async_records_source(), encoding="utf-8")
    target = workspace / MAKO_JS_IO_BOUNDARY_TARGET
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_io_boundary.mjs").write_text(test_source, encoding="utf-8")


def _write_less_pinned_mako_js_io_boundary_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        json.dumps(
            {
                "name": "@openmako/mock-workspace-manifest",
                "type": "module",
                "exports": {"./runtime": "./src/runtime/index.js"},
                "bin": {"mako-manifest": "./src/cli.js"},
                "scripts": {"test": "node tests/test_io_boundary.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    module_dir = workspace / "mako_js"
    module_dir.mkdir()
    (module_dir / "labels.js").write_text(_mako_js_labels_source(), encoding="utf-8")
    (module_dir / "async_records.js").write_text(_mako_js_async_records_source(), encoding="utf-8")
    target = workspace / MAKO_JS_IO_BOUNDARY_TARGET
    target.write_text(module_source if module_source.endswith("\n") else module_source + "\n", encoding="utf-8")
    runtime_dir = workspace / "src" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "index.js").write_text(
        "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
        "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n",
        encoding="utf-8",
    )
    (workspace / "src" / "cli.js").write_text(
        "import { scanWorkspaceManifest } from './runtime/index.js';\n"
        "export { scanWorkspaceManifest };\n",
        encoding="utf-8",
    )
    (workspace / "README.md").write_text("# Mock workspace manifest package\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_io_boundary.mjs").write_text(test_source, encoding="utf-8")


def _write_multi_package_mako_js_io_boundary_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text(
        json.dumps(
            {
                "name": "@openmako/workspace-root",
                "private": True,
                "type": "module",
                "workspaces": ["packages/*", "apps/*"],
                "scripts": {"test": "node tests/test_io_boundary.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    module_dir = workspace / "packages" / "core" / "mako_js"
    module_dir.mkdir(parents=True)
    (module_dir / "labels.js").write_text(_mako_js_labels_source(), encoding="utf-8")
    (module_dir / "async_records.js").write_text(_mako_js_async_records_source(), encoding="utf-8")
    (workspace / MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET).write_text(
        module_source if module_source.endswith("\n") else module_source + "\n",
        encoding="utf-8",
    )
    core_runtime_dir = workspace / "packages" / "core" / "src" / "runtime"
    core_runtime_dir.mkdir(parents=True)
    (core_runtime_dir / "index.js").write_text(
        "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
        "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n",
        encoding="utf-8",
    )
    app_runtime_dir = workspace / "apps" / "cli" / "src" / "runtime"
    app_runtime_dir.mkdir(parents=True)
    (app_runtime_dir / "index.js").write_text(
        "export { scanWorkspaceManifest } from \"../../../../packages/core/src/runtime/index.js\";\n",
        encoding="utf-8",
    )
    tools_dir = workspace / "packages" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "package.json").write_text("{\"name\":\"@openmako/tools\",\"type\":\"module\"}\n", encoding="utf-8")
    (tools_dir / "index.js").write_text("export const untouchedTool = 'tools';\n", encoding="utf-8")
    (workspace / "README.md").write_text("# OpenMako mock workspace\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_io_boundary.mjs").write_text(test_source, encoding="utf-8")


def _write_mako_js_fs_manifest_workspace(
    workspace: Path,
    module_source: str,
    test_source: str,
    fixture_files: Mapping[str, str],
) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    files = _mako_js_fs_manifest_base_files(module_source, test_source, fixture_files)
    for relative, content in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _write_mako_js_http_manifest_workspace(workspace: Path, module_source: str, test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    files = _mako_js_http_manifest_task_files(module_source, test_source)
    for relative, content in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _write_openclaw_combined_js_workspace(
    workspace: Path,
    *,
    balanced_source: str,
    json_pointer_source: str,
    test_source: str,
) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
    balanced_target = workspace / OPENCLAW_BALANCED_JSON_TARGET
    balanced_target.parent.mkdir(parents=True, exist_ok=True)
    balanced_target.write_text(balanced_source if balanced_source.endswith("\n") else balanced_source + "\n", encoding="utf-8")
    json_pointer_target = workspace / OPENCLAW_JSON_POINTER_TARGET
    json_pointer_target.parent.mkdir(parents=True, exist_ok=True)
    json_pointer_target.write_text(json_pointer_source if json_pointer_source.endswith("\n") else json_pointer_source + "\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_combined_openclaw_js.mjs").write_text(test_source, encoding="utf-8")


def _openclaw_js_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_PARSE_FINITE_NUMBER_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_parse_finite_number.mjs": test_source,
    }


def _openclaw_parse_timeout_package_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "name": "@openmako/openclaw-timeout-fixture",
                "type": "module",
                "exports": {"./timeout": "./src/timeout.js"},
                "scripts": {"test": "node tests/test_parse_timeout.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        "src/timeout.js": (
            "export { n as parseTimeoutMsWithFallback, t as parseTimeoutMs } from \"../third_party/openclaw/selected/parse-timeout-91AFhn8L.js\";\n"
        ),
        OPENCLAW_PARSE_TIMEOUT_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "README.md": "# OpenClaw timeout package fixture\n",
        "tests/test_parse_timeout.mjs": test_source,
    }


def _openclaw_arg_split_package_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "name": "@openmako/openclaw-arg-split-fixture",
                "type": "module",
                "exports": {"./args": "./src/args.js"},
                "scripts": {"test": "node tests/test_arg_split.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        "src/args.js": (
            "export { t as splitArgsPreservingQuotes } from \"../third_party/openclaw/selected/arg-split-DM7vx6uc.js\";\n"
        ),
        OPENCLAW_ARG_SPLIT_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "README.md": "# OpenClaw arg-split package fixture\n",
        "tests/test_arg_split.mjs": test_source,
    }


def _openclaw_balanced_json_js_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_BALANCED_JSON_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_balanced_json.mjs": test_source,
    }


def _openclaw_json_pointer_js_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_JSON_POINTER_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_json_pointer.mjs": test_source,
    }


def _openclaw_command_poll_js_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_COMMAND_POLL_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_command_poll_backoff.mjs": test_source,
    }


def _openclaw_async_lock_js_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_ASYNC_LOCK_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_async_lock.mjs": test_source,
    }


def _mako_js_labels_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_labels.mjs\"}}\n",
        "mako_js/index.js": "export { compactLabel, labelKey } from \"./labels.js\";\n",
        MAKO_JS_LABELS_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_labels.mjs": test_source,
    }


def _mako_js_async_records_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_async_records.mjs\"}}\n",
        "mako_js/index.js": "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n",
        MAKO_JS_ASYNC_RECORDS_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_async_records.mjs": test_source,
    }


def _mako_js_io_boundary_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_io_boundary.mjs\"}}\n",
        "mako_js/index.js": (
            "export { compactLabel, labelKey } from \"./labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"./io_boundary.js\";\n"
        ),
        "mako_js/labels.js": _mako_js_labels_source(),
        "mako_js/async_records.js": _mako_js_async_records_source(),
        MAKO_JS_IO_BOUNDARY_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "tests/test_io_boundary.mjs": test_source,
    }


def _less_pinned_mako_js_io_boundary_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "name": "@openmako/mock-workspace-manifest",
                "type": "module",
                "exports": {"./runtime": "./src/runtime/index.js"},
                "bin": {"mako-manifest": "./src/cli.js"},
                "scripts": {"test": "node tests/test_io_boundary.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        "src/runtime/index.js": (
            "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n"
        ),
        "src/cli.js": "import { scanWorkspaceManifest } from './runtime/index.js';\nexport { scanWorkspaceManifest };\n",
        "mako_js/labels.js": _mako_js_labels_source(),
        "mako_js/async_records.js": _mako_js_async_records_source(),
        MAKO_JS_IO_BOUNDARY_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "README.md": "# Mock workspace manifest package\n",
        "tests/test_io_boundary.mjs": test_source,
    }


def _multi_package_mako_js_io_boundary_task_files(module_source: str, test_source: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "name": "@openmako/workspace-root",
                "private": True,
                "type": "module",
                "workspaces": ["packages/*", "apps/*"],
                "scripts": {"test": "node tests/test_io_boundary.mjs"},
            },
            sort_keys=True,
        )
        + "\n",
        "apps/cli/src/runtime/index.js": (
            "export { scanWorkspaceManifest } from \"../../../../packages/core/src/runtime/index.js\";\n"
        ),
        "packages/core/src/runtime/index.js": (
            "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n"
        ),
        "packages/core/mako_js/labels.js": _mako_js_labels_source(),
        "packages/core/mako_js/async_records.js": _mako_js_async_records_source(),
        MAKO_JS_MULTI_PACKAGE_IO_BOUNDARY_TARGET: module_source if module_source.endswith("\n") else module_source + "\n",
        "packages/tools/package.json": "{\"name\":\"@openmako/tools\",\"type\":\"module\"}\n",
        "packages/tools/index.js": "export const untouchedTool = 'tools';\n",
        "README.md": "# OpenMako mock workspace\n",
        "tests/test_io_boundary.mjs": test_source,
    }


def _openclaw_combined_js_task_files(
    *,
    balanced_source: str,
    json_pointer_source: str,
    test_source: str,
) -> dict[str, str]:
    return {
        "package.json": "{\"type\":\"module\"}\n",
        OPENCLAW_BALANCED_JSON_TARGET: balanced_source if balanced_source.endswith("\n") else balanced_source + "\n",
        OPENCLAW_JSON_POINTER_TARGET: json_pointer_source if json_pointer_source.endswith("\n") else json_pointer_source + "\n",
        "tests/test_combined_openclaw_js.mjs": test_source,
    }


def _write_openclaw_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_parse_strict_integer_js_hidden_bounds",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_js_task_files(module_source, _openclaw_parse_strict_integer_hidden_bounds_tests()),
            "test_command": "node tests/test_parse_finite_number.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
        {
            "id": "openclaw_parse_strict_integer_js_hidden_safe_range",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_js_task_files(module_source, _openclaw_parse_strict_integer_hidden_safe_range_tests()),
            "test_command": "node tests/test_parse_finite_number.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_parse_timeout_package_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_parse_timeout_package_js_hidden_invalid_values",
            "instruction": f"Fix the failing npm-style OpenClaw parse-timeout JavaScript package tests using approved learning contract {trigger}.",
            "files": _openclaw_parse_timeout_package_task_files(
                module_source,
                _openclaw_parse_timeout_hidden_invalid_values_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "npm-style", "parse-timeout", "learning-effect", "hidden"],
        },
        {
            "id": "openclaw_parse_timeout_package_js_hidden_type_edges",
            "instruction": f"Fix the failing npm-style OpenClaw parse-timeout JavaScript package tests using approved learning contract {trigger}.",
            "files": _openclaw_parse_timeout_package_task_files(
                module_source,
                _openclaw_parse_timeout_hidden_type_edges_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "npm-style", "parse-timeout", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_arg_split_package_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_arg_split_package_js_hidden_backslash_quotes",
            "instruction": f"Fix the failing npm-style OpenClaw arg-split JavaScript package tests using approved learning contract {trigger}.",
            "files": _openclaw_arg_split_package_task_files(
                module_source,
                _openclaw_arg_split_hidden_backslash_quotes_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "npm-style", "arg-split", "learning-effect", "hidden"],
        },
        {
            "id": "openclaw_arg_split_package_js_hidden_quote_start",
            "instruction": f"Fix the failing npm-style OpenClaw arg-split JavaScript package tests using approved learning contract {trigger}.",
            "files": _openclaw_arg_split_package_task_files(
                module_source,
                _openclaw_arg_split_hidden_quote_start_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "npm-style", "arg-split", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_balanced_json_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_balanced_json_js_hidden_strings",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_balanced_json_js_task_files(module_source, _openclaw_balanced_json_hidden_strings_tests()),
            "test_command": "node tests/test_balanced_json.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
        {
            "id": "openclaw_balanced_json_js_hidden_fragments",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_balanced_json_js_task_files(module_source, _openclaw_balanced_json_hidden_fragments_tests()),
            "test_command": "node tests/test_balanced_json.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_json_pointer_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_json_pointer_js_hidden_escaped_tokens",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_json_pointer_js_task_files(module_source, _openclaw_json_pointer_hidden_escaped_tokens_tests()),
            "test_command": "node tests/test_json_pointer.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
        {
            "id": "openclaw_json_pointer_js_hidden_missing_modes",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_json_pointer_js_task_files(module_source, _openclaw_json_pointer_hidden_missing_modes_tests()),
            "test_command": "node tests/test_json_pointer.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_command_poll_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_command_poll_js_hidden_reset_isolated",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_command_poll_js_task_files(module_source, _openclaw_command_poll_hidden_reset_isolated_tests()),
            "test_command": "node tests/test_command_poll_backoff.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "stateful"],
        },
        {
            "id": "openclaw_command_poll_js_hidden_prune_boundaries",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_command_poll_js_task_files(module_source, _openclaw_command_poll_hidden_prune_boundaries_tests()),
            "test_command": "node tests/test_command_poll_backoff.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "stateful"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_mako_js_labels_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "package_level_js_labels_hidden_unicode_spacing",
            "instruction": f"Fix the failing JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_labels_task_files(module_source, _mako_js_labels_hidden_unicode_spacing_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "learning-effect", "hidden"],
        },
        {
            "id": "package_level_js_labels_hidden_empty_edges",
            "instruction": f"Fix the failing JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_labels_task_files(module_source, _mako_js_labels_hidden_empty_edges_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_mako_js_async_records_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "package_level_async_js_records_hidden_dedupe_errors",
            "instruction": f"Fix the failing async JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_async_records_task_files(module_source, _mako_js_async_records_hidden_dedupe_errors_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "async", "learning-effect", "hidden"],
        },
        {
            "id": "package_level_async_js_records_hidden_roles_invalid",
            "instruction": f"Fix the failing async JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_async_records_task_files(module_source, _mako_js_async_records_hidden_roles_invalid_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "async", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_async_lock_js_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "openclaw_async_lock_js_hidden_serial_order",
            "instruction": f"Fix the failing JavaScript async-lock tests using approved learning contract {trigger}.",
            "files": _openclaw_async_lock_js_task_files(module_source, _openclaw_async_lock_hidden_serial_order_tests()),
            "test_command": "node tests/test_async_lock.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "async-lock", "concurrency"],
        },
        {
            "id": "openclaw_async_lock_js_hidden_parallel_and_rejection",
            "instruction": f"Fix the failing JavaScript async-lock tests using approved learning contract {trigger}.",
            "files": _openclaw_async_lock_js_task_files(module_source, _openclaw_async_lock_hidden_parallel_and_rejection_tests()),
            "test_command": "node tests/test_async_lock.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "async-lock", "concurrency"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_mako_js_io_boundary_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "package_level_io_boundary_js_hidden_dynamic_errors",
            "instruction": f"Fix the failing mocked I/O boundary JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_io_boundary_task_files(module_source, _mako_js_io_boundary_hidden_dynamic_errors_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "mocked-io", "learning-effect", "hidden"],
        },
        {
            "id": "package_level_io_boundary_js_hidden_hardcoded_constants",
            "instruction": f"Fix the failing mocked I/O boundary JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_io_boundary_task_files(module_source, _mako_js_io_boundary_hidden_hardcoded_constants_tests()),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "mocked-io", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_mako_js_fs_manifest_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "package_level_fs_manifest_js_hidden_lock_and_missing",
            "instruction": f"Fix the failing real filesystem JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_fs_manifest_base_files(
                module_source,
                _mako_js_fs_manifest_hidden_lock_tests(),
                _mako_js_fs_manifest_hidden_lock_fixture_files(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 45,
            "tags": ["javascript", "package-level", "real-fs", "npm-lifecycle", "learning-effect", "hidden"],
        },
        {
            "id": "package_level_fs_manifest_js_hidden_depth_and_invalid",
            "instruction": f"Fix the failing real filesystem JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_fs_manifest_base_files(
                module_source,
                _mako_js_fs_manifest_hidden_depth_tests(),
                _mako_js_fs_manifest_hidden_depth_fixture_files(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 45,
            "tags": ["javascript", "package-level", "real-fs", "npm-lifecycle", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_mako_js_http_manifest_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "package_level_http_manifest_js_hidden_encoded_and_missing",
            "instruction": f"Fix the failing local HTTP fetch JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_http_manifest_task_files(
                module_source,
                _mako_js_http_manifest_hidden_encoded_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 45,
            "tags": ["javascript", "package-level", "real-fetch", "local-http", "learning-effect", "hidden"],
        },
        {
            "id": "package_level_http_manifest_js_hidden_invalid_and_errors",
            "instruction": f"Fix the failing local HTTP fetch JavaScript package tests using approved learning contract {trigger}.",
            "files": _mako_js_http_manifest_task_files(
                module_source,
                _mako_js_http_manifest_hidden_invalid_errors_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 45,
            "tags": ["javascript", "package-level", "real-fetch", "local-http", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_less_pinned_mako_js_io_boundary_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "less_pinned_io_boundary_js_hidden_dynamic_errors",
            "instruction": f"Fix the failing less-pinned mocked I/O boundary JavaScript package tests using approved learning contract {trigger}.",
            "files": _less_pinned_mako_js_io_boundary_task_files(
                module_source,
                _less_pinned_io_boundary_hidden_dynamic_errors_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "less-pinned", "mocked-io", "learning-effect", "hidden"],
        },
        {
            "id": "less_pinned_io_boundary_js_hidden_hardcoded_constants",
            "instruction": f"Fix the failing less-pinned mocked I/O boundary JavaScript package tests using approved learning contract {trigger}.",
            "files": _less_pinned_mako_js_io_boundary_task_files(
                module_source,
                _less_pinned_io_boundary_hidden_hardcoded_constants_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "package-level", "less-pinned", "mocked-io", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_multi_package_mako_js_io_boundary_learning_task_file(path: Path, module_source: str, *, trigger: str) -> None:
    tasks = [
        {
            "id": "multi_package_io_boundary_js_hidden_dynamic_errors",
            "instruction": f"Fix the failing multi-package mocked I/O boundary JavaScript workspace tests using approved learning contract {trigger}.",
            "files": _multi_package_mako_js_io_boundary_task_files(
                module_source,
                _multi_package_io_boundary_hidden_dynamic_errors_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "multi-package", "less-pinned", "mocked-io", "learning-effect", "hidden"],
        },
        {
            "id": "multi_package_io_boundary_js_hidden_hardcoded_constants",
            "instruction": f"Fix the failing multi-package mocked I/O boundary JavaScript workspace tests using approved learning contract {trigger}.",
            "files": _multi_package_mako_js_io_boundary_task_files(
                module_source,
                _multi_package_io_boundary_hidden_hardcoded_constants_tests(),
            ),
            "test_command": "npm test",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["javascript", "multi-package", "less-pinned", "mocked-io", "learning-effect", "hidden"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_openclaw_combined_js_learning_task_file(
    path: Path,
    *,
    balanced_source: str,
    json_pointer_source: str,
    trigger: str,
) -> None:
    tasks = [
        {
            "id": "openclaw_combined_js_hidden_escaped_pointer",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_combined_js_task_files(
                balanced_source=balanced_source,
                json_pointer_source=json_pointer_source,
                test_source=_openclaw_combined_js_hidden_escaped_pointer_tests(),
            ),
            "test_command": "node tests/test_combined_openclaw_js.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "multi-module"],
        },
        {
            "id": "openclaw_combined_js_hidden_fragments_missing",
            "instruction": f"Fix the failing JavaScript tests using approved learning contract {trigger}.",
            "files": _openclaw_combined_js_task_files(
                balanced_source=balanced_source,
                json_pointer_source=json_pointer_source,
                test_source=_openclaw_combined_js_hidden_fragments_missing_tests(),
            ),
            "test_command": "node tests/test_combined_openclaw_js.mjs",
            "max_iterations": 1,
            "timeout_seconds": 30,
            "tags": ["openclaw", "javascript", "learning-effect", "hidden", "multi-module"],
        },
    ]
    path.write_text(json.dumps({"tasks": tasks}, sort_keys=True) + "\n", encoding="utf-8")


def _write_workspace(workspace: Path, family: dict[str, Any], test_source: str) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for relative_path, source in _package_init_files(tuple(family["modules"])).items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    for relative_path, source in family["modules"].items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / "tests" / f"test_{family['id']}.py").write_text(test_source.strip() + "\n", encoding="utf-8")


def _task_files(family: dict[str, Any], test_source: str) -> dict[str, str]:
    files = _package_init_files(tuple(family["modules"]))
    files.update(family["modules"])
    files["tests/__init__.py"] = ""
    files[f"tests/test_{family['id']}.py"] = test_source.strip() + "\n"
    return files


def _package_init_files(paths: tuple[str, ...]) -> dict[str, str]:
    dirs: set[Path] = set()
    for item in paths:
        for parent in Path(item).parents:
            if str(parent) != ".":
                dirs.add(parent)
    return {
        (directory / "__init__.py").as_posix(): ""
        for directory in sorted(dirs, key=lambda path: (len(path.parts), path.as_posix()))
    }


def _with_learning_report(eval_result, report: dict[str, object], proposal):
    return replace(
        eval_result,
        require_learning_effect=True,
        learning_effect_report=bind_learning_effect_report_to_proposal(report, proposal),
    )


def _stage1_learning_report(task_id: str) -> dict[str, object]:
    return {
        "status": "pass",
        "total": 1,
        "solved": {"no_learning": 0, "approved_learning": 1},
        "score_delta": 10.0,
        "comparisons": [
            {
                "task_id": f"stage1-{task_id}",
                "score_delta": 10.0,
                "no_learning": {
                    "task_id": f"stage1-{task_id}",
                    "solved": False,
                    "steps": 0,
                    "failure_class": "no_approved_skill",
                    "invalid_reason": "",
                    "evidence": ["stage1 baseline intentionally has no approved-learning skill"],
                },
                "approved_learning": {
                    "task_id": f"stage1-{task_id}",
                    "solved": True,
                    "steps": 1,
                    "failure_class": "",
                    "invalid_reason": "",
                    "evidence": ["stage1 agent trajectory and unittest eval passed"],
                },
            }
        ],
    }
