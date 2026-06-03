from __future__ import annotations

import unittest

from quantagent.control_plane_policy import (
    ADMIN_SCOPE,
    PAIRING_SCOPE,
    READ_SCOPE,
    WRITE_SCOPE,
    RateLimiter,
    authorize_method,
    is_control_plane_write_method,
    least_privilege_scopes_for_method,
    resolve_control_plane_rate_limit_key,
    resolve_method_scope,
)


class ControlPlanePolicyTest(unittest.TestCase):
    def test_same_key_blocks_when_over_limit(self) -> None:
        limiter = RateLimiter(window_ms=1000, max_requests=2)

        first = limiter.consume("client-a", now_ms=0)
        second = limiter.consume("client-a", now_ms=100)
        third = limiter.consume("client-a", now_ms=200)

        self.assertTrue(first.allowed)
        self.assertEqual(first.remaining, 1)
        self.assertTrue(second.allowed)
        self.assertEqual(second.remaining, 0)
        self.assertFalse(third.allowed)
        self.assertEqual(third.reason, "rate_limited")
        self.assertEqual(third.retry_after_ms, 800)

    def test_window_expiry_restores_budget(self) -> None:
        limiter = RateLimiter(window_ms=1000, max_requests=1)

        self.assertTrue(limiter.consume("client-a", now_ms=0).allowed)
        self.assertFalse(limiter.consume("client-a", now_ms=999).allowed)
        restored = limiter.consume("client-a", now_ms=1000)

        self.assertTrue(restored.allowed)
        self.assertEqual(restored.remaining, 0)

    def test_different_keys_are_independent(self) -> None:
        limiter = RateLimiter(window_ms=1000, max_requests=1)

        self.assertTrue(limiter.consume("client-a", now_ms=0).allowed)
        self.assertFalse(limiter.consume("client-a", now_ms=100).allowed)
        self.assertTrue(limiter.consume("client-b", now_ms=100).allowed)

    def test_resolves_stable_identity_key_with_connection_fallback(self) -> None:
        self.assertEqual(
            resolve_control_plane_rate_limit_key(device_id=" device ", client_ip=" 127.0.0.1 "),
            "device|127.0.0.1",
        )
        self.assertEqual(
            resolve_control_plane_rate_limit_key(conn_id="conn-1"),
            "unknown-device|unknown-ip|conn=conn-1",
        )

    def test_method_scope_known_classification(self) -> None:
        self.assertEqual(resolve_method_scope("config.get"), READ_SCOPE)
        self.assertEqual(resolve_method_scope("chat.send"), WRITE_SCOPE)
        self.assertEqual(resolve_method_scope("daemon.start"), ADMIN_SCOPE)
        self.assertEqual(resolve_method_scope("connect"), PAIRING_SCOPE)
        self.assertEqual(least_privilege_scopes_for_method("chat.send"), (WRITE_SCOPE,))
        self.assertTrue(is_control_plane_write_method("chat.send"))
        self.assertFalse(is_control_plane_write_method("config.get"))

    def test_unknown_method_default_deny(self) -> None:
        decision = authorize_method("not.real", {ADMIN_SCOPE, READ_SCOPE, WRITE_SCOPE, PAIRING_SCOPE})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unknown_method")
        self.assertEqual(least_privilege_scopes_for_method("not.real"), ())

    def test_authorize_method_enforces_scopes(self) -> None:
        self.assertTrue(authorize_method("config.get", {READ_SCOPE}).allowed)
        self.assertTrue(authorize_method("config.get", {WRITE_SCOPE}).allowed)
        self.assertFalse(authorize_method("chat.send", {READ_SCOPE}).allowed)
        self.assertTrue(authorize_method("chat.send", {WRITE_SCOPE}).allowed)
        self.assertFalse(authorize_method("daemon.start", {WRITE_SCOPE}).allowed)
        self.assertTrue(authorize_method("daemon.start", {ADMIN_SCOPE}).allowed)


if __name__ == "__main__":
    unittest.main()
