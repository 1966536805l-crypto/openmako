from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from quantagent.cli import main
from quantagent.query_runtime import QueryRuntime
from quantagent.runtime_ledger import build_runtime_ledger_snapshot, render_runtime_ledger, search_runtime_ledger
from quantagent.runtime_store import (
    commit_budget_reservation,
    ensure_runtime_store,
    expire_budget_reservations,
    get_budget_reservation,
    inspect_budget_reservations,
    get_task_run,
    list_budget_reservations,
    list_compact_events,
    list_runtime_sessions,
    list_task_runs,
    load_runtime_query_events,
    record_model_call,
    release_budget_reservation,
    reserve_model_budget,
    runtime_db_path,
    search_messages,
)
from quantagent.sessions import append_message, compact_session, create_session
from quantagent.task_runtime import refresh_runtime_tasks, start_shell_task
from quantagent.task_state import BLOCKED, PASSED, add_task, update_task


class RuntimeStoreTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent runtime store ")

    def test_manual_tasks_are_mirrored_to_sqlite(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = add_task(project, "Audit evidence", detail="needs hash")
            updated = update_task(project, task.id, status=BLOCKED, note="waiting", evidence="audit.json")

            record = get_task_run(project, task.id)
            records = list_task_runs(project)

            self.assertTrue(runtime_db_path(project).exists())
            self.assertIsNotNone(record)
            self.assertEqual(record.status, BLOCKED)
            self.assertEqual(record.terminal_outcome, "blocked")
            self.assertEqual(record.progress_summary, "needs hash")
            self.assertEqual(records[0].task_id, updated.id)

    def test_runtime_shell_task_updates_sqlite_terminal_status(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = start_shell_task(
                project,
                [sys.executable, "-c", "print('stored task')"],
                title="stored",
                allow_risky=True,
            )

            for _ in range(30):
                refresh_runtime_tasks(project)
                record = get_task_run(project, task.id)
                if record and record.status == PASSED:
                    break
                time.sleep(0.05)

            record = get_task_run(project, task.id)

            self.assertIsNotNone(record)
            self.assertEqual(record.status, PASSED)
            self.assertEqual(record.delivery_status, "ready")
            self.assertEqual(record.terminal_outcome, "success")

    def test_sessions_and_messages_are_mirrored_to_sqlite(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "P4 review")
            append_message(project, session.session_id, "user", "first P4 evidence question")
            append_message(project, session.session_id, "assistant", "answer with hash")

            sessions = list_runtime_sessions(project)
            hits = search_messages(project, "evidence")

            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].title, "P4 review")
            self.assertEqual(sessions[0].message_count, 2)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["role"], "user")

    def test_schema_contains_openclaw_inspired_task_indexes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            add_task(project, "schema")
            conn = sqlite3.connect(runtime_db_path(project))
            try:
                names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'task_runs'"
                    )
                }
            finally:
                conn.close()

            self.assertIn("idx_task_runs_status", names)
            self.assertIn("idx_task_runs_child_session_key", names)
            self.assertIn("idx_task_runs_parent_flow_id", names)

    def test_query_runtime_events_are_mirrored_to_sqlite(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            runtime = QueryRuntime(project, query_id="qa-store")
            runtime.start("demo", mode="test")
            runtime.pre_tool("status", step=1)
            runtime.post_tool("status", step=1, ok=True, summary="ok")
            runtime.stop("done", ok=True)

            rows = load_runtime_query_events(project, query_id="qa-store")

            self.assertEqual([row["kind"] for row in rows], ["query_start", "pre_tool", "post_tool", "stop"])
            self.assertEqual(rows[-1]["ok"], 1)

    def test_runtime_ledger_unifies_sessions_tasks_and_search_cli(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "ledger")
            append_message(project, session.session_id, "user", "ledger evidence search text")
            record_model_call(project, model="gpt-test", provider="fake", ok=True, query_id="qa-ledger", usage={"prompt_tokens": 4, "completion_tokens": 2})
            compact_session(project, session.session_id, keep_last=1)
            task = add_task(project, "ledger task")
            update_task(project, task.id, status=PASSED, note="done")

            snapshot = build_runtime_ledger_snapshot(project, limit=10)
            search = search_runtime_ledger(project, "evidence", limit=10)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "runtime", "--project", tmp, "status", "--limit", "10"])

            self.assertEqual(rc, 0)
            self.assertIn("# Runtime Ledger", stdout.getvalue())
            self.assertIn("ledger task", render_runtime_ledger(snapshot))
            self.assertIn("## Model Calls", render_runtime_ledger(snapshot))
            self.assertIn("## Compact Events", render_runtime_ledger(snapshot))
            self.assertEqual(snapshot.counts["sessions"], 1)
            self.assertEqual(snapshot.counts["task_runs"], 1)
            self.assertEqual(snapshot.counts["model_calls"], 1)
            self.assertEqual(snapshot.counts["compact_events"], 0)
            self.assertEqual(len(search["messages"]), 1)

    def test_session_compact_records_compact_event(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "compact ledger")
            append_message(project, session.session_id, "user", "one")
            append_message(project, session.session_id, "assistant", "two")
            append_message(project, session.session_id, "user", "three")

            compacted = compact_session(project, session.session_id, keep_last=1)
            events = list_compact_events(project, session_id=session.session_id)

            self.assertEqual(len(compacted.messages), 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].mode, "session")
            self.assertEqual(events[0].reason, "manual_session_compact")
            self.assertTrue(events[0].applied)
            self.assertGreater(events[0].original_estimated_tokens, 0)

    def test_budget_reservation_is_atomic_under_concurrency(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            ensure_runtime_store(project)
            barrier = threading.Barrier(8)

            def reserve(index: int) -> str:
                barrier.wait()
                decision = reserve_model_budget(
                    project,
                    session_id="sess-budget",
                    query_id=f"qa-budget-{index}",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=1,
                )
                return str(decision["status"])

            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"}, clear=False):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    statuses = list(pool.map(reserve, range(8)))

            reservations = list_budget_reservations(project, session_id="sess-budget")

        self.assertEqual(statuses.count("reserved"), 1)
        self.assertEqual(statuses.count("blocked"), 7)
        self.assertEqual(len([item for item in reservations if item.status == "active"]), 1)

    def test_budget_reservation_commit_is_idempotent_under_concurrency(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                decision = reserve_model_budget(
                    project,
                    session_id="sess-idem",
                    query_id="qa-idem",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=2,
                )
                reservation_id = str(decision["reservation_id"])
                barrier = threading.Barrier(8)

                def commit(_index: int) -> bool:
                    barrier.wait()
                    return commit_budget_reservation(project, reservation_id, actual_tokens=3, actual_cost_usd=0.01)

                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(commit, range(8)))

                reservation = get_budget_reservation(project, reservation_id)

        self.assertEqual(results, [True] * 8)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.status, "committed")
        self.assertEqual(reservation.actual_tokens, 3)
        self.assertEqual(reservation.actual_cost_usd, 0.01)
        self.assertIsNone(reservation.model_call_id)

    def test_budget_reservation_release_after_commit_is_noop(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                decision = reserve_model_budget(
                    project,
                    session_id="sess-commit",
                    query_id="qa-commit",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=2,
                )
                reservation_id = str(decision["reservation_id"])
                committed = commit_budget_reservation(project, reservation_id, actual_tokens=5, actual_cost_usd=0.02)
                released = release_budget_reservation(project, reservation_id, reason="late_release")
                reservation = get_budget_reservation(project, reservation_id)

        self.assertTrue(committed)
        self.assertFalse(released)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.status, "committed")
        self.assertEqual(reservation.actual_tokens, 5)
        self.assertEqual(reservation.actual_cost_usd, 0.02)
        self.assertIsNone(reservation.model_call_id)
        self.assertEqual(reservation.release_reason, "")

    def test_expired_budget_reservation_does_not_block_new_request(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"}, clear=False):
                first = reserve_model_budget(
                    project,
                    session_id="sess-expire",
                    query_id="qa-expire-1",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=1,
                    ttl_seconds=1,
                )
                first_record = get_budget_reservation(project, str(first["reservation_id"]))
                self.assertIsNotNone(first_record)
                expired = expire_budget_reservations(project, now_ms=first_record.expires_at + 1)
                second = reserve_model_budget(
                    project,
                    session_id="sess-expire",
                    query_id="qa-expire-2",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=1,
                )
                reservations = list_budget_reservations(project, session_id="sess-expire")

        self.assertEqual(first["status"], "reserved")
        self.assertEqual(expired, 1)
        self.assertEqual(second["status"], "reserved")
        self.assertEqual(len([item for item in reservations if item.status == "expired"]), 1)
        self.assertEqual(len([item for item in reservations if item.status == "active"]), 1)
        self.assertEqual([item for item in reservations if item.status == "expired"][0].release_reason, "ttl_expired")

    def test_runtime_ledger_renders_budget_reservation_lifecycle(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                decision = reserve_model_budget(
                    project,
                    session_id="sess-ledger-budget",
                    query_id="qa-ledger-budget",
                    task_id="task-budget",
                    agent_id="agent-budget",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=8,
                    estimated_cost_usd=0.03,
                )
                model_call_id = record_model_call(
                    project,
                    model="gpt-test",
                    provider="fake",
                    ok=True,
                    query_id="qa-ledger-budget",
                    session_id="sess-ledger-budget",
                    usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                )
                commit_budget_reservation(project, str(decision["reservation_id"]), actual_tokens=7, actual_cost_usd=0.02, model_call_id=model_call_id)
                snapshot = build_runtime_ledger_snapshot(project, limit=10)
                rendered = render_runtime_ledger(snapshot)

        self.assertIn("## Budget Reservations", rendered)
        self.assertIn("summary:", rendered)
        self.assertIn("query=qa-ledger-budget", rendered)
        self.assertIn("task=task-budget", rendered)
        self.assertIn("agent=agent-budget", rendered)
        self.assertIn("actual_tokens=7", rendered)
        self.assertIn(f"model_call={model_call_id}", rendered)

    def test_budget_reservation_inspector_reports_stale_without_writing(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                decision = reserve_model_budget(
                    project,
                    session_id="sess-stale",
                    query_id="qa-stale",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=1,
                )
                reservation = get_budget_reservation(project, str(decision["reservation_id"]))
                self.assertIsNotNone(reservation)
                health = inspect_budget_reservations(project, now_ms=reservation.updated_at + 10_000, stale_ms=1)
                after = get_budget_reservation(project, str(decision["reservation_id"]))

        self.assertEqual(health["counts"]["stale_suspect"], 1)
        self.assertIn(str(decision["reservation_id"]), health["stale_suspect_ids"])
        self.assertEqual(after.status, "active")


if __name__ == "__main__":
    unittest.main()
