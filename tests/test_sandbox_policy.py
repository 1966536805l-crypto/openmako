from __future__ import annotations

import unittest

from quantagent.sandbox_policy import EnvSanitizeResult, sanitize_env


class SandboxPolicyEnvTest(unittest.TestCase):
    def test_secret_env_does_not_enter_child_env(self) -> None:
        child_env = sanitize_env(
            {
                "PATH": "/usr/bin",
                "OPENAI_API_KEY": "sk-test",
                "GITHUB_TOKEN": "ghp-test",
                "DB_PASSWORD": "secret",
                "NORMAL_FLAG": "1",
            }
        )

        self.assertEqual(child_env["PATH"], "/usr/bin")
        self.assertEqual(child_env["NORMAL_FLAG"], "1")
        self.assertNotIn("OPENAI_API_KEY", child_env)
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn("DB_PASSWORD", child_env)

    def test_allowlist_preserves_named_secret_env(self) -> None:
        child_env = sanitize_env({"OPENAI_API_KEY": "sk-test"}, allowlist=("OPENAI_API_KEY",))

        self.assertEqual(child_env, {"OPENAI_API_KEY": "sk-test"})

    def test_mask_mode_redacts_secret_env_and_reports(self) -> None:
        result = sanitize_env({"SERVICE_SECRET": "value", "PATH": "/bin"}, mask=True, include_report=True)

        self.assertIsInstance(result, EnvSanitizeResult)
        self.assertEqual(result.env["SERVICE_SECRET"], "[REDACTED]")
        self.assertEqual(result.masked, ("SERVICE_SECRET",))
        self.assertEqual(result.removed, ())

    def test_env_value_validation_blocks_null_bytes_and_reports_warnings(self) -> None:
        result = sanitize_env(
            {
                "PATH": "/bin",
                "SAFE_NULL": "abc\0def",
                "SAFE_BLOB": "A" * 80,
                "SAFE_LONG": "x" * 32769,
            },
            include_report=True,
        )

        self.assertIsInstance(result, EnvSanitizeResult)
        self.assertEqual(result.env["PATH"], "/bin")
        self.assertNotIn("SAFE_NULL", result.env)
        self.assertIn("SAFE_NULL", result.removed)
        self.assertTrue(any("SAFE_BLOB" in warning and "base64" in warning for warning in result.warnings))
        self.assertTrue(any("SAFE_LONG" in warning and "maximum length" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
