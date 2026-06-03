from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from quantagent.agent_loop import QuantAgent
from quantagent.hook_runner import HookHandler
from quantagent.lifecycle_hooks import GLOBAL_HOOKS
from quantagent.model_client import ModelClient, ModelRequest, ModelResponse
from quantagent.runtime_store import ensure_runtime_store, list_budget_reservations, list_compact_events, list_model_calls, list_runtime_sessions


class TokenMechanismTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent token mechanism ")

    def test_agent_ask_model_attaches_project_for_cost_hooks(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.requests = []

            def complete(self, request):
                self.requests.append(request)
                return ModelResponse(model=request.model, ok=True, text="ok", provider="fake")

        with self.make_project() as tmp:
            project = Path(tmp)
            client = FakeClient()
            agent = QuantAgent(project, model="gpt-test")
            agent.client = client  # type: ignore[assignment]

            response = agent.ask_model("fix failing test", token_budget=6000)

        self.assertTrue(response.ok)
        self.assertEqual(client.requests[0].project, str(project))
        self.assertIn("Task:\nfix failing test", client.requests[0].prompt)

    def test_model_client_project_request_runs_lifecycle_hooks(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"total_tokens":3}}'

        sent_payloads: list[dict[str, object]] = []
        seen: list[str] = []

        def before(payload, context):
            seen.append("before:" + context.project)
            return payload | {"prompt": "hooked prompt"}

        def after(payload, context):
            seen.append("after:" + str(payload["usage"].get("total_tokens")))

        def fake_urlopen(request, **_kwargs):
            body = request.data if isinstance(request.data, bytes) else bytes(request.data or b"")
            sent_payloads.append(json.loads(body.decode("utf-8")))
            return FakeResponse()

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(HookHandler("before_model_call", before, plugin_id="test-token"))
            GLOBAL_HOOKS.register(HookHandler("after_model_call", after, plugin_id="test-token"))
            try:
                client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
                with patch("urllib.request.urlopen", fake_urlopen):
                    response = client.complete(ModelRequest(model="gpt-test", prompt="original", project=str(project), query_id="qa-token"))
            finally:
                GLOBAL_HOOKS.handlers = [handler for handler in GLOBAL_HOOKS.handlers if handler.plugin_id != "test-token"]

        self.assertTrue(response.ok)
        self.assertEqual(sent_payloads[0]["messages"][0]["content"], "hooked prompt")  # type: ignore[index]
        self.assertTrue(seen[0].startswith("before:"))
        self.assertEqual(seen[-1], "after:3")

    def test_model_client_records_token_ledger_and_session_totals(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return (
                    b'{"choices":[{"message":{"content":"ok"}}],'
                    b'"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18,'
                    b'"prompt_tokens_details":{"cached_tokens":3},'
                    b'"completion_tokens_details":{"reasoning_tokens":2},'
                    b'"actual_cost_usd":0.0123}}'
                )

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            with patch("urllib.request.urlopen", fake_urlopen):
                response = client.complete(
                    ModelRequest(
                        model="gpt-test",
                        system="system",
                        prompt="original",
                        project=str(project),
                        query_id="qa-ledger",
                        session_id="sess-ledger",
                    )
                )

            calls = list_model_calls(project, query_id="qa-ledger")
            sessions = list_runtime_sessions(project)

        self.assertTrue(response.ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].session_id, "sess-ledger")
        self.assertEqual(calls[0].input_tokens, 11)
        self.assertEqual(calls[0].output_tokens, 7)
        self.assertEqual(calls[0].total_tokens, 18)
        self.assertEqual(calls[0].cache_read_tokens, 3)
        self.assertEqual(calls[0].reasoning_tokens, 2)
        self.assertEqual(calls[0].actual_cost_usd, 0.0123)
        self.assertEqual(calls[0].pressure_state, "ok")
        self.assertGreaterEqual(calls[0].estimated_input_tokens, 1)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].api_call_count, 1)
        self.assertEqual(sessions[0].input_tokens, 11)
        self.assertEqual(sessions[0].output_tokens, 7)
        self.assertEqual(sessions[0].cache_read_tokens, 3)
        self.assertEqual(sessions[0].reasoning_tokens, 2)
        self.assertEqual(sessions[0].actual_cost_usd, 0.0123)
        self.assertEqual(sessions[0].cost_status, "actual")

    def test_model_client_estimates_cost_from_local_price_table(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":1000,"completion_tokens":500,"total_tokens":1500}}'

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        pricing = {
            "version": "test-pricing",
            "models": {
                "gpt-test": {
                    "input_per_million": 1.0,
                    "output_per_million": 2.0,
                }
            },
        }
        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_PRICING_JSON": json.dumps(pricing)}, clear=False):
                with patch("urllib.request.urlopen", fake_urlopen):
                    response = client.complete(
                        ModelRequest(
                            model="gpt-test",
                            prompt="priced",
                            project=str(project),
                            query_id="qa-priced",
                            session_id="sess-priced",
                        )
                    )

            calls = list_model_calls(project, query_id="qa-priced")
            sessions = list_runtime_sessions(project)

        self.assertTrue(response.ok)
        self.assertEqual(calls[0].cost_status, "estimated")
        self.assertEqual(calls[0].cost_source, "local_price_table")
        self.assertEqual(calls[0].pricing_version, "test-pricing")
        self.assertEqual(calls[0].estimated_cost_usd, 0.002)
        self.assertEqual(sessions[0].estimated_cost_usd, 0.002)
        self.assertEqual(sessions[0].cost_status, "estimated")

    def test_model_client_records_ledger_without_provider_usage(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            with patch("urllib.request.urlopen", fake_urlopen):
                response = client.complete(
                    ModelRequest(
                        model="gpt-test",
                        prompt="usage missing",
                        project=str(project),
                        query_id="qa-no-usage",
                    )
                )

            calls = list_model_calls(project, query_id="qa-no-usage")
            sessions = list_runtime_sessions(project)

        self.assertTrue(response.ok)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0].session_id)
        self.assertEqual(calls[0].input_tokens, 0)
        self.assertEqual(calls[0].output_tokens, 0)
        self.assertEqual(calls[0].cost_status, "unpriced")
        self.assertGreaterEqual(calls[0].estimated_input_tokens, 1)
        self.assertEqual(sessions, [])

    def test_budget_guard_blocks_before_network_and_records_attempt(self) -> None:
        calls: list[str] = []

        def fake_urlopen(*_args, **_kwargs):
            calls.append("called")
            raise AssertionError("network should be blocked before urlopen")

        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_REQUEST_ESTIMATED_TOKENS": "1"}, clear=False):
                with patch("urllib.request.urlopen", fake_urlopen):
                    response = client.complete(
                        ModelRequest(
                            model="gpt-test",
                            prompt="this request must exceed one estimated token",
                            project=str(project),
                            query_id="qa-budget-block",
                        )
                    )

            ledger = list_model_calls(project, query_id="qa-budget-block")

        self.assertFalse(response.ok)
        self.assertEqual(calls, [])
        self.assertIn("token budget guard blocked", response.error)
        self.assertTrue(response.token_budget)
        self.assertEqual(response.token_budget["budget_guard"]["status"], "blocked")
        self.assertEqual(len(ledger), 1)
        self.assertFalse(ledger[0].ok)
        self.assertGreaterEqual(ledger[0].estimated_input_tokens, 1)

    def test_model_client_concurrent_calls_respect_session_call_reservation(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}'

        network_calls: list[str] = []
        lock = threading.Lock()

        def fake_urlopen(*_args, **_kwargs):
            with lock:
                network_calls.append("call")
            time.sleep(0.12)
            return FakeResponse()

        with self.make_project() as tmp:
            project = Path(tmp)
            ensure_runtime_store(project)
            barrier = threading.Barrier(8)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)

            def complete(index: int) -> ModelResponse:
                barrier.wait()
                return client.complete(
                    ModelRequest(
                        model="gpt-test",
                        prompt=f"concurrent request {index}",
                        project=str(project),
                        query_id=f"qa-concurrent-{index}",
                        session_id="sess-concurrent",
                    )
                )

            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"}, clear=False):
                with patch("urllib.request.urlopen", fake_urlopen):
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        responses = list(pool.map(complete, range(8)))

            sessions = list_runtime_sessions(project)
            reservations = list_budget_reservations(project, session_id="sess-concurrent")
            model_calls = list_model_calls(project, session_id="sess-concurrent", limit=20)

        self.assertEqual(len(network_calls), 1)
        self.assertEqual(sum(1 for response in responses if response.ok), 1)
        self.assertEqual(sum(1 for response in responses if not response.ok), 7)
        self.assertEqual(sessions[0].api_call_count, 1)
        self.assertEqual(len([item for item in reservations if item.status == "committed"]), 1)
        self.assertEqual(len([item for item in model_calls if item.ok]), 1)
        self.assertEqual(len([item for item in model_calls if not item.ok]), 7)

    def test_model_client_network_error_releases_budget_reservation(self) -> None:
        def fake_urlopen(*_args, **_kwargs):
            raise TimeoutError("boom")

        with self.make_project() as tmp:
            project = Path(tmp)
            ensure_runtime_store(project)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "1"}, clear=False):
                with patch("urllib.request.urlopen", fake_urlopen):
                    response = client.complete(
                        ModelRequest(
                            model="gpt-test",
                            prompt="network timeout",
                            project=str(project),
                            query_id="qa-network",
                            session_id="sess-network",
                        )
                    )

            reservations = list_budget_reservations(project, session_id="sess-network")
            model_calls = list_model_calls(project, session_id="sess-network")
            sessions = list_runtime_sessions(project)

        self.assertFalse(response.ok)
        self.assertEqual(response.error_kind, "timeout")
        self.assertEqual(response.token_budget["budget_reservation"]["status"], "released")
        self.assertEqual(response.token_budget["budget_reservation"]["release_reason"], "timeout")
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0].status, "released")
        self.assertEqual(reservations[0].release_reason, "timeout")
        self.assertEqual(len(model_calls), 1)
        self.assertFalse(model_calls[0].ok)
        self.assertEqual(sessions[0].api_call_count, 0)

    def test_repeated_after_model_call_does_not_double_count_committed_reservation(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}'

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(base_url="https://example.test/v1", api_key="test-key", max_retries=0)
            request = ModelRequest(
                model="gpt-test",
                prompt="idempotent after call",
                project=str(project),
                query_id="qa-after-idem",
                session_id="sess-after-idem",
            )
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                with patch("urllib.request.urlopen", fake_urlopen):
                    response = client.complete(request)
                client._after_model_call(request, response, started_at_ms=response.started_at_ms)

            sessions = list_runtime_sessions(project)
            calls = list_model_calls(project, session_id="sess-after-idem")
            reservations = list_budget_reservations(project, session_id="sess-after-idem")

        self.assertTrue(response.ok)
        self.assertEqual(sessions[0].api_call_count, 1)
        self.assertEqual(sessions[0].input_tokens, 2)
        self.assertEqual(sessions[0].output_tokens, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len([item for item in reservations if item.status == "committed"]), 1)

    def test_preflight_compact_records_compact_event_and_lineage(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":20,"completion_tokens":4,"total_tokens":24}}'

        def fake_urlopen(*_args, **_kwargs):
            return FakeResponse()

        long_prompt = "Project context:\n" + ("context detail\n" * 3000) + "\n\nUser:\nKEEP\n"
        with self.make_project() as tmp:
            project = Path(tmp)
            client = ModelClient(
                base_url="https://example.test/v1",
                api_key="test-key",
                max_retries=0,
                context_window_tokens=2000,
                output_reserve_tokens=200,
                preflight_pressure_threshold=0.8,
            )
            with patch("urllib.request.urlopen", fake_urlopen):
                response = client.complete(
                    ModelRequest(
                        model="gpt-test",
                        prompt=long_prompt,
                        project=str(project),
                        query_id="qa-compact",
                        session_id="sess-compact",
                        task_id="task-1",
                        agent_id="agent-1",
                        run_id="run-1",
                    )
                )

            compact_events = list_compact_events(project, query_id="qa-compact")
            calls = list_model_calls(project, query_id="qa-compact")

        self.assertTrue(response.ok)
        self.assertTrue(response.token_budget)
        self.assertTrue(response.token_budget["preflight_applied"])
        self.assertEqual(len(compact_events), 1)
        self.assertTrue(compact_events[0].applied)
        self.assertEqual(compact_events[0].mode, "preflight")
        self.assertEqual(compact_events[0].reason, "preflight_token_pressure")
        self.assertTrue(compact_events[0].protected_user_request)
        self.assertGreater(compact_events[0].saved_estimated_tokens, 0)
        self.assertEqual(calls[0].task_id, "task-1")
        self.assertEqual(calls[0].agent_id, "agent-1")
        self.assertEqual(calls[0].run_id, "run-1")


if __name__ == "__main__":
    unittest.main()
