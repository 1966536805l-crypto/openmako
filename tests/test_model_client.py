from __future__ import annotations

import os
import json
from io import BytesIO
import urllib.error
import unittest
from unittest.mock import patch

from quantagent.model_client import ModelClient, ModelRequest, resolve_model_token_profile
from quantagent.model_errors import ModelErrorKind


class ModelClientTest(unittest.TestCase):
    def test_bad_retry_env_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"QUANTAGENT_MODEL_MAX_RETRIES": "many"}, clear=False):
            client = ModelClient(api_key="test-key")

        self.assertEqual(client.max_retries, 3)

    def test_negative_retry_count_is_clamped(self) -> None:
        client = ModelClient(api_key="test-key", max_retries=-5)

        self.assertEqual(client.max_retries, 0)

    def test_timeout_can_come_from_environment(self) -> None:
        with patch.dict(os.environ, {"QUANTAGENT_MODEL_TIMEOUT_SECONDS": "7.5"}, clear=False):
            client = ModelClient(api_key="test-key")

        self.assertEqual(client.timeout, 7.5)

    def test_bad_timeout_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"QUANTAGENT_MODEL_TIMEOUT_SECONDS": "slow"}, clear=False):
            client = ModelClient(api_key="test-key")

        self.assertEqual(client.timeout, 60.0)

    def test_missing_api_key_is_classified_for_runtime_recovery(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "QUANTAGENT_OPENAI_API_KEY": ""}, clear=False):
            client = ModelClient(api_key="")

        response = client.complete(ModelRequest(model="gpt-test", prompt="hi"))

        self.assertFalse(response.ok)
        self.assertEqual(response.error_kind, ModelErrorKind.AUTH.value)
        self.assertFalse(response.retryable)
        self.assertTrue(response.should_rotate_credential)
        self.assertTrue(response.should_fallback)

    def test_retry_uses_error_classifier_for_overloaded_statuses(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        calls = []

        def fake_urlopen(*_args, **_kwargs):
            calls.append("call")
            if len(calls) == 1:
                raise urllib.error.HTTPError("https://example.test", 529, "overloaded", {}, BytesIO(b"overloaded"))
            return FakeResponse()

        client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=1)

        with patch("urllib.request.urlopen", fake_urlopen), patch("time.sleep", lambda *_args, **_kwargs: None):
            response = client.complete(ModelRequest(model="gpt-test", prompt="hi"))

        self.assertTrue(response.ok)
        self.assertEqual(response.text, "ok")
        self.assertEqual(len(calls), 2)

    def test_model_token_profile_hints_and_overrides_are_available(self) -> None:
        hinted = resolve_model_token_profile("deepseek-chat")
        self.assertEqual(hinted.context_window_tokens, 64_000)
        self.assertEqual(hinted.output_reserve_tokens, 8_000)

        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            context_window_tokens=4096,
            output_reserve_tokens=512,
        )
        profile = client._token_profile("unknown-model")

        self.assertEqual(profile.context_window_tokens, 4096)
        self.assertEqual(profile.output_reserve_tokens, 512)
        self.assertEqual(profile.available_input_tokens, 3584)

    def test_preflight_budget_compacts_before_request_and_preserves_user_block(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        calls: list[dict[str, object]] = []

        def fake_urlopen(request, **_kwargs):
            body = request.data if isinstance(request.data, bytes) else bytes(request.data or b"")
            calls.append({"bytes": len(body), "payload": json.loads(body.decode("utf-8"))})
            return FakeResponse()

        user_block = "\n\nUser:\nKEEP_THIS_USER_REQUEST_EXACT\n"
        long_prompt = "Project context:\n" + ("context detail\n" * 3000) + user_block
        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=0,
            context_window_tokens=2000,
            output_reserve_tokens=200,
            preflight_pressure_threshold=0.8,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.complete(ModelRequest(model="gpt-test", prompt=long_prompt))

        self.assertTrue(response.ok)
        self.assertEqual(len(calls), 1)
        self.assertTrue(response.compression)
        self.assertTrue(response.compression["applied"])
        self.assertEqual(response.compression["reason"], "preflight_token_pressure")
        self.assertEqual(response.compression["mode"], "preflight")
        self.assertTrue(response.token_budget)
        self.assertTrue(response.token_budget["preflight_applied"])
        self.assertEqual(response.token_budget["pressure_state"], "overflow")
        self.assertEqual(response.token_budget["model_profile"]["source"], "env_or_constructor_override")
        self.assertLess(response.token_budget["compressed_estimated_tokens"], response.token_budget["original_estimated_tokens"])
        compacted_prompt = calls[0]["payload"]["messages"][0]["content"]  # type: ignore[index]
        self.assertIn("OpenMako compressed prompt", compacted_prompt)
        self.assertTrue(str(compacted_prompt).endswith(user_block))
        self.assertLess(calls[0]["bytes"], len(json.dumps({"prompt": long_prompt}).encode("utf-8")))

    def test_token_budget_is_recorded_without_preflight_compression(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=0,
            context_window_tokens=100_000,
            output_reserve_tokens=1_000,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.complete(ModelRequest(model="gpt-test", system="system", prompt="small prompt"))

        self.assertTrue(response.ok)
        self.assertIsNone(response.compression)
        self.assertTrue(response.token_budget)
        self.assertFalse(response.token_budget["preflight_applied"])
        self.assertEqual(response.token_budget["pressure_state"], "ok")
        self.assertEqual(response.token_budget["model_profile"]["available_input_tokens"], 99_000)

    def test_preflight_budget_can_be_disabled(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        calls: list[dict[str, object]] = []

        def fake_urlopen(request, **_kwargs):
            body = request.data if isinstance(request.data, bytes) else bytes(request.data or b"")
            calls.append({"payload": json.loads(body.decode("utf-8"))})
            return FakeResponse()

        long_prompt = "Project context:\n" + ("context detail\n" * 3000) + "\n\nUser:\nKEEP\n"
        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=0,
            context_window_tokens=2000,
            output_reserve_tokens=200,
            preflight_pressure_threshold=0.8,
            preflight_compression=False,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            response = client.complete(ModelRequest(model="gpt-test", prompt=long_prompt))

        self.assertTrue(response.ok)
        self.assertIsNone(response.compression)
        self.assertTrue(response.token_budget)
        self.assertFalse(response.token_budget["preflight_compression_enabled"])
        self.assertFalse(response.token_budget["preflight_applied"])
        self.assertTrue(response.token_budget["over_soft_limit"])
        sent_prompt = calls[0]["payload"]["messages"][0]["content"]  # type: ignore[index]
        self.assertEqual(sent_prompt, long_prompt)

    def test_compressible_payload_error_without_savings_is_not_retried(self) -> None:
        calls = []

        def fake_urlopen(*_args, **_kwargs):
            calls.append("call")
            raise urllib.error.HTTPError("https://example.test", 413, "payload too large", {}, BytesIO(b"payload too large"))

        client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=3)

        with patch("urllib.request.urlopen", fake_urlopen), patch("time.sleep", lambda *_args, **_kwargs: None):
            response = client.complete(ModelRequest(model="gpt-test", prompt="hi"))

        self.assertFalse(response.ok)
        self.assertEqual(response.error_kind, ModelErrorKind.PAYLOAD_TOO_LARGE.value)
        self.assertTrue(response.should_compress)
        self.assertEqual(len(calls), 1)

    def test_compressible_context_error_retries_with_compacted_prompt(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"compressed ok"}}]}'

        calls: list[dict[str, object]] = []

        def fake_urlopen(request, **_kwargs):
            body = request.data if isinstance(request.data, bytes) else bytes(request.data or b"")
            payload = json.loads(body.decode("utf-8"))
            calls.append({"bytes": len(body), "payload": payload})
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://example.test",
                    400,
                    "context overflow",
                    {},
                    BytesIO(b"maximum context length exceeded"),
                )
            return FakeResponse()

        long_prompt = "BEGIN\n" + ("middle detail\n" * 4000) + "END user request"
        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=0,
            compressed_prompt_tokens=1200,
        )

        with patch("urllib.request.urlopen", fake_urlopen), patch("time.sleep", lambda *_args, **_kwargs: None):
            response = client.complete(ModelRequest(model="gpt-test", prompt=long_prompt))

        self.assertTrue(response.ok)
        self.assertEqual(response.text, "compressed ok")
        self.assertEqual(len(calls), 2)
        self.assertLess(calls[1]["bytes"], calls[0]["bytes"])
        self.assertTrue(response.compression)
        self.assertTrue(response.compression["applied"])
        self.assertEqual(response.compression["reason"], ModelErrorKind.CONTEXT_OVERFLOW.value)
        self.assertTrue(response.token_budget)
        self.assertTrue(response.token_budget["provider_retry_applied"])
        self.assertEqual(response.token_budget["provider_retry_reason"], ModelErrorKind.CONTEXT_OVERFLOW.value)
        compacted_prompt = calls[1]["payload"]["messages"][0]["content"]  # type: ignore[index]
        self.assertIn("OpenMako compressed prompt", compacted_prompt)
        self.assertIn("BEGIN", compacted_prompt)
        self.assertIn("END user request", compacted_prompt)

    def test_compressible_body_beats_retryable_status_before_normal_retries(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"compressed ok"}}]}'

        calls: list[dict[str, object]] = []

        def fake_urlopen(request, **_kwargs):
            body = request.data if isinstance(request.data, bytes) else bytes(request.data or b"")
            payload = json.loads(body.decode("utf-8"))
            calls.append({"bytes": len(body), "payload": payload})
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://example.test",
                    429,
                    "rate limited",
                    {},
                    BytesIO(b"prompt is too long"),
                )
            return FakeResponse()

        long_prompt = "BEGIN\n" + ("token detail\n" * 4000) + "END user request"
        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=3,
            compressed_prompt_tokens=1200,
        )

        with patch("urllib.request.urlopen", fake_urlopen), patch("time.sleep", lambda *_args, **_kwargs: None):
            response = client.complete(ModelRequest(model="gpt-test", prompt=long_prompt))

        self.assertTrue(response.ok)
        self.assertTrue(response.compression)
        self.assertTrue(response.compression["applied"])
        self.assertEqual(response.compression["reason"], ModelErrorKind.CONTEXT_OVERFLOW.value)
        self.assertEqual(len(calls), 2)
        compacted_prompt = calls[1]["payload"]["messages"][0]["content"]  # type: ignore[index]
        self.assertIn("OpenMako compressed prompt", compacted_prompt)

    def test_compressible_payload_error_gets_one_compacted_retry_not_normal_retries(self) -> None:
        calls = []

        def fake_urlopen(request, **_kwargs):
            calls.append(request)
            raise urllib.error.HTTPError("https://example.test", 413, "payload too large", {}, BytesIO(b"payload too large"))

        long_prompt = "BEGIN\n" + ("payload detail\n" * 4000) + "END user request"
        client = ModelClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_retries=3,
            compressed_prompt_tokens=1200,
        )

        with patch("urllib.request.urlopen", fake_urlopen), patch("time.sleep", lambda *_args, **_kwargs: None):
            response = client.complete(ModelRequest(model="gpt-test", prompt=long_prompt))

        self.assertFalse(response.ok)
        self.assertEqual(response.error_kind, ModelErrorKind.PAYLOAD_TOO_LARGE.value)
        self.assertTrue(response.should_compress)
        self.assertTrue(response.compression)
        self.assertTrue(response.compression["applied"])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
