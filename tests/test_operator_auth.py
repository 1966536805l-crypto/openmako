from __future__ import annotations

import unittest

from quantagent.operator_auth import (
    ADMIN,
    CONTROL,
    READ,
    WRITE,
    OperatorAuthPolicy,
    authorize_operator_command,
    command_scope,
    sender_allowed,
    validate_sender_identity,
)


class OperatorAuthTest(unittest.TestCase):
    def test_empty_sender_is_rejected(self) -> None:
        identity = validate_sender_identity("  ")
        decision = authorize_operator_command("", "/status", OperatorAuthPolicy(allowed_senders=("*",)))

        self.assertFalse(identity.valid)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "empty sender")

    def test_star_allowlist_allows_valid_sender(self) -> None:
        allowed, matched = sender_allowed("Slack:Alice", ("*",))

        self.assertTrue(allowed)
        self.assertEqual(matched, "*")

    def test_unknown_sender_is_rejected(self) -> None:
        decision = authorize_operator_command("mallory", "/status", OperatorAuthPolicy(allowed_senders=("alice",)))

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "sender not in allowlist")

    def test_unauthorized_exec_is_rejected(self) -> None:
        decision = authorize_operator_command("alice", "/exec pytest", OperatorAuthPolicy(allowed_senders=("alice",)))

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.scope, WRITE)
        self.assertEqual(decision.reason, "sender lacks write scope")

    def test_read_command_can_be_allowed(self) -> None:
        decision = authorize_operator_command("alice", "/status", OperatorAuthPolicy(allowed_senders=("alice",)))

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.scope, READ)

    def test_command_gate_distinguishes_scopes(self) -> None:
        self.assertEqual(command_scope("/status"), READ)
        self.assertEqual(command_scope("/pause"), CONTROL)
        self.assertEqual(command_scope("/exec make test"), WRITE)
        self.assertEqual(command_scope("/approve run-1"), ADMIN)

    def test_sender_specific_scope_can_authorize_exec(self) -> None:
        policy = OperatorAuthPolicy(allowed_senders=("alice",), sender_scopes={"alice": (WRITE,)})

        decision = authorize_operator_command("Alice", "/exec pytest", policy)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.scope, WRITE)


if __name__ == "__main__":
    unittest.main()
