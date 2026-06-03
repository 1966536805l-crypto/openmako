from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from quantagent.sessions import acquire_session_lock, release_session_lock, with_session_lock


class SessionLockTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent session lock ")

    def test_same_owner_renews_and_releases(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            first = acquire_session_lock(project, "sess-a", "owner-a", ttl_seconds=1)
            renewed = acquire_session_lock(project, "sess-a", "owner-a", ttl_seconds=30)

            self.assertIsNotNone(first)
            self.assertIsNotNone(renewed)
            assert first is not None
            assert renewed is not None
            self.assertEqual(renewed.owner, "owner-a")
            self.assertNotEqual(renewed.token, first.token)
            self.assertGreater(renewed.expires_at, first.expires_at)
            self.assertTrue(release_session_lock(project, "sess-a", "owner-a"))
            self.assertFalse(release_session_lock(project, "sess-a", "owner-a"))

    def test_different_owner_is_rejected_across_processes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            held = acquire_session_lock(project, "sess-b", "owner-a", ttl_seconds=30)
            self.assertIsNotNone(held)

            result = _run_child_acquire(project, "sess-b", "owner-b", ttl_seconds=30)

            self.assertFalse(result["acquired"])
            self.assertEqual(result["owner"], "")

    def test_expired_lock_can_be_stolen(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            held = acquire_session_lock(project, "sess-c", "owner-a", ttl_seconds=0.1)
            self.assertIsNotNone(held)

            time.sleep(0.25)
            stolen = acquire_session_lock(project, "sess-c", "owner-b", ttl_seconds=30)

            self.assertIsNotNone(stolen)
            assert stolen is not None
            self.assertEqual(stolen.owner, "owner-b")
            self.assertTrue(release_session_lock(project, "sess-c", "owner-b"))

    def test_context_manager_releases_on_exit(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            with with_session_lock(project, "sess-d", "owner-a", ttl_seconds=30) as lock:
                self.assertEqual(lock.owner, "owner-a")
                self.assertIsNone(acquire_session_lock(project, "sess-d", "owner-b", ttl_seconds=30))

            acquired = acquire_session_lock(project, "sess-d", "owner-b", ttl_seconds=30)
            self.assertIsNotNone(acquired)
            self.assertTrue(release_session_lock(project, "sess-d", "owner-b"))


def _run_child_acquire(project: Path, session_id: str, owner: str, *, ttl_seconds: float) -> dict[str, object]:
    script = """
import json
import sys
from pathlib import Path
from quantagent.sessions import acquire_session_lock

lock = acquire_session_lock(Path(sys.argv[1]), sys.argv[2], sys.argv[3], ttl_seconds=float(sys.argv[4]))
print(json.dumps({"acquired": lock is not None, "owner": lock.owner if lock else ""}))
"""
    env = dict(os.environ)
    repo = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(project), session_id, owner, str(ttl_seconds)],
        check=True,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )
    return dict(json.loads(completed.stdout))
