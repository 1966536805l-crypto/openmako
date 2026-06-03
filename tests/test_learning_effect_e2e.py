from __future__ import annotations

import contextlib
import json
import re
import shlex
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantagent.cli import main
from quantagent.learning_effect_coding_bench import run_learning_effect_coding_bench
from quantagent.skill_pipeline import (
    SkillProposal,
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    load_skill_proposal,
    propose_file_bundle_repair_skill_from_trajectory,
    propose_subject_repair_skill_from_trajectory,
    run_skill_eval_command,
    save_skill_proposal,
)
from quantagent.skills import install_skill, skill_root


FIXTURE = Path(__file__).parent / "fixtures" / "learning_effect_tasks.json"


class LearningEffectE2ETest(unittest.TestCase):
    def test_learning_effect_cli_passes_when_approved_command_improves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-pass-") as tmp:
            project = Path(tmp)
            no_learning = _write_fake_agent(project, "no_learning.py", solved=False, steps=6)
            approved = _write_fake_agent(project, "approved_learning.py", solved=True, steps=2)
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                code = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "run",
                        "--project",
                        str(project),
                        "--tasks",
                        str(FIXTURE),
                        "--no-learning-command",
                        _python_command(no_learning),
                        "--approved-learning-command",
                        _python_command(approved),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "pass")
        self.assertGreater(payload["score_delta"], 0)
        self.assertEqual(payload["solved"]["approved_learning"], 2)
        self.assertEqual(payload["solved"]["no_learning"], 0)

    def test_learning_effect_cli_fails_when_approved_command_does_not_improve(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-fail-") as tmp:
            project = Path(tmp)
            no_learning = _write_fake_agent(project, "no_learning.py", solved=False, steps=4)
            approved = _write_fake_agent(project, "approved_learning.py", solved=False, steps=4)
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                code = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "run",
                        "--project",
                        str(project),
                        "--tasks",
                        str(FIXTURE),
                        "--no-learning-command",
                        _python_command(no_learning),
                        "--approved-learning-command",
                        _python_command(approved),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "fail")
        self.assertLessEqual(payload["score_delta"], 0)
        self.assertIn("no approved-learning improvement", payload["gap"])

    def test_skill_pipeline_requires_passing_learning_effect_report_to_install_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-approve-") as tmp:
            project = Path(tmp)
            proposal = _save_proposal(project)
            pass_report = project / "learning-effect-pass.json"
            fail_report = project / "learning-effect-fail.json"
            no_learning = _write_fake_agent(project, "gate_no_learning.py", solved=False, steps=6)
            approved = _write_fake_agent(project, "gate_approved_learning.py", solved=True, steps=2)
            report_stdout = StringIO()
            with contextlib.redirect_stdout(report_stdout):
                report_code = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "learning-effect",
                        "run",
                        "--project",
                        str(project),
                        "--tasks",
                        str(FIXTURE),
                        "--no-learning-command",
                        _python_command(no_learning),
                        "--approved-learning-command",
                        _python_command(approved),
                        "--json",
                    ]
                )
            pass_payload = bind_learning_effect_report_to_proposal(json.loads(report_stdout.getvalue()), proposal)
            pass_report.write_text(json.dumps(pass_payload), encoding="utf-8")
            fail_report.write_text(
                json.dumps({"status": "fail", "score_delta": 0.0, "total": 2}) + "\n",
                encoding="utf-8",
            )
            eval_snippet = 'print("eval-ok")'
            eval_command = f"{shlex.quote(sys.executable)} -c {shlex.quote(eval_snippet)}"
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                blocked = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        str(project),
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--require-learning-effect",
                        str(fail_report),
                    ]
                )
                installed = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        str(project),
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--require-learning-effect",
                        str(pass_report),
                    ]
                )
                installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(report_code, 0)
        self.assertEqual(blocked, 2)
        self.assertEqual(installed, 0)
        self.assertTrue(installed_exists)

    def test_auto_subject_repair_proposal_from_real_agent_loop_trajectory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-real-trajectory-") as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def add_numbers(a, b):\n    return a - b\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (project / "tests" / "test_subject.py").write_text(
                "import unittest\nfrom subject import add_numbers\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_adds_values(self):\n"
                "        self.assertEqual(add_numbers(2, 3), 5)\n"
                "        self.assertEqual(add_numbers(-1, 4), 3)\n",
                encoding="utf-8",
            )
            from quantagent.agent_loop_core import run_agent_loop

            result = run_agent_loop(
                project,
                "Fix subject.py add_numbers so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                max_steps=12,
            )
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=project,
                name="auto-add-numbers-repair",
            )
            hint = _openmako_repair_hint(proposal.body)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(proposal.source, "subject_repair_trajectory")
        self.assertIn("openmako-repair", proposal.body)
        self.assertEqual(hint["target"], "subject.py")
        self.assertEqual(hint["function"], "add_numbers")
        self.assertNotIn("functions", hint)
        self.assertIn(str((project / "subject.py").resolve(strict=False)), proposal.evidence)
        self.assertIn(str((project / "tests" / "test_subject.py").resolve(strict=False)), proposal.evidence)

    def test_subject_repair_proposal_from_trajectory_rejects_multifunction_mismatch(self) -> None:
        source = (
            "def clean_token(value):\n"
            "    return str(value).strip().lower()\n\n\n"
            "def flip_items(items):\n"
            "    return list(reversed(items))\n"
        )
        cases = [
            (
                source + "\n\ndef helper_extra(value):\n    return value\n",
                "import unittest\nfrom subject import clean_token, flip_items\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_subject(self):\n"
                "        self.assertEqual(clean_token('  A  '), 'a')\n",
            ),
            (
                source,
                "import unittest\nfrom subject import clean_token\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_subject(self):\n"
                "        self.assertEqual(clean_token('  A  '), 'a')\n",
            ),
            (
                source,
                "import unittest\nfrom subject import *\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_subject(self):\n"
                "        self.assertEqual(clean_token('  A  '), 'a')\n",
            ),
        ]
        with tempfile.TemporaryDirectory(prefix="learning-effect-multifunction-reject-") as tmp:
            project = Path(tmp)
            for index, (subject_source, test_source) in enumerate(cases):
                workspace = project / f"case-{index}"
                workspace.mkdir()
                (workspace / "subject.py").write_text(subject_source, encoding="utf-8")
                (workspace / "test_subject.py").write_text(test_source, encoding="utf-8")
                trajectory = _write_successful_subject_only_trajectory(workspace)

                with self.subTest(index=index), self.assertRaisesRegex(ValueError, "functions must match"):
                    propose_subject_repair_skill_from_trajectory(
                        project,
                        trajectory,
                        workspace=workspace,
                        name=f"bad-multifunction-{index}",
                    )

    def test_two_stage_skill_pipeline_approve_then_reuse_without_preseeded_stage2_skills(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-stage2-reuse-") as tmp:
            project = Path(tmp)
            specs = _stage2_reuse_specs()
            approved_paths = []
            for spec in specs:
                stage1 = project / "stage1" / spec["function"]
                stage1.mkdir(parents=True)
                (stage1 / "subject.py").write_text(spec["source"], encoding="utf-8")
                (stage1 / "test_subject.py").write_text(spec["tests"], encoding="utf-8")
                trajectory = _write_successful_stage1_trajectory(stage1, spec)
                proposal_stdout = StringIO()
                with contextlib.redirect_stdout(proposal_stdout):
                    propose_code = _run_cli_no_chat(
                        [
                            "--no-trust-prompt",
                            "skill-pipeline",
                            "--project",
                            str(project),
                            "propose-subject-repair-from-trajectory",
                            str(trajectory),
                            "--workspace",
                            str(stage1),
                            "--name",
                            _skill_name(spec),
                            "--description",
                            f"Learned subject.py repair from stage1 {spec['label']} task.",
                            "--trigger",
                            spec["function"],
                            "--trigger",
                            spec["label"],
                            "--trigger",
                            _skill_name(spec),
                        ]
                    )
                proposal_payload = json.loads(proposal_stdout.getvalue())
                self.assertEqual(propose_code, 0, proposal_payload)
                self.assertEqual(proposal_payload["source"], "subject_repair_trajectory")
                self.assertNotIn(
                    ".quantagent/skills/",
                    "\n".join(str(value) for value in proposal_payload["evidence"]),
                )
                proposal = load_skill_proposal(project, proposal_payload["proposal_id"])
                eval_result = run_skill_eval_command(
                    project,
                    f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest test_subject -q",
                    summary=f"stage1 learned {spec['function']} repair verifies against its tests",
                    evidence=(str(stage1 / "test_subject.py"),),
                    timeout_seconds=30,
                )
                approved_paths.append(
                    approve_skill_proposal(
                        project,
                        proposal_payload["proposal_id"],
                        eval_result=_with_learning_report(eval_result, _stage1_learning_report(spec["function"]), proposal),
                    )
                )
            stage2_task_file = _write_stage2_task_file(project, specs)
            no_learning_command = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 --learning-context off "
                "{instruction}"
            )
            approved_command = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 --learning-context on "
                "{instruction}"
            )

            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=no_learning_command,
                approved_learning_agent_command=approved_command,
                task_file=stage2_task_file,
            )
            stage2_payload = json.loads(stage2_task_file.read_text(encoding="utf-8"))
            stage2_keys = [set(task["files"]) for task in stage2_payload["tasks"]]
            approved_results = report.approved_learning_run.results
            approved_exists = all(path.exists() for path in approved_paths)

        self.assertTrue(approved_exists)
        self.assertTrue(all(not any(key.startswith(".quantagent/skills/") for key in keys) for keys in stage2_keys))
        self.assertTrue(all("skill.json" not in keys for keys in stage2_keys))
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": len(specs)})
        self.assertTrue(all(result.status == "failed" for result in report.no_learning_run.results))
        self.assertTrue(all(result.status == "solved" for result in approved_results))
        self.assertTrue(all(result.patch_metrics.changed_files == ("subject.py",) for result in approved_results))
        self.assertTrue(all(result.patch_metrics.out_of_scope_files == () for result in approved_results))
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_real_hidden_stage1_agent_runs_extract_then_reuse_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-real-hidden-stage1-") as tmp:
            project = Path(tmp)
            seed_project = project / "seed_learning_project"
            specs = _stage2_reuse_specs()
            for spec in specs:
                _install_seed_subject_repair_skill(seed_project, spec)
            approved_paths = []
            from quantagent.agent_loop_core import run_agent_loop

            for spec in specs:
                stage1 = project / "stage1-real" / spec["function"]
                _write_stage1_repair_workspace(stage1, spec)
                result = run_agent_loop(
                    stage1,
                    f"Repair subject.py {spec['function']} with learned {spec['label']} contract and make the unit tests pass.",
                    explicit_mode="repair",
                    include_validation=True,
                    learning_context="on",
                    learning_project=seed_project,
                    max_steps=12,
                )
                self.assertTrue(result.ok, result.to_dict())
                proposal = propose_subject_repair_skill_from_trajectory(
                    project,
                    result.trajectory_path,
                    workspace=stage1,
                    name=_skill_name(spec),
                    description=f"Learned subject.py repair from real stage1 {spec['label']} agent run.",
                    triggers=(spec["function"], spec["label"], _skill_name(spec)),
                )
                eval_result = run_skill_eval_command(
                    project,
                    f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                    summary=f"real stage1 {spec['function']} agent repair verifies against its tests",
                    evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                    timeout_seconds=30,
                )
                approved_paths.append(
                    approve_skill_proposal(
                        project,
                        proposal.proposal_id,
                        eval_result=_with_learning_report(eval_result, _stage1_learning_report(spec["function"]), proposal),
                    )
                )
            stage2_task_file = _write_stage2_task_file(project, specs)
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = all(path.exists() for path in approved_paths)

        self.assertTrue(approved_exists)
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": len(specs)})
        self.assertTrue(all(result.status == "failed" for result in report.no_learning_run.results))
        self.assertTrue(all(result.status == "solved" for result in report.approved_learning_run.results))
        self.assertTrue(all(result.patch_metrics.changed_files == ("subject.py",) for result in report.approved_learning_run.results))
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_multi_function_subject_repair_reuses_approved_bundle_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-multi-function-bundle-") as tmp:
            project = Path(tmp)
            skill_dir = project / "bundle_skill_source" / "name-format-bundle-repair"
            skill_dir.mkdir(parents=True)
            repaired_source = (
                "def format_name(first, last):\n"
                "    return f\"{str(last).strip()}, {str(first).strip()}\"\n\n\n"
                "def initials(first, last):\n"
                "    return f\"{str(first).strip()[0].upper()}.{str(last).strip()[0].upper()}.\"\n"
            )
            hint = {
                "target": "subject.py",
                "functions": ["format_name", "initials"],
                "source": repaired_source,
            }
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: name-format-bundle-repair\n"
                "description: Repairs the paired format_name and initials subject.py functions.\n"
                "triggers: format_name, initials, name format, bundle repair\n"
                "---\n\n"
                "# name-format-bundle-repair\n\n"
                "```openmako-repair\n"
                f"{json.dumps(hint, sort_keys=True)}\n"
                "```\n",
                encoding="utf-8",
            )
            install_skill(project, skill_dir)
            task_file = project / "multi_function_stage2_tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "stage2_name_format_bundle_reuse",
                                "instruction": "Repair subject.py format_name and initials with learned name format bundle contract.",
                                "files": {
                                    "subject.py": (
                                        "def format_name(first, last):\n"
                                        "    return str(first) + ' ' + str(last)\n\n\n"
                                        "def initials(first, last):\n"
                                        "    return str(first)[0] + str(last)[0]\n"
                                    ),
                                    "test_subject.py": (
                                        "import unittest\nfrom subject import format_name, initials\n\n"
                                        "class TestSubject(unittest.TestCase):\n"
                                        "    def test_repairs_both_functions(self):\n"
                                        "        self.assertEqual(format_name(' Ada ', ' Lovelace '), 'Lovelace, Ada')\n"
                                        "        self.assertEqual(initials(' ada ', ' lovelace '), 'A.L.')\n"
                                    ),
                                },
                                "test_command": "{python} -m unittest test_subject -q",
                                "max_iterations": 1,
                                "timeout_seconds": 30,
                                "tags": ["stage2", "learning-project", "multi-function"],
                            }
                        ]
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
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

        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("subject.py",))
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_multi_function_subject_repair_trajectory_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-multi-function-trajectory-") as tmp:
            project = Path(tmp)
            seed_project = project / "seed_bundle_learning_project"
            spec = _multi_function_subject_repair_spec()
            _install_seed_subject_bundle_repair_skill(seed_project, spec)
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-multi-function"
            _write_multi_function_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair subject.py clean_token and flip_items so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="on",
                learning_project=seed_project,
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertTrue(Path(result.trajectory_path).exists())
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="multi-function-subject-repair",
                description="Learned multi-function subject.py repair from a real stage1 agent run.",
                triggers=("clean_token", "flip_items", "multi function subject repair"),
            )
            self.assertEqual(proposal.source, "subject_repair_bundle_trajectory")
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "subject.py")
            self.assertEqual(hint["functions"], sorted(spec["functions"]))
            self.assertNotIn("function", hint)
            self.assertIn(str(result.trajectory_path), proposal.evidence)
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="multi-function stage1 agent repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("multi-function-subject"), proposal),
            )
            stage2_task_file = _write_multi_function_stage2_task_file(project, spec)
            stage2_payload = json.loads(stage2_task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertFalse(any(key.startswith(".quantagent/skills/") for key in stage2_payload["tasks"][0]["files"]))
        self.assertNotIn("skill.json", stage2_payload["tasks"][0]["files"])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("subject.py",))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_no_seed_multi_function_stage1_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-no-seed-multi-function-") as tmp:
            project = Path(tmp)
            spec = _multi_function_subject_repair_spec()
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-no-seed-multi-function"
            _write_multi_function_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair subject.py clean_token and flip_items so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="no-seed-multi-function-subject-repair",
                description="Learned multi-function subject.py repair from a no-seed stage1 agent run.",
                triggers=("clean_token", "flip_items", "multi function subject repair"),
            )
            self.assertEqual(proposal.source, "subject_repair_bundle_trajectory")
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "subject.py")
            self.assertEqual(hint["functions"], sorted(spec["functions"]))
            self.assertEqual(hint["source"], spec["source"])
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="no-seed multi-function stage1 repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("no-seed-multi-function-subject"), proposal),
            )
            stage2_task_file = _write_multi_function_stage2_task_file(project, spec)
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("subject.py",))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_multi_file_repair_trajectory_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-multi-file-trajectory-") as tmp:
            project = Path(tmp)
            spec = _multi_file_repair_spec()
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-multi-file"
            _write_multi_file_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair subject.py format_label and label_helper so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            self.assertTrue(Path(result.trajectory_path).exists())
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="multi-file-format-label-repair",
                description="Learned multi-file repair from a no-seed real stage1 agent run.",
                triggers=("format_label", "label_helper", "multi file repair"),
            )
            self.assertEqual(proposal.source, "multi_file_repair_trajectory")
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "multi_file")
            self.assertEqual(hint["functions"], ["format_label"])
            self.assertEqual(sorted(hint["files"]), ["label_helper.py", "subject.py"])
            self.assertIn(str(result.trajectory_path), proposal.evidence)
            self.assertIn(str((stage1 / "label_helper.py").resolve(strict=False)), proposal.evidence)
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="multi-file stage1 agent repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("multi-file-format-label"), proposal),
            )
            stage2_task_file = _write_multi_file_stage2_task_file(project, spec)
            stage2_payload = json.loads(stage2_task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertFalse(any(key.startswith(".quantagent/skills/") for key in stage2_payload["tasks"][0]["files"]))
        self.assertIn("label_helper.py", stage2_payload["tasks"][0]["files"])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("label_helper.py", "subject.py"))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_no_seed_multi_file_stage1_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-no-seed-multi-file-") as tmp:
            project = Path(tmp)
            spec = _multi_file_repair_spec()
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-no-seed-multi-file"
            _write_multi_file_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair subject.py format_label and label_helper so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(sorted(implementation.data["files_touched"]), ["label_helper.py", "subject.py"])
            proposal = propose_subject_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="no-seed-multi-file-format-label-repair",
                description="Learned multi-file repair from a no-seed stage1 agent run.",
                triggers=("format_label", "label_helper", "multi file repair", "no seed"),
            )
            self.assertEqual(proposal.source, "multi_file_repair_trajectory")
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "multi_file")
            self.assertEqual(hint["functions"], ["format_label"])
            self.assertEqual(sorted(hint["files"]), ["label_helper.py", "subject.py"])
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="no-seed multi-file stage1 agent repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("no-seed-multi-file-format-label"), proposal),
            )
            stage2_task_file = _write_multi_file_stage2_task_file(project, spec)
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("label_helper.py", "subject.py"))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_package_module_file_bundle_repair_trajectory_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-package-file-bundle-") as tmp:
            project = Path(tmp)
            seed_project = project / "seed_package_file_bundle_learning_project"
            spec = _package_file_bundle_repair_spec()
            _install_seed_package_file_bundle_skill(seed_project, spec)
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-package-file-bundle"
            _write_package_file_bundle_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair mako_pkg/labels.py compact_label with learned package label contract so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="on",
                learning_project=seed_project,
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], ["mako_pkg/labels.py"])
            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="package-label-file-bundle-repair",
                description="Learned package-module repair from a real stage1 agent run.",
                triggers=("compact_label", "mako_pkg/labels.py", "mako_pkg.labels", "learned package label"),
            )
            self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "file_bundle")
            self.assertEqual(hint["functions"], ["compact_label"])
            self.assertEqual(sorted(hint["files"]), ["mako_pkg/labels.py"])
            self.assertIn(str(result.trajectory_path), proposal.evidence)
            self.assertIn(str((stage1 / "mako_pkg" / "labels.py").resolve(strict=False)), proposal.evidence)
            self.assertNotIn(".quantagent/skills/", "\n".join(proposal.evidence))
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="package-module stage1 agent repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_labels.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("package-file-bundle"), proposal),
            )
            stage2_task_file = _write_package_file_bundle_stage2_task_file(project, spec)
            stage2_payload = json.loads(stage2_task_file.read_text(encoding="utf-8"))
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertFalse(any(key.startswith(".quantagent/skills/") for key in stage2_payload["tasks"][0]["files"]))
        self.assertIn("mako_pkg/labels.py", stage2_payload["tasks"][0]["files"])
        self.assertIn("tests/test_labels.py", stage2_payload["tasks"][0]["files"])
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("mako_pkg/labels.py",))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)

    def test_no_seed_package_module_file_bundle_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-no-seed-package-file-bundle-") as tmp:
            project = Path(tmp)
            spec = _package_file_bundle_repair_spec()
            from quantagent.agent_loop_core import run_agent_loop

            stage1 = project / "stage1-no-seed-package-file-bundle"
            _write_package_file_bundle_stage_workspace(stage1, spec, stage_name="stage1")
            result = run_agent_loop(
                stage1,
                "Repair mako_pkg/labels.py compact_label so the unit tests pass.",
                explicit_mode="repair",
                include_validation=True,
                learning_context="off",
                max_steps=12,
            )
            self.assertTrue(result.ok, result.to_dict())
            implementation = next(item for item in result.observations if item.name == "implement")
            self.assertEqual(implementation.data["files_touched"], ["mako_pkg/labels.py"])
            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                result.trajectory_path,
                workspace=stage1,
                name="no-seed-package-label-file-bundle-repair",
                description="Learned package-module repair from a no-seed stage1 agent run.",
                triggers=("compact_label", "mako_pkg/labels.py", "no-seed package label"),
            )
            hint = _openmako_repair_hint(proposal.body)
            self.assertEqual(hint["target"], "file_bundle")
            self.assertEqual(hint["functions"], ["compact_label"])
            eval_result = run_skill_eval_command(
                project,
                f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                summary="no-seed package-module stage1 repair verifies against its tests",
                evidence=(result.trajectory_path, str(stage1 / "tests" / "test_labels.py")),
                timeout_seconds=30,
            )
            approved_path = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=_with_learning_report(eval_result, _stage1_learning_report("no-seed-package-file-bundle"), proposal),
            )
            stage2_task_file = _write_package_file_bundle_stage2_task_file(project, spec)
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = approved_path.exists()

        self.assertTrue(approved_exists)
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": 1})
        self.assertEqual(report.no_learning_run.results[0].status, "failed")
        self.assertEqual(report.approved_learning_run.results[0].status, "solved")
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.changed_files, ("mako_pkg/labels.py",))
        self.assertEqual(report.approved_learning_run.results[0].patch_metrics.out_of_scope_files, ())

    def test_skill_pipeline_cli_proposes_file_bundle_repair_from_trajectory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-cli-file-bundle-") as tmp:
            project = Path(tmp)
            spec = _package_file_bundle_repair_spec()
            stage1 = project / "stage1-cli-file-bundle"
            _write_package_file_bundle_stage_workspace(stage1, spec, stage_name="stage1")
            (stage1 / "mako_pkg" / "labels.py").write_text(spec["files"]["mako_pkg/labels.py"], encoding="utf-8")
            trajectory = _write_successful_file_bundle_trajectory(
                stage1 / "agent_loop_trajectory.jsonl",
                ("mako_pkg/labels.py",),
            )
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                code = _run_cli_no_chat(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        str(project),
                        "propose-file-bundle-repair-from-trajectory",
                        str(trajectory),
                        "--workspace",
                        str(stage1),
                        "--name",
                        "cli-package-label-file-bundle-repair",
                        "--description",
                        "Learned package-module repair from a CLI-proposed trajectory.",
                        "--trigger",
                        "compact_label",
                        "--trigger",
                        "mako_pkg/labels.py",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            hint = _openmako_repair_hint(payload["body"])

        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["source"], "file_bundle_repair_trajectory")
        self.assertEqual(payload["name"], "cli-package-label-file-bundle-repair")
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["functions"], ["compact_label"])
        self.assertEqual(sorted(hint["files"]), ["mako_pkg/labels.py"])
        self.assertIn(str((stage1 / "mako_pkg" / "labels.py").resolve(strict=False)), payload["evidence"])

    def test_file_bundle_trajectory_extracts_function_repair_from_complex_module(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-complex-file-bundle-") as tmp:
            project = Path(tmp)
            spec = _complex_package_function_repair_spec()
            stage1 = project / "stage1-complex-file-bundle"
            _write_complex_package_function_workspace(stage1, spec, repaired=True)
            trajectory = _write_successful_file_bundle_trajectory(
                stage1 / "agent_loop_trajectory.jsonl",
                ("mcp/shared/tool_name_validation.py",),
            )

            proposal = propose_file_bundle_repair_skill_from_trajectory(
                project,
                trajectory,
                workspace=stage1,
                name="complex-package-function-repair",
                description="Learned function-level repair from a complex upstream module.",
                triggers=("opaque-complex-package-contract-1",),
            )
            hint = _openmako_repair_hint(proposal.body)

        self.assertEqual(proposal.source, "file_bundle_repair_trajectory")
        self.assertEqual(hint["target"], "file_bundle")
        self.assertEqual(hint["mode"], "replace_functions")
        self.assertEqual(hint["functions"], ["validate_tool_name"])
        self.assertEqual(sorted(hint["files"]), ["mcp/shared/tool_name_validation.py"])
        snippet = hint["files"]["mcp/shared/tool_name_validation.py"]
        self.assertIn("def validate_tool_name", snippet)
        self.assertIn("ToolNameValidationResult", snippet)
        self.assertIn("TOOL_NAME_REGEX.match", snippet)
        self.assertNotIn("class ToolNamePolicy", snippet)
        self.assertNotIn("class ToolNameValidationResult", snippet)

    def test_file_bundle_trajectory_rejects_protected_touch_set(self) -> None:
        bad_touches = (
            ("tests/test_labels.py",),
            ("conftest.py",),
            ("../escape.py",),
            (".quantagent/run.py",),
            ("AI_协作交接/run.py",),
            ("mako_pkg/__init__.py",),
        )
        with tempfile.TemporaryDirectory(prefix="learning-effect-bad-file-bundle-") as tmp:
            project = Path(tmp)
            for index, files_touched in enumerate(bad_touches):
                trajectory = project / f"bad-file-bundle-{index}.jsonl"
                _write_successful_file_bundle_trajectory(trajectory, files_touched)

                with self.subTest(files_touched=files_touched), self.assertRaisesRegex(ValueError, "safe file-bundle"):
                    propose_file_bundle_repair_skill_from_trajectory(
                        project,
                        trajectory,
                        workspace=project,
                        name=f"bad-file-bundle-{index}",
                    )

    def test_from_scratch_stage1_test_inference_extracts_then_reuses_on_clean_stage2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="learning-effect-from-scratch-stage1-") as tmp:
            project = Path(tmp)
            specs = [
                {
                    "function": "combine_score",
                    "label": "combine score",
                    "arity": 2,
                    "broken": "def combine_score(a, b):\n    return a - b\n",
                    "stage1_cases": [(2, 3, 5), (-4, 9, 5)],
                    "stage2_case": (10, -3, 7),
                },
                {
                    "function": "scale_score",
                    "label": "scale score",
                    "arity": 2,
                    "broken": "def scale_score(a, b):\n    return a + b\n",
                    "stage1_cases": [(2, 3, 6), (-4, 5, -20)],
                    "stage2_case": (7, -2, -14),
                },
                {
                    "function": "delta_score",
                    "label": "delta score",
                    "arity": 2,
                    "broken": "def delta_score(a, b):\n    return a + b\n",
                    "stage1_cases": [(8, 3, 5), (-4, -9, 5)],
                    "stage2_case": (2, 10, -8),
                },
                {
                    "function": "clean_caption",
                    "label": "clean caption",
                    "arity": 1,
                    "broken": "def clean_caption(value):\n    return str(value)\n",
                    "stage1_cases": [("  Alpha  ", "alpha"), ("Beta MIX  ", "beta mix")],
                    "stage2_case": ("  MiXeD  ", "mixed"),
                },
                {
                    "function": "flip_items",
                    "label": "flip items",
                    "arity": 1,
                    "broken": "def flip_items(items):\n    return list(items)\n",
                    "stage1_cases": [(["a", "b", "c"], ["c", "b", "a"]), ([1, 2], [2, 1])],
                    "stage2_case": ([True, False], [False, True]),
                },
                {
                    "function": "order_tokens",
                    "label": "order tokens",
                    "arity": 1,
                    "broken": "def order_tokens(items):\n    return list(items)\n",
                    "stage1_cases": [(["b", "a"], ["a", "b"]), (["delta", "alpha", "charlie"], ["alpha", "charlie", "delta"])],
                    "stage2_case": (["zulu", "echo"], ["echo", "zulu"]),
                },
            ]
            approved_paths = []
            from quantagent.agent_loop_core import run_agent_loop

            for spec in specs:
                function = spec["function"]
                stage1 = project / "stage1-from-tests" / function
                (stage1 / "tests").mkdir(parents=True)
                (stage1 / "subject.py").write_text(spec["broken"], encoding="utf-8")
                (stage1 / "tests" / "__init__.py").write_text("", encoding="utf-8")
                (stage1 / "tests" / "test_subject.py").write_text(
                    _from_scratch_test_source(spec, "stage1"),
                    encoding="utf-8",
                )
                result = run_agent_loop(
                    stage1,
                    f"Repair subject.py {function} so the unit tests pass.",
                    explicit_mode="repair",
                    include_validation=True,
                    learning_context="off",
                    max_steps=12,
                )
                self.assertTrue(result.ok, result.to_dict())
                skill_name = "from-scratch-" + function.replace("_", "-") + "-repair"
                proposal = propose_subject_repair_skill_from_trajectory(
                    project,
                    result.trajectory_path,
                    workspace=stage1,
                    name=skill_name,
                    description=f"Learned {function} repair from a no-seed stage1 agent run.",
                    triggers=(function, spec["label"], skill_name),
                )
                eval_result = run_skill_eval_command(
                    project,
                    f"cd {shlex.quote(str(stage1))} && {shlex.quote(sys.executable)} -m unittest discover -s tests -q",
                    summary=f"from-scratch stage1 {function} repair verifies against its tests",
                    evidence=(result.trajectory_path, str(stage1 / "tests" / "test_subject.py")),
                    timeout_seconds=30,
                )
                approved_paths.append(
                    approve_skill_proposal(
                        project,
                        proposal.proposal_id,
                        eval_result=_with_learning_report(eval_result, _stage1_learning_report(function), proposal),
                    )
                )
            stage2_task_file = project / "stage2_from_scratch_reuse_tasks.json"
            stage2_task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": f"stage2_{spec['function']}_single_case_reuse",
                                "instruction": f"Repair subject.py {spec['function']} with learned {spec['label']} contract.",
                                "files": {
                                    "subject.py": spec["broken"],
                                    "test_subject.py": _from_scratch_test_source(spec, "stage2"),
                                },
                                "test_command": "{python} -m unittest test_subject -q",
                                "max_iterations": 1,
                                "timeout_seconds": 30,
                                "tags": ["stage2", "learning-project", "from-scratch-stage1"],
                            }
                            for spec in specs
                        ]
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            command_prefix = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
            )
            report = run_learning_effect_coding_bench(
                project,
                no_learning_agent_command=command_prefix + "--learning-context off {instruction}",
                approved_learning_agent_command=command_prefix + "--learning-context on {instruction}",
                task_file=stage2_task_file,
            )
            approved_exists = all(path.exists() for path in approved_paths)

        self.assertTrue(approved_exists)
        self.assertEqual(report.learning_effect.status, "pass")
        self.assertEqual(report.learning_effect.solved, {"no_learning": 0, "approved_learning": len(specs)})
        self.assertTrue(all(result.status == "failed" for result in report.no_learning_run.results))
        self.assertTrue(all(result.status == "solved" for result in report.approved_learning_run.results))
        self.assertTrue(all(result.patch_metrics.changed_files == ("subject.py",) for result in report.approved_learning_run.results))
        self.assertEqual(report.approved_learning_run.summary()["cheated"], 0)


def _run_cli_no_chat(argv: list[str]) -> int:
    with patch("quantagent.cli.run_chat", side_effect=AssertionError("learning-effect CLI fell through to chat")):
        try:
            return main(argv)
        except SystemExit as exc:
            return int(exc.code or 0)


def _write_fake_agent(project: Path, name: str, *, solved: bool, steps: int) -> Path:
    script = project / name
    script.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "payload = {\n"
        f"    'solved': {solved!r},\n"
        f"    'steps': {steps},\n"
        f"    'failure_class': {'' if solved else 'assertion'!r},\n"
        "    'evidence': ['pytest verification solved regression'] if "
        f"{solved!r} else ['pytest still failed'],\n"
        "}\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    return script


def _python_command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


def _save_proposal(project: Path) -> SkillProposal:
    return save_skill_proposal(
        project,
        SkillProposal(
            proposal_id="skill-learning-effect-e2e",
            name="learning-effect-e2e",
            description="Install only after a passing learning-effect report.",
            triggers=("learning-effect", "regression"),
            body="Use the verified repair only when the learning-effect gate passes.",
            evidence=("learning-effect-report.json",),
            applicability="same regression benchmark",
            failure_conditions="learning-effect report fails or has non-positive score_delta",
            evidence_strength=0.9,
            reproduction_count=2,
            risk=0.2,
            benefit=0.9,
        ),
    )


def _with_learning_report(eval_result, report: dict[str, object], proposal: SkillProposal):
    from dataclasses import replace

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
                "no_learning": {
                    "task_id": f"stage1-{task_id}",
                    "solved": False,
                    "steps": 1,
                    "failure_class": "tool_failed",
                    "evidence": ["stage1 baseline failed"],
                    "invalid_reason": "",
                },
                "approved_learning": {
                    "task_id": f"stage1-{task_id}",
                    "solved": True,
                    "steps": 1,
                    "failure_class": "",
                    "evidence": ["stage1 learned repair passed unittest"],
                    "invalid_reason": "",
                },
                "score_delta": 10.0,
            }
        ],
    }


def _from_scratch_test_source(spec: dict[str, Any], stage: str) -> str:
    cases = spec["stage1_cases"] if stage == "stage1" else [spec["stage2_case"]]
    if spec["arity"] == 2:
        return _binary_numeric_test_source(spec["function"], cases)
    return _single_literal_test_source(spec["function"], cases)


def _binary_numeric_test_source(function: str, cases: list[tuple[int, int, int]]) -> str:
    assertions = "".join(f"        self.assertEqual({function}({left}, {right}), {expected})\n" for left, right, expected in cases)
    return (
        f"import unittest\nfrom subject import {function}\n\n"
        "class TestSubject(unittest.TestCase):\n"
        "    def test_binary_numeric_cases(self):\n"
        f"{assertions}"
    )


def _single_literal_test_source(function: str, cases: list[tuple[Any, Any]]) -> str:
    assertions = "".join(f"        self.assertEqual({function}({value!r}), {expected!r})\n" for value, expected in cases)
    return (
        f"import unittest\nfrom subject import {function}\n\n"
        "class TestSubject(unittest.TestCase):\n"
        "    def test_single_literal_cases(self):\n"
        f"{assertions}"
    )


def _stage2_reuse_specs() -> list[dict[str, str]]:
    return [
        {
            "function": "juno_fold",
            "label": "juno fold",
            "source": (
                "def juno_fold(items):\n"
                "    result = []\n"
                "    for item in items:\n"
                "        if result and result[-1][0] == item:\n"
                "            value, count = result[-1]\n"
                "            result[-1] = (value, count + 1)\n"
                "        else:\n"
                "            result.append((item, 1))\n"
                "    return result\n"
            ),
            "broken": "def juno_fold(items):\n    return [(item, 1) for item in items]\n",
            "tests": (
                "import unittest\nfrom subject import juno_fold\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_keeps_adjacent_runs_and_boundaries(self):\n"
                "        self.assertEqual(juno_fold(['A', 'A', 'B', 'A']), [('A', 2), ('B', 1), ('A', 1)])\n"
                "    def test_empty(self):\n"
                "        self.assertEqual(juno_fold([]), [])\n"
                "    def test_uses_equality_not_hashing(self):\n"
                "        left = ['x']\n"
                "        right = ['x']\n"
                "        self.assertEqual(juno_fold([left, right, ['y']]), [(['x'], 2), (['y'], 1)])\n"
            ),
        },
        {
            "function": "normalize_label",
            "label": "normalize label",
            "source": (
                "import re\n\n\n"
                "def normalize_label(text):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(text).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            ),
            "broken": "def normalize_label(text):\n    return str(text)\n",
            "tests": (
                "import unittest\nfrom subject import normalize_label\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_normalizes_symbols(self):\n"
                "        self.assertEqual(normalize_label('  Alpha Beta  '), 'alpha-beta')\n"
                "        self.assertEqual(normalize_label('READY__Now!!'), 'ready-now')\n"
            ),
        },
        {
            "function": "project_fields",
            "label": "project fields",
            "source": (
                "def project_fields(row, keys):\n"
                "    return {key: row[key] for key in keys if key in row}\n"
            ),
            "broken": "def project_fields(row, keys):\n    return {}\n",
            "tests": (
                "import unittest\nfrom subject import project_fields\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_projects_known_keys_in_requested_order(self):\n"
                "        row = {'id': 7, 'name': 'Ada', 'extra': True}\n"
                "        self.assertEqual(project_fields(row, ['name', 'missing', 'id']), {'name': 'Ada', 'id': 7})\n"
            ),
        },
    ]


def _skill_name(spec: dict[str, str]) -> str:
    return "hidden-" + spec["function"].replace("_", "-") + "-repair"


def _install_seed_subject_repair_skill(project: Path, spec: dict[str, str]) -> None:
    skill_name = _skill_name(spec)
    hint = {"target": "subject.py", "function": spec["function"], "source": spec["source"]}
    skill_dir = project / "seed_skill_source" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        f"description: Seed repair skill for real stage1 {spec['label']} agent run.\n"
        f"triggers: {spec['function']}, {spec['label']}, {skill_name}\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )
    install_skill(project, skill_dir)


def _openmako_repair_hint(body: str) -> dict[str, Any]:
    match = re.search(r"```openmako-repair\s*\n(.*?)```", body, re.IGNORECASE | re.DOTALL)
    if match is None:
        raise AssertionError("proposal body has no openmako-repair block")
    payload = json.loads(match.group(1).strip())
    if not isinstance(payload, dict):
        raise AssertionError("openmako-repair block must contain an object")
    return payload


def _multi_function_subject_repair_spec() -> dict[str, Any]:
    return {
        "functions": ["clean_token", "flip_items"],
        "source": (
            "def clean_token(value):\n"
            "    return str(value).strip().lower()\n\n\n"
            "def flip_items(items):\n"
            "    return list(reversed(items))\n"
        ),
        "broken": (
            "def clean_token(value):\n"
            "    return str(value)\n\n\n"
            "def flip_items(items):\n"
            "    return list(items)\n"
        ),
        "stage1_tests": (
            "import unittest\nfrom subject import clean_token, flip_items\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_repairs_clean_token(self):\n"
            "        self.assertEqual(clean_token('  Alpha  '), 'alpha')\n"
            "        self.assertEqual(clean_token('Beta MIX  '), 'beta mix')\n"
            "    def test_repairs_flip_items(self):\n"
            "        self.assertEqual(flip_items(['a', 'b', 'c']), ['c', 'b', 'a'])\n"
            "        self.assertEqual(flip_items([1, 2]), [2, 1])\n"
        ),
        "stage2_tests": (
            "import unittest\nfrom subject import clean_token, flip_items\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_reuses_clean_token_contract(self):\n"
            "        self.assertEqual(clean_token('  MiXeD  '), 'mixed')\n"
            "    def test_reuses_flip_items_contract(self):\n"
            "        self.assertEqual(flip_items([True, False]), [False, True])\n"
        ),
    }


def _install_seed_subject_bundle_repair_skill(project: Path, spec: dict[str, Any]) -> None:
    skill_name = "seed-multi-function-subject-repair"
    hint = {"target": "subject.py", "functions": sorted(spec["functions"]), "source": spec["source"]}
    skill_dir = project / "seed_bundle_skill_source" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        "description: Seed repair skill for a real multi-function stage1 agent run.\n"
        "triggers: clean_token, flip_items, multi function subject repair\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )
    install_skill(project, skill_dir)


def _write_multi_function_stage_workspace(stage: Path, spec: dict[str, Any], *, stage_name: str) -> None:
    tests = spec["stage1_tests"] if stage_name == "stage1" else spec["stage2_tests"]
    (stage / "tests").mkdir(parents=True)
    (stage / "subject.py").write_text(spec["broken"], encoding="utf-8")
    (stage / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "tests" / "test_subject.py").write_text(tests, encoding="utf-8")


def _write_multi_function_stage2_task_file(project: Path, spec: dict[str, Any]) -> Path:
    task_file = project / "multi_function_stage2_tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "stage2_multi_function_subject_reuse",
                        "instruction": "Repair subject.py clean_token and flip_items with learned multi function contract.",
                        "files": {
                            "subject.py": spec["broken"],
                            "test_subject.py": spec["stage2_tests"],
                        },
                        "test_command": "{python} -m unittest test_subject -q",
                        "max_iterations": 1,
                        "timeout_seconds": 30,
                        "tags": ["stage2", "learning-project", "multi-function", "trajectory-extracted"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return task_file


def _multi_file_repair_spec() -> dict[str, Any]:
    return {
        "files": {
            "subject.py": (
                "from label_helper import normalize_piece\n\n\n"
                "def format_label(text):\n"
                "    return normalize_piece(text)\n"
            ),
            "label_helper.py": (
                "import re\n\n\n"
                "def normalize_piece(value):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            ),
        },
        "broken_files": {
            "subject.py": (
                "from label_helper import normalize_piece\n\n\n"
                "def format_label(text):\n"
                "    return str(text)\n"
            ),
            "label_helper.py": (
                "def normalize_piece(value):\n"
                "    return str(value)\n"
            ),
        },
        "stage1_tests": (
            "import unittest\nfrom subject import format_label\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_repairs_words(self):\n"
            "        self.assertEqual(format_label('  Alpha Beta!!  '), 'alpha-beta')\n"
            "    def test_repairs_symbols(self):\n"
            "        self.assertEqual(format_label('READY__Now'), 'ready-now')\n"
        ),
        "stage2_tests": (
            "import unittest\nfrom subject import format_label\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_reuses_helper_contract(self):\n"
            "        self.assertEqual(format_label('  New MIX!!  '), 'new-mix')\n"
        ),
    }


def _install_seed_multifile_repair_skill(project: Path, spec: dict[str, Any]) -> None:
    from quantagent.skills import install_skill

    skill_name = "seed-multi-file-format-label-repair"
    hint = {"target": "multi_file", "functions": ["format_label"], "files": spec["files"]}
    skill_dir = project / "seed_multifile_skill_source" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        "description: Seed multi-file repair skill for a real stage1 agent run.\n"
        "triggers: format_label, label_helper, multi file repair\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )
    install_skill(project, skill_dir)


def _write_multi_file_stage_workspace(stage: Path, spec: dict[str, Any], *, stage_name: str) -> None:
    tests = spec["stage1_tests"] if stage_name == "stage1" else spec["stage2_tests"]
    (stage / "tests").mkdir(parents=True)
    for path, source in spec["broken_files"].items():
        (stage / path).write_text(source, encoding="utf-8")
    (stage / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "tests" / "test_subject.py").write_text(tests, encoding="utf-8")


def _write_multi_file_stage2_task_file(project: Path, spec: dict[str, Any]) -> Path:
    task_file = project / "multi_file_stage2_tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "stage2_multi_file_reuse",
                        "instruction": "Repair subject.py format_label and label_helper with learned multi file repair contract.",
                        "files": {
                            "subject.py": spec["broken_files"]["subject.py"],
                            "label_helper.py": spec["broken_files"]["label_helper.py"],
                            "test_subject.py": spec["stage2_tests"],
                        },
                        "test_command": "{python} -m unittest test_subject -q",
                        "max_iterations": 1,
                        "timeout_seconds": 30,
                        "tags": ["stage2", "learning-project", "multi-file", "trajectory-extracted"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return task_file


def _package_file_bundle_repair_spec() -> dict[str, Any]:
    return {
        "files": {
            "mako_pkg/labels.py": (
                "import re\n\n\n"
                "def compact_label(value):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            ),
        },
        "broken_files": {
            "mako_pkg/__init__.py": "",
            "mako_pkg/labels.py": (
                "def compact_label(value):\n"
                "    return str(value)\n"
            ),
        },
        "stage1_tests": (
            "import unittest\nfrom mako_pkg.labels import compact_label\n\n"
            "class TestLabels(unittest.TestCase):\n"
            "    def test_repairs_words(self):\n"
            "        self.assertEqual(compact_label('  Alpha Beta!!  '), 'alpha-beta')\n"
            "    def test_repairs_symbols(self):\n"
            "        self.assertEqual(compact_label('READY__Now'), 'ready-now')\n"
        ),
        "stage2_tests": (
            "import unittest\nfrom mako_pkg.labels import compact_label\n\n"
            "class TestLabels(unittest.TestCase):\n"
            "    def test_reuses_package_contract(self):\n"
            "        self.assertEqual(compact_label('  New MIX!!  '), 'new-mix')\n"
        ),
    }


def _install_seed_package_file_bundle_skill(project: Path, spec: dict[str, Any]) -> None:
    from quantagent.skills import install_skill

    skill_name = "seed-package-label-file-bundle-repair"
    hint = {"target": "file_bundle", "functions": ["compact_label"], "files": spec["files"]}
    skill_dir = project / "seed_package_file_bundle_skill_source" / skill_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        "description: Seed package-module file-bundle repair skill for a real stage1 agent run.\n"
        "triggers: compact_label, mako_pkg/labels.py, mako_pkg.labels, learned package label\n"
        "---\n\n"
        f"# {skill_name}\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```\n",
        encoding="utf-8",
    )
    install_skill(project, skill_dir)


def _write_package_file_bundle_stage_workspace(stage: Path, spec: dict[str, Any], *, stage_name: str) -> None:
    tests = spec["stage1_tests"] if stage_name == "stage1" else spec["stage2_tests"]
    for path, source in spec["broken_files"].items():
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    (stage / "tests").mkdir(parents=True)
    (stage / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "tests" / "test_labels.py").write_text(tests, encoding="utf-8")


def _write_package_file_bundle_stage2_task_file(project: Path, spec: dict[str, Any]) -> Path:
    task_file = project / "package_file_bundle_stage2_tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "stage2_package_file_bundle_reuse",
                        "instruction": "Repair mako_pkg/labels.py compact_label with learned package label contract.",
                        "files": {
                            "mako_pkg/__init__.py": spec["broken_files"]["mako_pkg/__init__.py"],
                            "mako_pkg/labels.py": spec["broken_files"]["mako_pkg/labels.py"],
                            "tests/__init__.py": "",
                            "tests/test_labels.py": spec["stage2_tests"],
                        },
                        "test_command": "{python} -m unittest discover -s tests -q",
                        "max_iterations": 1,
                        "timeout_seconds": 30,
                        "tags": ["stage2", "learning-project", "package-module", "file-bundle"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return task_file


def _complex_package_function_repair_spec() -> dict[str, Any]:
    repaired_function = (
        "def validate_tool_name(name):\n"
        "    warnings = []\n"
        "    if not name:\n"
        "        return ToolNameValidationResult(is_valid=False, warnings=[\"Tool name cannot be empty\"])\n"
        "    if not TOOL_NAME_REGEX.match(name):\n"
        "        warnings.append(\"Tool name contains invalid characters\")\n"
        "        return ToolNameValidationResult(is_valid=False, warnings=warnings)\n"
        "    return ToolNameValidationResult(is_valid=True, warnings=warnings)\n"
    )
    module_prefix = (
        "import re\n\n"
        "from dataclasses import dataclass, field\n\n\n"
        "TOOL_NAME_REGEX = re.compile(r\"^[A-Za-z0-9._-]{1,128}$\")\n\n\n"
        "@dataclass\n"
        "class ToolNameValidationResult:\n"
        "    is_valid: bool\n"
        "    warnings: list[str] = field(default_factory=list)\n\n\n"
    )
    module_suffix = (
        "\n\n"
        "class ToolNamePolicy:\n"
        "    def __init__(self, regex=TOOL_NAME_REGEX):\n"
        "        self.regex = regex\n"
    )
    return {
        "path": "mcp/shared/tool_name_validation.py",
        "broken_module": module_prefix + "def validate_tool_name(name):\n    return ToolNameValidationResult(is_valid=True, warnings=[])\n" + module_suffix,
        "repaired_module": module_prefix + repaired_function + module_suffix,
        "tests": (
            "import unittest\n"
            "from mcp.shared.tool_name_validation import validate_tool_name\n\n"
            "class TestToolNameValidation(unittest.TestCase):\n"
            "    def test_accepts_safe_names(self):\n"
            "        self.assertTrue(validate_tool_name('alpha_1').is_valid)\n"
            "    def test_rejects_bad_names(self):\n"
            "        self.assertFalse(validate_tool_name('bad name').is_valid)\n"
            "        self.assertFalse(validate_tool_name('').is_valid)\n"
        ),
    }


def _write_complex_package_function_workspace(stage: Path, spec: dict[str, Any], *, repaired: bool) -> None:
    target = stage / spec["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    (stage / "mcp" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "mcp" / "shared" / "__init__.py").write_text("", encoding="utf-8")
    target.write_text(spec["repaired_module"] if repaired else spec["broken_module"], encoding="utf-8")
    (stage / "tests").mkdir(parents=True, exist_ok=True)
    (stage / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stage / "tests" / "test_tool_name_validation.py").write_text(spec["tests"], encoding="utf-8")


def _write_stage1_repair_workspace(stage1: Path, spec: dict[str, str]) -> None:
    (stage1 / "tests").mkdir(parents=True)
    (stage1 / "subject.py").write_text(spec["broken"], encoding="utf-8")
    (stage1 / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stage1 / "tests" / "test_subject.py").write_text(spec["tests"], encoding="utf-8")


def _write_successful_stage1_trajectory(stage1: Path, spec: dict[str, str]) -> Path:
    trajectory = stage1 / "AI_协作交接" / "agent_loop_trajectory.jsonl"
    trajectory.parent.mkdir(parents=True)
    entry = {
        "task": f"Repair subject.py {spec['function']} with learned {spec['label']} contract.",
        "ok": True,
        "status": "done",
        "failure_class": "",
        "observations": [
            {
                "name": "implement",
                "ok": True,
                "summary": "implemented subject.py repair",
                "data": {"files_touched": ["subject.py"]},
            },
            {
                "name": "unit_tests",
                "ok": True,
                "summary": "stage1 unit tests passed",
                "data": {"command": f"{sys.executable} -m unittest test_subject -q"},
            },
        ],
    }
    trajectory.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    return trajectory


def _write_successful_subject_only_trajectory(workspace: Path) -> Path:
    trajectory = workspace / "AI_协作交接" / "agent_loop_trajectory.jsonl"
    trajectory.parent.mkdir(parents=True)
    entry = {
        "task": "Repair subject.py so the unit tests pass.",
        "ok": True,
        "status": "done",
        "failure_class": "",
        "observations": [
            {
                "name": "implement",
                "ok": True,
                "summary": "implemented subject.py repair",
                "data": {"files_touched": ["subject.py"]},
            },
            {
                "name": "unit_tests",
                "ok": True,
                "summary": "unit tests passed",
                "data": {"command": f"{sys.executable} -m unittest test_subject -q"},
            },
        ],
    }
    trajectory.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    return trajectory


def _write_successful_file_bundle_trajectory(trajectory: Path, files_touched: tuple[str, ...]) -> Path:
    entry = {
        "task": "Repair package file bundle so the unit tests pass.",
        "ok": True,
        "status": "done",
        "failure_class": "",
        "observations": [
            {
                "name": "implement",
                "ok": True,
                "summary": "implemented file-bundle repair",
                "data": {"files_touched": list(files_touched)},
            },
            {
                "name": "unit_tests",
                "ok": True,
                "summary": "unit tests passed",
                "data": {"command": f"{sys.executable} -m unittest discover -s tests -q"},
            },
        ],
    }
    trajectory.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    return trajectory


def _write_stage2_task_file(project: Path, specs: list[dict[str, str]]) -> Path:
    task_file = project / "stage2_tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": f"stage2_{spec['function']}_reuse",
                        "instruction": f"Repair subject.py {spec['function']} with learned {spec['label']} contract.",
                        "files": {
                            "subject.py": spec["broken"],
                            "test_subject.py": spec["tests"],
                        },
                        "test_command": "{python} -m unittest test_subject -q",
                        "max_iterations": 1,
                        "timeout_seconds": 30,
                        "tags": ["stage2", "learning-project", "no-preseed"],
                    }
                    for spec in specs
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return task_file


if __name__ == "__main__":
    unittest.main()
