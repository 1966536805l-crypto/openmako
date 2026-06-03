from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


REQUIRED_CHANNEL_GATEWAY_API = (
    "create_pairing_code",
    "pair_sender",
    "resolve_sender_owner",
    "bind_sender_agent",
    "list_channel_bindings",
    "handle_channel_message",
    "list_channel_gateway_events",
)


def _gateway() -> Any:
    try:
        module = importlib.import_module("quantagent.channel_gateway")
    except ModuleNotFoundError as exc:
        raise AssertionError("quantagent.channel_gateway must implement the channel pairing/identity gateway") from exc
    missing = [name for name in REQUIRED_CHANNEL_GATEWAY_API if getattr(module, name, None) is None]
    if missing:
        raise AssertionError(f"missing channel gateway API functions: {missing}")
    return module


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    raise AssertionError(f"gateway result must be dict-like or expose to_dict: {value!r}")


def _field(value: Any, name: str, default: Any = None) -> Any:
    return _payload(value).get(name, default)


class ChannelGatewayPairingIdentityTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent channel gateway ")

    def test_unknown_sender_returns_pairing_required(self) -> None:
        gateway = _gateway()
        with self.make_project() as tmp:
            result = gateway.handle_channel_message(
                Path(tmp),
                channel="slack",
                sender="U_UNKNOWN",
                text="run unit tests",
            )

        self.assertFalse(bool(_field(result, "allowed", False)))
        self.assertEqual(_field(result, "status"), "pairing_required")
        self.assertEqual(_field(result, "owner_key", ""), "")

    def test_correct_pairing_code_binds_sender_and_resolves_owner(self) -> None:
        gateway = _gateway()
        with self.make_project() as tmp:
            project = Path(tmp)
            issued = gateway.create_pairing_code(project, owner_key="owner/alice", channel="slack", agent_id="coder", ttl_seconds=300)
            code = str(_field(issued, "code"))

            paired = gateway.pair_sender(project, channel="slack", sender="U_ALICE", code=code)
            owner = gateway.resolve_sender_owner(project, channel="slack", sender="U_ALICE")
            bindings = gateway.list_channel_bindings(project)

        self.assertTrue(bool(_field(paired, "paired", _field(paired, "allowed", False))))
        self.assertEqual(_field(paired, "status"), "paired")
        self.assertEqual(_field(owner, "owner_key"), "owner/alice")
        self.assertEqual(_field(owner, "payload")["agent_id"], "coder")
        self.assertEqual(_field(owner, "status"), "resolved")
        self.assertEqual(_payload(bindings[0])["agent_id"], "coder")

    def test_bound_agent_routes_queued_message_to_agent_queue(self) -> None:
        gateway = _gateway()
        with self.make_project() as tmp:
            project = Path(tmp)
            issued = gateway.create_pairing_code(project, owner_key="owner/alice", channel="webchat", ttl_seconds=300)
            gateway.pair_sender(project, channel="webchat", sender="browser-1", code=str(_field(issued, "code")))

            bound = gateway.bind_sender_agent(project, channel="webchat", sender="browser-1", agent_id="executor")
            sent = gateway.handle_channel_message(project, channel="webchat", sender="browser-1", text="run desktop task")

        self.assertEqual(_field(bound, "status"), "bound")
        self.assertEqual(_field(sent, "status"), "queued")
        self.assertEqual(_field(sent, "payload")["agent_id"], "executor")
        self.assertEqual(_field(sent, "payload")["queue"], "channel_gateway:executor")
        self.assertEqual(_field(sent, "payload")["task"]["payload"]["agent_id"], "executor")

    def test_wrong_pairing_code_fails_and_does_not_bind_sender(self) -> None:
        gateway = _gateway()
        with self.make_project() as tmp:
            project = Path(tmp)
            gateway.create_pairing_code(project, owner_key="owner/alice", channel="slack", ttl_seconds=300)

            paired = gateway.pair_sender(project, channel="slack", sender="U_MALLORY", code="wrong-code")
            owner = gateway.resolve_sender_owner(project, channel="slack", sender="U_MALLORY")

        self.assertFalse(bool(_field(paired, "paired", _field(paired, "allowed", True))))
        self.assertEqual(_field(paired, "status"), "invalid_pairing_code")
        self.assertEqual(_field(owner, "status"), "pairing_required")
        self.assertEqual(_field(owner, "owner_key", ""), "")

    def test_unauthorized_sender_does_not_execute_task(self) -> None:
        gateway = _gateway()
        calls: list[dict[str, Any]] = []

        def executor(payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(payload)
            return {"executed": True}

        with self.make_project() as tmp:
            result = gateway.handle_channel_message(
                Path(tmp),
                channel="slack",
                sender="U_MALLORY",
                text="exec: python3 -m unittest",
                executor=executor,
            )

        self.assertEqual(calls, [])
        self.assertFalse(bool(_field(result, "allowed", False)))
        self.assertEqual(_field(result, "status"), "pairing_required")
        self.assertNotEqual(_field(result, "status"), "executed")

    def test_event_payloads_are_json_serializable(self) -> None:
        gateway = _gateway()
        with self.make_project() as tmp:
            project = Path(tmp)
            issued = gateway.create_pairing_code(project, owner_key="owner/alice", channel="slack", ttl_seconds=300)
            gateway.pair_sender(project, channel="slack", sender="U_ALICE", code=str(_field(issued, "code")))
            gateway.handle_channel_message(project, channel="slack", sender="U_ALICE", text="status")

            events = gateway.list_channel_gateway_events(project)

        self.assertGreaterEqual(len(events), 3)
        for event in events:
            payload = _payload(event)
            json.dumps(payload, sort_keys=True)
            if "payload" in payload:
                json.dumps(payload["payload"], sort_keys=True)


if __name__ == "__main__":
    unittest.main()
