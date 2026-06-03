from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_audit import (
    PHASE4_ITEMS,
    DesktopAuditStep,
    DesktopClaim,
    DesktopEvidenceObject,
    FakeDesktopAuditAdapter,
    MixedSoakConfig,
    build_benchmark_provenance,
    build_diff_manifest_attribution,
    capture_desktop_observation,
    guard_claims_with_evidence,
    run_desktop_audit_workflow,
    run_mixed_soak,
    validate_trajectory_chain,
)
from quantagent.trajectory import read_events, record_action, record_observation, record_step


class DesktopAuditTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="desktop audit ")

    def test_unified_observation_captures_screenshot_ax_and_ocr(self) -> None:
        with self.make_project() as tmp:
            adapter = FakeDesktopAuditAdapter()

            evidence = capture_desktop_observation(tmp, adapter, name="initial")

            self.assertEqual([item.kind for item in evidence], ["screenshot", "ax", "ocr", "desktop_observation"])
            self.assertTrue(all(item.evidence_id.startswith("desk-ev-") for item in evidence))
            self.assertTrue(all(item.sha256 for item in evidence))
            for item in evidence[:3]:
                self.assertTrue(Path(item.path).exists())
            unified = evidence[-1]
            self.assertTrue(unified.verified)
            self.assertEqual(set(unified.data), {"screenshot", "ax", "ocr"})

    def test_fake_multi_app_workflow_requires_post_click_screenshot_and_records_chain(self) -> None:
        with self.make_project() as tmp:
            adapter = FakeDesktopAuditAdapter()
            steps = (
                DesktopAuditStep("open_app", {"app": "Safari"}, app="Safari"),
                DesktopAuditStep("click", {"x": 42, "y": 84}, app="Safari"),
                DesktopAuditStep("open_app", {"app": "Notes"}, app="Notes"),
                DesktopAuditStep("command", {"command": "echo desktop-audit"}),
                DesktopAuditStep("claim", {"text": "unsupported desktop claim"}),
            )

            report = run_desktop_audit_workflow(tmp, "Safari to Notes audit", steps, adapter=adapter)

            self.assertTrue(report.ok, report.summary)
            self.assertEqual(report.status, "success")
            self.assertIn("open:Safari", adapter.calls)
            self.assertIn("open:Notes", adapter.calls)
            click_index = adapter.calls.index("click")
            self.assertEqual(adapter.calls[click_index + 1], "screenshot")
            self.assertTrue(any(item.kind == "command_output" and item.data["stdout"] for item in report.evidence))
            chain = validate_trajectory_chain(report.trajectory_path)
            self.assertTrue(chain["ok"], chain)
            report_text = Path(report.report_path).read_text(encoding="utf-8")
            self.assertNotIn("unsupported desktop claim", report_text)
            self.assertEqual(len(report.rejected_claim_ids), 1)

            events = read_events(report.trajectory_path)
            self.assertEqual(events[0].meta["phase"], "task")
            self.assertEqual(events[-1].meta["phase"], "report")
            self.assertTrue(any(event.meta.get("phase") == "command_output" for event in events))
            self.assertTrue(any(event.meta.get("phase") == "claim" for event in events))

    def test_permission_failure_pauses_workflow_before_later_actions(self) -> None:
        with self.make_project() as tmp:
            adapter = FakeDesktopAuditAdapter(permission_fail_actions={"click"})
            steps = (
                DesktopAuditStep("click", {"x": 1, "y": 2}),
                DesktopAuditStep("command", {"command": "echo must-not-run"}),
            )

            report = run_desktop_audit_workflow(tmp, "permission pause", steps, adapter=adapter)

            self.assertFalse(report.ok)
            self.assertEqual(report.status, "paused")
            self.assertIn("permission denied clicking desktop", report.summary)
            self.assertIn("click", adapter.calls)
            self.assertNotIn("command", adapter.calls)
            self.assertEqual(adapter.calls.count("screenshot"), 1)

    def test_initial_observation_failure_pauses_before_actions(self) -> None:
        class FailingObservationAdapter(FakeDesktopAuditAdapter):
            def screenshot(self, project: Path, *, name: str = "") -> DesktopEvidenceObject:
                self.calls.append("screenshot")
                return DesktopEvidenceObject(
                    "desk-ev-observation-denied",
                    "screenshot",
                    "Screen Recording permission denied",
                    verified=False,
                    data={"permission_kind": "screen_recording"},
                )

        with self.make_project() as tmp:
            adapter = FailingObservationAdapter()
            report = run_desktop_audit_workflow(
                tmp,
                "permission pause before command",
                (DesktopAuditStep("command", {"command": "echo must-not-run"}),),
                adapter=adapter,
            )

            self.assertFalse(report.ok)
            self.assertEqual(report.status, "paused")
            self.assertNotIn("command", adapter.calls)
            self.assertFalse(validate_trajectory_chain(report.trajectory_path)["ok"])

    def test_desktop_audit_redacts_command_secrets_from_report_artifacts(self) -> None:
        with self.make_project() as tmp:
            secret_command = "echo token=abc123 password=hunter2 sk-liveeeeeeeeeee"

            report = run_desktop_audit_workflow(
                tmp,
                "redaction audit",
                (DesktopAuditStep("command", {"command": secret_command}),),
                adapter=FakeDesktopAuditAdapter(),
            )

            payload = (Path(report.report_path).parent / "report.json").read_text(encoding="utf-8")
            markdown = Path(report.report_path).read_text(encoding="utf-8")
            self.assertNotIn("abc123", payload)
            self.assertNotIn("hunter2", payload)
            self.assertNotIn("sk-liveeeeeeeeeee", payload)
            self.assertNotIn("abc123", markdown)
            self.assertIn("[redacted]", payload)

    def test_two_desktop_audit_runs_do_not_share_evidence_paths(self) -> None:
        with self.make_project() as tmp:
            steps = (DesktopAuditStep("click", {"x": 1, "y": 2}),)

            first = run_desktop_audit_workflow(tmp, "first run", steps, adapter=FakeDesktopAuditAdapter())
            second = run_desktop_audit_workflow(tmp, "second run", steps, adapter=FakeDesktopAuditAdapter())

            first_paths = {item.path for item in first.evidence if item.path}
            second_paths = {item.path for item in second.evidence if item.path}
            self.assertTrue(first_paths)
            self.assertTrue(second_paths)
            self.assertTrue(first_paths.isdisjoint(second_paths))
            for item in first.evidence + second.evidence:
                if item.path:
                    self.assertTrue(Path(item.path).exists())

    def test_mixed_soak_is_configurable_for_short_test_with_eight_hour_target(self) -> None:
        with self.make_project() as tmp:
            workflows = (
                ("workflow one", (DesktopAuditStep("command", {"command": "echo one"}),)),
                ("workflow two", (DesktopAuditStep("command", {"command": "echo two"}),)),
            )

            result = run_mixed_soak(
                tmp,
                workflows,
                config=MixedSoakConfig(target_hours=8.0, interval_seconds=0, max_cycles=2),
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.target_hours, 8.0)
            self.assertEqual(len(result.cycles), 2)
            self.assertIn("8h target", result.summary)

    def test_mixed_soak_honors_target_hours_when_max_cycles_is_unbounded(self) -> None:
        with self.make_project() as tmp:
            workflows = (("workflow one", (DesktopAuditStep("command", {"command": "echo one"}),)),)
            clock = {"value": 0.0}
            sleeps: list[float] = []

            def now() -> float:
                return clock["value"]

            def sleep(seconds: float) -> None:
                sleeps.append(seconds)
                clock["value"] += seconds

            result = run_mixed_soak(
                tmp,
                workflows,
                config=MixedSoakConfig(target_hours=1.0 / 3600.0, interval_seconds=0.25, max_cycles=0),
                sleep=sleep,
                now=now,
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(len(result.cycles), 4)
            self.assertEqual(sleeps, [0.25, 0.25, 0.25, 0.25])

    def test_trajectory_chain_rejects_out_of_order_phases(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "trajectory.jsonl"
            record_step(path, "task", phase="task")
            record_action(path, "action", phase="action")
            record_step(path, "report", phase="report")
            record_observation(path, "screenshot", phase="screenshot")
            record_observation(path, "command output", phase="command_output")
            record_observation(path, "claim", phase="claim")

            chain = validate_trajectory_chain(path)

            self.assertFalse(chain["ok"])
            self.assertEqual(chain["missing"], ())
            self.assertIn("report", chain["phases"])
            self.assertTrue(chain["order_errors"])

    def test_claim_guard_allows_only_verified_evidence_claims(self) -> None:
        with self.make_project() as tmp:
            evidence = capture_desktop_observation(tmp, FakeDesktopAuditAdapter())
            supported = DesktopEvidenceObject(
                "desk-ev-supported",
                "command_output",
                "claim support",
                verified=True,
                data={"supports_claims": ["claim-supported"]},
            )
            claims = (
                DesktopClaim("claim-supported", "screen was observed", (supported.evidence_id,)),
                DesktopClaim("claim-unrelated", "screen changed without evidence", (evidence[-1].evidence_id,)),
                DesktopClaim("claim-missing", "screen changed without evidence", ("missing-evidence",)),
                DesktopClaim("claim-empty", "screen changed without ids", ()),
            )

            allowed, rejected = guard_claims_with_evidence(claims, (*evidence, supported))

            self.assertEqual([claim.claim_id for claim in allowed], ["claim-supported"])
            self.assertEqual([claim.claim_id for claim in rejected], ["claim-unrelated", "claim-missing", "claim-empty"])

    def test_provenance_and_diff_manifest_attribute_phase4_changes(self) -> None:
        with self.make_project() as tmp:
            provenance = build_benchmark_provenance(tmp, task="phase4 audit", run_id="run-1")
            attribution = build_diff_manifest_attribution(
                {
                    "quantagent/desktop_audit.py": (26, 28, 36, 38, 39, 40),
                    "tests/test_desktop_audit.py": PHASE4_ITEMS,
                }
            )

            self.assertEqual(provenance.phase, "phase4")
            self.assertEqual(provenance.benchmark_items, PHASE4_ITEMS)
            self.assertTrue(provenance.task_digest)
            self.assertTrue(attribution.manifest_hash)
            self.assertEqual(attribution.files["quantagent/desktop_audit.py"], (26, 28, 36, 38, 39, 40))
            self.assertEqual(attribution.files["tests/test_desktop_audit.py"], PHASE4_ITEMS)

            with self.assertRaisesRegex(ValueError, "every changed file"):
                build_diff_manifest_attribution({"tests/test_desktop_audit.py": ()})
            with self.assertRaisesRegex(ValueError, "unknown phase4 benchmark item"):
                build_diff_manifest_attribution({"tests/test_desktop_audit.py": (999,)})
            with self.assertRaisesRegex(ValueError, "requires at least one changed file"):
                build_diff_manifest_attribution({})


if __name__ == "__main__":
    unittest.main()
