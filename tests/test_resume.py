from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.resume import create_resume_snapshot, list_resume_snapshots, load_resume_snapshot, render_resume_snapshot, resume_last_failure, resume_session, resume_task
from quantagent.sessions import append_message, create_session
from quantagent.task_state import FAILED, add_task


class ResumeTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent resume ")

    def test_resume_last_failure_and_task(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = add_task(project, "broken", status=FAILED)

            latest = resume_last_failure(project)
            exact = resume_task(project, task.id)

            self.assertEqual(latest.kind, "last_failure")
            self.assertIn(task.id, latest.body)
            self.assertEqual(exact.kind, "task")

    def test_resume_session_returns_latest(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "latest")

            bundle = resume_session(project)

            self.assertIn(session.session_id, bundle.body)
            self.assertIn("mako session --show", bundle.command)

    def test_resume_snapshot_persists_compacted_session(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "long task")
            for index in range(12):
                append_message(project, session.session_id, "user", f"step {index} " + "detail " * 20)

            snapshot = create_resume_snapshot(project, "session", source_id=session.session_id, target_summary_chars=500)
            loaded = load_resume_snapshot(project, snapshot.snapshot_id)
            rendered = render_resume_snapshot(loaded)

            self.assertEqual(loaded.source_id, session.session_id)
            self.assertTrue(loaded.compacted_messages)
            self.assertIn("saved_estimated_tokens", loaded.metrics)
            self.assertIn(snapshot.snapshot_id, rendered)
            self.assertEqual(list_resume_snapshots(project)[0].snapshot_id, snapshot.snapshot_id)

    def test_resume_snapshot_for_task_records_artifacts(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = add_task(project, "broken", status=FAILED)
            task.evidence.append("report.md")
            from quantagent.task_state import save_tasks

            save_tasks(project, [task])

            snapshot = create_resume_snapshot(project, "task", source_id=task.id)

            self.assertEqual(snapshot.kind, "task")
            self.assertEqual(snapshot.artifacts, ["report.md"])
            self.assertIn(task.id, snapshot.command)


if __name__ == "__main__":
    unittest.main()
