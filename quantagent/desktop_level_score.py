from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


L4_LONG_RUN_HOURS = 4.0
L4_SUCCESS_RATE = 0.85
L4_MAX_MISOPERATION_RATE = 0.01
L4_MAX_MISOPERATIONS = 1
L4_MAX_CRASHES = 0
L4_AUTOPSY_COVERAGE = 0.90
L4_RECOVERY_RATE = 0.70

L5_LONG_RUN_HOURS = 8.0
L5_SUCCESS_RATE = 0.95
L5_MAX_MISOPERATION_RATE = 0.0
L5_MAX_MISOPERATIONS = 0
L5_MAX_CRASHES = 0
L5_AUTOPSY_COVERAGE = 0.98
L5_RECOVERY_RATE = 0.90

GATE_ORDER = (
    "L4 long_run_hours >= 4.00",
    "L4 success_rate >= 0.85",
    "L4 misoperation_rate <= 0.01",
    "L4 misoperations <= 1",
    "L4 crashes <= 0",
    "L4 autopsy_coverage >= 0.90",
    "L4 recovery_rate >= 0.70",
    "L5 long_run_hours >= 8.00",
    "L5 success_rate >= 0.95",
    "L5 misoperation_rate <= 0.00",
    "L5 misoperations <= 0",
    "L5 crashes <= 0",
    "L5 autopsy_coverage >= 0.98",
    "L5 recovery_rate >= 0.90",
)


@dataclass(frozen=True)
class DesktopLevelScore:
    score: int
    level: str
    reasons: tuple[str, ...]
    gates: dict[str, bool]
    metrics: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_desktop_level(metrics: Mapping[str, Any]) -> DesktopLevelScore:
    normalized, missing = _normalize_metrics(metrics)
    raw_score = (
        normalized["success_rate"] * 40.0
        + min(normalized["long_run_hours"] / L5_LONG_RUN_HOURS, 1.0) * 20.0
        + _misoperation_points(normalized["misoperation_rate"], normalized["misoperations"])
        + _crash_points(normalized["crash_rate"], normalized["crashes"])
        + normalized["autopsy_coverage"] * 10.0
        + normalized["recovery_rate"] * 5.0
    )
    score = _clamp_int(round(raw_score), 0, 100)
    gates = _evaluate_gates(normalized)
    l4_pass = all(gates[name] for name in GATE_ORDER if name.startswith("L4 "))
    l5_pass = all(gates[name] for name in GATE_ORDER if name.startswith("L5 "))

    if score >= 90 and l5_pass:
        level = "L5"
    elif score >= 80 and l4_pass:
        level = "L4"
    elif score >= 60:
        level = "L3"
    elif score >= 35:
        level = "L2"
    else:
        level = "L1"

    reasons = _build_reasons(score, level, gates, missing)
    return DesktopLevelScore(score=score, level=level, reasons=reasons, gates=gates, metrics=normalized)


def render_desktop_level_score(score: DesktopLevelScore) -> str:
    lines = [
        f"Desktop level: {score.level}",
        f"Score: {score.score}/100",
        "",
        "Metrics:",
    ]
    for key in sorted(score.metrics):
        lines.append(f"- {key}: {_format_metric(score.metrics[key])}")
    lines.append("")
    lines.append("Gates:")
    for key in GATE_ORDER:
        lines.append(f"- {key}: {'pass' if score.gates.get(key, False) else 'fail'}")
    lines.append("")
    lines.append("Reasons:")
    for reason in score.reasons:
        lines.append(f"- {reason}")
    return "\n".join(lines) + "\n"


def _normalize_metrics(metrics: Mapping[str, Any]) -> tuple[dict[str, float], tuple[str, ...]]:
    missing: list[str] = []
    total_tasks = _first_number(metrics, ("total_tasks", "tasks", "cases", "task_count"))
    success_rate = _first_rate(metrics, ("success_rate", "pass_rate", "task_success_rate"))
    if success_rate is None:
        succeeded = _first_number(metrics, ("successful_tasks", "succeeded_tasks", "passed", "passed_tasks"))
        if total_tasks is not None and total_tasks > 0 and succeeded is not None:
            success_rate = succeeded / total_tasks
        else:
            missing.append("success_rate")
            success_rate = 0.0

    long_run_hours = _first_number(metrics, ("long_run_hours", "run_hours", "duration_hours", "runtime_hours"))
    if long_run_hours is None:
        minutes = _first_number(metrics, ("long_run_minutes", "duration_minutes", "runtime_minutes"))
        seconds = _first_number(metrics, ("long_run_seconds", "duration_seconds", "runtime_seconds"))
        if minutes is not None:
            long_run_hours = minutes / 60.0
        elif seconds is not None:
            long_run_hours = seconds / 3600.0
        else:
            missing.append("long_run_hours")
            long_run_hours = 0.0

    misoperations = _first_number(metrics, ("misoperations", "misoperation_count", "unsafe_actions", "wrong_actions"))
    missing_misoperations = misoperations is None
    if misoperations is None:
        missing.append("misoperations")
        misoperations = 1.0
    misoperation_rate = _first_rate(metrics, ("misoperation_rate", "unsafe_action_rate", "wrong_action_rate"))
    if misoperation_rate is None:
        total_actions = _first_number(metrics, ("total_actions", "actions", "action_count"))
        if total_actions is not None and total_actions > 0:
            misoperation_rate = misoperations / total_actions
        else:
            missing.append("misoperation_rate")
            misoperation_rate = 1.0 if missing_misoperations or misoperations > 0 else 0.0

    crashes = _first_number(metrics, ("crashes", "crash_count", "process_crashes", "daemon_crashes"))
    if crashes is None:
        missing.append("crashes")
        crashes = 1.0
    crash_rate = _first_rate(metrics, ("crash_rate", "process_crash_rate", "daemon_crash_rate"))
    if crash_rate is None:
        runs = _first_number(metrics, ("runs", "run_count", "sessions"))
        if runs is not None and runs > 0:
            crash_rate = crashes / runs
        else:
            crash_rate = 1.0 if crashes > 0 else 0.0

    autopsy_coverage = _first_rate(metrics, ("autopsy_coverage", "autopsy_rate", "failure_autopsy_coverage"))
    if autopsy_coverage is None:
        failures = _first_number(metrics, ("failures", "failed_runs", "failure_count"))
        autopsies = _first_number(metrics, ("autopsies", "autopsies_written", "failed_runs_with_autopsy"))
        if failures is not None and failures > 0 and autopsies is not None:
            autopsy_coverage = autopsies / failures
        elif failures == 0:
            autopsy_coverage = 1.0
        else:
            missing.append("autopsy_coverage")
            autopsy_coverage = 0.0

    recovery_rate = _first_rate(metrics, ("recovery_rate", "recoverable_recovery_rate"))
    if recovery_rate is None:
        recoverable = _first_number(metrics, ("recoverable_failures", "recovery_opportunities"))
        recovered = _first_number(metrics, ("recovered_failures", "recoveries", "successful_recoveries"))
        if recoverable is not None and recoverable > 0 and recovered is not None:
            recovery_rate = recovered / recoverable
        elif recoverable == 0:
            recovery_rate = 1.0
        else:
            missing.append("recovery_rate")
            recovery_rate = 0.0

    normalized = {
        "long_run_hours": _clamp_float(long_run_hours, 0.0, 10_000.0),
        "success_rate": _clamp_float(success_rate, 0.0, 1.0),
        "misoperations": _clamp_float(misoperations, 0.0, 10_000_000.0),
        "misoperation_rate": _clamp_float(misoperation_rate, 0.0, 1.0),
        "crashes": _clamp_float(crashes, 0.0, 10_000_000.0),
        "crash_rate": _clamp_float(crash_rate, 0.0, 1.0),
        "autopsy_coverage": _clamp_float(autopsy_coverage, 0.0, 1.0),
        "recovery_rate": _clamp_float(recovery_rate, 0.0, 1.0),
    }
    return normalized, tuple(sorted(set(missing)))


def _evaluate_gates(metrics: Mapping[str, float]) -> dict[str, bool]:
    return {
        "L4 long_run_hours >= 4.00": metrics["long_run_hours"] >= L4_LONG_RUN_HOURS,
        "L4 success_rate >= 0.85": metrics["success_rate"] >= L4_SUCCESS_RATE,
        "L4 misoperation_rate <= 0.01": metrics["misoperation_rate"] <= L4_MAX_MISOPERATION_RATE,
        "L4 misoperations <= 1": metrics["misoperations"] <= L4_MAX_MISOPERATIONS,
        "L4 crashes <= 0": metrics["crashes"] <= L4_MAX_CRASHES,
        "L4 autopsy_coverage >= 0.90": metrics["autopsy_coverage"] >= L4_AUTOPSY_COVERAGE,
        "L4 recovery_rate >= 0.70": metrics["recovery_rate"] >= L4_RECOVERY_RATE,
        "L5 long_run_hours >= 8.00": metrics["long_run_hours"] >= L5_LONG_RUN_HOURS,
        "L5 success_rate >= 0.95": metrics["success_rate"] >= L5_SUCCESS_RATE,
        "L5 misoperation_rate <= 0.00": metrics["misoperation_rate"] <= L5_MAX_MISOPERATION_RATE,
        "L5 misoperations <= 0": metrics["misoperations"] <= L5_MAX_MISOPERATIONS,
        "L5 crashes <= 0": metrics["crashes"] <= L5_MAX_CRASHES,
        "L5 autopsy_coverage >= 0.98": metrics["autopsy_coverage"] >= L5_AUTOPSY_COVERAGE,
        "L5 recovery_rate >= 0.90": metrics["recovery_rate"] >= L5_RECOVERY_RATE,
    }


def _build_reasons(
    score: int,
    level: str,
    gates: Mapping[str, bool],
    missing: tuple[str, ...],
) -> tuple[str, ...]:
    reasons: list[str] = [f"{level} assigned from score {score}/100 and hard level gates"]
    failed_l4 = [key for key in GATE_ORDER if key.startswith("L4 ") and not gates[key]]
    failed_l5 = [key for key in GATE_ORDER if key.startswith("L5 ") and not gates[key]]
    if failed_l4:
        reasons.append("L4 blocked by: " + "; ".join(failed_l4))
    if failed_l5:
        reasons.append("L5 blocked by: " + "; ".join(failed_l5))
    if missing:
        reasons.append("missing metrics defaulted conservatively: " + ", ".join(missing))
    return tuple(reasons)


def _misoperation_points(rate: float, count: float) -> float:
    rate_points = 15.0 * max(0.0, 1.0 - rate / 0.05)
    excess_count_penalty = max(0.0, count - L4_MAX_MISOPERATIONS) * 4.0
    return max(0.0, rate_points - excess_count_penalty)


def _crash_points(rate: float, count: float) -> float:
    if count <= 0 and rate <= 0:
        return 10.0
    rate_points = 10.0 * max(0.0, 1.0 - rate / 0.02)
    count_penalty = min(count, 10.0) * 5.0
    return max(0.0, rate_points - count_penalty)


def _first_rate(metrics: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    value = _first_number(metrics, keys)
    if value is None:
        return None
    if value > 1.0:
        value = value / 100.0
    return value


def _first_number(metrics: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in metrics:
            value = _to_float(metrics[key])
            if value is not None:
                return value
    return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _clamp_int(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)


def _format_metric(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")
