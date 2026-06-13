from __future__ import annotations

import ast
import hashlib
import json
import shlex
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from quantagent.agent_loop_core import run_agent_loop
from quantagent.coding_bench import run_coding_bench, run_coding_bench_stability
from quantagent.learning_effect_coding_bench import run_learning_effect_coding_bench
from quantagent.skill_pipeline import (
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    propose_file_bundle_repair_skill_from_trajectory,
    run_skill_eval_command,
)
from quantagent.skills import install_skill


REPO = Path(__file__).resolve().parents[1]
UPSTREAM_SOURCE = REPO / "third_party" / "mcp_python_sdk" / "src" / "mcp" / "shared" / "tool_name_validation.py"
UPSTREAM_MANIFEST = REPO / "third_party" / "mcp_python_sdk" / "MANIFEST.sha256"
TARGET_PATH = "mcp/shared/tool_name_validation.py"
PANDERA_SOURCE = REPO / "third_party" / "pandera" / "pandera" / "dtypes.py"
PANDERA_MANIFEST = REPO / "third_party" / "pandera" / "MANIFEST.sha256"
PANDERA_TARGET_PATH = "pandera/dtypes.py"
GE_SOURCE = (
    REPO
    / "third_party"
    / "great_expectations"
    / "great_expectations"
    / "expectations"
    / "expectation_configuration.py"
)
GE_MANIFEST = REPO / "third_party" / "great_expectations" / "MANIFEST.sha256"
GE_TARGET_PATH = "great_expectations/expectations/expectation_configuration.py"
AIDER_SOURCE = REPO / "third_party" / "aider" / "aider" / "repomap.py"
AIDER_MANIFEST = REPO / "third_party" / "aider" / "MANIFEST.sha256"
AIDER_TARGET_PATH = "aider/repomap.py"


class UpstreamFunctionFileBundleRegressionTest(unittest.TestCase):
    def test_vendored_mcp_function_level_repair_reuses_without_non_target_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-function-file-bundle-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = UPSTREAM_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), UPSTREAM_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _replace_function(
                actual_source,
                "validate_tool_name",
                (
                    "def validate_tool_name(name: str) -> ToolNameValidationResult:\n"
                    "    return ToolNameValidationResult(is_valid=True, warnings=[])\n"
                ),
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _stage1_tests())
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
            self.assertEqual(implementation.data["files_touched"], [TARGET_PATH])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-mcp-tool-name-function-repair",
                description="Learned function-level repair from vendored MCP Python SDK tool_name_validation.py.",
                triggers=("opaque-upstream-function-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "file_bundle")
            self.assertEqual(hint["mode"], "replace_functions")
            self.assertEqual(hint["functions"], ["validate_tool_name"])
            self.assertNotIn("class ToolNameValidationResult", hint["files"][TARGET_PATH])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored MCP no-seed function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_tool_name_validation.py"), str(UPSTREAM_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "upstream_function_stage2_tasks.json"
            _write_stage2_task_pack(
                task_file,
                broken_source,
                target_path=TARGET_PATH,
                task_specs=(
                    (
                        "upstream_mcp_tool_name_validation_function_repair_bounds_chars",
                        _stage2_tests(),
                        "opaque-upstream-function-contract-1",
                    ),
                    (
                        "upstream_mcp_tool_name_validation_function_repair_warnings_invalids",
                        _stage2_variant_tests(),
                        "opaque-upstream-function-contract-1",
                    ),
                ),
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            preservations = [
                _preservation_scan(broken_source, result.workspace)
                for result in report.approved_learning_run.results
            ]
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=TARGET_PATH,
                exclude_function="validate_tool_name",
                expected_result_count=4,
            )

        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        for approved_result in report.approved_learning_run.results:
            self.assertEqual(approved_result.patch_metrics.changed_files, (TARGET_PATH,))
            self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual([item["violations"] for item in preservations], [[], []])
        self.assertEqual(stability.summary()["solved"], 4)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)

    def test_vendored_pandera_scale_function_repair_reuses_without_non_target_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-pandera-function-bundle-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = PANDERA_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), PANDERA_MANIFEST.read_text(encoding="utf-8"))
            repaired_function = _function_source(actual_source, "_scale_to_exp")
            broken_source = _replace_function(
                actual_source,
                "_scale_to_exp",
                "def _scale_to_exp(scale: int) -> decimal.Decimal:\n    return decimal.Decimal('1')\n",
            )
            seed_project = root / "seed_learning_project"
            _install_seed_file_function_skill(
                seed_project,
                repaired_function,
                target_path=PANDERA_TARGET_PATH,
                function_name="_scale_to_exp",
                trigger="seed-pandera-scale-function-1",
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _pandera_stage1_tests(), target_path=PANDERA_TARGET_PATH)
            result = run_agent_loop(
                stage1,
                "Fix failing package tests using approved learning contract seed-pandera-scale-function-1.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="on",
                learning_project=seed_project,
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], [PANDERA_TARGET_PATH])

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-pandera-scale-function-repair",
                description="Learned function-level repair from vendored Pandera dtypes.py.",
                triggers=("opaque-pandera-scale-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "file_bundle")
            self.assertEqual(hint["mode"], "replace_functions")
            self.assertEqual(hint["functions"], ["_scale_to_exp"])
            self.assertNotIn("class Decimal", hint["files"][PANDERA_TARGET_PATH])

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored Pandera function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_dtypes_scale.py"), str(PANDERA_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "pandera_scale_stage2_tasks.json"
            _write_stage2_tasks(
                task_file,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                test_source=_pandera_stage2_tests(),
                task_id="upstream_pandera_scale_to_exp_function_repair",
                trigger="opaque-pandera-scale-contract-1",
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            preservation = _preservation_scan(
                broken_source,
                report.approved_learning_run.results[0].workspace,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="_scale_to_exp",
            )
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="_scale_to_exp",
                expected_result_count=2,
            )

        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 1)
        approved_result = report.approved_learning_run.results[0]
        self.assertEqual(approved_result.patch_metrics.changed_files, (PANDERA_TARGET_PATH,))
        self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
        self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
        self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual(preservation["violations"], [])
        self.assertEqual(stability.summary()["solved"], 2)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)

    def test_vendored_pandera_scale_no_seed_stage1_extracts_function_repair_without_non_target_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-pandera-no-seed-stage1-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = PANDERA_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), PANDERA_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _replace_function(
                actual_source,
                "_scale_to_exp",
                "def _scale_to_exp(scale: int) -> decimal.Decimal:\n    return decimal.Decimal('1')\n",
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _pandera_stage1_tests(), target_path=PANDERA_TARGET_PATH)
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
            self.assertEqual(implementation.data["files_touched"], [PANDERA_TARGET_PATH])
            solved = (stage1 / PANDERA_TARGET_PATH).read_text(encoding="utf-8")
            self.assertIn("scale_fmt = format(10**-scale", solved)
            self.assertIn("return decimal.Decimal(scale_fmt)", solved)
            self.assertNotIn("return decimal.Decimal('1')", solved)
            preservation = _preservation_scan(
                broken_source,
                stage1,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="_scale_to_exp",
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-pandera-scale-no-seed-function-repair",
                description="No-seed learned function-level repair from vendored Pandera dtypes.py.",
                triggers=("opaque-pandera-scale-no-seed-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored Pandera scale no-seed function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_dtypes_scale.py"), str(PANDERA_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "pandera_scale_no_seed_stage2_tasks.json"
            _write_stage2_task_pack(
                task_file,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                task_specs=(
                    (
                        "upstream_pandera_scale_to_exp_no_seed_function_repair_zero_three",
                        _pandera_stage2_tests(),
                        "opaque-pandera-scale-no-seed-contract-1",
                    ),
                    (
                        "upstream_pandera_scale_to_exp_no_seed_function_repair_one_five",
                        _pandera_stage2_variant_tests(),
                        "opaque-pandera-scale-no-seed-contract-1",
                    ),
                ),
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_pandera_scale_agent.py"
            _write_test_mutating_cheating_agent(cheating_agent)
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            approved_preservations = [
                _preservation_scan(
                    broken_source,
                    result.workspace,
                    target_path=PANDERA_TARGET_PATH,
                    exclude_function="_scale_to_exp",
                )
                for result in report.approved_learning_run.results
            ]
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="_scale_to_exp",
                expected_result_count=4,
            )

        self.assertEqual(preservation["violations"], [])
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["mode"], "replace_functions")
        self.assertEqual(hint["functions"], ["_scale_to_exp"])
        self.assertNotIn("class Decimal", hint["files"][PANDERA_TARGET_PATH])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        for approved_result in report.approved_learning_run.results:
            self.assertEqual(approved_result.patch_metrics.changed_files, (PANDERA_TARGET_PATH,))
            self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual([item["violations"] for item in approved_preservations], [[], []])
        self.assertEqual(stability.summary()["solved"], 4)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        _assert_hidden_test_cheat_run_caught(self, cheat_run, expected_total=2)

    def test_vendored_pandera_bool_predicate_no_seed_stage1_reuses_with_stability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-pandera-bool-no-seed-stage1-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = PANDERA_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), PANDERA_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _replace_function(
                actual_source,
                "is_bool",
                (
                    "def is_bool(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n"
                    "    return False\n"
                ),
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _pandera_bool_stage1_tests(), target_path=PANDERA_TARGET_PATH)
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
            self.assertEqual(implementation.data["files_touched"], [PANDERA_TARGET_PATH])
            solved = (stage1 / PANDERA_TARGET_PATH).read_text(encoding="utf-8")
            self.assertIn("return is_subdtype(pandera_dtype, Bool)", solved)
            self.assertNotIn("def is_bool(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n    return False", solved)
            preservation = _preservation_scan(
                broken_source,
                stage1,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="is_bool",
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-pandera-bool-no-seed-function-repair",
                description="No-seed learned dtype-predicate function-level repair from vendored Pandera dtypes.py.",
                triggers=("opaque-pandera-bool-no-seed-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored Pandera bool predicate no-seed function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_dtypes_scale.py"), str(PANDERA_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "pandera_bool_stage2_tasks.json"
            _write_stage2_task_pack(
                task_file,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                task_specs=(
                    (
                        "upstream_pandera_bool_predicate_function_repair_instance_binary",
                        _pandera_bool_stage2_tests(),
                        "opaque-pandera-bool-no-seed-contract-1",
                    ),
                    (
                        "upstream_pandera_bool_predicate_function_repair_class_numeric",
                        _pandera_bool_stage2_variant_tests(),
                        "opaque-pandera-bool-no-seed-contract-1",
                    ),
                ),
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_pandera_bool_agent.py"
            _write_test_mutating_cheating_agent(cheating_agent)
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            approved_preservations = [
                _preservation_scan(
                    broken_source,
                    result.workspace,
                    target_path=PANDERA_TARGET_PATH,
                    exclude_function="is_bool",
                )
                for result in report.approved_learning_run.results
            ]
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=PANDERA_TARGET_PATH,
                exclude_function="is_bool",
                expected_result_count=4,
            )

        self.assertEqual(preservation["violations"], [])
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["mode"], "replace_functions")
        self.assertEqual(hint["functions"], ["is_bool"])
        self.assertNotIn("class Bool", hint["files"][PANDERA_TARGET_PATH])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        for approved_result in report.approved_learning_run.results:
            self.assertEqual(approved_result.patch_metrics.changed_files, (PANDERA_TARGET_PATH,))
            self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual([item["violations"] for item in approved_preservations], [[], []])
        self.assertEqual(stability.summary()["solved"], 4)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        _assert_hidden_test_cheat_run_caught(self, cheat_run, expected_total=2)

    def test_vendored_great_expectations_result_format_no_seed_stage1_extracts_function_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-ge-result-format-no-seed-stage1-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = GE_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), GE_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _replace_function(
                actual_source,
                "parse_result_format",
                (
                    "def parse_result_format(result_format: Union[str, dict]) -> dict:\n"
                    "    return {\"result_format\": result_format}\n"
                ),
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _ge_stage1_tests(), target_path=GE_TARGET_PATH)
            _write_great_expectations_import_stubs(stage1)
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
            self.assertEqual(implementation.data["files_touched"], [GE_TARGET_PATH])
            solved = (stage1 / GE_TARGET_PATH).read_text(encoding="utf-8")
            self.assertIn('"partial_unexpected_count": 20', solved)
            self.assertIn("raise ValueError", solved)
            self.assertNotIn('return {"result_format": result_format}', solved)
            preservation = _preservation_scan(
                broken_source,
                stage1,
                target_path=GE_TARGET_PATH,
                exclude_function="parse_result_format",
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-ge-result-format-no-seed-function-repair",
                description="No-seed learned function-level repair from vendored Great Expectations expectation_configuration.py.",
                triggers=("opaque-ge-result-format-no-seed-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored Great Expectations no-seed function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_expectation_configuration.py"), str(GE_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "ge_result_format_stage2_tasks.json"
            _write_stage2_task_pack(
                task_file,
                broken_source,
                target_path=GE_TARGET_PATH,
                task_specs=(
                    (
                        "upstream_ge_result_format_function_repair_complete_summary",
                        _ge_stage2_tests(),
                        "opaque-ge-result-format-no-seed-contract-1",
                    ),
                    (
                        "upstream_ge_result_format_function_repair_boolean_basic",
                        _ge_stage2_variant_tests(),
                        "opaque-ge-result-format-no-seed-contract-1",
                    ),
                ),
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_ge_agent.py"
            _write_test_mutating_cheating_agent(cheating_agent)
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            approved_preservations = [
                _preservation_scan(
                    broken_source,
                    result.workspace,
                    target_path=GE_TARGET_PATH,
                    exclude_function="parse_result_format",
                )
                for result in report.approved_learning_run.results
            ]
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=GE_TARGET_PATH,
                exclude_function="parse_result_format",
                expected_result_count=4,
            )

        self.assertEqual(preservation["violations"], [])
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["mode"], "replace_functions")
        self.assertEqual(hint["functions"], ["parse_result_format"])
        self.assertNotIn("class ExpectationConfiguration", hint["files"][GE_TARGET_PATH])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        for approved_result in report.approved_learning_run.results:
            self.assertEqual(approved_result.patch_metrics.changed_files, (GE_TARGET_PATH,))
            self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual([item["violations"] for item in approved_preservations], [[], []])
        self.assertEqual(stability.summary()["solved"], 4)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        _assert_hidden_test_cheat_run_caught(self, cheat_run, expected_total=2)

    def test_vendored_aider_random_color_no_seed_stage1_reuses_on_opaque_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-aider-random-color-no-seed-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            actual_source = AIDER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(actual_source), AIDER_MANIFEST.read_text(encoding="utf-8"))
            broken_source = _replace_function(
                actual_source,
                "get_random_color",
                (
                    "def get_random_color():\n"
                    "    return \"#000000\"\n"
                ),
            )

            stage1 = root / "stage1_workspace"
            _write_workspace(stage1, broken_source, _aider_stage1_tests(), target_path=AIDER_TARGET_PATH)
            _write_aider_import_stubs(stage1)
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
            self.assertEqual(implementation.data["files_touched"], [AIDER_TARGET_PATH])
            solved = (stage1 / AIDER_TARGET_PATH).read_text(encoding="utf-8")
            self.assertIn("colorsys.hsv_to_rgb(hue, 1, 0.75)", solved)
            self.assertIn("f\"#{r:02x}{g:02x}{b:02x}\"", solved)
            self.assertNotIn('return "#000000"', solved)
            preservation = _preservation_scan(
                broken_source,
                stage1,
                target_path=AIDER_TARGET_PATH,
                exclude_function="get_random_color",
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="upstream-aider-random-color-no-seed-function-repair",
                description="No-seed learned function-level repair from vendored Aider repomap.py.",
                triggers=("opaque-aider-random-color-no-seed-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)

            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="vendored Aider no-seed function-level stage1 repair verifies against package tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_repomap_color.py"), str(AIDER_SOURCE)),
                timeout_seconds=30,
            )
            self.assertTrue(eval_result.passed, eval_result.to_dict())
            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
            )

            task_file = root / "aider_random_color_stage2_tasks.json"
            _write_stage2_task_pack(
                task_file,
                broken_source,
                target_path=AIDER_TARGET_PATH,
                task_specs=(
                    (
                        "upstream_aider_random_color_function_repair_cyan_blue",
                        _aider_stage2_tests(),
                        "opaque-aider-random-color-no-seed-contract-1",
                    ),
                    (
                        "upstream_aider_random_color_function_repair_yellow_magenta",
                        _aider_stage2_variant_tests(),
                        "opaque-aider-random-color-no-seed-contract-1",
                    ),
                ),
            )
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
                repeats=2,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_aider_agent.py"
            _write_test_mutating_cheating_agent(cheating_agent)
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            approved_preservations = [
                _preservation_scan(
                    broken_source,
                    result.workspace,
                    target_path=AIDER_TARGET_PATH,
                    exclude_function="get_random_color",
                )
                for result in report.approved_learning_run.results
            ]
            _assert_stability_preserves_function_repair(
                self,
                stability,
                broken_source,
                target_path=AIDER_TARGET_PATH,
                exclude_function="get_random_color",
                expected_result_count=4,
            )

        self.assertEqual(preservation["violations"], [])
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["mode"], "replace_functions")
        self.assertEqual(hint["functions"], ["get_random_color"])
        self.assertNotIn("class RepoMap", hint["files"][AIDER_TARGET_PATH])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 2})
        self.assertEqual(report.no_learning_run.summary()["solved"], 0)
        self.assertEqual(report.approved_learning_run.summary()["solved"], 2)
        for approved_result in report.approved_learning_run.results:
            self.assertEqual(approved_result.patch_metrics.changed_files, (AIDER_TARGET_PATH,))
            self.assertEqual(approved_result.patch_metrics.out_of_scope_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_added_files, ())
            self.assertEqual(approved_result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual([item["violations"] for item in approved_preservations], [[], []])
        self.assertEqual(stability.summary()["solved"], 4)
        self.assertEqual(stability.summary()["success_rate_spread"], 0.0)
        self.assertEqual(stability.summary()["unstable_task_count"], 0)
        self.assertEqual(stability.summary()["cheated"], 0)
        self.assertEqual(stability.summary()["errors"], 0)
        self.assertEqual(stability.summary()["invalid"], 0)
        _assert_hidden_test_cheat_run_caught(self, cheat_run, expected_total=2)

    def test_fixed_version_combined_upstream_hidden_pack_reuses_without_cheating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upstream-combined-hidden-pack-") as tmp:
            root = Path(tmp)
            project = root / "learning_project"
            project.mkdir()
            mcp_source = UPSTREAM_SOURCE.read_text(encoding="utf-8")
            pandera_source = PANDERA_SOURCE.read_text(encoding="utf-8")
            ge_source = GE_SOURCE.read_text(encoding="utf-8")
            aider_source = AIDER_SOURCE.read_text(encoding="utf-8")
            self.assertIn(_sha256(mcp_source), UPSTREAM_MANIFEST.read_text(encoding="utf-8"))
            self.assertIn(_sha256(pandera_source), PANDERA_MANIFEST.read_text(encoding="utf-8"))
            self.assertIn(_sha256(ge_source), GE_MANIFEST.read_text(encoding="utf-8"))
            self.assertIn(_sha256(aider_source), AIDER_MANIFEST.read_text(encoding="utf-8"))
            families = (
                {
                    "id": "mcp_tool_name",
                    "source": mcp_source,
                    "broken_source": _replace_function(
                        mcp_source,
                        "validate_tool_name",
                        (
                            "def validate_tool_name(name: str) -> ToolNameValidationResult:\n"
                            "    return ToolNameValidationResult(is_valid=True, warnings=[])\n"
                        ),
                    ),
                    "target_path": TARGET_PATH,
                    "function": "validate_tool_name",
                    "trigger": "opaque-combined-upstream-mcp-1",
                    "stage1_tests": _stage1_tests(),
                    "stage2": (
                        ("combined_upstream_mcp_bounds_chars", _stage2_tests()),
                        ("combined_upstream_mcp_warning_invalids", _stage2_variant_tests()),
                    ),
                },
                {
                    "id": "pandera_scale",
                    "source": pandera_source,
                    "broken_source": _replace_function(
                        pandera_source,
                        "_scale_to_exp",
                        "def _scale_to_exp(scale: int) -> decimal.Decimal:\n    return decimal.Decimal('1')\n",
                    ),
                    "target_path": PANDERA_TARGET_PATH,
                    "function": "_scale_to_exp",
                    "trigger": "opaque-combined-upstream-pandera-scale-1",
                    "stage1_tests": _pandera_stage1_tests(),
                    "stage2": (
                        ("combined_upstream_pandera_scale_zero_three", _pandera_stage2_tests()),
                        ("combined_upstream_pandera_scale_large_exponents", _pandera_stage2_variant_tests()),
                    ),
                },
                {
                    "id": "pandera_bool",
                    "source": pandera_source,
                    "broken_source": _replace_function(
                        pandera_source,
                        "is_bool",
                        (
                            "def is_bool(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n"
                            "    return False\n"
                        ),
                    ),
                    "target_path": PANDERA_TARGET_PATH,
                    "function": "is_bool",
                    "trigger": "opaque-combined-upstream-pandera-bool-1",
                    "stage1_tests": _pandera_bool_stage1_tests(),
                    "stage2": (
                        ("combined_upstream_pandera_bool_instance_binary", _pandera_bool_stage2_tests()),
                        ("combined_upstream_pandera_bool_class_numeric", _pandera_bool_stage2_variant_tests()),
                    ),
                },
                {
                    "id": "ge_result_format",
                    "source": ge_source,
                    "broken_source": _replace_function(
                        ge_source,
                        "parse_result_format",
                        (
                            "def parse_result_format(result_format: Union[str, dict]) -> dict:\n"
                            "    return {\"result_format\": result_format}\n"
                        ),
                    ),
                    "target_path": GE_TARGET_PATH,
                    "function": "parse_result_format",
                    "trigger": "opaque-combined-upstream-ge-1",
                    "stage1_tests": _ge_stage1_tests(),
                    "stage2": (
                        ("combined_upstream_ge_complete_summary", _ge_stage2_tests()),
                        ("combined_upstream_ge_boolean_basic", _ge_stage2_variant_tests()),
                    ),
                    "write_stubs": _write_great_expectations_import_stubs,
                },
                {
                    "id": "aider_random_color",
                    "source": aider_source,
                    "broken_source": _replace_function(
                        aider_source,
                        "get_random_color",
                        (
                            "def get_random_color():\n"
                            "    return \"#000000\"\n"
                        ),
                    ),
                    "target_path": AIDER_TARGET_PATH,
                    "function": "get_random_color",
                    "trigger": "opaque-combined-upstream-aider-1",
                    "stage1_tests": _aider_stage1_tests(),
                    "stage2": (
                        ("combined_upstream_aider_cyan_blue", _aider_stage2_tests()),
                        ("combined_upstream_aider_off_axis", _aider_stage2_variant_tests()),
                    ),
                    "write_stubs": _write_aider_import_stubs,
                },
            )
            self.assertEqual(
                [family["id"] for family in families],
                ["mcp_tool_name", "pandera_scale", "pandera_bool", "ge_result_format", "aider_random_color"],
            )
            expected: dict[str, dict[str, str]] = {}
            task_specs: list[tuple[str, str, str, str, str]] = []
            for family in families:
                _approve_no_seed_upstream_function_repair(
                    self,
                    root,
                    project,
                    family=family,
                )
                for task_id, test_source in family["stage2"]:
                    expected[task_id] = {
                        "target_path": family["target_path"],
                        "broken_source": family["broken_source"],
                        "function": family["function"],
                    }
                    task_specs.append(
                        (
                            task_id,
                            family["broken_source"],
                            family["target_path"],
                            test_source,
                            family["trigger"],
                        )
                    )
            expected_task_ids = (
                "combined_upstream_mcp_bounds_chars",
                "combined_upstream_mcp_warning_invalids",
                "combined_upstream_pandera_scale_zero_three",
                "combined_upstream_pandera_scale_large_exponents",
                "combined_upstream_pandera_bool_instance_binary",
                "combined_upstream_pandera_bool_class_numeric",
                "combined_upstream_ge_complete_summary",
                "combined_upstream_ge_boolean_basic",
                "combined_upstream_aider_cyan_blue",
                "combined_upstream_aider_off_axis",
            )
            self.assertEqual(tuple(task_id for task_id, *_ in task_specs), expected_task_ids)

            task_file = root / "combined_upstream_hidden_tasks.json"
            _write_combined_stage2_task_pack(task_file, tuple(task_specs))
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
            stability_repeats = 10
            stability = run_coding_bench_stability(
                project,
                agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=task_file,
                repeats=stability_repeats,
                keep_workspaces=True,
            )
            cheating_agent = root / "cheating_agent.py"
            cheating_agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "for test_file in (workspace / 'tests').glob('test_*.py'):\n"
                "    test_file.write_text('import unittest\\n\\nclass TestCheated(unittest.TestCase):\\n"
                "    def test_cheated(self):\\n        self.assertTrue(True)\\n', encoding='utf-8')\n"
                "(workspace / 'tests' / 'failure_log.txt').write_text('hidden failures removed\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            cheat_run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(cheating_agent)) + " {workspace}",
                task_file=task_file,
                keep_workspaces=True,
            )
            approved_results = report.approved_learning_run.results
            no_learning_results = report.no_learning_run.results
            stability_results = [result for run in stability.runs for result in run.results]
            expected_task_ids = set(expected)
            self.assertEqual({result.task_id for result in no_learning_results}, expected_task_ids)
            self.assertEqual({result.task_id for result in approved_results}, expected_task_ids)
            self.assertEqual({result.task_id for result in stability_results}, expected_task_ids)
            self.assertEqual(len(no_learning_results), len(task_specs))
            self.assertEqual(len(stability_results), len(task_specs) * stability_repeats)
            _assert_combined_upstream_results_preserve(self, approved_results, expected)
            _assert_combined_upstream_results_preserve(self, stability_results, expected, require_unique_workspaces=True)
            no_learning_summary = report.no_learning_run.summary()
            approved_summary = report.approved_learning_run.summary()
            stability_summary = stability.summary()
            cheat_summary = cheat_run.summary()
            cheat_results = cheat_run.results

        self.assertEqual(benchmark_fingerprint, "1ce60706b7ab88d90b30b3241f0cb294e859f93afd23d5eaf1b03e3f88979bb3")
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": len(task_specs)})
        self.assertEqual(no_learning_summary["total"], len(task_specs))
        self.assertEqual(no_learning_summary["solved"], 0)
        self.assertEqual(no_learning_summary["failed"], len(task_specs))
        self.assertEqual(no_learning_summary["cheated"], 0)
        self.assertEqual(no_learning_summary["errors"], 0)
        self.assertEqual(no_learning_summary["invalid"], 0)
        self.assertEqual(approved_summary["solved"], len(task_specs))
        self.assertEqual(approved_summary["failed"], 0)
        self.assertEqual(approved_summary["cheated"], 0)
        self.assertEqual(approved_summary["errors"], 0)
        self.assertEqual(approved_summary["invalid"], 0)
        self.assertEqual(stability_summary["solved"], len(task_specs) * stability_repeats)
        self.assertEqual(stability_summary["success_rate_spread"], 0.0)
        self.assertEqual(stability_summary["unstable_task_count"], 0)
        self.assertEqual(stability_summary.get("failed", 0), 0)
        self.assertEqual(stability_summary["cheated"], 0)
        self.assertEqual(stability_summary["errors"], 0)
        self.assertEqual(stability_summary["invalid"], 0)
        self.assertEqual(cheat_summary["total"], len(task_specs))
        self.assertEqual(cheat_summary["solved"], 0)
        self.assertEqual(cheat_summary["cheated"], len(task_specs))
        self.assertEqual(cheat_summary.get("failed", 0), 0)
        self.assertEqual(cheat_summary["errors"], 0)
        self.assertEqual(cheat_summary["invalid"], 0)
        for cheat_result in cheat_results:
            self.assertEqual(cheat_result.status, "cheated")
            self.assertFalse(cheat_result.solved)
            self.assertEqual(cheat_result.failure_class, "policy")
            self.assertIn("tests/failure_log.txt", cheat_result.patch_metrics.out_of_scope_files)
            self.assertTrue(
                any(path.startswith("tests/test_") for path in cheat_result.patch_metrics.out_of_scope_files),
                cheat_result.to_dict(),
            )


def _install_seed_file_function_skill(
    project: Path,
    replacement: str,
    *,
    target_path: str = TARGET_PATH,
    function_name: str = "validate_tool_name",
    trigger: str = "seed-upstream-function-1",
) -> None:
    skill_dir = project / "seed_upstream_function_skill"
    skill_dir.mkdir(parents=True)
    hint = {
        "target": "file_function_bundle",
        "functions": [function_name],
        "files": {target_path: {function_name: replacement if replacement.endswith("\n") else replacement + "\n"}},
    }
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: seed-upstream-function-repair\n"
        "description: Seed function-level repair for vendored MCP tool name validation.\n"
        f"triggers: {trigger}\n"
        "---\n\n"
        "# Seed Upstream Function Repair\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )
    install_skill(project, skill_dir)


def _write_workspace(workspace: Path, module_source: str, test_source: str, *, target_path: str = TARGET_PATH) -> None:
    target = workspace / target_path
    target.parent.mkdir(parents=True)
    current = target.parent
    while current != workspace:
        (current / "__init__.py").write_text("", encoding="utf-8")
        current = current.parent
    target.write_text(module_source, encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / "tests" / _test_name_for_target(target_path)).write_text(test_source, encoding="utf-8")


def _approve_no_seed_upstream_function_repair(
    test_case: unittest.TestCase,
    root: Path,
    project: Path,
    *,
    family: dict[str, Any],
) -> None:
    stage1 = root / f"stage1_{family['id']}"
    target_path = family["target_path"]
    function_name = family["function"]
    _write_workspace(stage1, family["broken_source"], family["stage1_tests"], target_path=target_path)
    if "write_stubs" in family:
        family["write_stubs"](stage1)
    result = run_agent_loop(
        stage1,
        "Fix the failing package tests without editing tests.",
        explicit_mode="repair",
        include_validation=True,
        learning_context="off",
        max_steps=12,
    )
    test_case.assertTrue(result.ok, result.to_dict())
    implementation = next(item for item in result.observations if item.name == "implement")
    test_case.assertEqual(implementation.data["files_touched"], [target_path])
    preservation = _preservation_scan(
        family["broken_source"],
        stage1,
        target_path=target_path,
        exclude_function=function_name,
    )
    test_case.assertEqual(preservation["violations"], [])

    proposal = propose_file_bundle_repair_skill_from_trajectory(
        project,
        result.trajectory_path,
        workspace=stage1,
        name=f"combined-{family['id'].replace('_', '-')}-function-repair",
        description="No-seed learned function-level repair for a combined upstream hidden benchmark.",
        triggers=(family["trigger"],),
    )
    hint = _openmako_repair_hint(proposal.body)
    test_case.assertEqual(hint["target"], "file_bundle")
    test_case.assertEqual(hint["mode"], "replace_functions")
    test_case.assertEqual(hint["functions"], [function_name])

    eval_result = run_skill_eval_command(
        project,
        f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
        summary=f"combined upstream {family['id']} no-seed stage1 repair verifies against package tests",
        evidence=(
            result.trajectory_path,
            str(stage1 / "tests" / _test_name_for_target(target_path)),
        ),
        timeout_seconds=30,
    )
    test_case.assertTrue(eval_result.passed, eval_result.to_dict())
    approve_skill_proposal(
        project,
        proposal.proposal_id,
        eval_result=_with_learning_report(eval_result, _stage1_learning_report(proposal), proposal),
    )


def _write_stage2_tasks(
    path: Path,
    broken_source: str,
    *,
    target_path: str = TARGET_PATH,
    test_source: str | None = None,
    task_id: str = "upstream_mcp_tool_name_validation_function_repair",
    trigger: str = "opaque-upstream-function-contract-1",
) -> None:
    _write_stage2_task_pack(
        path,
        broken_source,
        target_path=target_path,
        task_specs=((task_id, test_source or _stage2_tests(), trigger),),
    )


def _write_stage2_task_pack(
    path: Path,
    broken_source: str,
    *,
    target_path: str,
    task_specs: tuple[tuple[str, str, str], ...],
) -> None:
    payload = {
        "tasks": [
            {
                "id": task_id,
                "instruction": f"Fix failing package tests using approved learning contract {trigger}.",
                "files": _stage2_task_files(broken_source, target_path=target_path, test_source=task_test_source),
                "test_command": "{python} -m unittest discover -s tests -q",
                "max_iterations": 1,
                "timeout_seconds": 30,
                "tags": ["stage2", "upstream", "function-level", "file-bundle"],
            }
            for task_id, task_test_source, trigger in task_specs
        ]
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_combined_stage2_task_pack(path: Path, task_specs: tuple[tuple[str, str, str, str, str], ...]) -> None:
    payload = {
        "tasks": [
            {
                "id": task_id,
                "instruction": f"Fix failing package tests using approved learning contract {trigger}.",
                "files": _stage2_task_files(broken_source, target_path=target_path, test_source=task_test_source),
                "test_command": "{python} -m unittest discover -s tests -q",
                "max_iterations": 1,
                "timeout_seconds": 30,
                "tags": ["stage2", "upstream", "combined-hidden", "anti-cheat", "file-bundle"],
            }
            for task_id, broken_source, target_path, task_test_source, trigger in task_specs
        ]
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_test_mutating_cheating_agent(path: Path) -> None:
    path.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "workspace = Path(sys.argv[1])\n"
        "for test_file in (workspace / 'tests').glob('test_*.py'):\n"
        "    test_file.write_text('import unittest\\n\\nclass TestCheated(unittest.TestCase):\\n"
        "    def test_cheated(self):\\n        self.assertTrue(True)\\n', encoding='utf-8')\n"
        "(workspace / 'tests' / 'failure_log.txt').write_text('hidden failures removed\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )


def _assert_hidden_test_cheat_run_caught(test_case: unittest.TestCase, cheat_run: Any, *, expected_total: int) -> None:
    cheat_summary = cheat_run.summary()
    test_case.assertEqual(cheat_summary["total"], expected_total)
    test_case.assertEqual(cheat_summary["solved"], 0)
    test_case.assertEqual(cheat_summary["cheated"], expected_total)
    test_case.assertEqual(cheat_summary.get("failed", 0), 0)
    test_case.assertEqual(cheat_summary["errors"], 0)
    test_case.assertEqual(cheat_summary["invalid"], 0)
    for cheat_result in cheat_run.results:
        test_case.assertEqual(cheat_result.status, "cheated")
        test_case.assertFalse(cheat_result.solved)
        test_case.assertEqual(cheat_result.failure_class, "policy")
        changed_evidence_files = set(cheat_result.patch_metrics.out_of_scope_files)
        changed_evidence_files.update(cheat_result.patch_metrics.workspace_added_files)
        test_case.assertIn("tests/failure_log.txt", changed_evidence_files)
        test_case.assertTrue(
            any(path.startswith("tests/test_") for path in cheat_result.patch_metrics.out_of_scope_files),
            cheat_result.to_dict(),
        )


def _stage2_task_files(broken_source: str, *, target_path: str, test_source: str) -> dict[str, str]:
    package_files = _package_init_files(target_path)
    if target_path == GE_TARGET_PATH:
        extra_files = _great_expectations_import_stub_files()
    elif target_path == AIDER_TARGET_PATH:
        extra_files = _aider_import_stub_files()
    else:
        extra_files = {}
    return {
        **package_files,
        **extra_files,
        target_path: broken_source,
        "tests/__init__.py": "",
        "tests/failure_log.txt": "Hidden validation failures are protected benchmark evidence.\n",
        f"tests/{_test_name_for_target(target_path)}": test_source,
    }


def _test_name_for_target(target_path: str) -> str:
    if target_path == PANDERA_TARGET_PATH:
        return "test_dtypes_scale.py"
    if target_path == GE_TARGET_PATH:
        return "test_expectation_configuration.py"
    if target_path == AIDER_TARGET_PATH:
        return "test_repomap_color.py"
    return "test_tool_name_validation.py"


def _package_init_files(target_path: str) -> dict[str, str]:
    parts = Path(target_path).parts[:-1]
    files: dict[str, str] = {}
    for index in range(1, len(parts) + 1):
        files[Path(*parts[:index], "__init__.py").as_posix()] = ""
    return files


def _stage1_tests() -> str:
    return (
        "import unittest\n"
        "from mcp.shared.tool_name_validation import validate_tool_name\n\n"
        "class TestToolNameValidation(unittest.TestCase):\n"
        "    def test_accepts_valid_tool_names(self):\n"
        "        self.assertTrue(validate_tool_name('desktop.find-click').is_valid)\n"
        "    def test_rejects_empty_and_invalid_names(self):\n"
        "        self.assertFalse(validate_tool_name('').is_valid)\n"
        "        self.assertFalse(validate_tool_name('bad/name').is_valid)\n"
        "    def test_warns_without_rejecting_spaces(self):\n"
        "        result = validate_tool_name('bad name')\n"
        "        self.assertFalse(result.is_valid)\n"
        "        self.assertTrue(result.warnings)\n"
    )


def _stage2_tests() -> str:
    return (
        "import unittest\n"
        "from mcp.shared.tool_name_validation import validate_tool_name\n\n"
        "class TestToolNameValidation(unittest.TestCase):\n"
        "    def test_accepts_dot_dash_underscore(self):\n"
        "        self.assertTrue(validate_tool_name('alpha.beta_gamma-1').is_valid)\n"
        "    def test_rejects_empty_and_too_long(self):\n"
        "        self.assertFalse(validate_tool_name('').is_valid)\n"
        "        self.assertFalse(validate_tool_name('x' * 129).is_valid)\n"
        "    def test_rejects_disallowed_character(self):\n"
        "        result = validate_tool_name('bad/tool')\n"
        "        self.assertFalse(result.is_valid)\n"
        "        self.assertTrue(any('invalid characters' in item for item in result.warnings))\n"
    )


def _stage2_variant_tests() -> str:
    return (
        "import unittest\n"
        "from mcp.shared.tool_name_validation import validate_tool_name\n\n"
        "class TestToolNameValidationVariant(unittest.TestCase):\n"
        "    def test_accepts_edge_punctuation_with_warnings(self):\n"
        "        result = validate_tool_name('-alpha.tool.')\n"
        "        self.assertTrue(result.is_valid)\n"
        "        self.assertTrue(any('dash' in item for item in result.warnings))\n"
        "        self.assertTrue(any('dot' in item for item in result.warnings))\n"
        "    def test_reports_unique_invalid_characters(self):\n"
        "        result = validate_tool_name('bad/tool:name')\n"
        "        joined = '\\n'.join(result.warnings)\n"
        "        self.assertFalse(result.is_valid)\n"
        "        self.assertIn('invalid characters', joined)\n"
        "        self.assertIn(\"'/'\", joined)\n"
        "        self.assertIn(\"':'\", joined)\n"
        "        self.assertIn('Allowed characters', joined)\n"
    )


def _pandera_stage1_tests() -> str:
    return (
        "import decimal\n"
        "import unittest\n"
        "from pandera.dtypes import _scale_to_exp\n\n"
        "class TestPanderaScaleToExp(unittest.TestCase):\n"
        "    def test_scale_two(self):\n"
        "        self.assertEqual(_scale_to_exp(2), decimal.Decimal('0.01'))\n"
        "    def test_scale_four(self):\n"
        "        self.assertEqual(_scale_to_exp(4), decimal.Decimal('0.0001'))\n"
    )


def _pandera_stage2_tests() -> str:
    return (
        "import decimal\n"
        "import unittest\n"
        "from pandera.dtypes import _scale_to_exp\n\n"
        "class TestPanderaScaleToExpHidden(unittest.TestCase):\n"
        "    def test_scale_zero(self):\n"
        "        self.assertEqual(_scale_to_exp(0), decimal.Decimal('1'))\n"
        "    def test_scale_three(self):\n"
        "        self.assertEqual(_scale_to_exp(3), decimal.Decimal('0.001'))\n"
    )


def _pandera_stage2_variant_tests() -> str:
    return (
        "import decimal\n"
        "import unittest\n"
        "from pandera.dtypes import _scale_to_exp\n\n"
        "class TestPanderaScaleToExpVariant(unittest.TestCase):\n"
        "    def test_scale_values_follow_decimal_exponent_property(self):\n"
        "        for scale in (1, 5, 8, 9, 12):\n"
        "            with self.subTest(scale=scale):\n"
        "                result = _scale_to_exp(scale)\n"
        "                expected = decimal.Decimal(10) ** decimal.Decimal(-scale)\n"
        "                self.assertEqual(result, expected)\n"
        "                self.assertEqual(result * (decimal.Decimal(10) ** scale), decimal.Decimal('1'))\n"
    )


def _pandera_bool_stage1_tests() -> str:
    return (
        "import unittest\n"
        "import pandera.dtypes as dtypes\n"
        "from pandera.dtypes import is_bool\n\n"
        "class TestPanderaBoolPredicate(unittest.TestCase):\n"
        "    def test_accepts_bool_dtype_class_and_instance(self):\n"
        "        self.assertTrue(is_bool(dtypes.Bool))\n"
        "        self.assertTrue(is_bool(dtypes.Bool()))\n"
        "    def test_rejects_non_bool_dtypes(self):\n"
        "        self.assertFalse(is_bool(dtypes.String))\n"
        "        self.assertFalse(is_bool(dtypes.Int()))\n"
    )


def _pandera_bool_stage2_tests() -> str:
    return (
        "import unittest\n"
        "import pandera.dtypes as dtypes\n"
        "from pandera.dtypes import is_bool\n\n"
        "class TestPanderaBoolPredicateHidden(unittest.TestCase):\n"
        "    def test_accepts_bool_instance(self):\n"
        "        self.assertTrue(is_bool(dtypes.Bool()))\n"
        "    def test_rejects_string_and_binary_classes(self):\n"
        "        self.assertFalse(is_bool(dtypes.String))\n"
        "        self.assertFalse(is_bool(dtypes.Binary))\n"
    )


def _pandera_bool_stage2_variant_tests() -> str:
    return (
        "import unittest\n"
        "import pandera.dtypes as dtypes\n"
        "from pandera.dtypes import is_bool\n\n"
        "class TestPanderaBoolPredicateClassVariant(unittest.TestCase):\n"
        "    def test_accepts_bool_class(self):\n"
        "        self.assertTrue(is_bool(dtypes.Bool))\n"
        "    def test_rejects_numeric_and_category_instances(self):\n"
        "        self.assertFalse(is_bool(dtypes.Float()))\n"
        "        self.assertFalse(is_bool(dtypes.Category))\n"
    )


def _ge_stage1_tests() -> str:
    return (
        "import unittest\n"
        "from great_expectations.expectations.expectation_configuration import parse_result_format\n\n"
        "class TestResultFormat(unittest.TestCase):\n"
        "    def test_string_result_format_gets_defaults(self):\n"
        "        self.assertEqual(parse_result_format('SUMMARY'), {\n"
        "            'result_format': 'SUMMARY',\n"
        "            'partial_unexpected_count': 20,\n"
        "            'include_unexpected_rows': False,\n"
        "            'map_expectation_unexpected_rows_as_dict': False,\n"
        "        })\n"
        "    def test_dict_result_format_gets_defaults(self):\n"
        "        self.assertEqual(parse_result_format({'result_format': 'COMPLETE'}), {\n"
        "            'result_format': 'COMPLETE',\n"
        "            'partial_unexpected_count': 20,\n"
        "            'include_unexpected_rows': False,\n"
        "            'map_expectation_unexpected_rows_as_dict': False,\n"
        "        })\n"
        "    def test_include_unexpected_rows_requires_explicit_result_format(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            parse_result_format({'include_unexpected_rows': True})\n"
    )


def _ge_stage2_tests() -> str:
    return (
        "import unittest\n"
        "from great_expectations.expectations.expectation_configuration import parse_result_format\n\n"
        "class TestResultFormatHidden(unittest.TestCase):\n"
        "    def test_string_complete_result_format_gets_defaults(self):\n"
        "        self.assertEqual(parse_result_format('COMPLETE'), {\n"
        "            'result_format': 'COMPLETE',\n"
        "            'partial_unexpected_count': 20,\n"
        "            'include_unexpected_rows': False,\n"
        "            'map_expectation_unexpected_rows_as_dict': False,\n"
        "        })\n"
        "    def test_dict_preserves_explicit_values(self):\n"
        "        self.assertEqual(parse_result_format({\n"
        "            'result_format': 'SUMMARY',\n"
        "            'partial_unexpected_count': 5,\n"
        "            'include_unexpected_rows': True,\n"
        "        }), {\n"
        "            'result_format': 'SUMMARY',\n"
        "            'partial_unexpected_count': 5,\n"
        "            'include_unexpected_rows': True,\n"
        "            'map_expectation_unexpected_rows_as_dict': False,\n"
        "        })\n"
        "    def test_include_unexpected_rows_still_requires_result_format(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            parse_result_format({'include_unexpected_rows': False})\n"
    )


def _ge_stage2_variant_tests() -> str:
    return (
        "import unittest\n"
        "from great_expectations.expectations.expectation_configuration import parse_result_format\n\n"
        "class TestResultFormatVariant(unittest.TestCase):\n"
        "    def test_basic_string_gets_defaults(self):\n"
        "        self.assertEqual(parse_result_format('BASIC'), {\n"
        "            'result_format': 'BASIC',\n"
        "            'partial_unexpected_count': 20,\n"
        "            'include_unexpected_rows': False,\n"
        "            'map_expectation_unexpected_rows_as_dict': False,\n"
        "        })\n"
        "    def test_dict_preserves_mapping_flag(self):\n"
        "        self.assertEqual(parse_result_format({\n"
        "            'result_format': 'BOOLEAN_ONLY',\n"
        "            'map_expectation_unexpected_rows_as_dict': True,\n"
        "        }), {\n"
        "            'result_format': 'BOOLEAN_ONLY',\n"
        "            'map_expectation_unexpected_rows_as_dict': True,\n"
        "            'partial_unexpected_count': 20,\n"
        "            'include_unexpected_rows': False,\n"
        "        })\n"
        "    def test_include_unexpected_rows_true_still_requires_result_format(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            parse_result_format({'include_unexpected_rows': True})\n"
    )


def _aider_stage1_tests() -> str:
    return (
        "import unittest\n"
        "import aider.repomap as repomap\n"
        "from aider.repomap import get_random_color\n\n"
        "class TestRepoMapColor(unittest.TestCase):\n"
        "    def test_zero_hue_is_dark_red(self):\n"
        "        repomap.random.random = lambda: 0.0\n"
        "        self.assertEqual(get_random_color(), '#bf0000')\n"
        "    def test_green_hue_is_formatted_hex(self):\n"
        "        repomap.random.random = lambda: 0.3333333333333333\n"
        "        self.assertEqual(get_random_color(), '#00bf00')\n"
    )


def _aider_stage2_tests() -> str:
    return (
        "import unittest\n"
        "import aider.repomap as repomap\n"
        "from aider.repomap import get_random_color\n\n"
        "class TestRepoMapColorHidden(unittest.TestCase):\n"
        "    def test_cyan_hue_is_formatted_hex(self):\n"
        "        repomap.random.random = lambda: 0.5\n"
        "        self.assertEqual(get_random_color(), '#00bfbf')\n"
        "    def test_blue_hue_is_formatted_hex(self):\n"
        "        repomap.random.random = lambda: 0.6666666666666666\n"
        "        self.assertEqual(get_random_color(), '#0000bf')\n"
    )


def _aider_stage2_variant_tests() -> str:
    return (
        "import colorsys\n"
        "import unittest\n"
        "import aider.repomap as repomap\n"
        "from aider.repomap import get_random_color\n\n"
        "class TestRepoMapColorVariant(unittest.TestCase):\n"
        "    def assert_color_for_hue(self, hue):\n"
        "        repomap.random.random = lambda hue=hue: hue\n"
        "        r, g, b = colorsys.hsv_to_rgb(hue, 1, 0.75)\n"
        "        expected = '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))\n"
        "        self.assertEqual(get_random_color(), expected)\n"
        "    def test_off_axis_hue_sweep_is_formatted_hex(self):\n"
        "        for hue in (0.1, 0.17, 0.42, 0.58, 0.91):\n"
        "            with self.subTest(hue=hue):\n"
        "                self.assert_color_for_hue(hue)\n"
    )


def _write_great_expectations_import_stubs(workspace: Path) -> None:
    for relative_path, source in _great_expectations_import_stub_files().items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _great_expectations_import_stub_files() -> dict[str, str]:
    stub_files: dict[str, str] = {
        "typing_extensions.py": (
            "from typing import TypedDict\n\n"
            "def override(func):\n"
            "    return func\n"
        ),
        "marshmallow/__init__.py": (
            "class Schema:\n"
            "    def load(self, value):\n"
            "        return value\n"
            "    def dump(self, value):\n"
            "        return value\n\n"
            "class ValidationError(Exception):\n"
            "    pass\n\n"
            "class _Fields:\n"
            "    def __getattr__(self, _name):\n"
            "        def factory(*_args, **_kwargs):\n"
            "            return object()\n"
            "        return factory\n\n"
            "fields = _Fields()\n\n"
            "def _decorator(func=None, *_args, **_kwargs):\n"
            "    if callable(func):\n"
            "        return func\n"
            "    def wrap(inner):\n"
            "        return inner\n"
            "    return wrap\n\n"
            "post_dump = _decorator\n"
            "post_load = _decorator\n"
            "pre_dump = _decorator\n"
        ),
        "great_expectations/compatibility/typing_extensions.py": (
            "def override(func):\n"
            "    return func\n"
        ),
        "great_expectations/core/metric_domain_types.py": (
            "from enum import Enum\n\n"
            "class MetricDomainTypes(Enum):\n"
            "    TABLE = 'table'\n"
            "    COLUMN = 'column'\n"
            "    COLUMN_PAIR = 'column_pair'\n"
            "    MULTICOLUMN = 'multicolumn'\n"
        ),
        "great_expectations/core/suite_parameters.py": (
            "def build_suite_parameters(*_args, **_kwargs):\n"
            "    return {}, None\n"
        ),
        "great_expectations/exceptions.py": (
            "class ExpectationNotFoundError(Exception):\n"
            "    pass\n\n"
            "class InvalidExpectationConfigurationError(Exception):\n"
            "    pass\n\n"
            "class InvalidExpectationKwargsError(Exception):\n"
            "    pass\n"
        ),
        "great_expectations/expectations/metadata_types.py": (
            "from enum import Enum\n\n"
            "class FailureSeverity(Enum):\n"
            "    CRITICAL = 'critical'\n"
        ),
        "great_expectations/expectations/registry.py": (
            "class _Expectation:\n"
            "    domain_keys = ()\n"
            "    success_keys = ()\n\n"
            "def get_expectation_impl(_name):\n"
            "    return _Expectation\n"
        ),
        "great_expectations/render.py": (
            "class RenderedAtomicContent:\n"
            "    pass\n\n"
            "class RenderedAtomicContentSchema:\n"
            "    pass\n"
        ),
        "great_expectations/types.py": (
            "class SerializableDictDot:\n"
            "    pass\n"
        ),
        "great_expectations/util.py": (
            "def convert_to_json_serializable(value):\n"
            "    return value\n\n"
            "def ensure_json_serializable(value):\n"
            "    return value\n"
        ),
    }
    files = dict(stub_files)
    for relative_path, source in stub_files.items():
        current = Path(relative_path).parent
        while current != Path("."):
            files.setdefault((current / "__init__.py").as_posix(), "")
            current = current.parent
    return files


def _write_aider_import_stubs(workspace: Path) -> None:
    for relative_path, source in _aider_import_stub_files().items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def _aider_import_stub_files() -> dict[str, str]:
    stub_files: dict[str, str] = {
        "diskcache.py": (
            "class Cache(dict):\n"
            "    def __init__(self, *_args, **_kwargs):\n"
            "        super().__init__()\n"
            "    def close(self):\n"
            "        return None\n"
        ),
        "grep_ast/__init__.py": (
            "class TreeContext:\n"
            "    pass\n\n"
            "def filename_to_lang(_filename):\n"
            "    return None\n"
        ),
        "grep_ast/tsl.py": (
            "USING_TSL_PACK = False\n\n"
            "def get_language(_lang):\n"
            "    return None\n\n"
            "def get_parser(_lang):\n"
            "    return None\n"
        ),
        "pygments/__init__.py": "",
        "pygments/lexers.py": (
            "def guess_lexer_for_filename(*_args, **_kwargs):\n"
            "    return None\n"
        ),
        "pygments/token.py": (
            "class _Token:\n"
            "    pass\n\n"
            "Token = _Token()\n"
        ),
        "tqdm.py": (
            "def tqdm(iterable=None, *_args, **_kwargs):\n"
            "    return [] if iterable is None else iterable\n"
        ),
        "tree_sitter.py": (
            "class Query:\n"
            "    pass\n"
        ),
        "aider/dump.py": (
            "def dump(*_args, **_kwargs):\n"
            "    return None\n"
        ),
        "aider/special.py": (
            "def filter_important_files(files):\n"
            "    return files\n"
        ),
        "aider/waiting.py": (
            "class Spinner:\n"
            "    def __init__(self, *_args, **_kwargs):\n"
            "        pass\n"
            "    def __enter__(self):\n"
            "        return self\n"
            "    def __exit__(self, *_args):\n"
            "        return False\n"
        ),
    }
    files = dict(stub_files)
    for relative_path in stub_files:
        current = Path(relative_path).parent
        while current != Path("."):
            files.setdefault((current / "__init__.py").as_posix(), "")
            current = current.parent
    return files


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "".join(source.splitlines(keepends=True)[node.lineno - 1 : node.end_lineno])
    raise KeyError(name)


def _replace_function(source: str, name: str, replacement: str) -> str:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines[node.lineno - 1 : node.end_lineno] = (replacement.rstrip() + "\n").splitlines(keepends=True)
            return "".join(lines)
    raise KeyError(name)


def _openmako_repair_hint(body: str) -> dict[str, Any]:
    start = body.index("```openmako-repair") + len("```openmako-repair")
    end = body.index("```", start)
    return json.loads(body[start:end].strip())


def _stage1_learning_report(proposal: Any) -> dict[str, Any]:
    return {
        "status": "pass",
        "score_delta": 100.0,
        "total": 1,
        "solved": {"no_learning": 0, "approved_learning": 1},
        "comparisons": [
            {
                "task_id": "stage1-upstream-function",
                "score_delta": 100.0,
                "no_learning": {
                    "task_id": "stage1-upstream-function",
                    "solved": False,
                    "steps": 1,
                    "failure_class": "unsupported_without_learning",
                    "evidence": ["no-learning cannot infer complex upstream module function repair"],
                    "invalid_reason": "",
                },
                "approved_learning": {
                    "task_id": "stage1-upstream-function",
                    "solved": True,
                    "steps": 1,
                    "failure_class": "",
                    "evidence": ["approved seed function-level repair passed stage1 package tests"],
                    "invalid_reason": "",
                },
            }
        ],
    }


def _with_learning_report(eval_result: Any, report: dict[str, Any], proposal: Any) -> Any:
    return replace(
        eval_result,
        require_learning_effect=True,
        learning_effect_report=bind_learning_effect_report_to_proposal(report, proposal),
    )


def _preservation_scan(
    broken_source: str,
    workspace: str,
    *,
    target_path: str = TARGET_PATH,
    exclude_function: str = "validate_tool_name",
) -> dict[str, Any]:
    target = Path(workspace) / target_path
    solved_source = target.read_text(encoding="utf-8")
    before = _top_level_hashes(broken_source, exclude={exclude_function})
    after = _top_level_hashes(solved_source, exclude={exclude_function})
    violations = [key for key, before_hash in before.items() if after.get(key) != before_hash]
    violations.extend(sorted(set(after) - set(before)))
    return {
        "checked_non_target_definitions": sorted(before),
        "target_path": target_path,
        "violations": sorted(violations),
        "workspace": workspace,
    }


def _assert_stability_preserves_function_repair(
    test_case: unittest.TestCase,
    stability: Any,
    broken_source: str,
    *,
    target_path: str,
    exclude_function: str,
    expected_result_count: int,
) -> None:
    results = [result for run in stability.runs for result in run.results]
    test_case.assertEqual(len(results), expected_result_count)
    workspaces = [str(result.workspace) for result in results]
    test_case.assertEqual(len(set(workspaces)), len(workspaces), workspaces)
    for result in results:
        test_case.assertTrue(result.solved, result.to_dict())
        test_case.assertEqual(result.patch_metrics.changed_files, (target_path,))
        test_case.assertEqual(result.patch_metrics.out_of_scope_files, ())
        test_case.assertEqual(result.patch_metrics.workspace_added_files, ())
        test_case.assertEqual(result.patch_metrics.workspace_deleted_files, ())
    preservations = [
        _preservation_scan(
            broken_source,
            result.workspace,
            target_path=target_path,
            exclude_function=exclude_function,
        )
        for result in results
    ]
    test_case.assertEqual([item["violations"] for item in preservations], [[] for _ in results])


def _assert_combined_upstream_results_preserve(
    test_case: unittest.TestCase,
    results: Any,
    expected: dict[str, dict[str, str]],
    *,
    require_unique_workspaces: bool = False,
) -> None:
    result_list = list(results)
    if require_unique_workspaces:
        workspaces = [str(result.workspace) for result in result_list]
        test_case.assertEqual(len(set(workspaces)), len(workspaces), workspaces)
    for result in result_list:
        spec = expected[result.task_id]
        target_path = spec["target_path"]
        test_case.assertTrue(result.solved, result.to_dict())
        test_case.assertEqual(result.patch_metrics.changed_files, (target_path,))
        test_case.assertEqual(result.patch_metrics.out_of_scope_files, ())
        test_case.assertEqual(result.patch_metrics.workspace_added_files, ())
        test_case.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        preservation = _preservation_scan(
            spec["broken_source"],
            result.workspace,
            target_path=target_path,
            exclude_function=spec["function"],
        )
        test_case.assertEqual(preservation["violations"], [])


def _top_level_hashes(source: str, *, exclude: set[str]) -> dict[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    hashes: dict[str, str] = {}
    for index, node in enumerate(tree.body):
        name = getattr(node, "name", "")
        if name in exclude:
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        label = f"{index}:{type(node).__name__}:{name}"
        segment = "".join(lines[start - 1 : end])
        hashes[label] = _sha256(segment)
    return hashes


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
