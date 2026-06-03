from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from quantagent.cli import main
from quantagent.runtime_store import fail_runtime_queue_item


class RuntimeQueueCliTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent runtime queue cli ")

    def run_queue_cli(self, project: str, *args: str) -> tuple[int, dict[str, Any], str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = main(["--no-trust-prompt", "runtime", "--project", project, "queue", *args, "--json"])
        text = stdout.getvalue()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"runtime queue CLI must emit JSON, got: {text!r}") from exc
        return rc, payload, text

    def test_enqueue_list_claim_heartbeat_stop_emit_json_and_success_codes(self) -> None:
        with self.make_project() as tmp:
            rc, payload, _ = self.run_queue_cli(
                tmp,
                "enqueue",
                "audit task",
                "--item-id",
                "rq-cli-1",
                "--queue",
                "compat",
                "--task-kind",
                "unit",
                "--priority",
                "7",
                "--metadata-json",
                '{"source":"cli"}',
            )

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "enqueue")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["task"]["task_id"], "rq-cli-1")
            self.assertEqual(payload["task"]["status"], "queued")
            self.assertEqual(payload["task"]["payload"]["goal"], "audit task")
            self.assertEqual(payload["task"]["payload"]["source"], "cli")

            rc, payload, _ = self.run_queue_cli(tmp, "list", "--queue", "compat", "--status", "queued")

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "list")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["task"][0]["task_id"], "rq-cli-1")
            self.assertEqual(payload["task"][0]["status"], "queued")

            rc, payload, _ = self.run_queue_cli(tmp, "claim", "--queue", "compat", "--worker-id", "worker-a", "--lease-seconds", "60")

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "claim")
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["task"]["task_id"], "rq-cli-1")
            self.assertEqual(payload["task"]["status"], "running")
            self.assertEqual(payload["task"]["lease_owner"], "worker-a")

            rc, payload, _ = self.run_queue_cli(tmp, "heartbeat", "rq-cli-1", "--worker-id", "worker-a", "--lease-seconds", "60")

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "heartbeat")
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["task"]["task_id"], "rq-cli-1")
            self.assertEqual(payload["task"]["status"], "running")
            self.assertEqual(payload["task"]["lease_owner"], "worker-a")
            self.assertIsNotNone(payload["task"]["heartbeat_at"])

            rc, payload, _ = self.run_queue_cli(tmp, "stop", "rq-cli-1", "--worker-id", "worker-a", "--reason", "compat stop")

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "stop")
            self.assertEqual(payload["status"], "stopped")
            self.assertEqual(payload["task"]["task_id"], "rq-cli-1")
            self.assertEqual(payload["task"]["status"], "stopped")
            self.assertEqual(payload["task"]["summary"], "compat stop")

    def test_resume_emits_json_and_success_code_for_failed_item(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            enqueue_rc, enqueue_payload, _ = self.run_queue_cli(tmp, "enqueue", "resume task", "--item-id", "rq-cli-resume")
            claim_rc, claim_payload, _ = self.run_queue_cli(tmp, "claim", "--worker-id", "worker-a")
            failed = fail_runtime_queue_item(project, "rq-cli-resume", lease_owner="worker-a", error="compat failure")

            self.assertEqual(enqueue_rc, 0)
            self.assertEqual(claim_rc, 0)
            self.assertEqual(enqueue_payload["task"]["task_id"], "rq-cli-resume")
            self.assertEqual(claim_payload["task"]["task_id"], "rq-cli-resume")
            self.assertEqual(failed.status, "failed")

            rc, payload, _ = self.run_queue_cli(tmp, "resume", "rq-cli-resume")

            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["action"], "resume")
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["task"]["task_id"], "rq-cli-resume")
            self.assertEqual(payload["task"]["status"], "queued")
            self.assertIsNone(payload["task"]["lease_owner"])

    def test_claim_empty_returns_one_with_json_empty_payload(self) -> None:
        with self.make_project() as tmp:
            rc, payload, _ = self.run_queue_cli(tmp, "claim", "--worker-id", "worker-a")

            self.assertEqual(rc, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["action"], "claim")
            self.assertEqual(payload["status"], "empty")
            self.assertIsNone(payload["task"])

    def test_invalid_heartbeat_returns_two_with_json_error_payload(self) -> None:
        with self.make_project() as tmp:
            enqueue_rc, enqueue_payload, _ = self.run_queue_cli(tmp, "enqueue", "queued heartbeat", "--item-id", "rq-cli-bad-heartbeat")

            self.assertEqual(enqueue_rc, 0)
            self.assertEqual(enqueue_payload["task"]["status"], "queued")

            rc, payload, _ = self.run_queue_cli(tmp, "heartbeat", "rq-cli-bad-heartbeat", "--worker-id", "worker-a")

            self.assertEqual(rc, 2)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["action"], "heartbeat")
            self.assertEqual(payload["status"], "error")
            self.assertIn("not running", payload["error"])


if __name__ == "__main__":
    unittest.main()
