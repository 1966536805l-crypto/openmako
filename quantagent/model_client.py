from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from .lifecycle_hooks import run_lifecycle_hook
from .model_errors import ModelErrorClassification, classify_model_error
from .retry_utils import jittered_backoff, retry_after_seconds
from .runtime_store import (
    commit_budget_reservation,
    get_runtime_session,
    record_compact_event,
    record_model_call,
    release_budget_reservation,
    reserve_model_budget,
)
from .token_accounting import count_model_text_tokens, estimate_cost_usd, evaluate_budget_limits
from .trajectory_compact import estimate_tokens


DEFAULT_REASONING_EFFORT = "low"
DEFAULT_COMPRESSED_PROMPT_TOKENS = 24_000
MIN_COMPRESSED_PROMPT_TOKENS = 1_000
DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_MODEL_OUTPUT_RESERVE_TOKENS = 8_000
DEFAULT_PREFLIGHT_PRESSURE_THRESHOLD = 0.86


@dataclass(frozen=True)
class ModelTokenProfile:
    model: str
    context_window_tokens: int
    output_reserve_tokens: int
    source: str = "default"

    @property
    def available_input_tokens(self) -> int:
        return max(MIN_COMPRESSED_PROMPT_TOKENS, self.context_window_tokens - self.output_reserve_tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "context_window_tokens": self.context_window_tokens,
            "output_reserve_tokens": self.output_reserve_tokens,
            "available_input_tokens": self.available_input_tokens,
            "source": self.source,
        }


MODEL_TOKEN_PROFILE_HINTS: tuple[tuple[str, int, int], ...] = (
    ("gpt-4.1", 1_000_000, 16_000),
    ("gpt-4o", 128_000, 16_000),
    ("gpt-5", 400_000, 32_000),
    ("claude", 200_000, 16_000),
    ("gemini", 1_000_000, 32_000),
    ("qwen", 128_000, 8_000),
    ("kimi", 128_000, 8_000),
    ("deepseek", 64_000, 8_000),
)


@dataclass
class ModelRequest:
    model: str
    prompt: str
    system: str = ""
    project: str = ""
    query_id: str = ""
    session_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    run_id: str = ""


@dataclass
class ModelResponse:
    model: str
    text: str
    ok: bool
    error: str = ""
    provider: str = ""
    raw: dict[str, Any] | None = None
    classification: ModelErrorClassification | None = None
    compression: dict[str, Any] | None = None
    token_budget: dict[str, Any] | None = None
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    duration_ms: int | None = None

    @property
    def usage(self) -> dict[str, Any]:
        if not self.raw:
            return {}
        usage = self.raw.get("usage")
        return usage if isinstance(usage, dict) else {}

    def usage_summary(self) -> str:
        usage = self.usage
        if not usage:
            return "tokens: unavailable"
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
        completion = usage.get("completion_tokens") or usage.get("output_tokens")
        total = usage.get("total_tokens")
        parts = []
        if prompt is not None:
            parts.append(f"input={prompt}")
        if completion is not None:
            parts.append(f"output={completion}")
        if total is not None:
            parts.append(f"total={total}")
        return "tokens: " + (", ".join(parts) if parts else str(usage))

    @property
    def error_kind(self) -> str:
        return self.classification.reason.value if self.classification else ""

    @property
    def retryable(self) -> bool | None:
        return self.classification.retryable if self.classification else None

    @property
    def should_compress(self) -> bool:
        return bool(self.classification and self.classification.should_compress)

    @property
    def should_rotate_credential(self) -> bool:
        return bool(self.classification and self.classification.should_rotate_credential)

    @property
    def should_fallback(self) -> bool:
        return bool(self.classification and self.classification.should_fallback)


class ModelClient:
    """Small adapter boundary for OpenAI-compatible chat clients.

    Keys are read from environment variables only. Do not hardcode API keys in
    source files or project handoff documents.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        reasoning_effort: str | None = None,
        provider_group: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        compressed_prompt_tokens: int | None = None,
        context_window_tokens: int | None = None,
        output_reserve_tokens: int | None = None,
        preflight_pressure_threshold: float | None = None,
        preflight_compression: bool | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("QUANTAGENT_OPENAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("QUANTAGENT_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.reasoning_effort = reasoning_effort or os.environ.get("QUANTAGENT_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
        self.provider_group = provider_group or os.environ.get("QUANTAGENT_PROVIDER_GROUP", "")
        self.timeout = _parse_positive_float(
            timeout if timeout is not None else os.environ.get("QUANTAGENT_MODEL_TIMEOUT_SECONDS", "60"),
            default=60.0,
        )
        self.max_retries = _parse_nonnegative_int(
            max_retries if max_retries is not None else os.environ.get("QUANTAGENT_MODEL_MAX_RETRIES", "3"),
            default=3,
        )
        self.compressed_prompt_tokens = _parse_positive_int(
            compressed_prompt_tokens
            if compressed_prompt_tokens is not None
            else os.environ.get("QUANTAGENT_MODEL_COMPRESSED_PROMPT_TOKENS", str(DEFAULT_COMPRESSED_PROMPT_TOKENS)),
            default=DEFAULT_COMPRESSED_PROMPT_TOKENS,
            minimum=MIN_COMPRESSED_PROMPT_TOKENS,
        )
        self.context_window_tokens_override = _parse_optional_positive_int(
            context_window_tokens if context_window_tokens is not None else os.environ.get("QUANTAGENT_MODEL_CONTEXT_WINDOW_TOKENS"),
            minimum=MIN_COMPRESSED_PROMPT_TOKENS,
        )
        self.output_reserve_tokens_override = _parse_optional_positive_int(
            output_reserve_tokens if output_reserve_tokens is not None else os.environ.get("QUANTAGENT_MODEL_OUTPUT_RESERVE_TOKENS"),
            minimum=1,
        )
        self.preflight_pressure_threshold = _parse_fraction(
            preflight_pressure_threshold
            if preflight_pressure_threshold is not None
            else os.environ.get("QUANTAGENT_MODEL_PREFLIGHT_PRESSURE_THRESHOLD", str(DEFAULT_PREFLIGHT_PRESSURE_THRESHOLD)),
            default=DEFAULT_PREFLIGHT_PRESSURE_THRESHOLD,
            minimum=0.5,
            maximum=0.98,
        )
        self.preflight_compression = (
            _parse_bool_env(os.environ.get("QUANTAGENT_MODEL_PREFLIGHT_COMPRESSION"), default=True)
            if preflight_compression is None
            else bool(preflight_compression)
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, request: ModelRequest) -> ModelResponse:
        request = self._before_model_call(request)
        started_at_ms = _now_ms()
        if not self.api_key:
            classification = classify_model_error(
                status_code=401,
                provider=self.base_url,
                model=request.model,
                message="OPENAI_API_KEY or QUANTAGENT_OPENAI_API_KEY is not set.",
            )
            response = ModelResponse(
                model=request.model,
                ok=False,
                text="",
                error="OPENAI_API_KEY or QUANTAGENT_OPENAI_API_KEY is not set.",
                provider=self.base_url,
                classification=classification,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response
        url = self._chat_url()
        request, token_budget, preflight_compression = self._prepare_request_for_budget(request)
        guard_violation = self._budget_guard_violation(request, token_budget)
        if guard_violation:
            token_budget["budget_guard"] = guard_violation
            classification = classify_model_error(
                status_code=429,
                provider=self.base_url,
                model=request.model,
                message=guard_violation["summary"],
            )
            response = ModelResponse(
                model=request.model,
                ok=False,
                text="",
                error=guard_violation["summary"],
                provider=self.base_url,
                classification=classification,
                compression=preflight_compression,
                token_budget=token_budget,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response
        reservation_violation = self._reserve_budget(request, token_budget)
        if reservation_violation:
            classification = classify_model_error(
                status_code=429,
                provider=self.base_url,
                model=request.model,
                message=reservation_violation["summary"],
            )
            response = ModelResponse(
                model=request.model,
                ok=False,
                text="",
                error=reservation_violation["summary"],
                provider=self.base_url,
                classification=classification,
                compression=preflight_compression,
                token_budget=token_budget,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response
        payload = self._payload(request)
        try:
            raw = self._post_json(url, payload)
            text = self._extract_text(raw)
            if not text:
                classification = classify_model_error(
                    status_code=_status_from_raw(raw),
                    provider=self.base_url,
                    model=request.model,
                    message="No assistant text found in response.",
                    response_body=raw,
                )
                response = ModelResponse(
                    model=request.model,
                    ok=False,
                    text="",
                    error="No assistant text found in response.",
                    provider=self.base_url,
                    raw=raw,
                    classification=classification,
                    compression=preflight_compression,
                    token_budget=token_budget,
                )
                self._after_model_call(request, response, started_at_ms=started_at_ms)
                return response
            response = ModelResponse(
                model=request.model,
                ok=True,
                text=text,
                provider=self.base_url,
                raw=raw,
                compression=preflight_compression,
                token_budget=token_budget,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response
        except urllib.error.HTTPError as exc:
            body = _http_error_body(exc)
            classification = classify_model_error(
                exc,
                status_code=exc.code,
                provider=self.base_url,
                model=request.model,
                message=body,
                response_body=body,
            )
            if classification.should_compress:
                compressed_response = self._retry_with_compressed_request(
                    url,
                    request,
                    classification,
                    body,
                    previous_compression=preflight_compression,
                    previous_token_budget=token_budget,
                    started_at_ms=started_at_ms,
                )
                if compressed_response is not None:
                    return compressed_response
            response = ModelResponse(
                model=request.model,
                ok=False,
                text="",
                error=f"HTTP {exc.code}: {body}",
                provider=self.base_url,
                classification=classification,
                compression=preflight_compression,
                token_budget=token_budget,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response
        except Exception as exc:  # pragma: no cover - depends on local network/provider
            classification = classify_model_error(
                exc,
                provider=self.base_url,
                model=request.model,
                message=f"{type(exc).__name__}: {exc}",
            )
            response = ModelResponse(
                model=request.model,
                ok=False,
                text="",
                error=f"{type(exc).__name__}: {exc}",
                provider=self.base_url,
                classification=classification,
                compression=preflight_compression,
                token_budget=token_budget,
            )
            self._after_model_call(request, response, started_at_ms=started_at_ms)
            return response

    def _before_model_call(self, request: ModelRequest) -> ModelRequest:
        if not request.project:
            return request
        result = run_lifecycle_hook(
            Path(request.project),
            "before_model_call",
            {
                "model": request.model,
                "prompt": request.prompt,
                "system": request.system,
                "base_url": self.base_url,
            },
            query_id=request.query_id,
        )
        if result.blocked:
            raise PermissionError("; ".join(result.summaries or result.errors or ("model call blocked by hook",)))
        payload = result.payload
        return ModelRequest(
            model=str(payload.get("model") or request.model),
            prompt=str(payload.get("prompt") or request.prompt),
            system=str(payload.get("system") or request.system),
            project=request.project,
            query_id=request.query_id,
            session_id=request.session_id,
            task_id=request.task_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
        )

    def _after_model_call(self, request: ModelRequest, response: ModelResponse, *, started_at_ms: int | None = None) -> None:
        ended_at_ms = _now_ms()
        start = started_at_ms or response.started_at_ms or ended_at_ms
        response.started_at_ms = start
        response.ended_at_ms = ended_at_ms
        response.duration_ms = max(0, ended_at_ms - start)
        if not request.project:
            return
        model_call_id: int | None = None
        try:
            model_call_id = record_model_call(
                # Assigning to a local keeps the reservation terminal update
                # linked even if future callers need the model_call row id.
                # The insert itself remains best-effort observability.
                Path(request.project),
                model=response.model,
                provider=response.provider,
                ok=response.ok,
                query_id=request.query_id or None,
                session_id=request.session_id or None,
                task_id=request.task_id or None,
                agent_id=request.agent_id or None,
                run_id=request.run_id or None,
                usage=response.usage,
                token_budget=response.token_budget,
                compression=response.compression,
                error_kind=response.error_kind,
                error=response.error,
                started_at=response.started_at_ms,
                ended_at=response.ended_at_ms,
                duration_ms=response.duration_ms,
            )
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:354", exc)
        finally:
            self._finish_budget_reservation(request, response, model_call_id=model_call_id)
        run_lifecycle_hook(
            Path(request.project),
            "after_model_call",
            {
                "model": response.model,
                "ok": response.ok,
                "provider": response.provider,
                "usage": response.usage,
                "error": response.error,
                "error_kind": response.error_kind,
                "retryable": response.retryable,
                "should_compress": response.should_compress,
                "should_rotate_credential": response.should_rotate_credential,
                "should_fallback": response.should_fallback,
                "compression": response.compression or {},
                "token_budget": response.token_budget or {},
            },
            query_id=request.query_id,
        )

    def _chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def _messages(self, request: ModelRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = {
            "model": request.model,
            "messages": self._messages(request),
            "temperature": 0.2,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def _prepare_request_for_budget(self, request: ModelRequest) -> tuple[ModelRequest, dict[str, Any], dict[str, Any] | None]:
        profile = self._token_profile(request.model)
        system_estimate = count_model_text_tokens(request.system, request.model)
        prompt_estimate = count_model_text_tokens(request.prompt, request.model)
        original_system_tokens = system_estimate.count
        original_prompt_tokens = prompt_estimate.count
        original_tokens = original_system_tokens + original_prompt_tokens
        token_count_exact = system_estimate.exact and prompt_estimate.exact
        tokenizer_source = system_estimate.source if system_estimate.source == prompt_estimate.source else f"{system_estimate.source},{prompt_estimate.source}"
        available_tokens = profile.available_input_tokens
        soft_limit_tokens = max(MIN_COMPRESSED_PROMPT_TOKENS, int(available_tokens * self.preflight_pressure_threshold))
        pressure = round(original_tokens / max(1, available_tokens), 4)
        over_soft_limit = original_tokens > soft_limit_tokens
        token_budget = {
            "model_profile": profile.to_dict(),
            "original_estimated_tokens": original_tokens,
            "system_estimated_tokens": original_system_tokens,
            "prompt_estimated_tokens": original_prompt_tokens,
            "tokenizer_source": tokenizer_source,
            "token_count_exact": token_count_exact,
            "available_input_tokens": available_tokens,
            "soft_limit_tokens": soft_limit_tokens,
            "pressure": pressure,
            "pressure_state": _token_pressure_state(pressure, over_soft_limit=over_soft_limit),
            "over_soft_limit": over_soft_limit,
            "preflight_threshold": self.preflight_pressure_threshold,
            "preflight_compression_enabled": self.preflight_compression,
            "preflight_applied": False,
        }
        if not self.preflight_compression:
            return request, token_budget, None
        if original_tokens <= soft_limit_tokens:
            return request, token_budget, None
        compressed_request, compression = self._compressed_request(
            request,
            reason="preflight_token_pressure",
            mode="preflight",
            target_tokens=soft_limit_tokens,
            first_error_body="",
        )
        compression.update(
            {
                "model_profile": profile.to_dict(),
                "available_input_tokens": available_tokens,
                "soft_limit_tokens": soft_limit_tokens,
                "pressure": pressure,
                "pressure_state": token_budget["pressure_state"],
                "preflight_threshold": self.preflight_pressure_threshold,
            }
        )
        token_budget.update(
            {
                "preflight_applied": bool(compression.get("applied")),
                "target_tokens": compression.get("target_tokens"),
                "compressed_estimated_tokens": compression.get("compressed_estimated_tokens"),
                "saved_estimated_tokens": compression.get("saved_estimated_tokens"),
            }
        )
        return (compressed_request, token_budget, compression) if compression.get("applied") else (request, token_budget, compression)

    def _budget_guard_violation(self, request: ModelRequest, token_budget: dict[str, Any]) -> dict[str, Any] | None:
        request_tokens = int(token_budget.get("compressed_estimated_tokens") or token_budget.get("original_estimated_tokens") or 0)
        session_tokens = 0
        session_calls = 0
        session_cost = 0.0
        if request.project and request.session_id:
            session = get_runtime_session(Path(request.project), request.session_id)
            if session:
                session_tokens = session.input_tokens + session.output_tokens + session.reasoning_tokens
                session_calls = session.api_call_count
                session_cost = float(session.actual_cost_usd if session.actual_cost_usd is not None else session.estimated_cost_usd or 0.0)
        estimated_output = int(((token_budget.get("model_profile") or {}).get("output_reserve_tokens") if isinstance(token_budget.get("model_profile"), dict) else 0) or 0)
        estimated_request_cost, _, _ = estimate_cost_usd(
            request.model,
            {"input_tokens": request_tokens, "output_tokens": estimated_output, "reasoning_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            request.project or None,
        )
        checks = evaluate_budget_limits(
            request_estimated_tokens=request_tokens,
            session_tokens=session_tokens,
            session_model_calls=session_calls,
            session_cost_usd=session_cost,
            estimated_request_cost_usd=estimated_request_cost,
        )
        if not checks:
            token_budget["budget_guard"] = {"status": "not_configured"}
            return None
        payload = {
            "status": "allowed",
            "checks": [check.to_dict() for check in checks],
        }
        token_budget["budget_guard"] = payload
        exceeded = [check for check in checks if check.exceeded]
        if not exceeded:
            return None
        first = exceeded[0]
        return {
            "status": "blocked",
            "reason": "token_budget_exceeded",
            "summary": f"token budget guard blocked model call: {first.name} projected {first.projected} > limit {first.limit} {first.unit}",
            "checks": [check.to_dict() for check in checks],
        }

    def _reserve_budget(self, request: ModelRequest, token_budget: dict[str, Any]) -> dict[str, Any] | None:
        if not request.project or not request.session_id:
            token_budget["budget_reservation"] = {"status": "not_required", "reason": "missing_project_or_session"}
            return None
        request_tokens = int(token_budget.get("compressed_estimated_tokens") or token_budget.get("original_estimated_tokens") or 0)
        estimated_output = int(((token_budget.get("model_profile") or {}).get("output_reserve_tokens") if isinstance(token_budget.get("model_profile"), dict) else 0) or 0)
        estimated_request_cost, _, _ = estimate_cost_usd(
            request.model,
            {"input_tokens": request_tokens, "output_tokens": estimated_output, "reasoning_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            request.project,
        )
        try:
            reservation = reserve_model_budget(
                Path(request.project),
                session_id=request.session_id,
                model=request.model,
                provider=self.base_url,
                estimated_tokens=request_tokens,
                estimated_cost_usd=estimated_request_cost,
                query_id=request.query_id or None,
                task_id=request.task_id or None,
                agent_id=request.agent_id or None,
                run_id=request.run_id or None,
                checks=(token_budget.get("budget_guard") or {}).get("checks") if isinstance(token_budget.get("budget_guard"), dict) else None,
            )
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:599", exc)
            reservation = {
                "status": "blocked",
                "reason": "budget_reservation_failed",
                "summary": f"budget reservation failed closed: {type(exc).__name__}: {exc}",
                "checks": [],
            }
        token_budget["budget_reservation"] = reservation
        if reservation.get("status") == "blocked":
            return reservation
        return None

    def _finish_budget_reservation(self, request: ModelRequest, response: ModelResponse, *, model_call_id: int | None = None) -> None:
        token_budget = response.token_budget or {}
        reservation = token_budget.get("budget_reservation")
        if not isinstance(reservation, dict):
            return
        reservation_id = str(reservation.get("reservation_id") or "")
        if not reservation_id or not request.project:
            return
        usage = response.usage
        try:
            if usage:
                committed = commit_budget_reservation(
                    Path(request.project),
                    reservation_id,
                    actual_tokens=_usage_total_tokens(usage),
                    actual_cost_usd=_usage_cost_usd(usage),
                    model_call_id=model_call_id,
                )
                if committed:
                    reservation["status"] = "committed"
                    if model_call_id is not None:
                        reservation["model_call_id"] = model_call_id
            else:
                released = release_budget_reservation(
                    Path(request.project),
                    reservation_id,
                    reason=response.error_kind or response.error or "provider_usage_unavailable",
                    model_call_id=model_call_id,
                )
                if released:
                    reservation["status"] = "released"
                    if model_call_id is not None:
                        reservation["model_call_id"] = model_call_id
                    reservation["release_reason"] = response.error_kind or response.error or "provider_usage_unavailable"
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:641", exc)

    def _token_profile(self, model: str) -> ModelTokenProfile:
        profile = resolve_model_token_profile(model)
        context_window = self.context_window_tokens_override or profile.context_window_tokens
        output_reserve = min(
            max(1, self.output_reserve_tokens_override or profile.output_reserve_tokens),
            max(1, context_window - MIN_COMPRESSED_PROMPT_TOKENS),
        )
        source = profile.source
        if self.context_window_tokens_override is not None or self.output_reserve_tokens_override is not None:
            source = "env_or_constructor_override"
        return ModelTokenProfile(model=model, context_window_tokens=context_window, output_reserve_tokens=output_reserve, source=source)

    def _retry_with_compressed_request(
        self,
        url: str,
        request: ModelRequest,
        classification: ModelErrorClassification,
        first_error_body: str,
        previous_compression: dict[str, Any] | None = None,
        previous_token_budget: dict[str, Any] | None = None,
        started_at_ms: int | None = None,
    ) -> ModelResponse | None:
        compressed_request, compression = self._compressed_request(
            request,
            classification=classification,
            first_error_body=first_error_body,
            target_tokens=max(MIN_COMPRESSED_PROMPT_TOKENS, self.compressed_prompt_tokens),
            mode="provider_error_retry",
        )
        if previous_compression:
            compression["previous"] = previous_compression
        token_budget = _token_budget_with_retry(previous_token_budget, compression)
        if not compression.get("applied"):
            return None
        if token_budget:
            guard_violation = self._budget_guard_violation(compressed_request, token_budget)
            if guard_violation:
                token_budget["budget_guard"] = guard_violation
                blocked = classify_model_error(
                    status_code=429,
                    provider=self.base_url,
                    model=compressed_request.model,
                    message=guard_violation["summary"],
                )
                response = ModelResponse(
                    model=compressed_request.model,
                    ok=False,
                    text="",
                    error=guard_violation["summary"],
                    provider=self.base_url,
                    classification=blocked,
                    compression=compression,
                    token_budget=token_budget,
                )
                self._after_model_call(compressed_request, response, started_at_ms=started_at_ms)
                return response
        try:
            raw = self._post_json(url, self._payload(compressed_request))
            text = self._extract_text(raw)
            if not text:
                no_text = classify_model_error(
                    status_code=_status_from_raw(raw),
                    provider=self.base_url,
                    model=compressed_request.model,
                    message="No assistant text found in compressed retry response.",
                    response_body=raw,
                )
                response = ModelResponse(
                    model=compressed_request.model,
                    ok=False,
                    text="",
                    error="No assistant text found in compressed retry response.",
                    provider=self.base_url,
                    raw=raw,
                    classification=no_text,
                    compression=compression,
                    token_budget=token_budget,
                )
                self._after_model_call(compressed_request, response, started_at_ms=started_at_ms)
                return response
            response = ModelResponse(
                model=compressed_request.model,
                ok=True,
                text=text,
                provider=self.base_url,
                raw=raw,
                compression=compression,
                token_budget=token_budget,
            )
            self._after_model_call(compressed_request, response, started_at_ms=started_at_ms)
            return response
        except urllib.error.HTTPError as exc:
            body = _http_error_body(exc)
            failed = classify_model_error(
                exc,
                status_code=exc.code,
                provider=self.base_url,
                model=compressed_request.model,
                message=body,
                response_body=body,
            )
            response = ModelResponse(
                model=compressed_request.model,
                ok=False,
                text="",
                error=f"HTTP {exc.code}: {body}",
                provider=self.base_url,
                classification=failed,
                compression=compression,
                token_budget=token_budget,
            )
            self._after_model_call(compressed_request, response, started_at_ms=started_at_ms)
            return response
        except Exception as exc:
            failed = classify_model_error(
                exc,
                provider=self.base_url,
                model=compressed_request.model,
                message=f"{type(exc).__name__}: {exc}",
            )
            response = ModelResponse(
                model=compressed_request.model,
                ok=False,
                text="",
                error=f"{type(exc).__name__}: {exc}",
                provider=self.base_url,
                classification=failed,
                compression=compression,
                token_budget=token_budget,
            )
            self._after_model_call(compressed_request, response, started_at_ms=started_at_ms)
            return response

    def _compressed_request(
        self,
        request: ModelRequest,
        classification: ModelErrorClassification | None = None,
        first_error_body: str = "",
        *,
        target_tokens: int | None = None,
        reason: str | None = None,
        mode: str = "provider_error_retry",
    ) -> tuple[ModelRequest, dict[str, Any]]:
        reason = reason or (classification.reason.value if classification else "token_pressure")
        target_tokens = max(MIN_COMPRESSED_PROMPT_TOKENS, target_tokens or self.compressed_prompt_tokens)
        original_system = count_model_text_tokens(request.system, request.model)
        original_prompt = count_model_text_tokens(request.prompt, request.model)
        original_system_tokens = original_system.count
        original_prompt_tokens = original_prompt.count
        token_count_exact = original_system.exact and original_prompt.exact
        tokenizer_source = original_system.source if original_system.source == original_prompt.source else f"{original_system.source},{original_prompt.source}"
        system_target = max(200, min(target_tokens // 5, max(200, original_system_tokens)))
        prompt_target = max(400, target_tokens - min(system_target, original_system_tokens))
        compressed_system = _compact_text_to_token_budget(
            request.system,
            system_target,
            label="system",
            reason=reason,
        )
        compressed_prompt = _compact_prompt_to_token_budget(
            request.prompt,
            prompt_target,
            label="prompt",
            reason=reason,
        )
        original_tokens = original_system_tokens + original_prompt_tokens
        compressed_system_tokens = count_model_text_tokens(compressed_system, request.model).count
        compressed_prompt_tokens = count_model_text_tokens(compressed_prompt, request.model).count
        compressed_tokens = compressed_system_tokens + compressed_prompt_tokens
        applied = compressed_tokens < original_tokens and (compressed_system != request.system or compressed_prompt != request.prompt)
        protected_user_request = _last_current_user_marker(request.prompt) >= 0 or request.prompt.startswith("Task:\n")
        compression = {
            "applied": applied,
            "reason": reason,
            "mode": mode,
            "target_tokens": target_tokens,
            "tokenizer_source": tokenizer_source,
            "token_count_exact": token_count_exact,
            "protected_user_request": protected_user_request,
            "original_estimated_tokens": original_tokens,
            "compressed_estimated_tokens": compressed_tokens,
            "saved_estimated_tokens": max(0, original_tokens - compressed_tokens),
            "original_system_estimated_tokens": original_system_tokens,
            "original_prompt_estimated_tokens": original_prompt_tokens,
            "compressed_system_estimated_tokens": compressed_system_tokens,
            "compressed_prompt_estimated_tokens": compressed_prompt_tokens,
            "first_error_preview": first_error_body[:500],
        }
        if request.project:
            try:
                compact_event_id = record_compact_event(
                    Path(request.project),
                    model=request.model,
                    reason=reason,
                    mode=mode,
                    applied=applied,
                    query_id=request.query_id or None,
                    session_id=request.session_id or None,
                    task_id=request.task_id or None,
                    agent_id=request.agent_id or None,
                    run_id=request.run_id or None,
                    target_tokens=target_tokens,
                    original_estimated_tokens=original_tokens,
                    compacted_estimated_tokens=compressed_tokens,
                    saved_estimated_tokens=max(0, original_tokens - compressed_tokens),
                    protected_user_request=protected_user_request,
                    tokenizer_source=tokenizer_source,
                    token_count_exact=token_count_exact,
                    details={"first_error_preview": first_error_body[:500]},
                )
                compression["compact_event_id"] = compact_event_id
            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:642", exc)
        if not applied:
            return request, compression
        return (
            ModelRequest(
                model=request.model,
                system=compressed_system,
                prompt=compressed_prompt,
                project=request.project,
                query_id=request.query_id,
                session_id=request.session_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                run_id=request.run_id,
            ),
            compression,
        )

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        attempts = max(1, self.max_retries + 1)
        last_timeout: Exception | None = None
        for attempt in range(1, attempts + 1):
            http_request = urllib.request.Request(
                url,
                data=data,
                headers=self._headers(),
                method="POST",
            )
            try:
                with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = _http_error_body(exc)
                classification = classify_model_error(
                    exc,
                    status_code=exc.code,
                    provider=self.base_url,
                    message=body,
                    response_body=body,
                )
                if attempt >= attempts or not _should_retry_classified_error(classification):
                    raise _http_error_with_body(exc, body)
                delay = retry_after_seconds(exc.headers.get("Retry-After")) or jittered_backoff(attempt)
                time.sleep(min(delay, 30.0))
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                last_timeout = exc
                classification = classify_model_error(exc, provider=self.base_url)
                if attempt >= attempts or not _should_retry_classified_error(classification):
                    raise
                time.sleep(min(jittered_backoff(attempt), 30.0))
        if last_timeout:
            raise last_timeout
        raise RuntimeError("model request failed without a response")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if self.provider_group:
            headers.update(
                {
                    "X-Provider-Group": self.provider_group,
                    "X-Model-Group": self.provider_group,
                    "X-OneAPI-Group": self.provider_group,
                    "New-Api-Group": self.provider_group,
                }
            )
        return headers

    def _extract_text(self, raw: dict[str, Any]) -> str:
        choices = raw.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return "\n".join(parts).strip()
        output = raw.get("output")
        if isinstance(output, list):
            parts = []
            for item in output:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        parts.append(content["text"])
            return "\n".join(parts).strip()
        return ""


def _parse_nonnegative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _usage_total_tokens(usage: dict[str, Any]) -> int:
    total = _int_value(usage.get("total_tokens") or usage.get("totalTokens"))
    if total:
        return total
    input_tokens = _int_value(usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("inputTokens"))
    output_tokens = _int_value(usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokens"))
    reasoning_tokens = _int_value(usage.get("reasoning_tokens"))
    if not reasoning_tokens:
        reasoning_tokens = _nested_int_value(usage, "completion_tokens_details", "reasoning_tokens") or _nested_int_value(usage, "output_tokens_details", "reasoning_tokens")
    return input_tokens + output_tokens + reasoning_tokens


def _usage_cost_usd(usage: dict[str, Any]) -> float | None:
    for key in ("actual_cost_usd", "cost_usd", "total_cost_usd", "cost"):
        value = usage.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _nested_int_value(data: dict[str, Any], *keys: str) -> int:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _int_value(current)


def _parse_positive_int(value: Any, *, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _parse_optional_positive_int(value: Any, *, minimum: int = 1) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= minimum else None


def _parse_positive_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _parse_fraction(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum or parsed > maximum:
        return default
    return parsed


def _parse_bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _should_retry_classified_error(classification: ModelErrorClassification) -> bool:
    return classification.retryable and not classification.should_compress


def _token_pressure_state(pressure: float, *, over_soft_limit: bool = False) -> str:
    if pressure >= 1:
        return "overflow"
    if over_soft_limit or pressure >= DEFAULT_PREFLIGHT_PRESSURE_THRESHOLD:
        return "compact"
    if pressure >= 0.75:
        return "watch"
    return "ok"


def _token_budget_with_retry(previous_token_budget: dict[str, Any] | None, compression: dict[str, Any]) -> dict[str, Any] | None:
    if previous_token_budget is None:
        return None
    token_budget = dict(previous_token_budget)
    token_budget.update(
        {
            "provider_retry_applied": bool(compression.get("applied")),
            "provider_retry_reason": compression.get("reason"),
            "retry_target_tokens": compression.get("target_tokens"),
            "retry_compressed_estimated_tokens": compression.get("compressed_estimated_tokens"),
            "retry_saved_estimated_tokens": compression.get("saved_estimated_tokens"),
        }
    )
    return token_budget


def resolve_model_token_profile(model: str) -> ModelTokenProfile:
    normalized = model.lower()
    for marker, context_window, output_reserve in MODEL_TOKEN_PROFILE_HINTS:
        if marker in normalized:
            return ModelTokenProfile(
                model=model,
                context_window_tokens=context_window,
                output_reserve_tokens=output_reserve,
                source=f"hint:{marker}",
            )
    return ModelTokenProfile(
        model=model,
        context_window_tokens=DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS,
        output_reserve_tokens=DEFAULT_MODEL_OUTPUT_RESERVE_TOKENS,
    )


def _compact_prompt_to_token_budget(text: str, target_tokens: int, *, label: str, reason: str) -> str:
    if not text or estimate_tokens(text) <= target_tokens:
        return text
    prefix, compressible, suffix = _partition_prompt_for_compression(text)
    protected_tokens = estimate_tokens(prefix) + estimate_tokens(suffix)
    if compressible and protected_tokens < target_tokens:
        compressible_target = max(200, target_tokens - protected_tokens)
        compacted = _compact_text_to_token_budget(compressible, compressible_target, label=label, reason=reason)
        candidate = prefix + compacted + suffix
        if compacted != compressible:
            return candidate
    return _compact_text_to_token_budget(text, target_tokens, label=label, reason=reason)


def _partition_prompt_for_compression(text: str) -> tuple[str, str, str]:
    user_index = _last_current_user_marker(text)
    if user_index >= 0:
        return "", text[:user_index], text[user_index:]
    if text.startswith("Task:\n"):
        split_index = text.find("\n\n")
        if split_index > 0:
            return text[: split_index + 2], text[split_index + 2 :], ""
    return "", text, ""


def _last_current_user_marker(text: str) -> int:
    indexes = [text.rfind(marker) for marker in ("\n\nUser:\n", "\nUser:\n")]
    if text.startswith("User:\n"):
        indexes.append(0)
    return max(indexes)


def _compact_text_to_token_budget(text: str, target_tokens: int, *, label: str, reason: str) -> str:
    if not text or estimate_tokens(text) <= target_tokens:
        return text
    original_tokens = estimate_tokens(text)
    ratio = max(0.05, min(0.95, target_tokens / max(1, original_tokens)))
    char_budget = max(300, int(len(text) * ratio))
    compacted = _middle_omission_summary(text, char_budget, label=label, reason=reason, original_tokens=original_tokens, target_tokens=target_tokens)
    for _ in range(6):
        if estimate_tokens(compacted) <= target_tokens:
            return compacted
        char_budget = max(180, int(char_budget * 0.72))
        compacted = _middle_omission_summary(text, char_budget, label=label, reason=reason, original_tokens=original_tokens, target_tokens=target_tokens)
    return compacted


def _middle_omission_summary(
    text: str,
    char_budget: int,
    *,
    label: str,
    reason: str,
    original_tokens: int,
    target_tokens: int,
) -> str:
    header = (
        f"[OpenMako compressed {label} for model retry]\n"
        f"Reason: {reason}\n"
        f"Original estimated tokens: {original_tokens}\n"
        f"Target estimated tokens: {target_tokens}\n"
        "The middle of this field was omitted after the provider reported a token/payload overflow.\n"
    )
    available = max(80, char_budget - len(header) - 120)
    head_chars = max(40, available // 3)
    tail_chars = max(80, available - head_chars)
    if head_chars + tail_chars >= len(text):
        body = text[:char_budget]
    else:
        body = (
            "--- preserved beginning ---\n"
            f"{text[:head_chars].rstrip()}\n"
            "--- omitted middle ---\n"
            f"{max(0, len(text) - head_chars - tail_chars):,} characters omitted.\n"
            "--- preserved ending ---\n"
            f"{text[-tail_chars:].lstrip()}"
        )
    return header + body


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:2000]
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:865", exc)
        return str(exc)[:2000]


def _http_error_with_body(exc: urllib.error.HTTPError, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(exc.url, exc.code, exc.msg, exc.headers, BytesIO(body.encode("utf-8")))


def _status_from_raw(raw: dict[str, Any]) -> int | None:
    for key in ("status_code", "status", "code"):
        value = raw.get(key)
        try:
            status = int(value)
        except (TypeError, ValueError):
            continue
        if 100 <= status <= 599:
            return status
    return None
