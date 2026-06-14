from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_runtime import AgentRuntimeView, RuntimeEvidence, RuntimePlanStep
from quantagent.skill_learning import (
    append_skill_candidates_registry,
    approve_skill_candidate,
    detect_repeated_failure,
    generate_skill_candidates,
    load_skill_candidates_registry,
    registry_path,
    reject_skill_candidate,
)


class SkillLearningTest(unittest.TestCase):
    def test_generates_inert_success_and_failure_candidates_from_events(self) -> None:
        query_events = [
            {
                "kind": "query_start",
                "query_id": "qa-skill",
                "summary": "query started: fix pytest regression",
                "data": {"task": "fix pytest regression", "mode": "agent"},
            },
            {
                "kind": "post_tool",
                "query_id": "qa-skill",
                "name": "pytest",
                "ok": True,
                "step": 1,
                "summary": "pytest passed after focused regression test",
                "data": {},
            },
            {
                "kind": "post_tool",
                "query_id": "qa-skill",
                "name": "mypy",
                "ok": False,
                "step": 2,
                "summary": "mypy failed because imported symbol was missing",
                "data": {},
            },
        ]
        trajectory = [
            {
                "kind": "test",
                "content": "unit test failed before the import guard was added",
                "step": 3,
                "ok": False,
                "meta": {"command": "pytest tests/test_demo.py"},
            }
        ]

        candidates = generate_skill_candidates(query_events=query_events, trajectory=trajectory)
        by_prefix = {candidate.name.split("-", 1)[0]: candidate for candidate in candidates}

        self.assertEqual({candidate.status for candidate in candidates}, {"candidate"})
        self.assertIn("repeat", by_prefix)
        self.assertIn("avoid", by_prefix)
        self.assertIn("pytest", by_prefix["repeat"].trigger)
        self.assertIn("Repeat the observed successful pattern", by_prefix["repeat"].body)
        self.assertIn("Avoid the observed failure pattern", by_prefix["avoid"].body)
        self.assertTrue(any("query_events:pytest step=1 [ok]" in line for line in by_prefix["repeat"].evidence))
        self.assertTrue(any("[failed]" in line for line in by_prefix["avoid"].evidence))

    def test_registry_writes_jsonl_and_approval_is_pure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill learning ") as tmp:
            project = Path(tmp)
            candidates = generate_skill_candidates(
                query_events=[
                    {
                        "kind": "post_tool",
                        "query_id": "qa-skill",
                        "name": "execution_gate",
                        "ok": True,
                        "summary": "execution gate passed with evidence hash",
                        "data": {},
                    }
                ]
            )

            approved = approve_skill_candidate(candidates[0])
            rejected = reject_skill_candidate(candidates[0])
            path = append_skill_candidates_registry(project, [candidates[0], approved, rejected])
            reloaded = load_skill_candidates_registry(project)
            raw_lines = path.read_text(encoding="utf-8").splitlines()
            payloads = [json.loads(line) for line in raw_lines]

        self.assertEqual(path, registry_path(project))
        self.assertEqual(candidates[0].status, "candidate")
        self.assertEqual(approved.status, "approved")
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual([item.status for item in reloaded], ["candidate", "approved", "rejected"])
        self.assertEqual([payload["status"] for payload in payloads], ["candidate", "approved", "rejected"])

    def test_runtime_view_object_input_produces_failure_candidate(self) -> None:
        view = AgentRuntimeView(
            ok=False,
            status="fail",
            summary="runtime failed at semantic verification",
            task="desktop verify click target",
            steps=(
                RuntimePlanStep(
                    step_id="verify-1",
                    index=1,
                    name="verify",
                    kind="desktop",
                    status="fail",
                    summary="semantic verifier rejected target",
                ),
            ),
            evidence=(
                RuntimeEvidence(
                    evidence_id="e1",
                    source="desktop_eval",
                    kind="verify",
                    status="fail",
                    summary="target text mismatch",
                    ok=False,
                ),
            ),
            verifiers=(),
        )

        candidates = generate_skill_candidates(runtime_view=view)
        failure_candidates = [candidate for candidate in candidates if candidate.name.startswith("avoid-")]

        self.assertEqual(len(failure_candidates), 1)
        self.assertIn("desktop", failure_candidates[0].trigger)
        self.assertTrue(any("desktop_eval" in line for line in failure_candidates[0].evidence))

    def test_detects_repeated_failure_from_retained_registry_without_installing_skill(self) -> None:
        first_failure = [
            {
                "kind": "query_start",
                "query_id": "qa-repeat",
                "summary": "query started: repair parser regression",
                "data": {"task": "repair parser regression", "mode": "agent"},
            },
            {
                "kind": "post_tool",
                "query_id": "qa-repeat",
                "name": "pytest",
                "ok": False,
                "step": 1,
                "summary": "pytest failed because parser dropped diff-content lines",
                "data": {},
            },
        ]
        repeated_failure = [
            {
                "kind": "query_start",
                "query_id": "qa-repeat-2",
                "summary": "query started: repair parser regression",
                "data": {"task": "repair parser regression", "mode": "agent"},
            },
            {
                "kind": "post_tool",
                "query_id": "qa-repeat-2",
                "name": "pytest",
                "ok": False,
                "step": 1,
                "summary": "pytest failed because parser dropped diff-content lines",
                "data": {},
            },
        ]
        different_failure = [
            {
                "kind": "query_start",
                "query_id": "qa-repeat-3",
                "summary": "query started: repair parser regression",
                "data": {"task": "repair parser regression", "mode": "agent"},
            },
            {
                "kind": "post_tool",
                "query_id": "qa-repeat-3",
                "name": "pytest",
                "ok": False,
                "step": 1,
                "summary": "pytest failed because cache metadata was missing",
                "data": {},
            },
        ]

        with tempfile.TemporaryDirectory(prefix="skill recurrence ") as tmp:
            project = Path(tmp)
            failure_candidate = next(
                candidate
                for candidate in generate_skill_candidates(query_events=first_failure)
                if candidate.name.startswith("avoid-")
            )
            append_skill_candidates_registry(project, [approve_skill_candidate(failure_candidate)])

            repeated = detect_repeated_failure(project, query_events=repeated_failure)
            different = detect_repeated_failure(project, query_events=different_failure)
            no_failure = detect_repeated_failure(project, query_events=[])

        self.assertTrue(repeated.repeated)
        self.assertTrue(repeated.signature.startswith("failure:"))
        self.assertEqual(repeated.matched_names, (approve_skill_candidate(failure_candidate).name,))
        self.assertEqual(repeated.matched_statuses, ("approved",))
        self.assertTrue(any("diff-content" in line for line in repeated.current_evidence))
        self.assertTrue(any("diff-content" in line for line in repeated.matched_evidence))
        self.assertIn("do not retry the same action unchanged", repeated.guidance)
        self.assertFalse(different.repeated)
        self.assertNotEqual(different.signature, repeated.signature)
        self.assertFalse(no_failure.repeated)
        self.assertEqual(no_failure.signature, "")


if __name__ == "__main__":
    unittest.main()
