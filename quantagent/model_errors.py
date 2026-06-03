from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import enum
import json
import re
import socket
import urllib.error
from dataclasses import dataclass, field
from typing import Any


class ModelErrorKind(str, enum.Enum):
    """Provider error taxonomy used by retry and failover decisions."""

    AUTH = "auth"
    auth = "auth"
    AUTH_PERMANENT = "auth_permanent"
    auth_permanent = "auth_permanent"
    BILLING = "billing"
    billing = "billing"
    RATE_LIMIT = "rate_limit"
    rate_limit = "rate_limit"
    OVERLOADED = "overloaded"
    overloaded = "overloaded"
    SERVER_ERROR = "server_error"
    server_error = "server_error"
    TIMEOUT = "timeout"
    timeout = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    context_overflow = "context_overflow"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    payload_too_large = "payload_too_large"
    IMAGE_TOO_LARGE = "image_too_large"
    image_too_large = "image_too_large"
    MODEL_NOT_FOUND = "model_not_found"
    model_not_found = "model_not_found"
    PROVIDER_POLICY_BLOCKED = "provider_policy_blocked"
    provider_policy_blocked = "provider_policy_blocked"
    FORMAT_ERROR = "format_error"
    format_error = "format_error"
    MULTIMODAL_TOOL_CONTENT_UNSUPPORTED = "multimodal_tool_content_unsupported"
    multimodal_tool_content_unsupported = "multimodal_tool_content_unsupported"
    UNKNOWN = "unknown"
    unknown = "unknown"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ModelErrorClassification:
    reason: ModelErrorKind
    status_code: int | None = None
    provider: str | None = None
    model: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = True
    should_compress: bool = False
    should_rotate_credential: bool = False
    should_fallback: bool = False

    @property
    def kind(self) -> ModelErrorKind:
        return self.reason

    @property
    def is_auth(self) -> bool:
        return self.reason in {ModelErrorKind.AUTH, ModelErrorKind.AUTH_PERMANENT}


_ACTION_HINTS: dict[ModelErrorKind, dict[str, bool]] = {
    ModelErrorKind.AUTH: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": True,
        "should_fallback": True,
    },
    ModelErrorKind.AUTH_PERMANENT: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.BILLING: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": True,
        "should_fallback": True,
    },
    ModelErrorKind.RATE_LIMIT: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": True,
        "should_fallback": True,
    },
    ModelErrorKind.OVERLOADED: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": True,
    },
    ModelErrorKind.SERVER_ERROR: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": True,
    },
    ModelErrorKind.TIMEOUT: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.CONTEXT_OVERFLOW: {
        "retryable": True,
        "should_compress": True,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.PAYLOAD_TOO_LARGE: {
        "retryable": True,
        "should_compress": True,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.IMAGE_TOO_LARGE: {
        "retryable": True,
        "should_compress": True,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.MODEL_NOT_FOUND: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": True,
    },
    ModelErrorKind.PROVIDER_POLICY_BLOCKED: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.FORMAT_ERROR: {
        "retryable": False,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": True,
    },
    ModelErrorKind.MULTIMODAL_TOOL_CONTENT_UNSUPPORTED: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
    ModelErrorKind.UNKNOWN: {
        "retryable": True,
        "should_compress": False,
        "should_rotate_credential": False,
        "should_fallback": False,
    },
}

_AUTH_PERMANENT_PATTERNS = (
    "invalid api key",
    "incorrect api key",
    "api key is invalid",
    "api key not found",
    "invalid_api_key",
    "key has been revoked",
    "key has been disabled",
    "revoked api key",
    "expired api key",
    "not a valid api key",
)

_AUTH_PATTERNS = (
    "authentication failed",
    "authorization failed",
    "unauthorized",
    "forbidden",
    "access denied",
    "permission denied",
    "missing bearer token",
    "invalid bearer token",
    "token expired",
)

_BILLING_PATTERNS = (
    "insufficient quota",
    "insufficient_quota",
    "insufficient credits",
    "insufficient balance",
    "credit balance",
    "out of credits",
    "credits exhausted",
    "payment required",
    "billing",
    "plan and billing",
    "hard limit",
    "prepaid balance",
    "top up",
    "account is deactivated",
)

_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "throttle",
    "throttled",
    "requests per minute",
    "tokens per minute",
    "requests per day",
    "retry after",
    "try again in",
    "resource exhausted",
    "quota exceeded",
    "service quota exceeded",
    "too many concurrent requests",
)

_OVERLOADED_PATTERNS = (
    "overloaded",
    "server busy",
    "service unavailable",
    "temporarily unavailable",
    "at capacity",
    "capacity exceeded",
    "no healthy upstream",
    "upstream unavailable",
)

_SERVER_ERROR_PATTERNS = (
    "internal server error",
    "bad gateway",
    "upstream error",
    "backend error",
    "gateway error",
)

_TIMEOUT_PATTERNS = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "read timed out",
    "connection timed out",
    "gateway timeout",
)

_CONTEXT_OVERFLOW_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "max context",
    "too many tokens",
    "token limit",
    "prompt is too long",
    "prompt too long",
    "input is too long",
    "input too long",
    "maximum number of tokens",
    "context_length_exceeded",
    "max_tokens_exceeded",
    "max input token",
    "input tokens exceed",
    "exceeds max_model_len",
    "max_model_len",
    "maximum model length",
    "input token limit",
    "context length exceeded",
    "超过最大长度",
    "上下文长度",
)

_PAYLOAD_TOO_LARGE_PATTERNS = (
    "payload too large",
    "request entity too large",
    "request body too large",
    "request_too_large",
    "content length",
    "maximum request size",
)

_IMAGE_TOO_LARGE_PATTERNS = (
    "image too large",
    "image_too_large",
    "image exceeds",
    "image size exceeds",
    "maximum image size",
    "image file is too large",
)

_MODEL_NOT_FOUND_PATTERNS = (
    "model not found",
    "model_not_found",
    "invalid model",
    "unknown model",
    "no such model",
    "model does not exist",
    "does not exist or you do not have access",
    "unsupported model",
    "not a valid model",
)

_PROVIDER_POLICY_BLOCKED_PATTERNS = (
    "provider policy",
    "data policy",
    "data collection",
    "privacy setting",
    "guardrail restrictions",
    "no endpoints available matching",
    "provider restrictions",
)

_FORMAT_ERROR_PATTERNS = (
    "bad request",
    "invalid request",
    "invalid_request_error",
    "malformed",
    "invalid json",
    "schema validation",
    "validation error",
    "unsupported content type",
    "missing required parameter",
)

_MULTIMODAL_TOOL_CONTENT_PATTERNS = (
    "tool message content must be a string",
    "tool content must be a string",
    "tool message must be a string",
    "tool_call.content must be string",
    "expected string, got list",
    "expected string, got array",
    "content should be a valid string",
    "text is not set",
)

_HTTP_STATUS_PATTERN = re.compile(r"\b(?:http|status(?: code)?|error code)\D*([1-5]\d{2})\b")


def classify_model_error(
    error: Any = None,
    *,
    status_code: int | str | None = None,
    provider: str | None = None,
    model: str | None = None,
    message: str | None = None,
    body: Any = None,
    response_body: Any = None,
) -> ModelErrorClassification:
    """Classify provider failures into retry/failover actions.

    The classifier accepts plain exceptions, response dictionaries, strings,
    and explicit HTTP status/message fields. Specific provider messages win
    over broad HTTP status fallbacks, so a 400 context overflow is not treated
    as a generic request formatting error.
    """

    raw_parts: list[str] = []
    if message:
        raw_parts.append(message)
    raw_parts.extend(_text_fragments(response_body))
    raw_parts.extend(_text_fragments(body))
    raw_parts.extend(_text_fragments(error))

    combined = _compact_message(raw_parts)
    normalized = _normalize(combined)
    provider_text = _normalize(provider or "")

    resolved_status = (
        _coerce_status_code(status_code)
        or _status_from_value(error)
        or _status_from_value(response_body)
        or _status_from_value(body)
        or _status_from_text(combined)
    )

    reason = _classify_reason(error, resolved_status, normalized, provider_text)
    return _make_classification(
        reason,
        status_code=resolved_status,
        provider=provider,
        model=model,
        message=combined,
    )


def classify_provider_error(
    error: Any = None,
    **kwargs: Any,
) -> ModelErrorClassification:
    """Alias for callers that name the boundary by provider rather than model."""

    return classify_model_error(error, **kwargs)


def _classify_reason(
    error: Any,
    status_code: int | None,
    text: str,
    provider_text: str,
) -> ModelErrorKind:
    if _has_provider_policy_signal(text, provider_text):
        return ModelErrorKind.PROVIDER_POLICY_BLOCKED
    if _contains_any(text, _MULTIMODAL_TOOL_CONTENT_PATTERNS):
        return ModelErrorKind.MULTIMODAL_TOOL_CONTENT_UNSUPPORTED
    if _contains_any(text, _IMAGE_TOO_LARGE_PATTERNS):
        return ModelErrorKind.IMAGE_TOO_LARGE
    if _contains_any(text, _CONTEXT_OVERFLOW_PATTERNS):
        return ModelErrorKind.CONTEXT_OVERFLOW
    if status_code == 413 or _contains_any(text, _PAYLOAD_TOO_LARGE_PATTERNS):
        return ModelErrorKind.PAYLOAD_TOO_LARGE
    if _contains_any(text, _AUTH_PERMANENT_PATTERNS):
        return ModelErrorKind.AUTH_PERMANENT
    if status_code == 402 or _contains_any(text, _BILLING_PATTERNS):
        return ModelErrorKind.BILLING
    if status_code == 429 or _contains_any(text, _RATE_LIMIT_PATTERNS):
        return ModelErrorKind.RATE_LIMIT
    if status_code in {401, 403} or _contains_any(text, _AUTH_PATTERNS):
        return ModelErrorKind.AUTH
    if status_code == 404 or _contains_any(text, _MODEL_NOT_FOUND_PATTERNS):
        return ModelErrorKind.MODEL_NOT_FOUND
    if status_code in {503, 529} or _contains_any(text, _OVERLOADED_PATTERNS):
        return ModelErrorKind.OVERLOADED
    if status_code in {500, 502} or _contains_any(text, _SERVER_ERROR_PATTERNS):
        return ModelErrorKind.SERVER_ERROR
    if _is_timeout(error) or status_code in {408, 504} or _contains_any(text, _TIMEOUT_PATTERNS):
        return ModelErrorKind.TIMEOUT
    if status_code in {400, 422} or _contains_any(text, _FORMAT_ERROR_PATTERNS):
        return ModelErrorKind.FORMAT_ERROR
    return ModelErrorKind.UNKNOWN


def _make_classification(
    reason: ModelErrorKind,
    *,
    status_code: int | None,
    provider: str | None,
    model: str | None,
    message: str,
) -> ModelErrorClassification:
    return ModelErrorClassification(
        reason=reason,
        status_code=status_code,
        provider=provider,
        model=model,
        message=message,
        **_ACTION_HINTS[reason],
    )


def _has_provider_policy_signal(text: str, provider_text: str) -> bool:
    if not _contains_any(text, _PROVIDER_POLICY_BLOCKED_PATTERNS):
        return False
    if "openrouter" in provider_text:
        return True
    return "endpoint" in text or "data policy" in text or "privacy" in text or "provider" in text


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_timeout(error: Any) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    if isinstance(error, urllib.error.URLError):
        return isinstance(error.reason, (TimeoutError, socket.timeout))
    error_name = type(error).__name__.casefold() if error is not None else ""
    return "timeout" in error_name


def _text_fragments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        return [value.decode("utf-8", errors="replace")]
    if isinstance(value, str):
        return [value]
    if isinstance(value, (dict, list, tuple)):
        return [_jsonish(value)]
    if isinstance(value, BaseException):
        parts = [f"{type(value).__name__}: {value}"]
        for attr in ("message", "body", "text", "content", "reason"):
            try:
                attr_value = getattr(value, attr)
            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:489", exc)
                continue
            if attr_value is not value:
                parts.extend(_text_fragments(attr_value))
        return parts
    return [str(value)]


def _jsonish(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _compact_message(parts: list[str]) -> str:
    message = " ".join(part.strip() for part in parts if part and part.strip())
    return re.sub(r"\s+", " ", message)[:4000]


def _normalize(message: str) -> str:
    lowered = message.casefold().replace("-", " ")
    return re.sub(r"\s+", " ", lowered)


def _status_from_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, str)):
        return _coerce_status_code(value)
    if isinstance(value, dict):
        for key in ("status_code", "status", "http_status", "code"):
            status = _coerce_status_code(value.get(key))
            if status is not None:
                return status
        for key in ("error", "response", "body"):
            status = _status_from_value(value.get(key))
            if status is not None:
                return status
        return None
    for attr in ("status_code", "status", "code"):
        try:
            status = _coerce_status_code(getattr(value, attr))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:532", exc)
            continue
        if status is not None:
            return status
    try:
        response = getattr(value, "response")
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:538", exc)
        return None
    return _status_from_value(response)


def _status_from_text(message: str) -> int | None:
    match = _HTTP_STATUS_PATTERN.search(message.casefold())
    if not match:
        return None
    return _coerce_status_code(match.group(1))


def _coerce_status_code(value: Any) -> int | None:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    if 100 <= status <= 599:
        return status
    return None


ProviderErrorKind = ModelErrorKind
ModelErrorReason = ModelErrorKind
FailoverReason = ModelErrorKind
ProviderErrorClassification = ModelErrorClassification
ClassifiedModelError = ModelErrorClassification
ClassifiedProviderError = ModelErrorClassification

__all__ = [
    "ClassifiedModelError",
    "ClassifiedProviderError",
    "FailoverReason",
    "ModelErrorClassification",
    "ModelErrorKind",
    "ModelErrorReason",
    "ProviderErrorClassification",
    "ProviderErrorKind",
    "classify_model_error",
    "classify_provider_error",
]
