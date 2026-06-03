from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from quantagent import runtime_store


REQUIRED_QUEUE_API = (
    "enqueue_runtime_queue_item",
    "claim_runtime_queue_item",
    "heartbeat_runtime_queue_item",
    "complete_runtime_queue_item",
    "fail_runtime_queue_item",
    "pause_runtime_queue_item",
    "block_runtime_queue_item",
    "stop_runtime_queue_item",
    "list_runtime_queue_items",
)

RUNTIME_QUEUE_STATUSES = {
    "queued",
    "running",
    "paused",
    "failed",
    "done",
    "stopped",
    "blocked",
    "lost",
}


def _api(name: str) -> Any:
    func = getattr(runtime_store, name, None)
    if func is None:
        raise AssertionError(f"quantagent.runtime_store must expose {name} for the Unified Runtime Queue MVP")
    return func


def _field(item: Any, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _item_id(item: Any) -> str:
    value = _field(item, "item_id", None)
    if value is None:
        value = _field(item, "id", None)
    if value is None:
        raise AssertionError(f"runtime queue item must expose item_id or id: {item!r}")
    return str(value)


def _status(item: Any) -> str:
    value = _field(item, "status", None)
    if value is None:
        raise AssertionError(f"runtime queue item must expose status: {item!r}")
    return str(value)


def _lease_owner(item: Any) -> str | None:
    value = _field(item, "lease_owner", None)
    return str(value) if value is not None else None


def _lease_expires_at(item: Any) -> int | None:
    value = _field(item, "lease_expires_at", None)
    return int(value) if value is not None else None


class RuntimeQueueContractTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent runtime queue ")

    def require_queue_api(self) -> None:
        missing = [name for name in REQUIRED_QUEUE_API if getattr(runtime_store, name, None) is None]
        if missing:
            self.skipTest(f"runtime queue behavior contract waits for missing API functions: {missing}")

    def enqueue(self, project: Path, item_id: str, **kwargs: Any) -> Any:
        return _api("enqueue_runtime_queue_item")(
            project,
            item_id=item_id,
            queue="runtime",
            task_kind="unit",
            payload={"goal": item_id},
            **kwargs,
        )

    def test_runtime_store_exposes_unified_runtime_queue_api(self) -> None:
        missing = [name for name in REQUIRED_QUEUE_API if getattr(runtime_store, name, None) is None]
        self.assertEqual(missing, [], f"missing runtime queue API functions: {missing}")

    def test_enqueue_lists_items_with_canonical_statuses_and_payload(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)

            item = self.enqueue(project, "rq-enqueue-1", priority=5)
            rows = _api("list_runtime_queue_items")(project, queue="runtime")

        self.assertEqual(_item_id(item), "rq-enqueue-1")
        self.assertEqual(_status(item), "queued")
        self.assertIn(_status(item), RUNTIME_QUEUE_STATUSES)
        self.assertEqual([_item_id(row) for row in rows], ["rq-enqueue-1"])
        self.assertEqual(_status(rows[0]), "queued")
        self.assertEqual(_field(rows[0], "payload", {}).get("goal"), "rq-enqueue-1")

    def test_claim_is_atomic_under_concurrency_and_sets_lease(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-atomic-1")
            barrier = threading.Barrier(8)

            def claim(index: int) -> Any:
                barrier.wait()
                return _api("claim_runtime_queue_item")(
                    project,
                    queue="runtime",
                    lease_owner=f"worker-{index}",
                    lease_seconds=60,
                    now_ms=1_000,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(pool.map(claim, range(8)))

            claimed = [item for item in claims if item is not None]
            rows = _api("list_runtime_queue_items")(project, queue="runtime")

        self.assertEqual(len(claimed), 1, f"exactly one worker may claim one queued item: {claims!r}")
        self.assertEqual(_status(claimed[0]), "running")
        self.assertIn(_lease_owner(claimed[0]), {f"worker-{index}" for index in range(8)})
        self.assertEqual(_lease_expires_at(claimed[0]), 61_000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(_status(rows[0]), "running")
        self.assertEqual(_lease_owner(rows[0]), _lease_owner(claimed[0]))

    def test_expired_running_lease_can_be_reclaimed_by_another_worker(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-lease-1")

            first = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-a",
                lease_seconds=1,
                now_ms=10_000,
            )
            still_locked = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-b",
                lease_seconds=1,
                now_ms=10_500,
            )
            reclaimed = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-b",
                lease_seconds=2,
                now_ms=11_001,
            )

        self.assertEqual(_status(first), "running")
        self.assertEqual(_lease_owner(first), "worker-a")
        self.assertIsNone(still_locked)
        self.assertEqual(_item_id(reclaimed), "rq-lease-1")
        self.assertEqual(_status(reclaimed), "running")
        self.assertEqual(_lease_owner(reclaimed), "worker-b")
        self.assertEqual(_lease_expires_at(reclaimed), 13_001)

    def test_terminal_and_owner_checked_state_transitions_are_rejected(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-transition-1")
            claimed = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-a",
                lease_seconds=60,
                now_ms=1_000,
            )

            with self.assertRaises(ValueError):
                _api("complete_runtime_queue_item")(project, "rq-transition-1", lease_owner="worker-b", result={"ok": True})

            failed = _api("fail_runtime_queue_item")(project, "rq-transition-1", lease_owner="worker-a", error="unit failure")

            with self.assertRaises(ValueError):
                _api("complete_runtime_queue_item")(project, "rq-transition-1", lease_owner="worker-a", result={"late": True})

            rows = _api("list_runtime_queue_items")(project, queue="runtime")

        self.assertEqual(_status(claimed), "running")
        self.assertEqual(_status(failed), "failed")
        self.assertEqual(_status(rows[0]), "failed")
        self.assertIn("unit failure", str(_field(rows[0], "error", "")))

    def test_complete_stop_fail_only_accept_running_items(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-illegal-1")

            with self.assertRaises(ValueError):
                _api("complete_runtime_queue_item")(project, "rq-illegal-1", lease_owner="worker-a", result={"ok": True})
            with self.assertRaises(ValueError):
                _api("fail_runtime_queue_item")(project, "rq-illegal-1", lease_owner="worker-a", error="not running")
            with self.assertRaises(ValueError):
                _api("heartbeat_runtime_queue_item")(project, "rq-illegal-1", lease_owner="worker-a", lease_seconds=60, now_ms=1_000)

            rows = _api("list_runtime_queue_items")(project, queue="runtime")

        self.assertEqual(_status(rows[0]), "queued")

    def test_paused_and_blocked_items_can_be_resumed(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-pause-1")

            _api("claim_runtime_queue_item")(project, queue="runtime", lease_owner="worker-a", lease_seconds=60)
            paused = _api("pause_runtime_queue_item")(project, "rq-pause-1", lease_owner="worker-a", reason="needs operator")
            resumed_paused = _api("resume_runtime_queue_item")(project, "rq-pause-1")

        with self.make_project() as tmp:
            project = Path(tmp)
            self.enqueue(project, "rq-block-1")

            _api("claim_runtime_queue_item")(project, queue="runtime", lease_owner="worker-b", lease_seconds=60)
            blocked = _api("block_runtime_queue_item")(project, "rq-block-1", lease_owner="worker-b", reason="policy block")
            resumed_blocked = _api("resume_runtime_queue_item")(project, "rq-block-1")

        self.assertEqual(_status(paused), "paused")
        self.assertEqual(_status(resumed_paused), "queued")
        self.assertEqual(_status(blocked), "blocked")
        self.assertEqual(_status(resumed_blocked), "queued")

    def test_stop_file_presence_moves_running_item_to_stopped(self) -> None:
        self.require_queue_api()
        with self.make_project() as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"
            self.enqueue(project, "rq-stop-1", stop_file=str(stop_file))
            claimed = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-a",
                lease_seconds=60,
                now_ms=1_000,
            )

            stop_file.write_text("stop requested\n", encoding="utf-8")
            stopped = _api("heartbeat_runtime_queue_item")(
                project,
                "rq-stop-1",
                lease_owner="worker-a",
                lease_seconds=60,
                now_ms=2_000,
            )
            second_claim = _api("claim_runtime_queue_item")(
                project,
                queue="runtime",
                lease_owner="worker-b",
                lease_seconds=60,
                now_ms=70_000,
            )
            rows = _api("list_runtime_queue_items")(project, queue="runtime")

        self.assertEqual(_status(claimed), "running")
        self.assertEqual(_status(stopped), "stopped")
        self.assertIsNone(second_claim)
        self.assertEqual(_status(rows[0]), "stopped")


if __name__ == "__main__":
    unittest.main()
