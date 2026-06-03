from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
from pathlib import Path

from quantagent.edit_loop import (
    ChangeSetCandidate,
    ChangeSetPlan,
    EditPlan,
    FileReplacement,
    AutoPatchSpec,
    PatchPlan,
    PatchPlanFile,
    _run_patch_plan_from_patch_plan,
    propose_repair_candidates,
    run_isolated_repair_loop,
    apply_unified_diff,
    build_repair_trajectory,
    classify_test_failure,
    create_patch_plan,
    load_patch_plan,
    run_auto_patch,
    run_change_set_retry,
    run_edit_test_retry,
    write_patch_plan,
)
from quantagent.failure_interrupt_cache import build_failure_interrupt, build_invalidation_keys, cache_path, find_diagnosis_asset, record_diagnosis_asset
from quantagent.model_client import ModelResponse


class EditLoopTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent edit loop ")

    def test_retries_candidates_until_test_passes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.txt"
            target.write_text("threshold=old\n", encoding="utf-8")

            result = run_edit_test_retry(
                project,
                EditPlan(
                    path="strategy.txt",
                    old="threshold=old",
                    candidate_replacements=["threshold=wrong", "threshold=fixed"],
                    test_command=["grep", "-q", "threshold=fixed", "strategy.txt"],
                    max_attempts=2,
                ),
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.attempt_count, 2)
            self.assertEqual(result.attempts[0].test_returncode, 1)
            self.assertTrue(result.attempts[0].restored)
            self.assertEqual(result.attempts[1].test_returncode, 0)
            self.assertFalse(result.attempts[1].restored)
            self.assertIn("+threshold=fixed", result.attempts[1].diff)
            self.assertEqual(target.read_text(encoding="utf-8"), "threshold=fixed\n")

    def test_restores_original_when_all_candidates_fail(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.txt"
            original = "threshold=old\n"
            target.write_text(original, encoding="utf-8")

            result = run_edit_test_retry(
                project,
                EditPlan(
                    path="strategy.txt",
                    old="threshold=old",
                    candidate_replacements=["threshold=wrong", "threshold=still_wrong"],
                    test_command=["grep", "-q", "threshold=fixed", "strategy.txt"],
                    max_attempts=2,
                ),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.attempt_count, 2)
            self.assertTrue(all(attempt.restored for attempt in result.attempts))
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_preview_failure_does_not_apply_change(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "dupes.txt"
            original = "same\nsame\n"
            target.write_text(original, encoding="utf-8")

            result = run_edit_test_retry(
                project,
                EditPlan(
                    path="dupes.txt",
                    old="same",
                    candidate_replacements=["other"],
                    test_command=["grep", "-q", "other", "dupes.txt"],
                ),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.attempt_count, 1)
            self.assertFalse(result.attempts[0].preview_ok)
            self.assertFalse(result.attempts[0].apply_ok)
            self.assertIsNone(result.attempts[0].test_returncode)
            self.assertIn("expected 1 occurrence", result.attempts[0].summary)
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_contextual_replace_disambiguates_duplicate_old_text(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.py"
            target.write_text("def slow():\n    return value\n\ndef fast():\n    return value\n", encoding="utf-8")

            result = run_edit_test_retry(
                project,
                EditPlan(
                    path="strategy.py",
                    old="return value",
                    candidate_replacements=["return value * 2"],
                    before_context="def fast():\n    ",
                    test_command=["grep", "-q", "return value \\* 2", "strategy.py"],
                ),
            )

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.attempts[0].contextual)
            self.assertIn("+    return value * 2", result.attempts[0].diff)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "def slow():\n    return value\n\ndef fast():\n    return value * 2\n",
            )

    def test_structured_result_contains_command_and_output_previews(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.txt"
            target.write_text("threshold=old\n", encoding="utf-8")

            result = run_edit_test_retry(
                project,
                EditPlan(
                    path="strategy.txt",
                    old="threshold=old",
                    candidate_replacements=["threshold=fixed"],
                    test_command=["grep", "-n", "threshold=fixed", "strategy.txt"],
                    output_preview_chars=8,
                ),
            )

            payload = result.to_dict()
            self.assertTrue(result.ok, result.summary)
            self.assertEqual(payload["command"], "grep -n threshold=fixed strategy.txt")
            self.assertEqual(payload["attempts"][0]["stdout_preview"], "1:thresh\n[output trimmed]")
            self.assertFalse(payload["attempts"][0]["contextual"])

    def test_change_set_applies_multiple_files_and_keeps_passing_candidate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("alpha=old\n", encoding="utf-8")
            (project / "b.txt").write_text("beta=old\n", encoding="utf-8")

            result = run_change_set_retry(
                project,
                ChangeSetPlan(
                    candidates=[
                        ChangeSetCandidate(
                            name="fix both",
                            edits=[
                                FileReplacement("a.txt", "alpha=old", "alpha=new"),
                                FileReplacement("b.txt", "beta=old", "beta=new"),
                            ],
                        )
                    ],
                    test_command=["grep", "-q", "alpha=new", "a.txt"],
                ),
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.final_candidate, "fix both")
            self.assertEqual(result.attempt_count, 1)
            self.assertEqual(len(result.attempts[0].diffs), 2)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "alpha=new\n")
            self.assertEqual((project / "b.txt").read_text(encoding="utf-8"), "beta=new\n")

    def test_change_set_restores_all_files_when_tests_fail(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            original_a = "alpha=old\n"
            original_b = "beta=old\n"
            (project / "a.txt").write_text(original_a, encoding="utf-8")
            (project / "b.txt").write_text(original_b, encoding="utf-8")

            result = run_change_set_retry(
                project,
                ChangeSetPlan(
                    candidates=[
                        ChangeSetCandidate(
                            edits=[
                                FileReplacement("a.txt", "alpha=old", "alpha=new"),
                                FileReplacement("b.txt", "beta=old", "beta=new"),
                            ],
                        )
                    ],
                    test_command=["grep", "-q", "missing", "a.txt"],
                ),
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.attempts[0].restored)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), original_a)
            self.assertEqual((project / "b.txt").read_text(encoding="utf-8"), original_b)

    def test_change_set_restores_prior_edits_when_later_edit_fails(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            original_a = "alpha=old\n"
            original_b = "beta=old\n"
            (project / "a.txt").write_text(original_a, encoding="utf-8")
            (project / "b.txt").write_text(original_b, encoding="utf-8")

            result = run_change_set_retry(
                project,
                ChangeSetPlan(
                    candidates=[
                        ChangeSetCandidate(
                            edits=[
                                FileReplacement("a.txt", "alpha=old", "alpha=new"),
                                FileReplacement("b.txt", "missing", "beta=new"),
                            ],
                        )
                    ],
                    test_command=["true"],
                ),
            )

            self.assertFalse(result.ok)
            self.assertFalse(result.attempts[0].apply_ok)
            self.assertTrue(result.attempts[0].restored)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), original_a)
            self.assertEqual((project / "b.txt").read_text(encoding="utf-8"), original_b)

    def test_patch_plan_infers_tests_and_risks(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "tests").mkdir()
            (project / "agent.py").write_text("x = 1\n", encoding="utf-8")

            plan = create_patch_plan(project, "fix approval runtime", paths=["agent.py"])

            self.assertEqual(plan.files[0].path, "agent.py")
            self.assertIn("python3", plan.test_command)
            self.assertTrue(any("runtime" in risk for risk in plan.risks))

    def test_patch_plan_includes_repo_map_context(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "agent.py").write_text(
                "import json\n\nclass RuntimeAgent:\n    def run(self):\n        return json.dumps({'ok': True})\n",
                encoding="utf-8",
            )

            plan = create_patch_plan(project, "fix RuntimeAgent json behavior", paths=["agent.py"], test_command=["true"])

            self.assertIn("# Repo Context Map", plan.repo_context)
            self.assertIn("RuntimeAgent", plan.repo_context)
            self.assertIn("agent.py", plan.repo_context)

    def test_patch_plan_json_round_trip(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = create_patch_plan(project, "fix", paths=["a.py"], test_command=["true"])
            path = write_patch_plan(project / "plan.json", plan)

            loaded = load_patch_plan(path)

            self.assertEqual(loaded.task, "fix")
            self.assertEqual(loaded.files[0].path, "a.py")
            self.assertEqual(loaded.test_command, ["true"])

    def test_patch_run_requires_explicit_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix", paths=["a.txt"], test_command=["grep", "-q", "new", "a.txt"])
            plan = plan.__class__(
                task=plan.task,
                files=plan.files,
                risks=plan.risks,
                test_command=plan.test_command,
                candidates=[ChangeSetCandidate([FileReplacement("a.txt", "old", "new")])],
            )

            result = _run_patch_plan_from_patch_plan(project, plan, apply=False)

            self.assertFalse(result.ok)
            self.assertFalse(result.applied)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "old\n")

    def test_patch_run_applies_reviewed_plan(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix", paths=["a.txt"], test_command=["grep", "-q", "new", "a.txt"])
            plan = plan.__class__(
                task=plan.task,
                files=plan.files,
                risks=plan.risks,
                test_command=plan.test_command,
                candidates=[ChangeSetCandidate([FileReplacement("a.txt", "old", "new")])],
            )

            result = _run_patch_plan_from_patch_plan(project, plan, apply=True)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.applied)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "new\n")

    def test_failure_classifier_categories(self) -> None:
        cases = [
            ("syntax", {"stderr": "SyntaxError: invalid syntax", "returncode": 1}),
            ("import", {"stderr": "ModuleNotFoundError: No module named x", "returncode": 1}),
            ("assertion", {"stderr": "AssertionError: nope", "returncode": 1}),
            ("path", {"stderr": "FileNotFoundError: missing", "returncode": 1}),
            ("env", {"stderr": "environment variable API_KEY missing", "returncode": 1}),
            ("policy", {"stderr": "", "returncode": 1, "blocked": True}),
            ("timeout", {"stderr": "timed out", "returncode": 124}),
            ("unknown", {"stderr": "weird", "returncode": 2}),
        ]

        for expected, kwargs in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_test_failure(**kwargs), expected)

    def test_repair_trajectory_respects_retry_limit(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            result = run_change_set_retry(
                project,
                ChangeSetPlan(
                    candidates=[
                        ChangeSetCandidate([FileReplacement("a.txt", "old", "bad")], name="bad"),
                        ChangeSetCandidate([FileReplacement("a.txt", "old", "worse")], name="worse"),
                    ],
                    test_command=["grep", "-q", "new", "a.txt"],
                    max_attempts=2,
                ),
            )

            trajectory = build_repair_trajectory(result, max_rounds=1)

            self.assertEqual(len(trajectory), 1)
            self.assertEqual(trajectory[0].index, 1)

    def test_unified_diff_preview_and_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("one\nold\nthree\n", encoding="utf-8")
            diff = "--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n-old\n+new\n three\n"

            preview = apply_unified_diff(project, diff, apply=False)
            applied = apply_unified_diff(project, diff, apply=True)

            self.assertTrue(preview.ok)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "one\nnew\nthree\n")
            self.assertEqual(applied.changed_paths, ["a.txt"])

    def test_patch_run_creates_checkpoint_for_unified_diff(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            plan = PatchPlan(
                task="diff first",
                files=[PatchPlanFile("a.txt")],
                risks=["low"],
                test_command=[],
                unified_diff="--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n",
            )

            result = _run_patch_plan_from_patch_plan(project, plan, apply=True)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.checkpoint_id.startswith("chk-"))
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "new\n")

    def test_patch_run_executes_tests_after_unified_diff(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = PatchPlan(
                task="diff first with tests",
                files=[PatchPlanFile("a.py")],
                risks=["low"],
                test_command=["python3", "-m", "py_compile", "a.py"],
                unified_diff="--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-VALUE = 1\n+VALUE = 2\n",
            )

            result = _run_patch_plan_from_patch_plan(project, plan, apply=True)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.repair_trajectory[0].classification, "unknown")

    def test_auto_patch_generates_preview_without_applying(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")

            result = run_auto_patch(
                project,
                AutoPatchSpec("fix", "a.txt", "old", "new", ["grep", "-q", "new", "a.txt"]),
                apply=False,
            )

            self.assertFalse(result.ok)
            self.assertFalse(result.applied)
            self.assertIn("-old", result.preview)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "old\n")

    def test_auto_patch_requires_review_before_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")

            result = run_auto_patch(
                project,
                AutoPatchSpec("fix", "a.txt", "old", "new", ["grep", "-q", "new", "a.txt"], reviewed=False),
                apply=True,
            )

            self.assertFalse(result.ok)
            self.assertFalse(result.applied)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "old\n")

    def test_auto_patch_apply_runs_tests_and_records_rounds(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")

            result = run_auto_patch(
                project,
                AutoPatchSpec("fix", "a.txt", "old", "new", ["grep", "-q", "new", "a.txt"], reviewed=True),
                apply=True,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.applied)
            self.assertTrue(result.checkpoint_id)
            self.assertTrue(any(round_item.stage == "test" for round_item in result.rounds))
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "new\n")

    def test_auto_patch_classifies_failed_test(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")

            result = run_auto_patch(
                project,
                AutoPatchSpec("fix", "a.txt", "old", "new", ["grep", "-q", "missing", "a.txt"], reviewed=True),
                apply=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.applied)
            self.assertTrue(result.rounds)
            self.assertIn(result.rounds[-1].classification, {"path", "unknown"})

    def test_model_repair_proposal_parses_candidates_without_applying(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix failing value", paths=["a.py"], test_command=["python3", "-m", "py_compile", "a.py"])

            result = propose_repair_candidates(project, plan, "AssertionError: expected 2", model="fake-model", client=FakeClient())

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.candidates[0].edits[0].path, "a.py")
            self.assertEqual((project / "a.py").read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_model_repair_prompt_includes_repo_map_context(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.prompt = ""

            def complete(self, request):
                self.prompt = request.prompt
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("class ValueHolder:\n    VALUE = 1\n", encoding="utf-8")
            client = FakeClient()
            plan = create_patch_plan(project, "fix ValueHolder", paths=["a.py"], test_command=["true"])

            result = propose_repair_candidates(project, plan, "AssertionError: expected 2", model="fake-model", client=client)

            self.assertTrue(result.ok, result.error)
            self.assertIn("repo_context", client.prompt)
            self.assertIn("ValueHolder", client.prompt)

    def test_model_repair_proposal_rejects_non_json(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(model=request.model, ok=True, text="not json", provider="fake")

        with self.make_project() as tmp:
            project = Path(tmp)
            plan = create_patch_plan(project, "fix", paths=["a.py"], test_command=["true"])

            result = propose_repair_candidates(project, plan, "failure", model="fake-model", client=FakeClient())

            self.assertFalse(result.ok)
            self.assertEqual(result.error, "invalid_json")

    def test_isolated_repair_loop_retries_transient_proposal_failure(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(model=request.model, ok=False, text="", error="transient upstream failure", provider="fake")
                self.prompt = request.prompt
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=client, max_rounds=2)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(client.calls, 2)
            self.assertEqual(result.rounds[0].classification, "transient upstream failure")
            self.assertIn("Previous model repair proposal failed", client.prompt)

    def test_isolated_repair_loop_applies_candidate_in_copy_and_creates_review(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=FakeClient())

            self.assertTrue(result.ok, result.summary)
            self.assertIsNotNone(result.review)
            self.assertEqual((project / "a.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertIn("a.py", result.review.changed_paths if result.review else [])
            _interrupt, asset = find_diagnosis_asset(project, project, "AssertionError", failure_class="assertion", planned_paths=["a.py"])
            self.assertIsNotNone(asset)

    def test_isolated_repair_loop_red_to_green_real_unittest_and_writes_asset(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text=json.dumps(
                        {
                            "candidates": [
                                {
                                    "name": "fix-add-operator",
                                    "summary": "operator repair",
                                    "edits": [
                                        {
                                            "path": "calculator.py",
                                            "old": "    return a - b",
                                            "new": "    return a + b",
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_adds_numbers(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            targeted_command = ["python3", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_calculator.py"]
            pre = subprocess.run(targeted_command, cwd=project, text=True, capture_output=True, check=False)
            self.assertNotEqual(pre.returncode, 0, pre.stdout + pre.stderr)
            failure = "AssertionError: add(2, 3) expected 5"
            plan = create_patch_plan(project, "fix add", paths=["calculator.py"], test_command=targeted_command, allow_risky_tests=True)

            result = run_isolated_repair_loop(project, plan, failure, model="fake-model", client=FakeClient(), max_rounds=1)
            context_paths = result.rounds[0].context_paths if result.rounds else ["calculator.py"]
            _interrupt, asset = find_diagnosis_asset(project, project, failure, failure_class="assertion", planned_paths=context_paths)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual((project / "calculator.py").read_text(encoding="utf-8"), "def add(a, b):\n    return a - b\n")
            self.assertIsNotNone(result.review)
            self.assertIn("calculator.py", result.review.changed_paths if result.review else [])
            self.assertIsNotNone(asset)
            assert asset is not None
            self.assertIn("targeted_test=passed", asset.evidence_facts)
            self.assertIn("full_test=passed", asset.evidence_facts)
            self.assertEqual(asset.successful_fix_pattern, "operator repair")

    def test_isolated_repair_loop_uses_diagnosis_asset_without_reusing_old_patch(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self, replacement: str) -> None:
                self.replacement = replacement
                self.calls = 0
                self.prompts: list[str] = []

            def complete(self, request):
                self.calls += 1
                self.prompts.append(request.prompt)
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"schema/caller field mismatch","edits":[{"path":"a.py","old":"VALUE = 1","new":"%s"}]}]}' % self.replacement,
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            first_client = FakeClient("VALUE = 2")
            second_client = FakeClient("VALUE = 3")

            first = run_isolated_repair_loop(project, plan, "AssertionError: expected VALUE = 2", model="fake-model", client=first_client)
            second = run_isolated_repair_loop(project, plan, "AssertionError: expected VALUE = 2", model="fake-model", client=second_client, max_rounds=1)
            project_text = (project / "a.py").read_text(encoding="utf-8")

        self.assertTrue(first.ok, first.summary)
        self.assertFalse(second.ok, second.summary)
        self.assertEqual(first_client.calls, 1)
        self.assertEqual(second_client.calls, 1)
        self.assertIn("schema/caller field mismatch", second_client.prompts[0])
        self.assertIn("evidence_receipt", second_client.prompts[0])
        self.assertIn("successful_fix_pattern", second_client.prompts[0])
        prompt_payload = json.loads(second_client.prompts[0])
        self.assertNotIn("diagnosis_asset", prompt_payload)
        self.assertNotIn("failure_signature", json.dumps(prompt_payload["evidence_receipt"]))
        self.assertNotIn("invalidation_keys", json.dumps(prompt_payload["evidence_receipt"]))
        self.assertIn("failure_class=assertion", prompt_payload["evidence_receipt"]["evidence_facts"])
        self.assertTrue(prompt_payload["evidence_receipt"]["suspect_symbols"])
        self.assertTrue(any(item.startswith("evidence_receipt=valid") for item in second.rounds[0].diagnostics))
        self.assertEqual(project_text, "VALUE = 1\n")

    def test_isolated_repair_loop_blocks_contradicted_diagnosis_asset_prompt(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def complete(self, request):
                self.prompts.append(request.prompt)
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 3"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            failure = "AssertionError: expected VALUE = 2"
            record_diagnosis_asset(
                project,
                project,
                failure,
                failure_class="assertion",
                planned_paths=["a.py"],
                evidence_facts=["failure_class=assertion", "python_file=a.py"],
                suspect_symbols=["missing.py:calc"],
                successful_fix_pattern="wrong import path",
                validation_result={"full_test": {"ok": False}},
            )
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, failure, model="fake-model", client=client, max_rounds=1)

        self.assertFalse(result.ok)
        prompt_payload = json.loads(client.prompts[0])
        self.assertEqual(prompt_payload["evidence_receipt"], {})

    def test_isolated_repair_loop_uses_weakened_asset_without_evidence_facts(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def complete(self, request):
                self.prompts.append(request.prompt)
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 3"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            failure = "AssertionError: expected VALUE = 2"
            interrupt = build_failure_interrupt(project, failure, failure_class="assertion", planned_paths=["a.py"])
            cache_payload = {
                "version": 1,
                "entries": {
                    interrupt.signature: {
                        "failure_signature": interrupt.signature,
                        "invalidation_keys": build_invalidation_keys(project, interrupt),
                        "evidence_facts": ["python_file=a.py", "imports[a.py]=old_dep"],
                        "suspect_symbols": [],
                        "successful_fix_pattern": "schema/caller field mismatch",
                        "validation_result": {"full_test": {"ok": False}},
                    }
                },
            }
            path = cache_path(project)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache_payload), encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, failure, model="fake-model", client=client, max_rounds=1)

        self.assertFalse(result.ok)
        prompt_payload = json.loads(client.prompts[0])
        receipt_payload = prompt_payload["evidence_receipt"]
        self.assertEqual(receipt_payload["successful_fix_pattern"], "schema/caller field mismatch")
        self.assertEqual(receipt_payload.get("evidence_facts", []), [])
        self.assertEqual(receipt_payload.get("suspect_symbols", []), [])
        self.assertNotIn("old_dep", client.prompts[0])

    def test_isolated_repair_loop_blocks_unverified_diagnosis_asset_prompt(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def complete(self, request):
                self.prompts.append(request.prompt)
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 3"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            failure = "AssertionError: expected VALUE = 2"
            interrupt = build_failure_interrupt(project, failure, failure_class="assertion", planned_paths=["a.py"])
            cache_payload = {
                "version": 1,
                "entries": {
                    interrupt.signature: {
                        "failure_signature": interrupt.signature,
                        "invalidation_keys": build_invalidation_keys(project, interrupt),
                        "evidence_facts": ["free form old clue"],
                        "suspect_symbols": [],
                        "successful_fix_pattern": "mock return shape mismatch",
                        "validation_result": {},
                    }
                },
            }
            path = cache_path(project)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache_payload), encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, failure, model="fake-model", client=client, max_rounds=1)

        self.assertFalse(result.ok)
        prompt_payload = json.loads(client.prompts[0])
        self.assertEqual(prompt_payload["evidence_receipt"], {})

    def test_isolated_repair_loop_does_not_write_asset_when_full_test_fails(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"stale test expectation","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_full.py").write_text(
                "import unittest\n\nclass FullTest(unittest.TestCase):\n    def test_full_regression(self):\n        self.assertEqual(1, 2)\n",
                encoding="utf-8",
            )
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_isolated_repair_loop(project, plan, "AssertionError: expected VALUE = 2", model="fake-model", client=FakeClient(), max_rounds=1)
            _interrupt, asset = find_diagnosis_asset(project, project, "AssertionError: expected VALUE = 2", failure_class="assertion", planned_paths=["a.py"])

        self.assertFalse(result.ok)
        self.assertIn("full tests failed", result.rounds[0].summary)
        self.assertIsNone(asset)

    def test_isolated_repair_loop_restores_failed_round_before_retry(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                replacement = "VALUE = 3" if self.calls == 1 else "VALUE = 2"
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"round-%d","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"%s"}]}]}' % (self.calls, replacement),
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=FakeClient(), max_rounds=2)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.rounds[0].restored)
            self.assertFalse(result.rounds[0].test_ok)
            self.assertTrue(result.rounds[1].test_ok)
            self.assertIn("a.py", result.rounds[1].context_paths)

    def test_isolated_repair_loop_tries_all_candidates_before_next_round(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.calls = 0

            def complete(self, request):
                self.calls += 1
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text=(
                        '{"candidates":['
                        '{"name":"wrong","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 3"}]},'
                        '{"name":"right","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}'
                        "]}"
                    ),
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=client, max_rounds=2)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(client.calls, 1)
            self.assertEqual([round_item.candidate_index for round_item in result.rounds], [1, 2])
            self.assertTrue(result.rounds[0].restored)
            self.assertFalse(result.rounds[0].test_ok)
            self.assertTrue(result.rounds[1].test_ok)
            self.assertTrue(result.rounds[1].diagnostics)

    def test_isolated_repair_loop_prioritizes_exact_old_text_matches(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text=(
                        '{"candidates":['
                        '{"name":"stale","summary":"old text no longer matches","edits":[{"path":"a.py","old":"VALUE = 0","new":"VALUE = 9"}]},'
                        '{"name":"good","summary":"exact old text matches","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}'
                        "]}"
                    ),
                    provider="fake",
                )

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=FakeClient(), max_rounds=1)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(len(result.rounds), 1)
            self.assertEqual(result.rounds[0].candidate, "good")
            self.assertEqual(result.rounds[0].candidate_index, 2)
            self.assertEqual(result.rounds[0].candidate_rank, 1)
            self.assertTrue(result.rounds[0].test_ok)

    def test_isolated_repair_loop_prompt_includes_thick_failed_candidate_feedback(self) -> None:
        class FakeClient:
            configured = True

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def complete(self, request):
                self.prompts.append(request.prompt)
                if len(self.prompts) == 1:
                    text = (
                        '{"candidates":['
                        '{"name":"bad-threshold","summary":"sets the wrong value","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 3"}]}'
                        "]}"
                    )
                else:
                    text = (
                        '{"candidates":['
                        '{"name":"good-threshold","summary":"sets expected value","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}'
                        "]}"
                    )
                return ModelResponse(model=request.model, ok=True, text=text, provider="fake")

        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])
            client = FakeClient()

            result = run_isolated_repair_loop(project, plan, "AssertionError", model="fake-model", client=client, max_rounds=2)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(len(client.prompts), 2)
            second_prompt = client.prompts[1]
            self.assertIn("bad-threshold", second_prompt)
            self.assertIn("classification=", second_prompt)
            self.assertIn("summary=", second_prompt)
            self.assertTrue("Next repair retrieval queries" in second_prompt or "retrieval" in second_prompt)


if __name__ == "__main__":
    unittest.main()
