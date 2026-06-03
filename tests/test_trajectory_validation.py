from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.trajectory import append_event, TrajectoryEvent


class TrajectoryValidationTest(unittest.TestCase):
    def test_reject_out_of_order_step(self) -> None:
        """Write step=5, then try step=3, expect ValueError with 'Out-of-order'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            # Write step=5 first
            append_event(trajectory_path, TrajectoryEvent(kind="step", content="Step 5", step=5))

            # Try to write step=3, should raise ValueError
            with self.assertRaises(ValueError) as context:
                append_event(trajectory_path, TrajectoryEvent(kind="step", content="Step 3", step=3))

            self.assertIn("Out-of-order", str(context.exception))
            self.assertIn("3", str(context.exception))
            self.assertIn("5", str(context.exception))

    def test_reject_invalid_kind(self) -> None:
        """Try kind='thought', expect ValueError with 'Unknown trajectory event kind'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            with self.assertRaises(ValueError) as context:
                append_event(trajectory_path, TrajectoryEvent(kind="thought", content="Thinking", step=1))

            self.assertIn("Unknown trajectory event kind", str(context.exception))
            self.assertIn("thought", str(context.exception))

    def test_allow_same_step_multiple_events(self) -> None:
        """Write step=2 twice, should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            # Write step=2 first time
            event1 = append_event(trajectory_path, TrajectoryEvent(kind="action", content="Action 1", step=2))
            self.assertEqual(event1.step, 2)

            # Write step=2 second time, should succeed
            event2 = append_event(trajectory_path, TrajectoryEvent(kind="observation", content="Observation 1", step=2))
            self.assertEqual(event2.step, 2)

    def test_allow_valid_event_sequence(self) -> None:
        """Write step=1,2,3 in order, should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            event1 = append_event(trajectory_path, TrajectoryEvent(kind="step", content="Step 1", step=1))
            self.assertEqual(event1.step, 1)

            event2 = append_event(trajectory_path, TrajectoryEvent(kind="step", content="Step 2", step=2))
            self.assertEqual(event2.step, 2)

            event3 = append_event(trajectory_path, TrajectoryEvent(kind="step", content="Step 3", step=3))
            self.assertEqual(event3.step, 3)

    def test_allow_step_none(self) -> None:
        """Write events with step=None, should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            event1 = append_event(trajectory_path, TrajectoryEvent(kind="action", content="Action without step", step=None))
            self.assertIsNone(event1.step)

            event2 = append_event(trajectory_path, TrajectoryEvent(kind="observation", content="Observation without step", step=None))
            self.assertIsNone(event2.step)

    def test_first_event_any_step(self) -> None:
        """First event can have any step (no previous events to compare)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = Path(tmpdir) / "trajectory.jsonl"

            # First event can be step=100
            event = append_event(trajectory_path, TrajectoryEvent(kind="step", content="First step", step=100))
            self.assertEqual(event.step, 100)


if __name__ == "__main__":
    unittest.main()
