from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .evidence_ledger import EvidenceRecord, create_evidence_record, record_evidence
from .experiment_runner import ExperimentSpec, run_experiment
from .quant_data_contract import validate_quant_data_contract
from .quant_execution_gate import QuantExecutionEvidenceSpec, run_quant_execution_gate
from .quant_leak_check import run_quant_leak_check
from .quant_priority import EXECUTION_TERMS, METRIC_TERMS, PUBLISH_TERMS


PASS = "pass"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class QuantRunSpec:
    name: str
    input_path: str
    return_col: str = "net_return"
    date_col: str = "entry_date"
    threshold_col: str = ""
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
    prohibited_actions: tuple[str, ...] = (
        "Do not approve live trading from this run unless live_ready is true.",
        "Do not quote PF/收益/胜率/回撤 without run_id, input_hash, split, and artifact evidence.",
        "Do not treat slippage/capacity assumptions as broker execution evidence.",
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assumptions"] = list(self.assumptions)
        payload["prohibited_actions"] = list(self.prohibited_actions)
        return payload


@dataclass(frozen=True)
class QuantSplitCheck:
    ok: bool
    date_col: str
    rows: int
    years: tuple[str, ...] = ()
    year_counts: dict[str, int] = field(default_factory=dict)
    oos_start: str = ""
    oos_end: str = ""
    oos_rows: int = 0
    in_sample_rows: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["years"] = list(self.years)
        return payload


@dataclass(frozen=True)
class QuantEvidenceBundle:
    gate_id: str
    run_id: str = ""
    input_path: str = ""
    input_sha256: str = ""
    spec_hash: str = ""
    run_dir: str = ""
    rows_before_filter: int = 0
    rows_after_filter: int = 0
    data_contract_ok: bool = False
    leak_check_ok: bool = False
    split_ok: bool = False
    split_years: tuple[str, ...] = ()
    metric_keys: tuple[str, ...] = ()
    fee_slippage_assumptions: dict[str, Any] = field(default_factory=dict)
    execution_source: str = ""
    execution_gate: dict[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    runner_sha256: str = ""  # CRITICAL: verify metrics are from trusted computation

    @property
    def research_ready(self) -> bool:
        return bool(
            self.run_id
            and self.input_sha256
            and self.spec_hash
            and self.data_contract_ok
            and self.leak_check_ok
            and self.split_ok
            and self.runner_sha256  # CRITICAL: must have runner signature
        )

    @property
    def live_ready(self) -> bool:
        return self.research_ready and bool(self.execution_gate.get("live_ready"))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["split_years"] = list(self.split_years)
        payload["metric_keys"] = list(self.metric_keys)
        payload["evidence_ids"] = list(self.evidence_ids)
        payload["research_ready"] = self.research_ready
        payload["live_ready"] = self.live_ready
        return payload


@dataclass(frozen=True)
class QuantRunVerdict:
    action: str
    ok: bool
    research_ready: bool
    live_ready: bool
    reasons: tuple[str, ...] = ()
    allowed_conclusions: tuple[str, ...] = ()
    blocked_conclusions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["allowed_conclusions"] = list(self.allowed_conclusions)
        payload["blocked_conclusions"] = list(self.blocked_conclusions)
        return payload


@dataclass(frozen=True)
class QuantGateRun:
    gate_id: str
    project: str
    started_at: str
    finished_at: str
    spec: QuantRunSpec
    split_check: QuantSplitCheck
    data_contract: dict[str, Any]
    leak_check: dict[str, Any]
    experiment: dict[str, Any] = field(default_factory=dict)
    evidence_bundle: QuantEvidenceBundle = field(default_factory=lambda: QuantEvidenceBundle(gate_id=""))
    verdict: QuantRunVerdict = field(default_factory=lambda: QuantRunVerdict(BLOCK, False, False, False))
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "project": self.project,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "spec": self.spec.to_dict(),
            "split_check": self.split_check.to_dict(),
            "data_contract": self.data_contract,
            "leak_check": self.leak_check,
            "experiment": self.experiment,
            "evidence_bundle": self.evidence_bundle.to_dict(),
            "verdict": self.verdict.to_dict(),
        }


def run_quant_gate(project: str | Path, spec: QuantRunSpec) -> QuantGateRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    started_monotonic = time.monotonic()
    started = datetime.now().isoformat(timespec="seconds")
    gate_id = "qgate-" + str(int(time.time() * 1000))
    input_path = _resolve_input(project_path, spec.input_path)

    contract = validate_quant_data_contract(input_path, kind=spec.data_kind, strict_dedup=spec.strict_dedup)
    leak_check = run_quant_leak_check(input_path)
    split_check = run_quant_split_check(input_path, date_col=spec.date_col, oos_start=spec.oos_start, oos_end=spec.oos_end)
    execution_gate = _run_execution_gate_if_configured(project_path, spec)
    experiment: dict[str, Any] = {}
    if contract.ok and leak_check.ok and split_check.ok:
        experiment = run_experiment(project_path, _experiment_spec(input_path, spec))
    bundle = build_quant_evidence_bundle(project_path, gate_id, spec, contract.to_dict(), leak_check.to_dict(), split_check, experiment, execution_gate)
    verdict = build_quant_run_verdict(bundle, split_check=split_check, contract=contract.to_dict(), leak_check=leak_check.to_dict())
    finished = datetime.now().isoformat(timespec="seconds")
    run = QuantGateRun(
        gate_id=gate_id,
        project=str(project_path),
        started_at=started,
        finished_at=finished,
        spec=spec,
        split_check=split_check,
        data_contract=contract.to_dict(),
        leak_check=leak_check.to_dict(),
        experiment=experiment,
        evidence_bundle=bundle,
        verdict=verdict,
        duration_ms=_elapsed_ms(started_monotonic),
    )
    _write_quant_gate_run(project_path, run)
    return run


def run_quant_split_check(
    input_path: str | Path,
    *,
    date_col: str = "entry_date",
    oos_start: str = "",
    oos_end: str = "",
) -> QuantSplitCheck:
    path = Path(input_path).expanduser().resolve(strict=False)
    rows = _read_rows(path)
    dates: list[date] = []
    invalid = 0
    for row in rows:
        parsed = _parse_date(row.get(date_col, ""))
        if parsed is None:
            invalid += 1
            continue
        dates.append(parsed)
    year_counts: dict[str, int] = {}
    for item in dates:
        year_counts[str(item.year)] = year_counts.get(str(item.year), 0) + 1
    years = tuple(sorted(year_counts))
    start = _parse_date(oos_start) if oos_start else None
    end = _parse_date(oos_end) if oos_end else None
    oos_rows = 0
    if start or end:
        for item in dates:
            if start and item < start:
                continue
            if end and item > end:
                continue
            oos_rows += 1
    in_sample_rows = max(0, len(dates) - oos_rows) if (start or end) else 0
    has_year_split = len(years) >= 2
    has_explicit_oos = bool((start or end) and oos_rows > 0 and in_sample_rows > 0)

    # Sample size validation
    total_rows = len(dates)
    oos_ratio = oos_rows / total_rows if total_rows > 0 else 0.0
    in_sample_ratio = in_sample_rows / total_rows if total_rows > 0 else 0.0
    oos_sufficient = oos_rows == 0 or oos_ratio >= 0.20
    in_sample_sufficient = in_sample_rows == 0 or in_sample_ratio >= 0.50

    ok = bool(dates) and invalid == 0 and (has_year_split or has_explicit_oos) and oos_sufficient and in_sample_sufficient
    if not dates:
        reason = f"no valid dates found in {date_col}"
    elif invalid:
        reason = f"{invalid} row(s) have invalid dates in {date_col}"
    elif not (has_year_split or has_explicit_oos):
        reason = "need at least two years or explicit OOS range with in-sample and OOS rows"
    elif not oos_sufficient:
        reason = f"OOS sample size insufficient: {oos_rows}/{total_rows} ({oos_ratio:.1%}) < 20%"
    elif not in_sample_sufficient:
        reason = f"in-sample size insufficient: {in_sample_rows}/{total_rows} ({in_sample_ratio:.1%}) < 50%"
    else:
        reason = "split has yearly/OOS coverage"
    return QuantSplitCheck(
        ok=ok,
        date_col=date_col,
        rows=len(rows),
        years=years,
        year_counts=year_counts,
        oos_start=oos_start,
        oos_end=oos_end,
        oos_rows=oos_rows,
        in_sample_rows=in_sample_rows,
        reason=reason,
    )


def build_quant_evidence_bundle(
    project: str | Path,
    gate_id: str,
    spec: QuantRunSpec,
    data_contract: dict[str, Any],
    leak_check: dict[str, Any],
    split_check: QuantSplitCheck,
    experiment: dict[str, Any],
    execution_gate: dict[str, Any] | None = None,
) -> QuantEvidenceBundle:
    metrics = experiment.get("metrics") if isinstance(experiment.get("metrics"), dict) else {}
    runner_sha256 = str(experiment.get("runner_sha256") or "")  # CRITICAL: extract runner signature
    bundle = QuantEvidenceBundle(
        gate_id=gate_id,
        run_id=str(experiment.get("run_id") or ""),
        input_path=str(experiment.get("input_path") or _resolve_input(Path(project), spec.input_path)),
        input_sha256=str(experiment.get("input_sha256") or data_contract.get("sha256") or ""),
        spec_hash=str(experiment.get("spec_hash") or ""),
        run_dir=str(experiment.get("run_dir") or ""),
        rows_before_filter=int(experiment.get("rows_before_filter") or data_contract.get("rows") or 0),
        rows_after_filter=int(experiment.get("rows_after_filter") or 0),
        data_contract_ok=bool(data_contract.get("ok")),
        leak_check_ok=bool(leak_check.get("ok")),
        split_ok=split_check.ok,
        split_years=split_check.years,
        metric_keys=tuple(sorted(str(key) for key in metrics.keys())),
        fee_slippage_assumptions={
            "fees_bps": spec.fees_bps,
            "slippage_bps": spec.slippage_bps,
            "capacity_notes": spec.capacity_notes,
            "assumptions": list(spec.assumptions),
        },
        execution_source=spec.execution_source,
        execution_gate=dict(execution_gate or {}),
        runner_sha256=runner_sha256,  # CRITICAL: include runner signature
    )
    records = _record_quant_gate_evidence(project, bundle, spec)
    return QuantEvidenceBundle(
        gate_id=bundle.gate_id,
        run_id=bundle.run_id,
        input_path=bundle.input_path,
        input_sha256=bundle.input_sha256,
        spec_hash=bundle.spec_hash,
        run_dir=bundle.run_dir,
        rows_before_filter=bundle.rows_before_filter,
        rows_after_filter=bundle.rows_after_filter,
        data_contract_ok=bundle.data_contract_ok,
        leak_check_ok=bundle.leak_check_ok,
        split_ok=bundle.split_ok,
        split_years=bundle.split_years,
        metric_keys=bundle.metric_keys,
        fee_slippage_assumptions=bundle.fee_slippage_assumptions,
        execution_source=bundle.execution_source,
        execution_gate=bundle.execution_gate,
        evidence_ids=tuple(record.evidence_id for record in records),
        runner_sha256=bundle.runner_sha256,  # CRITICAL: preserve runner signature
    )


def build_quant_run_verdict(
    bundle: QuantEvidenceBundle,
    *,
    split_check: QuantSplitCheck | None = None,
    contract: dict[str, Any] | None = None,
    leak_check: dict[str, Any] | None = None,
    task: str = "",
    answer: str = "",
) -> QuantRunVerdict:
    reasons: list[str] = []
    blocked: list[str] = []
    allowed: list[str] = []
    contract_ok = bundle.data_contract_ok if contract is None else bool(contract.get("ok"))
    leak_ok = bundle.leak_check_ok if leak_check is None else bool(leak_check.get("ok"))
    split_ok = bundle.split_ok if split_check is None else split_check.ok
    if not contract_ok:
        reasons.append("data contract failed")
        blocked.append("Do not use this input for backtest metrics.")
    if not leak_ok:
        reasons.append("hard leakage check failed")
        blocked.append("Do not report metrics from a leaky input or strategy.")
    if not split_ok:
        reason = split_check.reason if split_check is not None else "split check failed"
        reasons.append(reason)
        blocked.append("Do not report aggregate metrics without yearly/OOS split evidence.")
    if not bundle.run_id:
        reasons.append("experiment run artifact is missing")
        blocked.append("Do not state PF/收益/胜率/回撤 as facts without run_id and artifact hashes.")
    if bundle.research_ready:
        allowed.append("Research/reporting metrics may be cited with run_id, input_sha256, spec_hash, and split evidence.")
    execution_gate = dict(bundle.execution_gate or {})
    if bundle.live_ready:
        allowed.append("Execution/live claims may cite broker/fill/tick/slippage/capacity evidence from the execution gate.")
    else:
        blocked.append("Do not approve live trading, order placement, slippage, or capacity as proven.")
        if execution_gate:
            for issue in execution_gate.get("issues") or ():
                if isinstance(issue, dict) and issue.get("level") == BLOCK:
                    reasons.append(f"execution evidence failed: {issue.get('code')}: {issue.get('message')}")
    if requires_quant_run_gate(" ".join(part for part in (task, answer) if part)) and not bundle.research_ready:
        reasons.append("task/answer requires QuantRunGate evidence")
    if requires_live_quant_evidence(" ".join(part for part in (task, answer) if part)) and not bundle.live_ready:
        reasons.append("task/answer requires broker/fill/slippage/capacity execution evidence")
    action = PASS if bundle.research_ready and not any("requires broker/fill" in item for item in reasons) else BLOCK
    ok = action == PASS
    return QuantRunVerdict(
        action=action,
        ok=ok,
        research_ready=bundle.research_ready,
        live_ready=bundle.live_ready,
        reasons=tuple(_dedupe(reasons) or ["quant run gate passed"]),
        allowed_conclusions=tuple(_dedupe(allowed)),
        blocked_conclusions=tuple(_dedupe(blocked)),
    )


def quant_gate_dir(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quant_run_gate"


def latest_quant_gate_run(project: str | Path) -> QuantGateRun | None:
    root = quant_gate_dir(project)
    files = sorted(root.glob("qgate-*.json"))
    if not files:
        return None
    return load_quant_gate_run(project, files[-1].stem)


def load_quant_gate_run(project: str | Path, gate_id: str) -> QuantGateRun:
    root = quant_gate_dir(project)
    path = root / f"{gate_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"quant gate run not found: {gate_id}")
    return _run_from_dict(json.loads(path.read_text(encoding="utf-8")))


def replay_quant_gate(project: str | Path, gate_id: str = "") -> QuantGateRun:
    previous = load_quant_gate_run(project, gate_id) if gate_id else latest_quant_gate_run(project)
    if previous is None:
        raise FileNotFoundError("no quant gate run to replay")
    return run_quant_gate(project, previous.spec)


def latest_quant_evidence_bundle(project: str | Path) -> QuantEvidenceBundle | None:
    run = latest_quant_gate_run(project)
    return run.evidence_bundle if run is not None else None


def requires_quant_run_gate(text: str) -> bool:
    lowered = _norm(text)
    if not lowered:
        return False
    material_terms = tuple(METRIC_TERMS | EXECUTION_TERMS | PUBLISH_TERMS)
    return any(term in lowered for term in material_terms)


def requires_live_quant_evidence(text: str) -> bool:
    lowered = _norm(text)
    if not lowered:
        return False
    live_terms = {
        "09:30",
        "execution",
        "fill",
        "broker",
        "slippage",
        "capacity",
        "tick",
        "live",
        "go live",
        "trade live",
        "safe to trade",
        "成交",
        "撮合",
        "券商",
        "滑点",
        "容量",
        "逐笔",
        "实盘",
        "下单",
        "可以上",
        "能交易",
    }
    return any(term in lowered for term in live_terms)


def quant_gate_evidence_records(bundle: QuantEvidenceBundle) -> tuple[EvidenceRecord, ...]:
    return (
        create_evidence_record(
            claim="quant run gate evidence bundle",
            value=f"run_id={bundle.run_id} input_sha256={bundle.input_sha256} spec_hash={bundle.spec_hash}",
            evidence_type="quant_run_gate",
            source=bundle.run_dir,
            path=bundle.input_path,
            tool="quant_run_gate",
            metadata=bundle.to_dict(),
        ),
    )


def render_quant_gate_run(run: QuantGateRun) -> str:
    bundle = run.evidence_bundle
    verdict = run.verdict
    lines = [
        "# Quant Run Gate",
        "",
        f"- gate_id: {run.gate_id}",
        f"- project: {run.project}",
        f"- action: {verdict.action}",
        f"- research_ready: {str(verdict.research_ready).lower()}",
        f"- live_ready: {str(verdict.live_ready).lower()}",
        f"- run_id: {bundle.run_id or '-'}",
        f"- input_sha256: `{bundle.input_sha256 or '-'}`",
        f"- spec_hash: `{bundle.spec_hash or '-'}`",
        f"- rows: {bundle.rows_after_filter}/{bundle.rows_before_filter}",
        f"- split: {str(bundle.split_ok).lower()} years={','.join(bundle.split_years) or '-'}",
        f"- data_contract_ok: {str(bundle.data_contract_ok).lower()}",
        f"- leak_check_ok: {str(bundle.leak_check_ok).lower()}",
        f"- duration_ms: {run.duration_ms}",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {item}" for item in verdict.reasons)
    lines.extend(["", "## Allowed Conclusions", ""])
    lines.extend(f"- {item}" for item in verdict.allowed_conclusions) if verdict.allowed_conclusions else lines.append("- none")
    lines.extend(["", "## Blocked Conclusions", ""])
    lines.extend(f"- {item}" for item in verdict.blocked_conclusions) if verdict.blocked_conclusions else lines.append("- none")
    lines.extend(["", "## Spec", "", "```json", json.dumps(run.spec.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return "\n".join(lines).rstrip() + "\n"


def render_quant_evidence_bundle(bundle: QuantEvidenceBundle) -> str:
    lines = [
        "# Quant Evidence Bundle",
        "",
        f"- gate_id: {bundle.gate_id}",
        f"- run_id: {bundle.run_id or '-'}",
        f"- research_ready: {str(bundle.research_ready).lower()}",
        f"- live_ready: {str(bundle.live_ready).lower()}",
        f"- input: {bundle.input_path}",
        f"- input_sha256: `{bundle.input_sha256 or '-'}`",
        f"- spec_hash: `{bundle.spec_hash or '-'}`",
        f"- run_dir: {bundle.run_dir or '-'}",
        f"- rows: {bundle.rows_after_filter}/{bundle.rows_before_filter}",
        f"- data_contract_ok: {str(bundle.data_contract_ok).lower()}",
        f"- leak_check_ok: {str(bundle.leak_check_ok).lower()}",
        f"- split_ok: {str(bundle.split_ok).lower()} years={','.join(bundle.split_years) or '-'}",
        f"- execution_source: {bundle.execution_source or '-'}",
        f"- execution_gate_live_ready: {str(bool(bundle.execution_gate.get('live_ready'))).lower()}",
        "",
        "## Evidence IDs",
        "",
    ]
    lines.extend(f"- {item}" for item in bundle.evidence_ids) if bundle.evidence_ids else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_quant_verdict(verdict: QuantRunVerdict) -> str:
    lines = [
        "# Quant Verdict",
        "",
        f"- action: {verdict.action}",
        f"- ok: {str(verdict.ok).lower()}",
        f"- research_ready: {str(verdict.research_ready).lower()}",
        f"- live_ready: {str(verdict.live_ready).lower()}",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {item}" for item in verdict.reasons)
    lines.extend(["", "## Allowed Conclusions", ""])
    lines.extend(f"- {item}" for item in verdict.allowed_conclusions) if verdict.allowed_conclusions else lines.append("- none")
    lines.extend(["", "## Blocked Conclusions", ""])
    lines.extend(f"- {item}" for item in verdict.blocked_conclusions) if verdict.blocked_conclusions else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_quant_gate_json(run: QuantGateRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_quant_gate_run(project: Path, run: QuantGateRun) -> Path:
    root = quant_gate_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run.gate_id}.json"
    path.write_text(render_quant_gate_json(run), encoding="utf-8")
    (root / f"{run.gate_id}.md").write_text(render_quant_gate_run(run), encoding="utf-8")
    return path


def _record_quant_gate_evidence(project: str | Path, bundle: QuantEvidenceBundle, spec: QuantRunSpec) -> tuple[EvidenceRecord, ...]:
    records = [
        record_evidence(
            project,
            claim="quant run gate evidence bundle",
            value=f"run_id={bundle.run_id} input_sha256={bundle.input_sha256} spec_hash={bundle.spec_hash}",
            evidence_type="quant_run_gate",
            source=bundle.run_dir,
            path=bundle.input_path,
            tool="quant_run_gate",
            metadata=bundle.to_dict(),
        ),
        record_evidence(
            project,
            claim="quant run gate split evidence",
            value="years=" + ",".join(bundle.split_years),
            evidence_type="quant_run_gate",
            source=bundle.run_dir,
            path=bundle.input_path,
            tool="quant_run_gate",
            metadata={"gate_id": bundle.gate_id, "run_id": bundle.run_id},
        ),
    ]
    if spec.execution_source:
        records.append(
            record_evidence(
                project,
                claim="broker fill slippage capacity execution source",
                value=spec.execution_source,
                evidence_type="quant_execution_source",
                source=spec.execution_source,
                path=bundle.input_path,
                tool="quant_run_gate",
                metadata={"gate_id": bundle.gate_id, "run_id": bundle.run_id, "capacity_notes": spec.capacity_notes},
            )
        )
    if bundle.execution_gate:
        records.append(
            record_evidence(
                project,
                claim="quant execution gate evidence bundle",
                value=f"live_ready={bundle.execution_gate.get('live_ready')} action={bundle.execution_gate.get('action')}",
                evidence_type="quant_execution_gate",
                source=spec.execution_source,
                path=bundle.input_path,
                tool="quant_execution_gate",
                metadata={"gate_id": bundle.gate_id, "run_id": bundle.run_id, "execution_gate": bundle.execution_gate},
            )
        )
    return tuple(records)


def _run_execution_gate_if_configured(project: Path, spec: QuantRunSpec) -> dict[str, Any]:
    configured = any(
        str(item).strip()
        for item in (
            spec.tick_path,
            spec.fill_path,
            spec.broker_path,
            spec.order_path,
            spec.position_path,
            spec.account_path,
            spec.slippage_path,
            spec.capacity_path,
            spec.execution_source,
        )
    )
    if not configured:
        return {}
    result = run_quant_execution_gate(
        project,
        QuantExecutionEvidenceSpec(
            tick_path=spec.tick_path,
            fill_path=spec.fill_path,
            broker_path=spec.broker_path,
            order_path=spec.order_path,
            position_path=spec.position_path,
            account_path=spec.account_path,
            slippage_path=spec.slippage_path,
            capacity_path=spec.capacity_path,
            execution_source=spec.execution_source,
        ),
    )
    return result.to_dict()


def _experiment_spec(input_path: Path, spec: QuantRunSpec) -> ExperimentSpec:
    return ExperimentSpec(
        name=spec.name or input_path.stem,
        input_path=input_path,
        return_col=spec.return_col,
        date_col=spec.date_col,
        threshold_col=spec.threshold_col or None,
        threshold_lte=spec.threshold_lte,
    )


def _resolve_input(project: Path, input_path: str | Path) -> Path:
    path = Path(input_path).expanduser()
    if not path.is_absolute():
        path = project / path
    return path.resolve(strict=False)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized[:19]).date()
    except ValueError:
        return None


def _run_from_dict(payload: dict[str, Any]) -> QuantGateRun:
    spec_payload = dict(payload.get("spec") or {})
    split_payload = dict(payload.get("split_check") or {})
    bundle_payload = dict(payload.get("evidence_bundle") or {})
    verdict_payload = dict(payload.get("verdict") or {})
    return QuantGateRun(
        gate_id=str(payload.get("gate_id") or ""),
        project=str(payload.get("project") or ""),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        duration_ms=int(payload.get("duration_ms") or 0),
        spec=QuantRunSpec(
            name=str(spec_payload.get("name") or ""),
            input_path=str(spec_payload.get("input_path") or ""),
            return_col=str(spec_payload.get("return_col") or "net_return"),
            date_col=str(spec_payload.get("date_col") or "entry_date"),
            threshold_col=str(spec_payload.get("threshold_col") or ""),
            threshold_lte=spec_payload.get("threshold_lte"),
            data_kind=str(spec_payload.get("data_kind") or "trade_csv"),
            strict_dedup=bool(spec_payload.get("strict_dedup", True)),
            oos_start=str(spec_payload.get("oos_start") or ""),
            oos_end=str(spec_payload.get("oos_end") or ""),
            fees_bps=float(spec_payload.get("fees_bps") or 0.0),
            slippage_bps=float(spec_payload.get("slippage_bps") or 0.0),
            capacity_notes=str(spec_payload.get("capacity_notes") or ""),
            execution_source=str(spec_payload.get("execution_source") or ""),
            tick_path=str(spec_payload.get("tick_path") or ""),
            fill_path=str(spec_payload.get("fill_path") or ""),
            broker_path=str(spec_payload.get("broker_path") or ""),
            order_path=str(spec_payload.get("order_path") or ""),
            position_path=str(spec_payload.get("position_path") or ""),
            account_path=str(spec_payload.get("account_path") or ""),
            slippage_path=str(spec_payload.get("slippage_path") or ""),
            capacity_path=str(spec_payload.get("capacity_path") or ""),
            assumptions=tuple(str(item) for item in spec_payload.get("assumptions") or ()),
            prohibited_actions=tuple(str(item) for item in spec_payload.get("prohibited_actions") or ()),
        ),
        split_check=QuantSplitCheck(
            ok=bool(split_payload.get("ok")),
            date_col=str(split_payload.get("date_col") or "entry_date"),
            rows=int(split_payload.get("rows") or 0),
            years=tuple(str(item) for item in split_payload.get("years") or ()),
            year_counts={str(key): int(value) for key, value in dict(split_payload.get("year_counts") or {}).items()},
            oos_start=str(split_payload.get("oos_start") or ""),
            oos_end=str(split_payload.get("oos_end") or ""),
            oos_rows=int(split_payload.get("oos_rows") or 0),
            in_sample_rows=int(split_payload.get("in_sample_rows") or 0),
            reason=str(split_payload.get("reason") or ""),
        ),
        data_contract=dict(payload.get("data_contract") or {}),
        leak_check=dict(payload.get("leak_check") or {}),
        experiment=dict(payload.get("experiment") or {}),
        evidence_bundle=QuantEvidenceBundle(
            gate_id=str(bundle_payload.get("gate_id") or ""),
            run_id=str(bundle_payload.get("run_id") or ""),
            input_path=str(bundle_payload.get("input_path") or ""),
            input_sha256=str(bundle_payload.get("input_sha256") or ""),
            spec_hash=str(bundle_payload.get("spec_hash") or ""),
            run_dir=str(bundle_payload.get("run_dir") or ""),
            rows_before_filter=int(bundle_payload.get("rows_before_filter") or 0),
            rows_after_filter=int(bundle_payload.get("rows_after_filter") or 0),
            data_contract_ok=bool(bundle_payload.get("data_contract_ok")),
            leak_check_ok=bool(bundle_payload.get("leak_check_ok")),
            split_ok=bool(bundle_payload.get("split_ok")),
            split_years=tuple(str(item) for item in bundle_payload.get("split_years") or ()),
            metric_keys=tuple(str(item) for item in bundle_payload.get("metric_keys") or ()),
            fee_slippage_assumptions=dict(bundle_payload.get("fee_slippage_assumptions") or {}),
            execution_source=str(bundle_payload.get("execution_source") or ""),
            execution_gate=dict(bundle_payload.get("execution_gate") or {}),
            evidence_ids=tuple(str(item) for item in bundle_payload.get("evidence_ids") or ()),
            runner_sha256=str(bundle_payload.get("runner_sha256") or ""),
        ),
        verdict=QuantRunVerdict(
            action=str(verdict_payload.get("action") or BLOCK),
            ok=bool(verdict_payload.get("ok")),
            research_ready=bool(verdict_payload.get("research_ready")),
            live_ready=bool(verdict_payload.get("live_ready")),
            reasons=tuple(str(item) for item in verdict_payload.get("reasons") or ()),
            allowed_conclusions=tuple(str(item) for item in verdict_payload.get("allowed_conclusions") or ()),
            blocked_conclusions=tuple(str(item) for item in verdict_payload.get("blocked_conclusions") or ()),
        ),
    )


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace("_", " ").replace("-", " ").split())


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
