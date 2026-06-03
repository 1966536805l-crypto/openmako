from __future__ import annotations

import json
import sys
import time
import unittest

from quantagent.daemon_supervisor import DaemonSupervisor, RunStatus


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _wait(supervisor: DaemonSupervisor, run_id: str, *, timeout: float = 3.0):
    deadline = time.time() + timeout
    record = supervisor.get(run_id)
    while record is not None and not record.terminal and time.time() < deadline:
        time.sleep(0.02)
        record = supervisor.get(run_id)
    assert record is not None
    return record


class DaemonSupervisorTest(unittest.TestCase):
    def test_spawned_run_reaches_terminal_success(self) -> None:
        supervisor = DaemonSupervisor()
        record = supervisor.start(_py("print('daemon-ok')"), scope="build")

        final = _wait(supervisor, record.run_id)

        self.assertEqual(final.status, RunStatus.SUCCEEDED)
        self.assertEqual(final.returncode, 0)
        self.assertIn("daemon-ok", final.to_dict()["output"])

    def test_timeout_marks_run_failed_and_stops_process(self) -> None:
        supervisor = DaemonSupervisor(terminate_grace_seconds=0.05)
        record = supervisor.start(_py("import time; time.sleep(5)"), timeout_seconds=0.1)

        final = _wait(supervisor, record.run_id)

        self.assertEqual(final.status, RunStatus.FAILED)
        self.assertIn("timeout", final.error)
        self.assertTrue(final.terminal)

    def test_cancel_by_scope_stops_only_matching_runs(self) -> None:
        supervisor = DaemonSupervisor(terminate_grace_seconds=0.05)
        first = supervisor.start(_py("import time; time.sleep(5)"), scope="alpha")
        second = supervisor.start(_py("import time; time.sleep(5)"), scope="beta")

        canceled = supervisor.cancel_scope("alpha", reason="test cancel")
        supervisor.update(second.run_id)

        self.assertEqual([item.run_id for item in canceled], [first.run_id])
        self.assertEqual(supervisor.get(first.run_id).status, RunStatus.CANCELED)  # type: ignore[union-attr]
        self.assertEqual(supervisor.get(second.run_id).status, RunStatus.RUNNING)  # type: ignore[union-attr]
        supervisor.cancel(second.run_id, reason="cleanup")

    def test_no_output_timeout_marks_run_failed(self) -> None:
        supervisor = DaemonSupervisor(terminate_grace_seconds=0.05)
        record = supervisor.start(
            _py("import time; time.sleep(5)"),
            timeout_seconds=2.0,
            no_output_timeout_seconds=0.1,
        )

        final = _wait(supervisor, record.run_id)

        self.assertEqual(final.status, RunStatus.FAILED)
        self.assertIn("no-output", final.error)

    def test_snapshot_is_json_serializable(self) -> None:
        supervisor = DaemonSupervisor()
        record = supervisor.start(_py("print('snapshot-ok')"), scope="snapshot")
        _wait(supervisor, record.run_id)

        snapshot = supervisor.snapshot()
        encoded = json.dumps(snapshot, sort_keys=True)

        self.assertIn("snapshot-ok", encoded)
        self.assertEqual(snapshot["runs"][0]["status"], "succeeded")
        self.assertNotIn("process", snapshot["runs"][0])


if __name__ == "__main__":
    unittest.main()

