from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.sessions import load_session
from quantagent.subagents import (
    create_subagent_review_bundle,
    get_subagent,
    load_subagent_review_bundles,
    load_subagents,
    refresh_subagents,
    render_subagent_review_bundle,
    render_subagents,
    start_subagent,
    stop_subagent,
)
from quantagent.task_state import ABORTED, PASSED, RUNNING, ResearchTask, load_tasks


class SubagentLifecycleTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent subagent ")

    def fake_child(self, status: str = RUNNING, task_id: str = "qrt-0001") -> ResearchTask:
        return ResearchTask(
            id=task_id,
            title="child",
            status=status,
            kind="local_agent",
            detail="background local agent",
            evidence=["/tmp/result.json"],
        )

    def test_start_subagent_persists_parent_child_and_session(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "inspect project", context_mode="isolated", include_validation=False, agent_profile="audit")

            loaded = load_subagents(project)
            tasks = load_tasks(project)
            session = load_session(project, record.child_session_id)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].subagent_id, record.subagent_id)
            self.assertEqual(record.context_mode, "isolated")
            self.assertEqual(record.agent_profile, "audit")
            self.assertEqual(record.child_task_id, "qrt-0001")
            self.assertTrue(record.child_session_id)
            self.assertTrue(Path(record.context_path).exists())
            self.assertIn("Parent transcript and session messages are intentionally withheld", Path(record.context_path).read_text(encoding="utf-8"))
            self.assertEqual(session.messages[0].meta["agent_profile"], "audit")
            self.assertEqual(tasks[0].status, RUNNING)

    def test_fork_context_includes_latest_session_and_project_context(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            from quantagent.sessions import append_message, create_session

            session = create_session(project, "parent work")
            append_message(project, session.session_id, "user", "parent clue about approval bug")
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "inspect approval bug", context_mode="fork", include_validation=False)

            text = Path(record.context_path).read_text(encoding="utf-8")

            self.assertIn("Forked Session", text)
            self.assertIn("parent clue about approval bug", text)
            self.assertIn("Forked Project Context", text)

    def test_start_subagent_can_bind_isolated_worktree(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()) as start:
                record = start_subagent(project, "repair safely", include_validation=False, isolate_worktree=True)

            kwargs = start.call_args.kwargs
            self.assertTrue(record.isolation_worktree_id)
            self.assertTrue(Path(record.isolation_workspace_path).exists())
            self.assertEqual(kwargs["runtime_project"], record.isolation_workspace_path)
            self.assertIn("isolation_worktree_id", Path(record.context_path).read_text(encoding="utf-8"))

    def test_refresh_updates_terminal_outcome_and_parent_task(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "finish project", include_validation=False)

            finished = self.fake_child(PASSED)
            with patch("quantagent.subagents.refresh_runtime_tasks", return_value=[finished]), patch(
                "quantagent.subagents.read_task_output", return_value="Agent v2 completed\nsummary ok"
            ):
                records = refresh_subagents(project)

            self.assertEqual(records[0].status, PASSED)
            self.assertEqual(records[0].terminal_outcome, "ok")
            self.assertIn("Agent v2 completed", records[0].progress_summary)
            self.assertEqual(load_tasks(project)[0].status, PASSED)
            self.assertEqual(get_subagent(project, record.subagent_id).status, PASSED)

    def test_refresh_isolated_subagent_creates_review(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "finish project", include_validation=False, isolate_worktree=True)
            (Path(record.isolation_workspace_path) / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

            finished = self.fake_child(PASSED)
            with patch("quantagent.subagents.refresh_runtime_tasks", return_value=[finished]), patch(
                "quantagent.subagents.read_task_output", return_value="Agent v2 completed\nsummary ok"
            ):
                records = refresh_subagents(project)

            self.assertTrue(records[0].review_id)
            self.assertTrue(any(records[0].review_id in item for item in records[0].artifacts))

    def test_create_review_bundle_collects_completed_isolated_reviews_without_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project / "b.py").write_text("VALUE = 10\n", encoding="utf-8")
            children = [
                self.fake_child(task_id="qrt-0001"),
                self.fake_child(task_id="qrt-0002"),
            ]
            with patch("quantagent.subagents.start_agent_task", side_effect=children):
                first = start_subagent(project, "repair a", parent_task_id="qa-parent", include_validation=False, isolate_worktree=True)
                second = start_subagent(project, "repair b", parent_task_id="qa-parent", include_validation=False, isolate_worktree=True)

            (Path(first.isolation_workspace_path) / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
            (Path(second.isolation_workspace_path) / "b.py").write_text("VALUE = 20\n", encoding="utf-8")
            finished = [
                self.fake_child(PASSED, task_id="qrt-0001"),
                self.fake_child(PASSED, task_id="qrt-0002"),
            ]
            with patch("quantagent.subagents.refresh_runtime_tasks", return_value=finished), patch(
                "quantagent.subagents.read_task_output", return_value="Agent v2 completed\nsummary ok"
            ):
                refreshed = refresh_subagents(project)
                bundle = create_subagent_review_bundle(project, parent_task_id="qa-parent")

            review_ids = [record.review_id for record in refreshed]
            self.assertEqual(bundle.parent_task_id, "qa-parent")
            self.assertEqual(bundle.subagent_ids, [first.subagent_id, second.subagent_id])
            self.assertEqual(bundle.review_ids, review_ids)
            self.assertEqual(bundle.changed_paths, ["a.py", "b.py"])
            self.assertEqual(bundle.terminal_outcomes, {first.subagent_id: "ok", second.subagent_id: "ok"})
            self.assertEqual(len(load_subagent_review_bundles(project)), 1)
            self.assertIn(review_ids[0], render_subagent_review_bundle(bundle))
            self.assertEqual((project / "a.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertEqual((project / "b.py").read_text(encoding="utf-8"), "VALUE = 10\n")

    def test_review_bundle_can_be_created_from_explicit_subagent_ids(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "repair a", include_validation=False, isolate_worktree=True)
            (Path(record.isolation_workspace_path) / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

            with patch("quantagent.subagents.refresh_runtime_tasks", return_value=[self.fake_child(PASSED)]), patch(
                "quantagent.subagents.read_task_output", return_value="Agent v2 completed\nsummary ok"
            ):
                refresh_subagents(project)
                bundle = create_subagent_review_bundle(project, subagent_ids=[record.subagent_id])

            self.assertEqual(bundle.subagent_ids, [record.subagent_id])
            self.assertEqual(bundle.changed_paths, ["a.py"])

    def test_stop_subagent_marks_record_aborted(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch("quantagent.subagents.start_agent_task", return_value=self.fake_child()):
                record = start_subagent(project, "long task", include_validation=False)
            with patch("quantagent.subagents.stop_runtime_task", return_value=self.fake_child(ABORTED)):
                stopped = stop_subagent(project, record.subagent_id)

            self.assertEqual(stopped.status, ABORTED)
            self.assertEqual(load_subagents(project)[0].terminal_outcome, ABORTED)

    def test_render_empty_and_records(self) -> None:
        self.assertIn("No subagents", render_subagents([]))
        self.assertIn("sub-1", render_subagents([self._record("sub-1")]))

    def test_invalid_context_mode_rejected(self) -> None:
        with self.make_project() as tmp:
            with self.assertRaises(ValueError):
                start_subagent(Path(tmp), "task", context_mode="shared")

    def _record(self, subagent_id: str):
        from quantagent.subagents import SubagentRecord

        return SubagentRecord(subagent_id, "qa-0001", "qrt-0001", "session-1", "task")


if __name__ == "__main__":
    unittest.main()
