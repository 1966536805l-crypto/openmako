from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.trajectory import (
    TrajectoryEvent,
    append_event,
    failed_events,
    failed_steps,
    read_events,
    recent_summary,
    record_action,
    record_edit,
    record_observation,
    record_step,
    record_test,
)


class TrajectoryTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent trajectory ")

    def test_appends_and_reads_jsonl_events(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "trajectory.jsonl"

            append_event(
                path,
                TrajectoryEvent(
                    kind="step",
                    step=1,
                    content="plan next inspection",
                    ok=True,
                    timestamp="2026-05-24T01:02:03Z",
                    meta={"tool": "planner"},
                ),
            )
            append_event(
                path,
                {
                    "kind": "observation",
                    "step": "1",
                    "content": "validation output captured",
                    "ok": False,
                    "timestamp": "2026-05-24T01:03:03Z",
                    "meta": {"stderr": "failed"},
                },
            )

            events = read_events(path)

            self.assertEqual([event.kind for event in events], ["step", "observation"])
            self.assertEqual(events[0].meta, {"tool": "planner"})
            self.assertEqual(events[1].step, 1)
            self.assertIs(events[1].ok, False)
            self.assertEqual(path.read_text(encoding="utf-8").count("\n"), 2)

    def test_record_helpers_cover_agent_event_kinds(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "run" / "trajectory.jsonl"

            record_step(path, "start", step=1, ok=True)
            record_action(path, "read file", step=1, ok=True, tool="read")
            record_observation(path, "file has target function", step=1, ok=True)
            record_edit(path, "patched trajectory module", step=2, ok=True, files=["quantagent/trajectory.py"])
            record_test(path, "pytest failed", step=3, ok=False, command="pytest tests/test_trajectory.py")

            events = read_events(path)

            self.assertEqual([event.kind for event in events], ["step", "action", "observation", "edit", "test"])
            self.assertEqual(events[1].meta["tool"], "read")
            self.assertEqual(events[-1].meta["command"], "pytest tests/test_trajectory.py")

    def test_recent_summary_is_deterministic_and_limited(self) -> None:
        events = [
            TrajectoryEvent(kind="step", content="first", step=1, ok=True),
            TrajectoryEvent(kind="action", content="second " * 30, step=2),
            TrajectoryEvent(kind="test", content="third failed with long stderr", step=3, ok=False),
        ]

        summary_a = recent_summary(events, limit=2, max_content_chars=24)
        summary_b = recent_summary(events, limit=2, max_content_chars=24)

        self.assertEqual(summary_a, summary_b)
        self.assertIn("Trajectory has 3 event(s); showing 2 recent event(s):", summary_a)
        self.assertIn("action step=2 unknown: second second second", summary_a)
        self.assertIn("test step=3 failed: third failed with long…", summary_a)
        self.assertIn("…", summary_a)
        self.assertNotIn("first", summary_a)

    def test_filters_failed_events_and_groups_failed_steps(self) -> None:
        events = [
            TrajectoryEvent(kind="step", content="begin", step=1, ok=True, timestamp="t1"),
            TrajectoryEvent(kind="test", content="unit tests failed", step=2, ok=False, timestamp="t2"),
            TrajectoryEvent(kind="observation", content="stderr mentions assertion", step=2, ok=False, timestamp="t3"),
            TrajectoryEvent(kind="edit", content="unverified edit", step=3, timestamp="t4"),
        ]

        failures = failed_events(events)
        steps = failed_steps(events)

        self.assertEqual([event.content for event in failures], ["unit tests failed", "stderr mentions assertion"])
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["step"], 2)
        self.assertEqual(steps[0]["count"], 2)
        self.assertIn("test: unit tests failed", steps[0]["summary"])
        self.assertIn("observation: stderr mentions assertion", steps[0]["summary"])

    def test_rejects_invalid_json_and_unknown_event_kind(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "trajectory.jsonl"
            path.write_text("{bad json}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid trajectory JSONL at line 1"):
                read_events(path)

            with self.assertRaisesRegex(ValueError, "Unknown trajectory event kind"):
                append_event(path, {"kind": "thought", "content": "not part of the public trajectory vocabulary"})


if __name__ == "__main__":
    unittest.main()
