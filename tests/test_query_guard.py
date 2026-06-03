from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.query_guard import DISPATCHING, IDLE, RUNNING, QueryGuard
from quantagent.query_runtime import QueryRuntime, load_query_events


class QueryGuardTest(unittest.TestCase):
    def test_start_and_end_use_generation_token(self) -> None:
        guard = QueryGuard()

        generation = guard.start()

        self.assertEqual(generation, 1)
        self.assertEqual(guard.state, RUNNING)
        self.assertEqual(guard.generation, 1)
        self.assertFalse(guard.end(0))
        self.assertEqual(guard.state, RUNNING)
        self.assertTrue(guard.end(1))
        self.assertEqual(guard.state, IDLE)

    def test_reservation_dispatches_into_same_generation(self) -> None:
        guard = QueryGuard()

        reservation = guard.reserve()

        self.assertEqual(reservation, 1)
        self.assertEqual(guard.state, DISPATCHING)
        self.assertIsNone(guard.reserve())
        self.assertEqual(guard.start(), reservation)
        self.assertEqual(guard.state, RUNNING)
        self.assertTrue(guard.end(reservation or -1))
        self.assertEqual(guard.state, IDLE)

    def test_reservation_is_rejected_while_running(self) -> None:
        guard = QueryGuard()

        first = guard.start()

        self.assertEqual(first, 1)
        self.assertIsNone(guard.reserve())
        self.assertEqual(guard.state, RUNNING)
        self.assertTrue(guard.end(first or -1))
        self.assertEqual(guard.state, IDLE)

    def test_stale_end_cannot_clear_new_run(self) -> None:
        guard = QueryGuard()

        first = guard.start()
        self.assertTrue(guard.force_end())
        second = guard.start()

        self.assertEqual(first, 1)
        self.assertEqual(second, 3)
        self.assertFalse(guard.end(first or -1))
        self.assertEqual(guard.state, RUNNING)
        self.assertTrue(guard.end(second or -1))
        self.assertEqual(guard.state, IDLE)

    def test_cancel_reservation_releases_dispatching_state(self) -> None:
        guard = QueryGuard()

        reservation = guard.reserve()

        self.assertTrue(guard.cancel_reservation())
        self.assertEqual(guard.state, IDLE)
        self.assertEqual(guard.generation, reservation)
        self.assertFalse(guard.cancel_reservation())
        next_generation = guard.start()
        self.assertEqual(next_generation, 2)
        self.assertFalse(guard.end(reservation or -1))
        self.assertTrue(guard.end(next_generation or -1))

    def test_force_end_clears_state_and_invalidates_generation(self) -> None:
        guard = QueryGuard()

        generation = guard.start()
        forced_generation = guard.force_end()

        self.assertEqual(generation, 1)
        self.assertEqual(forced_generation, 2)
        self.assertEqual(guard.state, IDLE)
        self.assertFalse(guard.end(generation or -1))
        self.assertEqual(guard.reserve(), 3)

    def test_end_requires_integer_generation(self) -> None:
        guard = QueryGuard()

        with self.assertRaises(TypeError):
            guard.end("1")  # type: ignore[arg-type]


class QueryRuntimeGuardTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent query guard ")

    def test_query_runtime_uses_existing_reservation(self) -> None:
        with self.make_project() as tmp:
            guard = QueryGuard()
            reservation = guard.reserve()
            runtime = QueryRuntime(Path(tmp), query_id="qa-guard", guard=guard)

            started = runtime.start("reserved task")
            stopped = runtime.stop("done")
            events = load_query_events(Path(tmp))

            self.assertEqual(started.data["guard_generation"], reservation)
            self.assertEqual(started.data["guard_state"], RUNNING)
            self.assertTrue(stopped.data["guard_ended"])
            self.assertEqual(stopped.data["guard_state"], IDLE)
            self.assertEqual(guard.state, IDLE)
            self.assertEqual(events[0].data["guard_generation"], reservation)
            self.assertTrue(events[-1].data["guard_ended"])

    def test_query_runtime_rejects_busy_guard(self) -> None:
        with self.make_project() as tmp:
            guard = QueryGuard()
            self.assertEqual(guard.start(), 1)
            runtime = QueryRuntime(Path(tmp), query_id="qa-busy", guard=guard)

            with self.assertRaises(RuntimeError):
                runtime.start("overlap")

            self.assertEqual(guard.state, RUNNING)
            self.assertEqual(load_query_events(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
