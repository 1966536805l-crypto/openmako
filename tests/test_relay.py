from __future__ import annotations

import contextlib
import io
import json
import multiprocessing as mp
import tempfile
import threading
import time
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.relay import (
    MESSAGE_DONE,
    MESSAGE_FAILED,
    MESSAGE_RUNNING,
    MESSAGE_UNREAD,
    append_jsonl,
    detect_stale_heartbeat,
    get_active_lease,
    get_message_state,
    list_events,
    mark_done,
    mark_failed,
    parse_evidence_packet,
    reclaim_expired,
    read_inbox,
    read_jsonl,
    relay_status,
    run_demo,
    run_stress,
    send_message,
    update_heartbeat,
    watch_loop,
    write_json_atomic,
    poll_once,
)


def _mp_poll_worker(project: str, queue: mp.Queue) -> None:
    from quantagent.relay import poll_once

    try:
        message = poll_once(project, "executor", requester_agent="executor", lease_seconds=30)
        queue.put(message.to_dict() if message else None)
    except Exception as exc:
        queue.put({"error": f"{type(exc).__name__}:{exc}"})


def _mp_done_worker(project: str, message_id: str, lease_id: str, queue: mp.Queue) -> None:
    from quantagent.relay import mark_done

    try:
        message = mark_done(project, "executor", message_id, {"summary": "mp done"}, lease_id=lease_id)
        queue.put({"ok": True, "message": message.to_dict()})
    except Exception as exc:
        queue.put({"ok": False, "error": f"{type(exc).__name__}:{exc}"})


class RelayTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent relay ")

    def handoff(self, task_id: str = "relay-001") -> dict[str, object]:
        return {
            "task_id": task_id,
            "lines": ["fix only the listed file"],
            "allowed_files": ["quantagent/relay.py"],
            "forbidden_files": ["long_context.md"],
            "success_criteria": ["tests pass"],
        }

    def evidence_packet(self, task_id: str = "relay-001") -> dict[str, object]:
        return {
            "task_id": task_id,
            "facts": [{"id": "F1", "text": "test failed", "source": "tests/output.log"}],
            "inferences": [{"id": "I1", "fact_ids": ["F1"], "text": "fix source", "confidence": "high"}],
            "actions": [{"id": "A1", "inference_ids": ["I1"], "text": "edit source"}],
            "blocked": [],
        }

    def run_relay_cli(self, project: str, *args: str) -> tuple[int, dict[str, object] | list[object], str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = main(["--no-trust-prompt", "relay", "--project", project, *args, "--json"])
        text = stdout.getvalue()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"relay CLI must emit JSON, got: {text!r}") from exc
        return rc, payload, text

    def test_evidence_packet_requires_fact_source(self) -> None:
        payload = self.evidence_packet()
        payload["facts"] = [{"id": "F1", "text": "missing source"}]

        with self.assertRaises(ValueError):
            parse_evidence_packet(payload)

    def test_action_without_inference_binding_cannot_send_to_executor(self) -> None:
        with self.make_project() as tmp:
            payload = self.evidence_packet()
            payload["actions"] = [{"id": "A1", "text": "edit source"}]

            with self.assertRaises(ValueError):
                send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="TASK", task_id="relay-001", payload=payload)

    def test_handoff_over_ten_lines_fails(self) -> None:
        with self.make_project() as tmp:
            payload = self.handoff()
            payload["lines"] = [f"line {index}" for index in range(11)]

            with self.assertRaises(ValueError):
                send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=payload)

    def test_duplicate_message_id_fails(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-fixed")

            with self.assertRaises(ValueError):
                send_message(tmp, to_agent="reviewer", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-fixed")

    def test_agent_cannot_read_another_agent_inbox(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="reviewer", from_agent="executor", message_type="REVIEW_REQUEST", task_id="relay-001", payload=self.blind_review_payload())

            with self.assertRaises(PermissionError):
                read_inbox(tmp, "reviewer", requester_agent="executor")
            with self.assertRaises(PermissionError):
                read_inbox(tmp, "reviewer")

    def test_unread_running_done_state_flow_uses_events_not_inbox_mutation(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-done")
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_UNREAD)

            claimed = poll_once(tmp, "executor", requester_agent="executor")
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_RUNNING)

            mark_done(tmp, "executor", message.id, {"summary": "done"}, lease_id=claimed.lease_id)
            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_DONE)
            inbox = read_inbox(tmp, "executor", requester_agent="executor")
            self.assertEqual(inbox[0].status, MESSAGE_UNREAD)

    def test_unread_running_failed_state_flow_writes_outbox_error(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-fail")
            claimed = poll_once(tmp, "executor", requester_agent="executor")
            assert claimed is not None

            mark_failed(tmp, "executor", message.id, {"summary": "boom"}, lease_id=claimed.lease_id)

            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_FAILED)
            outbox = read_jsonl(Path(tmp) / ".quantagent" / "agents" / "executor" / "outbox.jsonl")
            self.assertEqual(len(outbox), 1)
            self.assertEqual(outbox[0]["status"], MESSAGE_FAILED)
            self.assertEqual(outbox[0]["output"]["result"]["error"], "boom")

    def test_two_polls_do_not_claim_same_message_twice(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-once")

            first = poll_once(tmp, "executor", requester_agent="executor")
            second = poll_once(tmp, "executor", requester_agent="executor")

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            running_events = [row for row in list_events(tmp, message_id="msg-once") if row["event_type"] == "MESSAGE_RUNNING"]
            self.assertEqual(len(running_events), 1)

    def test_concurrent_mark_running_and_done_do_not_duplicate_events(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-race")
            running_errors: list[str] = []

            def claim() -> None:
                try:
                    from quantagent.relay import mark_running

                    mark_running(tmp, "executor", message.id)
                except Exception as exc:
                    running_errors.append(type(exc).__name__)

            threads = [threading.Thread(target=claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            running_events = [row for row in list_events(tmp, message_id=message.id) if row["event_type"] == "MESSAGE_RUNNING"]
            self.assertEqual(len(running_events), 1)
            self.assertEqual(len(running_errors), 1)
            lease = get_active_lease(tmp, message.id)
            self.assertIsNotNone(lease)
            assert lease is not None

            done_errors: list[str] = []

            def finish() -> None:
                try:
                    mark_done(tmp, "executor", message.id, {"summary": "done"}, lease_id=lease.lease_id)
                except Exception as exc:
                    done_errors.append(type(exc).__name__)

            threads = [threading.Thread(target=finish) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            done_events = [row for row in list_events(tmp, message_id=message.id) if row["event_type"] == "MESSAGE_DONE"]
            outbox = read_jsonl(Path(tmp) / ".quantagent" / "agents" / "executor" / "outbox.jsonl")
            self.assertEqual(len(done_events), 1)
            self.assertEqual(len(outbox), 1)
            self.assertEqual(len(done_errors), 1)

    def test_heartbeat_stale_can_be_detected(self) -> None:
        with self.make_project() as tmp:
            update_heartbeat(tmp, "executor", status="idle")

            heartbeat = detect_stale_heartbeat(tmp, "executor", stale_after_seconds=-1)

            self.assertEqual(heartbeat.status, "stale")

    def test_watch_max_iterations_exits(self) -> None:
        with self.make_project() as tmp:
            claimed = watch_loop(tmp, "executor", interval=0, max_iterations=2, requester_agent="executor")

            self.assertEqual(claimed, [])

    def test_shared_chat_references_and_paths_are_forbidden(self) -> None:
        with self.make_project() as tmp:
            payload = self.handoff()
            payload["lines"] = ["Use Shared_Chat.md for coordination"]

            with self.assertRaises(ValueError):
                send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=payload)
            with self.assertRaises(ValueError):
                append_jsonl(Path(tmp) / ".quantagent" / "relay" / "SHARED_CHAT.MD", {"x": 1})
            with self.assertRaises(ValueError):
                write_json_atomic(Path(tmp) / ".quantagent" / "relay" / "Shared_Chat.md", {"x": 1})

    def test_blind_review_author_explanation_is_forbidden(self) -> None:
        with self.make_project() as tmp:
            payload = self.blind_review_payload()
            payload["author_explanation"] = "I did this because..."

            with self.assertRaises(ValueError):
                send_message(tmp, to_agent="reviewer", from_agent="executor", message_type="REVIEW_REQUEST", task_id="relay-001", payload=payload)

    def test_two_processes_poll_same_message_only_one_succeeds(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-mp-poll")
            queue: mp.Queue = mp.Queue()
            processes = [mp.Process(target=_mp_poll_worker, args=(tmp, queue)) for _ in range(2)]

            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)

            results = [queue.get(timeout=2) for _ in processes]
            claimed = [item for item in results if isinstance(item, dict) and item.get("id") == "msg-mp-poll"]
            self.assertEqual(len(claimed), 1)
            self.assertEqual(get_message_state(tmp, "msg-mp-poll"), MESSAGE_RUNNING)

    def test_poll_and_done_concurrency_does_not_duplicate_or_regress_state(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-poll-done")
            claimed = poll_once(tmp, "executor", requester_agent="executor", lease_seconds=30)
            assert claimed is not None
            queue: mp.Queue = mp.Queue()
            processes = [
                mp.Process(target=_mp_done_worker, args=(tmp, message.id, claimed.lease_id, queue)),
                mp.Process(target=_mp_poll_worker, args=(tmp, queue)),
            ]

            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)

            self.assertEqual(get_message_state(tmp, message.id), MESSAGE_DONE)
            running_events = [row for row in list_events(tmp, message_id=message.id) if row["event_type"] == "MESSAGE_RUNNING"]
            done_events = [row for row in list_events(tmp, message_id=message.id) if row["event_type"] == "MESSAGE_DONE"]
            self.assertEqual(len(running_events), 1)
            self.assertEqual(len(done_events), 1)

    def test_lease_expired_and_missing_heartbeat_can_reclaim(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-reclaim")
            claimed = poll_once(tmp, "executor", requester_agent="executor", lease_seconds=0.01)
            assert claimed is not None
            (Path(tmp) / ".quantagent" / "agents" / "executor" / "heartbeat.json").unlink()
            time.sleep(0.02)

            reclaimed = reclaim_expired(tmp, "executor", lease_seconds=30, stale_seconds=60)

            self.assertEqual(len(reclaimed), 1)
            self.assertEqual(reclaimed[0].id, "msg-reclaim")
            self.assertNotEqual(reclaimed[0].lease_id, claimed.lease_id)

    def test_missing_heartbeat_but_unexpired_lease_cannot_reclaim(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-no-reclaim")
            poll_once(tmp, "executor", requester_agent="executor", lease_seconds=30)
            (Path(tmp) / ".quantagent" / "agents" / "executor" / "heartbeat.json").unlink()

            reclaimed = reclaim_expired(tmp, "executor", lease_seconds=30, stale_seconds=60)

            self.assertEqual(reclaimed, [])

    def test_running_lease_expired_but_nonstale_agent_cannot_reclaim(self) -> None:
        with self.make_project() as tmp:
            send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-agent-live")
            poll_once(tmp, "executor", requester_agent="executor", lease_seconds=0.01)
            update_heartbeat(tmp, "executor", status="running", current_task_id="relay-001")
            time.sleep(0.02)

            reclaimed = reclaim_expired(tmp, "executor", lease_seconds=30, stale_seconds=60)

            self.assertEqual(reclaimed, [])

    def test_old_expired_and_completed_leases_are_rejected(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-lease-check")
            first = poll_once(tmp, "executor", requester_agent="executor", lease_seconds=0.01)
            assert first is not None
            time.sleep(0.02)
            with self.assertRaises(ValueError):
                mark_done(tmp, "executor", message.id, {"summary": "expired"}, lease_id=first.lease_id)

            (Path(tmp) / ".quantagent" / "agents" / "executor" / "heartbeat.json").unlink()
            second = reclaim_expired(tmp, "executor", lease_seconds=30, stale_seconds=60)[0]
            with self.assertRaises(ValueError):
                mark_done(tmp, "executor", message.id, {"summary": "old"}, lease_id=first.lease_id)

            mark_done(tmp, "executor", message.id, {"summary": "done"}, lease_id=second.lease_id)
            with self.assertRaises(ValueError):
                mark_failed(tmp, "executor", message.id, {"summary": "late fail"}, lease_id=second.lease_id)
            self.assertEqual(reclaim_expired(tmp, "executor", lease_seconds=30, stale_seconds=60), [])

    def test_status_is_derived_from_events_not_inbox_status_snapshot(self) -> None:
        with self.make_project() as tmp:
            message = send_message(tmp, to_agent="executor", from_agent="diagnoser", message_type="HANDOFF", task_id="relay-001", payload=self.handoff(), message_id="msg-status")
            inbox_path = Path(tmp) / ".quantagent" / "agents" / "executor" / "inbox.jsonl"
            row = read_jsonl(inbox_path)[0]
            row["status"] = MESSAGE_FAILED
            inbox_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            status = relay_status(tmp, task_id="relay-001")

            self.assertEqual(status["messages"][0]["id"], message.id)
            self.assertEqual(status["messages"][0]["state"], MESSAGE_UNREAD)

    def test_demo_and_stress_helpers_run_without_real_ai(self) -> None:
        with self.make_project() as tmp:
            demo = run_demo(tmp)
            stress = run_stress(tmp, agents=["executor"], workers=2, messages=5, lease_seconds=30)

            self.assertTrue(demo["ok"])
            self.assertEqual(demo["decision"]["status"], "MERGE")
            self.assertTrue(stress["ok"])
            self.assertEqual(stress["done"], 5)
            self.assertFalse(stress["duplicate_done"])

    def test_relay_cli_smoke_card_send_poll_done_events_and_watch(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            handoff_path = project / "handoff.json"
            done_path = project / "done.json"
            handoff_path.write_text(json.dumps(self.handoff()), encoding="utf-8")
            done_path.write_text(json.dumps({"summary": "done"}), encoding="utf-8")

            rc, card, _ = self.run_relay_cli(tmp, "card", "fix relay", "--task-id", "relay-cli")
            self.assertEqual(rc, 0)
            assert isinstance(card, dict)
            self.assertEqual(card["id"], "relay-cli")

            rc, sent, _ = self.run_relay_cli(tmp, "send", "--to", "executor", "--from-agent", "diagnoser", "--type", "HANDOFF", "--task", "relay-001", "--message-id", "msg-cli", "--input", str(handoff_path))
            self.assertEqual(rc, 0)
            assert isinstance(sent, dict)
            self.assertEqual(sent["id"], "msg-cli")

            rc, inbox, _ = self.run_relay_cli(tmp, "inbox", "--agent", "executor")
            self.assertEqual(rc, 0)
            assert isinstance(inbox, list)
            self.assertEqual(inbox[0]["state"], MESSAGE_UNREAD)

            rc, polled, _ = self.run_relay_cli(tmp, "poll", "--agent", "executor")
            self.assertEqual(rc, 0)
            assert isinstance(polled, dict)
            self.assertEqual(polled["status"], MESSAGE_RUNNING)
            message_payload = polled["message"]
            assert isinstance(message_payload, dict)
            lease_id = str(message_payload["lease_id"])

            rc, done, _ = self.run_relay_cli(tmp, "done", "--agent", "executor", "--message", "msg-cli", "--lease", lease_id, "--output", str(done_path))
            self.assertEqual(rc, 0)
            assert isinstance(done, dict)
            self.assertEqual(done["status"], MESSAGE_DONE)

            rc, heartbeat, _ = self.run_relay_cli(tmp, "heartbeat", "--agent", "executor", "--status", "idle")
            self.assertEqual(rc, 0)
            assert isinstance(heartbeat, dict)
            self.assertEqual(heartbeat["status"], "idle")

            rc, watched, _ = self.run_relay_cli(tmp, "watch", "--agent", "executor", "--interval", "0", "--max-iterations", "1")
            self.assertEqual(rc, 0)
            assert isinstance(watched, dict)
            self.assertEqual(watched["count"], 0)

            rc, events, _ = self.run_relay_cli(tmp, "events", "--task", "relay-001")
            self.assertEqual(rc, 0)
            assert isinstance(events, list)
            self.assertGreaterEqual(len(events), 3)

            rc, status, _ = self.run_relay_cli(tmp, "status", "--task", "relay-001")
            self.assertEqual(rc, 0)
            assert isinstance(status, dict)
            self.assertEqual(status["messages"][0]["state"], MESSAGE_DONE)

            rc, demo, _ = self.run_relay_cli(tmp, "demo")
            self.assertEqual(rc, 0)
            assert isinstance(demo, dict)
            self.assertTrue(demo["ok"])

            rc, stress, _ = self.run_relay_cli(tmp, "stress", "--agents", "executor", "--workers", "2", "--messages", "3")
            self.assertEqual(rc, 0)
            assert isinstance(stress, dict)
            self.assertTrue(stress["ok"])

    def blind_review_payload(self) -> dict[str, object]:
        return {
            "task_id": "relay-001",
            "task_card": {"goal": "fix relay"},
            "diff_summary": "changed relay.py",
            "test_result": "tests pass",
            "changed_files": ["quantagent/relay.py"],
        }


if __name__ == "__main__":
    unittest.main()
