from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exception_audit import audit_suppressed_exception
from .trajectory_compact import estimate_tokens


@dataclass(frozen=True)
class TokenEstimate:
    count: int
    source: str
    exact: bool = False


@dataclass(frozen=True)
class BudgetLimit:
    name: str
    limit: int | float
    current: int | float
    projected: int | float
    unit: str

    @property
    def exceeded(self) -> bool:
        return self.projected > self.limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "limit": self.limit,
            "current": self.current,
            "projected": self.projected,
            "unit": self.unit,
            "exceeded": self.exceeded,
        }


def count_model_text_tokens(text: str, model: str = "") -> TokenEstimate:
    if not text:
        return TokenEstimate(0, "empty", exact=True)
    try:
        import tiktoken  # type: ignore[import-not-found]

        try:
            encoding = tiktoken.encoding_for_model(model) if model else tiktoken.get_encoding("cl100k_base")
            source = f"tiktoken:{getattr(encoding, 'name', 'model')}"
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
            source = "tiktoken:cl100k_base"
        return TokenEstimate(len(encoding.encode(text)), source, exact=True)
    except ModuleNotFoundError:
        return TokenEstimate(estimate_tokens(text), "heuristic:trajectory_compact", exact=False)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:52", exc)
        return TokenEstimate(estimate_tokens(text), "heuristic:trajectory_compact", exact=False)


def load_model_pricing(project: str | Path | None = None) -> tuple[dict[str, Any], str]:
    raw = os.environ.get("QUANTAGENT_MODEL_PRICING_JSON")
    if raw:
        return _parse_pricing_json(raw, "env:QUANTAGENT_MODEL_PRICING_JSON")
    path_text = os.environ.get("QUANTAGENT_MODEL_PRICING_FILE")
    if path_text:
        path = Path(path_text).expanduser()
        return _load_pricing_file(path, f"file:{path}")
    if project:
        project_path = Path(project).expanduser().resolve(strict=False)
        for candidate in (project_path / ".quantagent" / "model_pricing.json", project_path / "model_pricing.json"):
            if candidate.exists():
                return _load_pricing_file(candidate, f"file:{candidate}")
    return {}, ""


def estimate_cost_usd(model: str, usage: dict[str, Any], project: str | Path | None = None) -> tuple[float | None, str, str]:
    table, source = load_model_pricing(project)
    if not table:
        return None, "", ""
    row = _pricing_row_for_model(table, model)
    if not row:
        return None, "", ""
    input_rate = _float(row.get("input_per_million") or row.get("input_usd_per_million") or row.get("input_per_1m"))
    output_rate = _float(row.get("output_per_million") or row.get("output_usd_per_million") or row.get("output_per_1m"))
    reasoning_rate = _float(row.get("reasoning_per_million") or row.get("reasoning_usd_per_million") or row.get("reasoning_per_1m"))
    cache_read_rate = _float(row.get("cache_read_per_million") or row.get("cache_read_usd_per_million") or row.get("cache_read_per_1m"))
    cache_write_rate = _float(row.get("cache_write_per_million") or row.get("cache_write_usd_per_million") or row.get("cache_write_per_1m"))
    cost = 0.0
    priced = False
    for key, rate in (
        ("input_tokens", input_rate),
        ("output_tokens", output_rate),
        ("reasoning_tokens", reasoning_rate),
        ("cache_read_tokens", cache_read_rate),
        ("cache_write_tokens", cache_write_rate),
    ):
        if rate is None:
            continue
        cost += max(0, int(usage.get(key) or 0)) * rate / 1_000_000
        priced = True
    if not priced:
        return None, "", ""
    version = str(table.get("pricing_version") or table.get("version") or row.get("pricing_version") or "")
    return round(cost, 12), source, version


def env_budget_limits() -> dict[str, int | float]:
    return {
        "max_request_estimated_tokens": _positive_int_env("QUANTAGENT_MODEL_MAX_REQUEST_ESTIMATED_TOKENS"),
        "max_session_tokens": _positive_int_env("QUANTAGENT_MODEL_MAX_SESSION_TOKENS"),
        "max_session_model_calls": _positive_int_env("QUANTAGENT_MODEL_MAX_SESSION_CALLS"),
        "max_session_cost_usd": _positive_float_env("QUANTAGENT_MODEL_MAX_SESSION_COST_USD"),
    }


def evaluate_budget_limits(
    *,
    request_estimated_tokens: int,
    session_tokens: int = 0,
    session_model_calls: int = 0,
    session_cost_usd: float = 0.0,
    estimated_request_cost_usd: float | None = None,
) -> list[BudgetLimit]:
    limits = env_budget_limits()
    checks: list[BudgetLimit] = []
    max_request = limits.get("max_request_estimated_tokens")
    if max_request:
        checks.append(BudgetLimit("request_estimated_tokens", int(max_request), 0, request_estimated_tokens, "tokens"))
    max_session_tokens = limits.get("max_session_tokens")
    if max_session_tokens:
        checks.append(
            BudgetLimit(
                "session_tokens",
                int(max_session_tokens),
                session_tokens,
                session_tokens + request_estimated_tokens,
                "tokens",
            )
        )
    max_calls = limits.get("max_session_model_calls")
    if max_calls:
        checks.append(BudgetLimit("session_model_calls", int(max_calls), session_model_calls, session_model_calls + 1, "calls"))
    max_cost = limits.get("max_session_cost_usd")
    if max_cost:
        projected_cost = session_cost_usd + float(estimated_request_cost_usd or 0.0)
        checks.append(BudgetLimit("session_cost_usd", float(max_cost), session_cost_usd, projected_cost, "usd"))
    return checks


def _parse_pricing_json(raw: str, source: str) -> tuple[dict[str, Any], str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        audit_suppressed_exception(f"{__name__}:162", exc)
        return {}, ""
    return (data, source) if isinstance(data, dict) else ({}, "")


def _load_pricing_file(path: Path, source: str) -> tuple[dict[str, Any], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        audit_suppressed_exception(f"{__name__}:171", exc)
        return {}, ""
    return (data, source) if isinstance(data, dict) else ({}, "")


def _pricing_row_for_model(table: dict[str, Any], model: str) -> dict[str, Any] | None:
    raw_models = table.get("models")
    if isinstance(raw_models, list):
        lowered = model.lower()
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            item_model = str(item.get("model") or "").lower()
            if item_model == lowered or (item_model and item_model in lowered):
                return dict(item)
        return None
    models = raw_models if isinstance(raw_models, dict) else table
    if not isinstance(models, dict):
        return None
    if isinstance(models.get(model), dict):
        return dict(models[model])
    lowered = model.lower()
    for key, value in models.items():
        if not isinstance(value, dict):
            continue
        marker = str(key).lower()
        if marker and marker in lowered:
            return dict(value)
    return None


def _positive_int_env(name: str) -> int:
    try:
        value = int(os.environ.get(name, "0"))
    except ValueError:
        return 0
    return max(0, value)


def _positive_float_env(name: str) -> float:
    try:
        value = float(os.environ.get(name, "0"))
    except ValueError:
        return 0.0
    return max(0.0, value)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
