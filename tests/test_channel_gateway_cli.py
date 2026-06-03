from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest

from quantagent.cli import main


class ChannelGatewayCliTest(unittest.TestCase):
    def run_channel_cli(self, project: str, *args: str) -> tuple[int, dict[str, object] | list[object], str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = main(["--no-trust-prompt", "channel", "--project", project, *args, "--json"])
        text = stdout.getvalue()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"channel CLI must emit JSON, got: {text!r}") from exc
        return rc, payload, text

    def test_pair_resolve_send_and_events_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent channel cli ") as tmp:
            rc, issued, _ = self.run_channel_cli(tmp, "pair-code", "--owner-key", "owner/alice", "--channel", "slack", "--agent-id", "coder")
            self.assertEqual(rc, 0)
            assert isinstance(issued, dict)
            code = str(issued["code"])
            self.assertFalse(code.startswith("-"))

            rc, paired, _ = self.run_channel_cli(tmp, "pair", "--channel", "slack", "--sender", "U_ALICE", "--code", code)
            self.assertEqual(rc, 0)
            assert isinstance(paired, dict)
            self.assertEqual(paired["status"], "paired")

            rc, resolved, _ = self.run_channel_cli(tmp, "resolve", "--channel", "slack", "--sender", "U_ALICE")
            self.assertEqual(rc, 0)
            assert isinstance(resolved, dict)
            self.assertEqual(resolved["owner_key"], "owner/alice")
            self.assertEqual(resolved["payload"]["agent_id"], "coder")

            rc, bound, _ = self.run_channel_cli(tmp, "bind-agent", "--channel", "slack", "--sender", "U_ALICE", "--agent-id", "executor")
            self.assertEqual(rc, 0)
            assert isinstance(bound, dict)
            self.assertEqual(bound["status"], "bound")

            rc, bindings, _ = self.run_channel_cli(tmp, "bindings")
            self.assertEqual(rc, 0)
            assert isinstance(bindings, list)
            self.assertEqual(bindings[0]["agent_id"], "executor")

            rc, sent, _ = self.run_channel_cli(tmp, "send", "--channel", "slack", "--sender", "U_ALICE", "run desktop status")
            self.assertEqual(rc, 0)
            assert isinstance(sent, dict)
            self.assertEqual(sent["status"], "queued")
            self.assertEqual(sent["payload"]["agent_id"], "executor")
            self.assertEqual(sent["payload"]["queue"], "channel_gateway:executor")
            self.assertTrue(str(sent["item_id"]).startswith("rq-"))

            rc, events, _ = self.run_channel_cli(tmp, "events")
            self.assertEqual(rc, 0)
            assert isinstance(events, list)
            self.assertGreaterEqual(len(events), 4)

    def test_unknown_sender_send_returns_one_and_pairing_required_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent channel cli ") as tmp:
            rc, payload, _ = self.run_channel_cli(tmp, "send", "--channel", "slack", "--sender", "U_UNKNOWN", "status")

        self.assertEqual(rc, 1)
        assert isinstance(payload, dict)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["status"], "pairing_required")


if __name__ == "__main__":
    unittest.main()
