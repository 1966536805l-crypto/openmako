from __future__ import annotations

import socket
import unittest

from quantagent.model_errors import (
    ModelErrorKind,
    classify_model_error,
    classify_provider_error,
)


class ModelErrorsTest(unittest.TestCase):
    def test_taxonomy_values_are_stable(self) -> None:
        self.assertIs(ModelErrorKind.auth, ModelErrorKind.AUTH)
        self.assertIs(ModelErrorKind.context_overflow, ModelErrorKind.CONTEXT_OVERFLOW)
        self.assertEqual(
            {kind.value for kind in ModelErrorKind},
            {
                "auth",
                "auth_permanent",
                "billing",
                "rate_limit",
                "overloaded",
                "server_error",
                "timeout",
                "context_overflow",
                "payload_too_large",
                "image_too_large",
                "model_not_found",
                "provider_policy_blocked",
                "format_error",
                "multimodal_tool_content_unsupported",
                "unknown",
            },
        )

    def test_status_code_fallbacks(self) -> None:
        cases = {
            401: ModelErrorKind.AUTH,
            402: ModelErrorKind.BILLING,
            404: ModelErrorKind.MODEL_NOT_FOUND,
            408: ModelErrorKind.TIMEOUT,
            413: ModelErrorKind.PAYLOAD_TOO_LARGE,
            429: ModelErrorKind.RATE_LIMIT,
            500: ModelErrorKind.SERVER_ERROR,
            502: ModelErrorKind.SERVER_ERROR,
            503: ModelErrorKind.OVERLOADED,
            529: ModelErrorKind.OVERLOADED,
        }

        for status_code, expected in cases.items():
            with self.subTest(status_code=status_code):
                self.assertEqual(classify_model_error(status_code=status_code).reason, expected)

    def test_specific_messages_beat_generic_bad_request(self) -> None:
        context = classify_model_error(
            status_code=400,
            message="This model's maximum context length is 128000 tokens.",
        )
        self.assertEqual(context.reason, ModelErrorKind.CONTEXT_OVERFLOW)
        self.assertTrue(context.retryable)
        self.assertTrue(context.should_compress)

        image = classify_model_error(
            status_code=400,
            message="messages.0.content.1.image.source.base64: image exceeds 5 MB maximum",
        )
        self.assertEqual(image.reason, ModelErrorKind.IMAGE_TOO_LARGE)
        self.assertTrue(image.should_compress)

        tool_content = classify_model_error(
            status_code=400,
            message="tool message content must be a string; expected string, got array",
        )
        self.assertEqual(tool_content.reason, ModelErrorKind.MULTIMODAL_TOOL_CONTENT_UNSUPPORTED)
        self.assertTrue(tool_content.retryable)
        self.assertFalse(tool_content.should_compress)

    def test_auth_billing_and_rate_limit_actions(self) -> None:
        permanent_auth = classify_model_error(message="Incorrect API key provided: sk-test")
        self.assertEqual(permanent_auth.reason, ModelErrorKind.AUTH_PERMANENT)
        self.assertFalse(permanent_auth.retryable)
        self.assertFalse(permanent_auth.should_rotate_credential)
        self.assertTrue(permanent_auth.is_auth)

        transient_auth = classify_model_error(status_code=403, message="token expired")
        self.assertEqual(transient_auth.reason, ModelErrorKind.AUTH)
        self.assertFalse(transient_auth.retryable)
        self.assertTrue(transient_auth.should_rotate_credential)
        self.assertTrue(transient_auth.should_fallback)

        billing = classify_model_error(status_code=429, message="insufficient_quota: check plan and billing")
        self.assertEqual(billing.reason, ModelErrorKind.BILLING)
        self.assertFalse(billing.retryable)
        self.assertTrue(billing.should_rotate_credential)
        self.assertTrue(billing.should_fallback)

        rate_limit = classify_model_error(status_code=429, message="Rate limit reached for requests per minute")
        self.assertEqual(rate_limit.reason, ModelErrorKind.RATE_LIMIT)
        self.assertTrue(rate_limit.retryable)
        self.assertTrue(rate_limit.should_rotate_credential)
        self.assertTrue(rate_limit.should_fallback)

    def test_fallback_actions_for_provider_and_model_failures(self) -> None:
        model_missing = classify_model_error(status_code=404, message="model does not exist")
        self.assertEqual(model_missing.reason, ModelErrorKind.MODEL_NOT_FOUND)
        self.assertFalse(model_missing.retryable)
        self.assertTrue(model_missing.should_fallback)

        policy_block = classify_model_error(
            status_code=404,
            provider="https://openrouter.ai/api/v1",
            message="No endpoints available matching your guardrail restrictions and data policy.",
        )
        self.assertEqual(policy_block.reason, ModelErrorKind.PROVIDER_POLICY_BLOCKED)
        self.assertFalse(policy_block.retryable)
        self.assertFalse(policy_block.should_fallback)

        overloaded = classify_model_error(status_code=503)
        self.assertEqual(overloaded.reason, ModelErrorKind.OVERLOADED)
        self.assertTrue(overloaded.retryable)
        self.assertTrue(overloaded.should_fallback)

    def test_body_and_exception_inputs_are_supported(self) -> None:
        body = {"error": {"message": "prompt is too long", "status": "400"}}
        classified = classify_model_error(body=body)

        self.assertEqual(classified.status_code, 400)
        self.assertEqual(classified.reason, ModelErrorKind.CONTEXT_OVERFLOW)

        timeout = classify_model_error(socket.timeout("read timed out"))
        self.assertEqual(timeout.reason, ModelErrorKind.TIMEOUT)
        self.assertTrue(timeout.retryable)

    def test_format_error_and_unknown_defaults(self) -> None:
        format_error = classify_provider_error(status_code=422, message="schema validation failed")
        self.assertEqual(format_error.reason, ModelErrorKind.FORMAT_ERROR)
        self.assertFalse(format_error.retryable)
        self.assertTrue(format_error.should_fallback)

        unknown = classify_model_error(message="provider returned a strange result")
        self.assertEqual(unknown.reason, ModelErrorKind.UNKNOWN)
        self.assertTrue(unknown.retryable)
        self.assertFalse(unknown.should_fallback)


if __name__ == "__main__":
    unittest.main()
