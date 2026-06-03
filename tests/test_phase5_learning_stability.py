from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from quantagent.chat_ui import ChatSession
from quantagent.cli import main
from quantagent.desktop_soak import run_desktop_soak
from quantagent.retry_utils import RetryFuse
from quantagent.runtime_store import ensure_runtime_store, list_model_calls, record_model_call, reserve_model_budget
from quantagent.skill_pipeline import (
    SkillEvalResult,
    SkillProposal,
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    curate_skill_proposals,
    list_skill_proposals,
    propose_skill_from_trajectory,
    reject_skill_proposal,
    rollback_skill_proposal_install,
    run_skill_eval_command,
    save_skill_proposal,
)
from quantagent.skills import skill_root
from quantagent.tool_loop import run_tool_loop
from quantagent.trajectory import record_action, record_observation, record_test
from quantagent.trajectory_compact import compact_trajectory


class Phase5LearningStabilityTest(unittest.TestCase):
    def test_failed_trajectory_becomes_evidenced_proposal_not_installed_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 proposal ") as tmp:
            project = Path(tmp).resolve(strict=False)
            trajectory = project / "failed.jsonl"
            record_action(trajectory, "run focused regression", step=1, ok=True)
            record_observation(trajectory, "failure: import moved across files", step=2, ok=False)
            record_test(trajectory, "rerun regression after diagnosis", step=3, ok=True)

            proposal = propose_skill_from_trajectory(project, trajectory, name="import-repair", triggers=("import", "regression"))

            self.assertEqual(proposal.status, "proposed")
            self.assertTrue(proposal.evidence)
            self.assertTrue(proposal.applicability)
            self.assertTrue(proposal.failure_conditions)
            self.assertGreater(proposal.evidence_strength, 0)
            self.assertFalse((skill_root(project) / proposal.name / "SKILL.md").exists())

    def test_curator_ranking_uses_evidence_reproduction_risk_and_benefit(self) -> None:
        weak = SkillProposal(
            proposal_id="skill-weak",
            name="weak",
            description="thin proposal",
            triggers=("thin",),
            body="one observation",
            evidence=("one.jsonl",),
            evidence_strength=0.2,
            reproduction_count=1,
            risk=0.8,
            benefit=0.2,
        )
        strong = SkillProposal(
            proposal_id="skill-strong",
            name="strong",
            description="repeated repair proposal",
            triggers=("repair",),
            body="verified repair with repeated evidence",
            evidence=("one.jsonl", "two.jsonl", "three.jsonl"),
            evidence_strength=0.9,
            reproduction_count=3,
            risk=0.1,
            benefit=0.9,
        )

        ranked = curate_skill_proposals((weak, strong))

        self.assertEqual(ranked[0].proposal.proposal_id, "skill-strong")
        self.assertGreater(ranked[0].score, ranked[1].score)
        self.assertEqual(ranked[0].reproduction_score, 1.0)

    def test_eval_gate_blocks_install_until_targeted_eval_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 eval gate ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "eval-gated-repair")

            with self.assertRaises(PermissionError):
                approve_skill_proposal(project, proposal.proposal_id)
            with self.assertRaises(PermissionError):
                approve_skill_proposal(project, proposal.proposal_id, eval_result={"passed": True})
            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=SkillEvalResult(
                        True,
                        command="python -c 'print(\"fake\")'",
                        summary="claimed pass without executed provenance",
                        evidence=("claimed only",),
                        returncode=0,
                    ),
                )
            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=SkillEvalResult(
                        False,
                        command="python -c 'raise SystemExit(1)'",
                        summary="failed",
                        returncode=1,
                    ),
                )
            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project),
                )

            installed = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._learning_effect_report()),
            )
            saved = list_skill_proposals(project)[0]

            self.assertTrue(installed.exists())
            self.assertEqual(saved.status, "approved")
            self.assertEqual(saved.eval_status, "passed")
            self.assertIn("pytest passed", saved.eval_evidence)

    def test_bad_experience_rejection_blocks_install_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 reject ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "bad-learning")

            rejected = reject_skill_proposal(project, proposal.proposal_id, reason="contradicted by later eval")

            self.assertEqual(rejected.status, "rejected")
            self.assertEqual(rejected.rejection_reason, "contradicted by later eval")
            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, self._learning_effect_report()),
                )
            self.assertFalse((skill_root(project) / proposal.name / "SKILL.md").exists())

    def test_skill_install_can_be_rolled_back_to_proposal_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 rollback ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "rollback-learning")
            installed = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._learning_effect_report()),
            )

            rolled_back = rollback_skill_proposal_install(project, proposal.proposal_id, reason="bad downstream result")

            self.assertFalse(installed.exists())
            self.assertEqual(rolled_back.status, "rolled_back")
            self.assertEqual(rolled_back.rollback_reason, "bad downstream result")

    def test_skill_pipeline_cli_curate_outputs_ranked_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli curate ") as tmp:
            project = Path(tmp)
            weak = self._proposal(project, "weak-learning")
            strong = SkillProposal(
                proposal_id="skill-strong-learning",
                name="strong-learning",
                description="Repeated repair proposal.",
                triggers=("strong",),
                body="Verified repair.",
                evidence=("one.jsonl", "two.jsonl", "three.jsonl"),
                applicability=("same failure",),
                failure_conditions=("eval fails",),
                evidence_strength=0.95,
                reproduction_count=3,
                risk=0.1,
                benefit=0.9,
            )
            save_skill_proposal(project, strong)
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "skill-pipeline", "--project", tmp, "curate", "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload[0]["proposal"]["proposal_id"], strong.proposal_id)
        self.assertEqual(payload[-1]["proposal"]["proposal_id"], weak.proposal_id)

    def test_skill_pipeline_cli_approve_requires_and_accepts_eval_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli approve ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-eval-gated")
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "print(\\"eval-ok\\")"'
            report = self._write_learning_effect_report(project)

            with contextlib.redirect_stdout(stdout):
                blocked = main(["--no-trust-prompt", "skill-pipeline", "--project", tmp, "approve", proposal.proposal_id])
                fake_evidence_blocked = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-summary",
                        "phase5 cli eval passed",
                        "--eval-evidence",
                        "pytest passed",
                    ]
                )
                eval_only_blocked = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--eval-summary",
                        "phase5 cli eval passed",
                        "--eval-evidence",
                        "pytest passed",
                    ]
                )
                installed_code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--eval-summary",
                        "phase5 cli eval passed",
                        "--eval-evidence",
                        "pytest passed",
                        "--learning-effect-report",
                        str(report),
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(blocked, 2)
        self.assertEqual(fake_evidence_blocked, 2)
        self.assertEqual(eval_only_blocked, 2)
        self.assertEqual(installed_code, 0)
        self.assertEqual(saved.status, "approved")
        self.assertIn('"returncode": 0', saved.eval_evidence)
        self.assertIn("eval-ok", saved.eval_evidence)
        self.assertTrue(installed_exists)

    def test_skill_pipeline_cli_approve_blocks_failed_eval_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli approve failed ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-eval-failed")
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "import sys; print(\\"eval-fail\\"); sys.exit(7)"'

            with contextlib.redirect_stdout(stdout):
                blocked = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(blocked, 2)
        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_skill_pipeline_cli_approve_learning_effect_report_approves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli learning pass ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-learning-pass")
            report = self._write_learning_effect_report(project, score_delta=10.5)
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "print(\\"eval-ok\\")"'

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--learning-effect-report",
                        str(report),
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(code, 0)
        self.assertEqual(saved.status, "approved")
        eval_evidence = json.loads(saved.eval_evidence)
        learning_evidence = json.loads(eval_evidence["evidence"][0])
        self.assertEqual(learning_evidence["learning_effect"]["score_delta"], 10.5)
        self.assertTrue(installed_exists)

    def test_skill_pipeline_cli_approve_learning_effect_fail_report_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli learning fail ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-learning-fail")
            report = project / "learning-effect.json"
            report.write_text(
                json.dumps({"status": "fail", "total": 1, "score_delta": 3.0}),
                encoding="utf-8",
            )
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "print(\\"eval-ok\\")"'

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--require-learning-effect",
                        "--learning-effect-report",
                        str(report),
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(code, 2)
        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_skill_pipeline_cli_approve_learning_effect_report_requires_comparisons(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli learning weak ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-learning-weak")
            report = project / "learning-effect.json"
            report.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "total": 1,
                        "solved": {"no_learning": 0, "approved_learning": 1},
                        "score_delta": 10.5,
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "print(\\"eval-ok\\")"'

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--learning-effect-report",
                        str(report),
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(code, 2)
        self.assertIn("per-task comparisons", stdout.getvalue())
        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_skill_pipeline_cli_approve_learning_effect_requires_report_or_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli learning missing ") as tmp:
            project = Path(tmp).resolve(strict=False)
            proposal = self._proposal(project, "cli-learning-missing")
            stdout = StringIO()
            eval_command = f'"{sys.executable}" -c "print(\\"eval-ok\\")"'

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        proposal.proposal_id,
                        "--eval-command",
                        eval_command,
                        "--require-learning-effect",
                    ]
                )
            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(code, 2)
        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_skill_pipeline_cli_reject_and_rollback_are_operable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 cli lifecycle ") as tmp:
            project = Path(tmp)
            rejected = self._proposal(project, "cli-rejected")
            rollback = self._proposal(project, "cli-rollback")
            rejected_report = self._write_learning_effect_report(project, proposal=rejected)
            rollback_report = self._write_learning_effect_report(project, proposal=rollback, name="learning-effect-rollback.json")
            stdout = StringIO()

            with contextlib.redirect_stdout(stdout):
                reject_code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "reject",
                        rejected.proposal_id,
                        "--reason",
                        "contradicted by later eval",
                    ]
                )
                rejected_approve_code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        rejected.proposal_id,
                        "--eval-command",
                        f'"{sys.executable}" -c "print(\\"ok\\")"',
                        "--eval-summary",
                        "passed",
                        "--eval-evidence",
                        "passed",
                        "--learning-effect-report",
                        str(rejected_report),
                    ]
                )
                approve_code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "approve",
                        rollback.proposal_id,
                        "--eval-command",
                        f'"{sys.executable}" -c "print(\\"ok\\")"',
                        "--eval-summary",
                        "passed",
                        "--eval-evidence",
                        "passed",
                        "--learning-effect-report",
                        str(rollback_report),
                    ]
                )
                rollback_code = main(
                    [
                        "--no-trust-prompt",
                        "skill-pipeline",
                        "--project",
                        tmp,
                        "rollback",
                        rollback.proposal_id,
                        "--reason",
                        "bad downstream result",
                    ]
                )
            proposals = {item.proposal_id: item for item in list_skill_proposals(project)}

        self.assertEqual(reject_code, 0)
        self.assertEqual(rejected_approve_code, 2)
        self.assertEqual(approve_code, 0)
        self.assertEqual(rollback_code, 0)
        self.assertEqual(proposals[rejected.proposal_id].status, "rejected")
        self.assertEqual(proposals[rollback.proposal_id].status, "rolled_back")
        self.assertFalse((skill_root(project) / rollback.name / "SKILL.md").exists())

    def test_session_token_cost_budget_blocks_second_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 budget ") as tmp:
            project = Path(tmp)
            with patch.dict(os.environ, {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"}, clear=False):
                first = reserve_model_budget(project, session_id="sess-budget", model="gpt-test", estimated_tokens=1)
                second = reserve_model_budget(project, session_id="sess-budget", model="gpt-test", estimated_tokens=1)

            self.assertEqual(first["status"], "reserved")
            self.assertEqual(second["status"], "blocked")
            self.assertEqual(second["reason"], "budget_reservation_exceeded")

    def test_long_context_compaction_preserves_boundaries_and_saves_tokens(self) -> None:
        messages = [{"role": "system", "content": "rules"}]
        messages.extend({"role": "tool", "content": f"middle {index} " * 120} for index in range(12))
        messages.append({"role": "assistant", "content": "final answer"})

        result = compact_trajectory(messages, first_n=1, last_n=1, target_summary_chars=240)

        self.assertEqual(result.messages[0]["content"], "rules")
        self.assertEqual(result.messages[-1]["content"], "final answer")
        self.assertIsNotNone(result.summary_entry)
        self.assertGreater(result.metrics.saved_estimated_tokens, 0)

    def test_watchdog_kill_records_timeout_attribution(self) -> None:
        def run_eval(_project, **_kwargs):
            time.sleep(5)
            return {"ok": True, "status": "success", "summary": "too late", "run_id": "hung"}

        with tempfile.TemporaryDirectory(prefix="phase5 watchdog ") as tmp:
            started = time.monotonic()
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                run_eval=run_eval,
                watchdog=True,
                cycle_timeout_seconds=0.15,
                watchdog_interval_seconds=0.02,
            )
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.metrics["watchdog_kills"], 1)
        self.assertEqual(result.cycles[0].watchdog_status, "timeout")
        self.assertIn("timed out", result.cycles[0].watchdog_summary)

    def test_retry_fuse_blocks_unbounded_retries(self) -> None:
        fuse = RetryFuse(max_attempts=2)

        first = fuse.before_retry("provider:429")
        second = fuse.before_retry("provider:429")
        third = fuse.before_retry("provider:429")
        fuse.reset("provider:429")
        after_reset = fuse.before_retry("provider:429")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertEqual(third.reason, "retry fuse exhausted")
        self.assertTrue(after_reset.allowed)
        self.assertEqual(after_reset.attempts, 1)

    def test_runtime_store_handles_light_concurrent_write_stress(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5 store stress ") as tmp:
            project = Path(tmp)
            ensure_runtime_store(project)

            def write(index: int) -> int:
                return record_model_call(
                    project,
                    session_id="stress",
                    query_id=f"q-{index}",
                    model="gpt-test",
                    provider="fake",
                    ok=True,
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(write, range(24)))
            calls = list_model_calls(project, session_id="stress", limit=50)

        self.assertEqual(len(ids), 24)
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(len(calls), 24)

    def test_chat_session_budget_blocks_second_model_call_before_network(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}'

        network_calls: list[int] = []

        def fake_urlopen(*_args, **_kwargs):
            network_calls.append(1)
            return FakeResponse()

        with tempfile.TemporaryDirectory(prefix="phase5 chat budget ") as tmp:
            project = Path(tmp)
            with patch.dict(
                os.environ,
                {"QUANTAGENT_OPENAI_API_KEY": "test-key", "QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"},
                clear=False,
            ):
                session = ChatSession(project=project, model="gpt-test", base_url="https://example.test/v1")
                with patch("urllib.request.urlopen", fake_urlopen):
                    with contextlib.redirect_stdout(StringIO()):
                        first = session.ask("first")
                        second = session.ask("second")
            calls = list_model_calls(project, session_id=session.session_id, limit=10)

        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(len(network_calls), 1)
        self.assertIn("token budget guard blocked", second.text)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(item.session_id == session.session_id for item in calls))
        self.assertEqual(sum(1 for item in calls if item.ok), 1)
        self.assertEqual(sum(1 for item in calls if not item.ok), 1)

    def test_tool_loop_budget_reuses_session_across_model_steps(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                content = json.dumps({"tool_calls": [{"tool": "status", "args": {}}]})
                return json.dumps(
                    {
                        "choices": [{"message": {"content": content}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                ).encode("utf-8")

        network_calls: list[int] = []

        def fake_urlopen(*_args, **_kwargs):
            network_calls.append(1)
            return FakeResponse()

        with tempfile.TemporaryDirectory(prefix="phase5 tool budget ") as tmp:
            project = Path(tmp)
            with patch.dict(
                os.environ,
                {"QUANTAGENT_OPENAI_API_KEY": "test-key", "QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"},
                clear=False,
            ):
                with patch("urllib.request.urlopen", fake_urlopen):
                    result = run_tool_loop(
                        project,
                        "inspect with model",
                        model="gpt-test",
                        base_url="https://example.test/v1",
                        max_steps=2,
                        session_id="tool-session",
                    )
            calls = list_model_calls(project, session_id="tool-session", limit=10)

        self.assertFalse(result.ok)
        self.assertEqual(len(network_calls), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sum(1 for item in calls if item.ok), 1)
        self.assertEqual(sum(1 for item in calls if not item.ok), 1)

    def _proposal(self, project: Path, name: str) -> SkillProposal:
        proposal = SkillProposal(
            proposal_id=f"skill-{name}",
            name=name,
            description="Learned repair with targeted eval.",
            triggers=(name, "phase5"),
            body="Reproduce the failure, apply the smallest repair, and rerun the targeted eval.",
            evidence=("failure-trajectory.jsonl",),
            applicability=("same failing test signal",),
            failure_conditions=("targeted eval fails",),
            evidence_strength=0.7,
            reproduction_count=1,
            risk=0.2,
            benefit=0.8,
        )
        return save_skill_proposal(project, proposal)

    def _eval_result(self, project: Path, report: dict[str, object] | None = None) -> SkillEvalResult:
        result = run_skill_eval_command(
            project,
            f'"{sys.executable}" -c "print(\\"eval-ok\\")"',
            summary="phase5 eval gate passed",
            evidence=("pytest passed",),
            timeout_seconds=10,
        )
        if report is not None:
            proposals = list_skill_proposals(project)
            if proposals:
                report = bind_learning_effect_report_to_proposal(report, proposals[0])
        return replace(
            result,
            require_learning_effect=report is not None,
            learning_effect_report=report,
        )

    def _learning_effect_report(self, *, score_delta: float = 10.5) -> dict[str, object]:
        return {
            "status": "pass",
            "total": 1,
            "solved": {"no_learning": 0, "approved_learning": 1},
            "score_delta": score_delta,
            "comparisons": [
                {
                    "task_id": "repair-one",
                    "no_learning": {
                        "task_id": "repair-one",
                        "solved": False,
                        "steps": 4,
                        "failure_class": "assertion",
                        "evidence": ["pytest failed before learning"],
                        "invalid_reason": "",
                    },
                    "approved_learning": {
                        "task_id": "repair-one",
                        "solved": True,
                        "steps": 2,
                        "failure_class": "",
                        "evidence": ["pytest passed after approved learning"],
                        "invalid_reason": "",
                    },
                    "score_delta": score_delta,
                }
            ],
        }

    def _write_learning_effect_report(
        self,
        project: Path,
        *,
        score_delta: float = 10.5,
        proposal: SkillProposal | None = None,
        name: str = "learning-effect.json",
    ) -> Path:
        report = project / name
        payload = self._learning_effect_report(score_delta=score_delta)
        if proposal is None:
            proposals = list_skill_proposals(project)
            proposal = proposals[0] if proposals else None
        if proposal is not None:
            payload = bind_learning_effect_report_to_proposal(payload, proposal)
        report.write_text(json.dumps(payload), encoding="utf-8")
        return report


if __name__ == "__main__":
    unittest.main()
