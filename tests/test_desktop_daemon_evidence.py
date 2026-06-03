from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_daemon_evidence import (
    append_daemon_event,
    append_daemon_trajectory,
    build_desktop_evidence_object,
    daemon_autopsy_path,
    daemon_query_events_path,
    daemon_trajectory_path,
    write_daemon_failure_autopsy,
)


class DesktopDaemonEvidenceTest(unittest.TestCase):
    def test_builds_unified_desktop_evidence_object_for_fake_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop evidence object ") as tmp:
            project = Path(tmp)
            screenshot = project / "screen.png"
            ax = project / "ax.json"
            ocr = project / "ocr.txt"
            command_output = project / "stdout.txt"
            screenshot.write_bytes(b"fake-png")
            ax.write_text('{"role":"window"}\n', encoding="utf-8")
            ocr.write_text("Search\n", encoding="utf-8")
            command_output.write_text("clicked target\n", encoding="utf-8")

            objects = [
                build_desktop_evidence_object("screenshot", screenshot, summary="after click", step=2).to_dict(),
                build_desktop_evidence_object("ax", ax, summary="window tree", step=2).to_dict(),
                build_desktop_evidence_object("ocr", ocr, summary="visible text", step=2, meta={"source": "fake"}).to_dict(),
                build_desktop_evidence_object("command_output", command_output, summary="click command stdout", step=2).to_dict(),
            ]
            append_daemon_trajectory(project, "observation", "post-click evidence captured", step=2, ok=True, meta={"evidence": objects})
            payload = json.loads(daemon_trajectory_path(project).read_text(encoding="utf-8").strip())

        self.assertEqual([item["kind"] for item in objects], ["screenshot", "ax", "ocr", "command_output"])
        self.assertEqual(objects[0]["sha256"], hashlib.sha256(b"fake-png").hexdigest())
        self.assertEqual(objects[3]["sha256"], hashlib.sha256(b"clicked target\n").hexdigest())
        self.assertEqual(objects[2]["meta"], {"source": "fake"})
        self.assertEqual(payload["meta"]["evidence"][0]["kind"], "screenshot")
        self.assertEqual(payload["meta"]["evidence"][1]["summary"], "window tree")
        self.assertEqual(payload["meta"]["evidence"][3]["kind"], "command_output")

    def test_desktop_evidence_hash_is_stable_for_same_artifact_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop evidence stable hash ") as tmp:
            artifact = Path(tmp) / "stdout.txt"
            artifact.write_text("same output\n", encoding="utf-8")

            first = build_desktop_evidence_object("command_output", artifact)
            second = build_desktop_evidence_object("command_output", artifact)

        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.sha256, hashlib.sha256(b"same output\n").hexdigest())

    def test_missing_desktop_evidence_artifact_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop evidence missing ") as tmp:
            missing = Path(tmp) / "missing.png"

            with self.assertRaisesRegex(FileNotFoundError, "desktop evidence artifact not found"):
                build_desktop_evidence_object("screenshot", missing)

    def test_rejects_unknown_desktop_evidence_kind(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop evidence object ") as tmp:
            artifact = Path(tmp) / "artifact.txt"
            artifact.write_text("data\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "desktop evidence kind"):
                build_desktop_evidence_object("network", artifact)

    def test_append_helpers_write_query_and_trajectory_jsonl(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon evidence ") as tmp:
            project = Path(tmp)

            query_event = append_daemon_event(
                project,
                "stop_failure",
                "daemon paused after verify failure",
                step=4,
                name="verify",
                failed_at="verify step 4",
                failure_class="verify_failed",
                sources=["tokens.json", "state.json"],
            )
            trajectory_event = append_daemon_trajectory(
                project,
                "test",
                "semantic verification failed",
                step=4,
                ok=False,
                failed_at="verify step 4",
                failure_class="verify_failed",
                sources=["tokens.json"],
            )
            query_payload = json.loads(daemon_query_events_path(project).read_text(encoding="utf-8").strip())
            trajectory_payload = json.loads(daemon_trajectory_path(project).read_text(encoding="utf-8").strip())

        self.assertIs(query_event.ok, False)
        self.assertIs(trajectory_event.ok, False)
        self.assertEqual(query_payload["kind"], "stop_failure")
        self.assertEqual(query_payload["data"]["failed_at"], "verify step 4")
        self.assertEqual(query_payload["data"]["failure_class"], "verify_failed")
        self.assertEqual(query_payload["data"]["sources"], ["tokens.json", "state.json"])
        self.assertEqual(trajectory_payload["kind"], "test")
        self.assertEqual(trajectory_payload["meta"]["failed_at"], "verify step 4")
        self.assertEqual(trajectory_payload["meta"]["failure_class"], "verify_failed")

    def test_failure_autopsy_writes_openmako_markdown_from_existing_agent_autopsy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon autopsy ") as tmp:
            project = Path(tmp)
            append_daemon_event(
                project,
                "query_start",
                "query started: click Search",
                data={"task": "click Search", "mode": "desktop_daemon"},
            )
            append_daemon_trajectory(project, "action", "clicked Search", step=1, ok=True)
            append_daemon_trajectory(
                project,
                "test",
                "semantic verification failed: target did not change",
                step=2,
                ok=False,
                failed_at="verify:semantic step 2",
                failure_class="verify_failed",
                sources=["tokens.json"],
            )

            output = write_daemon_failure_autopsy(project, goal="click Search", status="paused", summary="daemon paused")
            markdown = output.read_text(encoding="utf-8")
            expected_output = daemon_autopsy_path(project)
            expected_query_events = str(daemon_query_events_path(project))
            expected_trajectory = str(daemon_trajectory_path(project))

        self.assertEqual(output, expected_output)
        self.assertEqual(output.name, "openmako-autopsy.md")
        self.assertIn("# Desktop Daemon Autopsy: paused", markdown)
        self.assertIn("- source_agent: desktop_daemon", markdown)
        self.assertIn("- command: click Search", markdown)
        self.assertIn("- status: FAILED", markdown)
        self.assertIn("- failure_class: verify_failed", markdown)
        self.assertIn("- failed_at: verify:semantic step 2", markdown)
        self.assertIn("semantic verification failed", markdown)
        self.assertIn("tokens.json", markdown)
        self.assertIn(expected_query_events, markdown)
        self.assertIn(expected_trajectory, markdown)
        self.assertIn("Middleware Trial", markdown)

    def test_explicit_failure_metadata_overrides_jsonl_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon autopsy override ") as tmp:
            project = Path(tmp)
            append_daemon_trajectory(
                project,
                "test",
                "action failed",
                step=1,
                ok=False,
                failed_at="jsonl failed_at",
                failure_class="jsonl_class",
            )

            output = write_daemon_failure_autopsy(
                project,
                goal="click Search",
                status="failed",
                summary="explicit failure",
                failed_at="explicit failed_at",
                failure_class="explicit_class",
                sources=["explicit-source.json"],
            )
            markdown = output.read_text(encoding="utf-8")

        self.assertIn("- failure_class: explicit_class", markdown)
        self.assertIn("- failed_at: explicit failed_at", markdown)
        self.assertIn("explicit-source.json", markdown)


if __name__ == "__main__":
    unittest.main()
