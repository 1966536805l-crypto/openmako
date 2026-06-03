from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_return: float
    total_return_units: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    max_drawdown_units: float


def to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if text == "":
            return None
        return float(text)
    except ValueError:
        return None


def compute_metrics(returns: Iterable[float]) -> PerformanceMetrics:
    values = [float(item) for item in returns]
    trades = len(values)
    wins = sum(1 for item in values if item > 0)
    losses = sum(1 for item in values if item < 0)
    gross_profit = sum(item for item in values if item > 0)
    gross_loss = -sum(item for item in values if item < 0)
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss
    total = sum(values)
    avg = total / trades if trades else 0.0
    win_rate = wins / trades if trades else 0.0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    return PerformanceMetrics(
        trades=trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        avg_return=avg,
        total_return_units=total,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown_units=max_drawdown,
    )


def group_metrics(rows: list[dict[str, str]], return_col: str, key_fn) -> dict[str, PerformanceMetrics]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = to_float(row.get(return_col))
        if value is None:
            continue
        grouped[str(key_fn(row))].append(value)
    return {key: compute_metrics(values) for key, values in sorted(grouped.items())}


def date_year(value: str) -> str:
    text = str(value).strip()
    return text[:4] if len(text) >= 4 else "unknown"


def date_month(value: str) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) >= 6:
        return f"{text[:4]}-{text[4:6]}"
    return "unknown"

