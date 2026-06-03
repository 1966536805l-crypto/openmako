from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .evidence_ledger import record_evidence
from .experiment_runner import fmt_pf, resolve_default_input
from .quant_run_gate import QuantGateRun, QuantRunSpec, run_quant_gate


PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class QuantJudgeSpec:
    scenario: str = "A"
    input_path: str = ""
    name: str = ""
    return_col: str = "net_return"
    date_col: str = "entry_date"
    threshold_col: str = "t1_auction_return"
    threshold_lte: float | None = None
    data_kind: str = "trade_csv"
    strict_dedup: bool = True
    oos_start: str = ""
    oos_end: str = ""
    fees_bps: float = 0.0
    slippage_bps: float = 0.0
    capacity_notes: str = ""
    execution_source: str = ""
    tick_path: str = ""
    fill_path: str = ""
    broker_path: str = ""
    order_path: str = ""
    position_path: str = ""
    account_path: str = ""
    slippage_path: str = ""
    capacity_path: str = ""
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assumptions"] = list(self.assumptions)
        return payload


@dataclass(frozen=True)
class QuantJudgeResult:
    judge_id: str
    project: str
    status: str
    ok: bool
    scenario: str = ""
    input_path: str = ""
    gate_id: str = ""
    run_id: str = ""
    research_ready: bool = False
    live_ready: bool = False
    input_sha256: str = ""
    spec_hash: str = ""
    rows_before_filter: int = 0
    rows_after_filter: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    yearly: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    output_json: str = ""
    output_markdown: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


def run_quant_judge(project: str | Path, spec: QuantJudgeSpec) -> QuantJudgeResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    judge_id = "judge-" + str(int(time.time() * 1000))
    output_json = str(_judge_dir(project_path) / f"{judge_id}.json")
    output_markdown = str(_judge_dir(project_path) / f"{judge_id}.md")
    try:
        input_path = _resolve_judge_input(project_path, spec)
        run_spec = _run_spec_from_judge(project_path, spec, input_path)
        run = run_quant_gate(project_path, run_spec)
        result = _result_from_run(project_path, judge_id, spec, input_path, run, output_json, output_markdown)
    except (OSError, ValueError) as exc:
        result = QuantJudgeResult(
            judge_id=judge_id,
            project=str(project_path),
            status=INCONCLUSIVE,
            ok=False,
            scenario=spec.scenario,
            input_path=str(_safe_input_guess(project_path, spec)),
            output_json=output_json,
            output_markdown=output_markdown,
            error=str(exc),
        )
    return _write_judge_result(project_path, result)


def render_quant_judge(result: QuantJudgeResult) -> str:
    metrics = result.metrics or {}
    lines = [
        "# Mako Judge",
        "",
        f"- status: {result.status}",
        f"- ok: {str(result.ok).lower()}",
        f"- research_ready: {str(result.research_ready).lower()}",
        f"- live_ready: {str(result.live_ready).lower()}",
        f"- scenario: {result.scenario or '-'}",
        f"- input: {result.input_path or '-'}",
        f"- gate_id: {result.gate_id or '-'}",
        f"- run_id: {result.run_id or '-'}",
        f"- input_sha256: `{result.input_sha256 or '-'}`",
        f"- spec_hash: `{result.spec_hash or '-'}`",
        f"- rows: {result.rows_after_filter}/{result.rows_before_filter}",
        f"- trades: {metrics.get('trades', '-')}",
        f"- profit_factor: {fmt_pf(metrics.get('profit_factor')) if metrics else '-'}",
        f"- win_rate: {_pct(metrics.get('win_rate')) if metrics else '-'}",
        f"- avg_return: {_pct(metrics.get('avg_return')) if metrics else '-'}",
        f"- max_drawdown_units: {metrics.get('max_drawdown_units', '-') if metrics else '-'}",
        f"- output_json: {result.output_json or '-'}",
        "",
        "## Yearly",
        "",
    ]
    if not result.yearly:
        lines.append("- none")
    for year, item in result.yearly.items():
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {year}: trades={item.get('trades', '-')} "
            f"PF={fmt_pf(item.get('profit_factor'))} "
            f"avg={_pct(item.get('avg_return'))} "
            f"max_dd={item.get('max_drawdown_units', '-')}"
        )
    lines.extend(["", "## Evidence Lock", ""])
    lines.extend(f"- {item}" for item in result.evidence_ids) if result.evidence_ids else lines.append("- none")
    lines.extend(["", "## Reasons", ""])
    reasons = result.verdict.get("reasons") if isinstance(result.verdict, dict) else ()
    if result.error:
        lines.append(f"- {result.error}")
    elif reasons:
        lines.extend(f"- {item}" for item in reasons)
    else:
        lines.append("- quant judge passed")
    return "\n".join(lines).rstrip() + "\n"


def render_quant_judge_json(result: QuantJudgeResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _resolve_judge_input(project: Path, spec: QuantJudgeSpec) -> Path:
    if spec.input_path:
        path = Path(spec.input_path).expanduser()
        return (path if path.is_absolute() else project / path).resolve(strict=False)
    default = resolve_default_input(project, spec.scenario)
    if default.exists():
        return default.resolve(strict=False)
    fallback = _scenario_fallback_input(project, spec.scenario)
    if fallback is not None:
        return fallback.resolve(strict=False)
    raise FileNotFoundError(f"judge input not found for scenario {spec.scenario}: {default}")


def _scenario_fallback_input(project: Path, scenario: str) -> Path | None:
    comm = project / "AI_协作交接"
    if not comm.exists():
        return None
    key = str(scenario or "").upper()
    candidates = sorted(comm.glob(f"*scenario_{key}*dedup*.csv")) + sorted(comm.glob(f"*_{key}_*dedup*.csv"))
    return candidates[0] if candidates else None


def _safe_input_guess(project: Path, spec: QuantJudgeSpec) -> Path:
    if spec.input_path:
        path = Path(spec.input_path).expanduser()
        return (path if path.is_absolute() else project / path).resolve(strict=False)
    return resolve_default_input(project, spec.scenario)


def _run_spec_from_judge(project: Path, spec: QuantJudgeSpec, input_path: Path) -> QuantRunSpec:
    threshold_col = spec.threshold_col if spec.threshold_lte is not None else ""
    threshold_part = f"_{threshold_col}_lte_{spec.threshold_lte:g}" if threshold_col and spec.threshold_lte is not None else ""
    name = spec.name or f"judge_{input_path.stem}{threshold_part}"
    return QuantRunSpec(
        name=name,
        input_path=str(input_path),
        return_col=spec.return_col,
        date_col=spec.date_col,
        threshold_col=threshold_col,
        threshold_lte=spec.threshold_lte,
        data_kind=spec.data_kind,
        strict_dedup=spec.strict_dedup,
        oos_start=spec.oos_start,
        oos_end=spec.oos_end,
        fees_bps=spec.fees_bps,
        slippage_bps=spec.slippage_bps,
        capacity_notes=spec.capacity_notes,
        execution_source=spec.execution_source,
        tick_path=spec.tick_path,
        fill_path=spec.fill_path,
        broker_path=spec.broker_path,
        order_path=spec.order_path,
        position_path=spec.position_path,
        account_path=spec.account_path,
        slippage_path=spec.slippage_path,
        capacity_path=spec.capacity_path,
        assumptions=spec.assumptions,
    )


def _result_from_run(
    project: Path,
    judge_id: str,
    spec: QuantJudgeSpec,
    input_path: Path,
    run: QuantGateRun,
    output_json: str,
    output_markdown: str,
) -> QuantJudgeResult:
    status = _judge_status(run)

    # CRITICAL FIX: Only trust metrics if they come from a verified experiment with runner_sha256
    metrics_raw = run.experiment.get("metrics") if isinstance(run.experiment.get("metrics"), dict) else {}
    yearly_raw = run.experiment.get("yearly") if isinstance(run.experiment.get("yearly"), dict) else {}

    # Verify metrics are from trusted computation, not self-reported
    runner_sha256 = run.experiment.get("runner_sha256")
    if not runner_sha256:
        # No runner signature = untrusted metrics
        metrics = {}
        yearly = {}
    else:
        metrics = dict(metrics_raw)
        yearly = dict(yearly_raw)

    base_evidence_ids = tuple(run.evidence_bundle.evidence_ids)
    judge_record = record_evidence(
        project,
        claim="mako judge verdict",
        value=f"{status} research_ready={run.verdict.research_ready} live_ready={run.verdict.live_ready}",
        evidence_type="quant_judge",
        source=output_json,
        path=str(input_path),
        tool="judge",
        metadata={"judge_id": judge_id, "gate_id": run.gate_id, "run_id": run.evidence_bundle.run_id, "status": status},
    )
    return QuantJudgeResult(
        judge_id=judge_id,
        project=str(project),
        status=status,
        ok=status == PASS,
        scenario=spec.scenario,
        input_path=str(input_path),
        gate_id=run.gate_id,
        run_id=run.evidence_bundle.run_id,
        research_ready=run.verdict.research_ready,
        live_ready=run.verdict.live_ready,
        input_sha256=run.evidence_bundle.input_sha256,
        spec_hash=run.evidence_bundle.spec_hash,
        rows_before_filter=run.evidence_bundle.rows_before_filter,
        rows_after_filter=run.evidence_bundle.rows_after_filter,
        metrics=metrics,
        yearly=yearly,
        verdict=run.verdict.to_dict(),
        evidence_ids=(*base_evidence_ids, judge_record.evidence_id),
        output_json=output_json,
        output_markdown=output_markdown,
    )


def _judge_status(run: QuantGateRun) -> str:
    if run.verdict.ok and run.verdict.research_ready:
        return PASS
    contract_failed = not bool(run.data_contract.get("ok"))
    leak_failed = not bool(run.leak_check.get("ok"))
    if contract_failed or leak_failed:
        return FAIL
    return INCONCLUSIVE


def _write_judge_result(project: Path, result: QuantJudgeResult) -> QuantJudgeResult:
    root = _judge_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    Path(result.output_json).write_text(render_quant_judge_json(result), encoding="utf-8")
    Path(result.output_markdown).write_text(render_quant_judge(result), encoding="utf-8")
    return result


def _judge_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    if not base.exists():
        base = project / ".quantagent"
    return base / "judge"


def _pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.2%}"
