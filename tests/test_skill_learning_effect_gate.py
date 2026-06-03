from __future__ import annotations

from dataclasses import replace
import json
import sys
import tempfile
import unittest
from pathlib import Path

from quantagent.skill_pipeline import (
    SkillEvalResult,
    SkillProposal,
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    list_skill_proposals,
    run_skill_eval_command,
    save_skill_proposal,
)
from quantagent.skills import load_skill_manifest, select_approved_project_skills, skill_manifest_path, skill_root


class SkillLearningEffectGateTest(unittest.TestCase):
    def test_pass_report_allows_approval_when_learning_effect_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect pass ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-pass")

            installed = approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._report("pass", score_delta=3.5)),
            )
            saved = list_skill_proposals(project)[0]
            installed_exists = installed.exists()

        self.assertTrue(installed_exists)
        self.assertEqual(saved.status, "approved")

    def test_fail_report_blocks_approval_when_learning_effect_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect fail ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-fail")

            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, self._report("fail", score_delta=4.0, gap="invalid_sample: docs-only gain")),
                    require_learning_effect=True,
                )

            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_missing_report_blocks_when_learning_effect_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect missing ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-missing")

            with self.assertRaises(PermissionError):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, None),
                    require_learning_effect=True,
                )

            saved = list_skill_proposals(project)[0]

        self.assertEqual(saved.status, "proposed")

    def test_weak_pass_report_without_comparisons_blocks_when_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect weak ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-weak")
            weak_report = {
                "status": "pass",
                "total": 1,
                "solved": {"no_learning": 0, "approved_learning": 1},
                "score_delta": 1.25,
            }

            with self.assertRaisesRegex(PermissionError, "per-task comparisons"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, weak_report),
                    require_learning_effect=True,
                )

            saved = list_skill_proposals(project)[0]

        self.assertEqual(saved.status, "proposed")

    def test_eval_evidence_records_learning_effect_score_delta(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect evidence ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-evidence")

            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._report("pass", score_delta=1.25, gap="")),
                require_learning_effect=True,
            )
            saved = list_skill_proposals(project)[0]
            evidence = json.loads(saved.eval_evidence)

        self.assertTrue(evidence["executed"])
        self.assertEqual(evidence["learning_effect"]["status"], "pass")
        self.assertEqual(evidence["learning_effect"]["score_delta"], 1.25)
        self.assertIn("gap", evidence["learning_effect"])
        self.assertIn("summary", evidence["learning_effect"])
        self.assertEqual(evidence["learning_effect"]["proposal_id"], "skill-learning-effect-evidence")
        self.assertIn("proposal_body_hash", evidence["learning_effect"])

    def test_report_bound_to_different_proposal_blocks_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect wrong proposal ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-bound")
            other = self._proposal(project, "learning-effect-other")
            report = bind_learning_effect_report_to_proposal(self._report("pass", score_delta=2.0), other)

            with self.assertRaisesRegex(PermissionError, "proposal_id"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, report, bind=False),
                )

            saved = {item.proposal_id: item for item in list_skill_proposals(project)}

        self.assertEqual(saved[proposal.proposal_id].status, "proposed")

    def test_unbound_pass_report_blocks_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect unbound ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-unbound")

            with self.assertRaisesRegex(PermissionError, "proposal_id"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, self._report("pass", score_delta=2.0), bind=False),
                )

            saved = list_skill_proposals(project)[0]

        self.assertEqual(saved.status, "proposed")

    def test_approved_manifest_binds_proposal_and_eval_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect manifest provenance ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-provenance")

            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._report("pass", score_delta=2.0)),
            )
            manifest = load_skill_manifest(skill_manifest_path(project, proposal.name))
            selected_before_tamper = select_approved_project_skills("learning-effect-provenance", project=project)
            proposal_path = project / ".quantagent" / "skill_proposals" / f"{proposal.proposal_id}.json"
            payload = json.loads(proposal_path.read_text(encoding="utf-8"))
            payload["body"] = str(payload["body"]) + "\nTampered after approval.\n"
            proposal_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            selected_after_tamper = select_approved_project_skills("learning-effect-provenance", project=project)

        self.assertEqual(manifest.proposal_id, proposal.proposal_id)
        self.assertEqual(manifest.source_path, f"skill_proposal:{proposal.proposal_id}")
        self.assertEqual(len(manifest.proposal_body_hash), 64)
        self.assertEqual(len(manifest.eval_evidence_hash), 64)
        self.assertEqual(len(manifest.eval_command_hash), 64)
        self.assertEqual([skill.name for skill in selected_before_tamper], [proposal.name])
        self.assertEqual(selected_after_tamper, [])

    def test_proposal_manifest_without_eval_hash_is_not_selectable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect manifest missing eval hash ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-missing-eval-hash")

            approve_skill_proposal(
                project,
                proposal.proposal_id,
                eval_result=self._eval_result(project, self._report("pass", score_delta=2.0)),
            )
            manifest_path = skill_manifest_path(project, proposal.name)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["eval_evidence_hash"] = ""
            manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            selected = select_approved_project_skills("learning-effect-missing-eval-hash", project=project)

        self.assertEqual(selected, [])

    def test_executed_eval_without_learning_effect_report_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect mandatory ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-mandatory")

            with self.assertRaisesRegex(PermissionError, "learning-effect report"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, None),
                )

            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_forged_returncode_zero_eval_result_blocks_even_with_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect forged ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-forged")

            with self.assertRaisesRegex(PermissionError, "executed by run_skill_eval_command"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=SkillEvalResult(
                        passed=True,
                        command="python -c 'print(\"claimed\")'",
                        summary="claimed pass",
                        evidence=("claimed",),
                        returncode=0,
                        learning_effect_report=self._report("pass", score_delta=1.0),
                    ),
                )

            saved = list_skill_proposals(project)[0]
            installed_exists = (skill_root(project) / proposal.name / "SKILL.md").exists()

        self.assertEqual(saved.status, "proposed")
        self.assertFalse(installed_exists)

    def test_pass_report_requires_per_task_score_delta(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect task delta ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-task-delta")
            report = self._report("pass", score_delta=3.0)
            report["comparisons"][0].pop("score_delta")

            with self.assertRaisesRegex(PermissionError, "comparison requires numeric score_delta"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, report),
                )

            saved = list_skill_proposals(project)[0]

        self.assertEqual(saved.status, "proposed")

    def test_nan_score_delta_blocks_even_with_passing_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning effect nan ") as tmp:
            project = Path(tmp)
            proposal = self._proposal(project, "learning-effect-nan")
            report = self._report("pass", score_delta=1.0)
            report["score_delta"] = "NaN"

            with self.assertRaisesRegex(PermissionError, "finite score_delta"):
                approve_skill_proposal(
                    project,
                    proposal.proposal_id,
                    eval_result=self._eval_result(project, report),
                )

            saved = list_skill_proposals(project)[0]

        self.assertEqual(saved.status, "proposed")

    def _proposal(self, project: Path, name: str) -> SkillProposal:
        proposal = SkillProposal(
            proposal_id=f"skill-{name}",
            name=name,
            description="Verified learning-effect gate test proposal.",
            triggers=(name,),
            body="Procedure:\n1. Run the targeted verification.",
            evidence=("targeted regression",),
        )
        return save_skill_proposal(project, proposal)

    def _eval_result(self, project: Path, report: dict[str, object] | None, *, bind: bool = True) -> SkillEvalResult:
        result = run_skill_eval_command(
            project,
            f'"{sys.executable}" -c "print(\\"eval-ok\\")"',
            summary="targeted eval passed",
            evidence=("pytest passed",),
            timeout_seconds=10,
        )
        if report is not None and bind:
            proposals = list_skill_proposals(project)
            if proposals:
                report = bind_learning_effect_report_to_proposal(report, proposals[0])
        return replace(
            result,
            require_learning_effect=report is not None,
            learning_effect_report=report,
        )

    def _report(self, status: str, *, score_delta: float, gap: str = "") -> dict[str, object]:
        return {
            "status": status,
            "total": 1,
            "solved": {"no_learning": 0, "approved_learning": 1},
            "steps": {"no_learning": 8, "approved_learning": 4},
            "failure_class": {"no_learning": "regression", "approved_learning": ""},
            "score_delta": score_delta,
            "comparisons": [
                {
                    "task_id": "repair-one",
                    "no_learning": {
                        "task_id": "repair-one",
                        "solved": False,
                        "steps": 8,
                        "failure_class": "regression",
                        "evidence": ["pytest failed before learning"],
                        "invalid_reason": "",
                    },
                    "approved_learning": {
                        "task_id": "repair-one",
                        "solved": True,
                        "steps": 4,
                        "failure_class": "",
                        "evidence": ["pytest passed after approved learning"],
                        "invalid_reason": "",
                    },
                    "score_delta": score_delta,
                }
            ],
            "gap": gap,
        }


if __name__ == "__main__":
    unittest.main()
