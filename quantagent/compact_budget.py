from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .trajectory_compact import CompactResult, compact_trajectory, estimate_tokens


@dataclass(frozen=True)
class CompactPlan:
    should_compact: bool
    pressure: float
    estimated_tokens: int
    token_budget: int
    keep_first: int
    keep_last: int
    target_summary_chars: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_auto_compact(
    messages: list[Any],
    *,
    token_budget: int = 80_000,
    pressure_threshold: float = 0.72,
) -> CompactPlan:
    estimated = sum(estimate_tokens(message) for message in messages)
    pressure = estimated / max(1, token_budget)
    should = pressure >= pressure_threshold
    keep_last = 10 if pressure < 1 else 6
    target_summary_chars = 2400 if pressure < 1 else 1600
    reason = "token pressure above threshold" if should else "token pressure below threshold"
    return CompactPlan(should, round(pressure, 4), estimated, token_budget, 2, keep_last, target_summary_chars, reason)


def auto_compact_messages(
    messages: list[Any],
    *,
    token_budget: int = 80_000,
    pressure_threshold: float = 0.72,
) -> tuple[CompactPlan, CompactResult | None]:
    plan = plan_auto_compact(messages, token_budget=token_budget, pressure_threshold=pressure_threshold)
    if not plan.should_compact:
        return plan, None
    result = compact_trajectory(
        messages,
        first_n=plan.keep_first,
        last_n=plan.keep_last,
        target_summary_chars=plan.target_summary_chars,
        summary_kind="auto_compact_budget",
    )
    return plan, result


def render_compact_plan(plan: CompactPlan) -> str:
    return "\n".join(
        [
            "# Auto Compact Plan",
            "",
            f"- should_compact: {str(plan.should_compact).lower()}",
            f"- pressure: {plan.pressure}",
            f"- estimated_tokens: {plan.estimated_tokens}",
            f"- token_budget: {plan.token_budget}",
            f"- keep_first: {plan.keep_first}",
            f"- keep_last: {plan.keep_last}",
            f"- target_summary_chars: {plan.target_summary_chars}",
            f"- reason: {plan.reason}",
        ]
    ) + "\n"
