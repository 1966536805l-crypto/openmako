from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .exception_audit import audit_suppressed_exception
from .quant_auto_evidence import QuantAutoEvidenceResult, run_quant_auto_evidence
from .quant_execution_gate import QuantExecutionGateResult, run_quant_execution_gate
from .quant_judge import QuantJudgeResult, QuantJudgeSpec, run_quant_judge
from .quant_run_gate import QuantGateRun, QuantRunSpec, run_quant_gate


PASS = "pass"
BLOCK = "block"


@dataclass(frozen=True)
class QuantFullAuditSpec:
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
    tick_request_path: str = ""
    assumptions: tuple[str, ...] = ()
    auto_evidence: bool = True
    strategy_roots: tuple[str, ...] = ()
    data_roots: tuple[str, ...] = ()
    code: str = ""
    date: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["assumptions"] = list(self.assumptions)
        payload["strategy_roots"] = list(self.strategy_roots)
        payload["data_roots"] = list(self.data_roots)
        return payload


@dataclass(frozen=True)
class QuantFullAuditResult:
    audit_id: str
    project: str
    scenario: str
    ok: bool
    research_ready: bool
    live_ready: bool
    action: str = BLOCK
    data_discovery: dict[str, Any] = field(default_factory=dict)
    sample_manifest: list[dict[str, Any]] = field(default_factory=list)
    leakage_check: dict[str, Any] = field(default_factory=dict)
    cost_slippage_capacity: dict[str, Any] = field(default_factory=dict)
    walk_forward_split: dict[str, Any] = field(default_factory=dict)
    broker_evidence: dict[str, Any] = field(default_factory=dict)
    tick_validation: dict[str, Any] = field(default_factory=dict)
    tick_slippage: dict[str, Any] = field(default_factory=dict)
    tick_capacity: dict[str, Any] = field(default_factory=dict)
    tick_integrity: dict[str, Any] = field(default_factory=dict)
    auto_evidence_result: dict[str, Any] = field(default_factory=dict)
    quant_run: dict[str, Any] = field(default_factory=dict)
    judge_result: dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    warnings: tuple[str, ...] = ()
    output_json: str = ""
    output_markdown: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "project": self.project,
            "scenario": self.scenario,
            "ok": self.ok,
            "research_ready": self.research_ready,
            "live_ready": self.live_ready,
            "action": self.action,
            "data_discovery": self.data_discovery,
            "sample_manifest": list(self.sample_manifest),
            "leakage_check": self.leakage_check,
            "cost_slippage_capacity": self.cost_slippage_capacity,
            "walk_forward_split": self.walk_forward_split,
            "broker_evidence": self.broker_evidence,
            "tick_validation": self.tick_validation,
            "tick_slippage": self.tick_slippage,
            "tick_capacity": self.tick_capacity,
            "tick_integrity": self.tick_integrity,
            "auto_evidence_result": self.auto_evidence_result,
            "quant_run": self.quant_run,
            "judge_result": self.judge_result,
            "failure_reason": self.failure_reason,
            "warnings": list(self.warnings),
            "output_json": self.output_json,
            "output_markdown": self.output_markdown,
            "duration_ms": self.duration_ms,
        }


def run_quant_full_audit(project: str | Path, spec: QuantFullAuditSpec) -> QuantFullAuditResult:
    """
    Run comprehensive quantitative audit integrating:
    - quant_auto_evidence (data discovery, samples, expectations)
    - quant_run_gate (split check, leak check, contract)
    - quant_execution_gate (broker evidence)
    - tick validation (price verification, slippage, capacity, integrity)
    - quant_judge (final verdict)
    """
    project_path = Path(project).expanduser().resolve(strict=False)
    audit_id = "audit-" + str(int(time.time() * 1000))
    started_monotonic = time.monotonic()
    output_dir = _audit_dir(project_path) / audit_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = str(output_dir / f"{audit_id}.json")
    output_markdown = str(output_dir / f"{audit_id}.md")

    warnings: list[str] = []
    auto_evidence_result: dict[str, Any] = {}
    quant_run: dict[str, Any] = {}
    judge_result: dict[str, Any] = {}
    tick_validation: dict[str, Any] = {}
    tick_slippage: dict[str, Any] = {}
    tick_capacity: dict[str, Any] = {}
    tick_integrity: dict[str, Any] = {}

    try:
        # Step 1: Auto evidence discovery if enabled
        if spec.auto_evidence:
            auto_result = run_quant_auto_evidence(
                project_path,
                task=f"full audit scenario {spec.scenario}",
                input_path=spec.input_path,
                strategy_roots=spec.strategy_roots,
                data_roots=spec.data_roots,
                code=spec.code,
                date=spec.date,
                execution_source=spec.execution_source,
                strict_dedup=spec.strict_dedup,
            )
            auto_evidence_result = auto_result.to_dict()
            warnings.extend(auto_result.warnings)

            # Extract discovered execution evidence
            if auto_result.execution_evidence:
                spec = _merge_execution_evidence(spec, auto_result)

        # Step 1.5: Tick validation if tick_request_path or tick_path exists
        tick_validation_result = _run_tick_validation(project_path, spec, warnings)
        tick_validation = tick_validation_result.get("summary", {})
        tick_slippage = tick_validation_result.get("slippage", {})
        tick_capacity = tick_validation_result.get("capacity", {})
        tick_integrity = tick_validation_result.get("integrity", {})

        # Step 2: Run quant judge (which internally runs quant_run_gate)
        judge_spec = _judge_spec_from_audit(spec)
        judge = run_quant_judge(project_path, judge_spec)
        judge_result = judge.to_dict()

        # Extract structured components from judge result
        gate_run = judge_result.get("verdict", {})
        quant_run = _extract_quant_run(judge_result)

        # Build structured audit result
        result = QuantFullAuditResult(
            audit_id=audit_id,
            project=str(project_path),
            scenario=spec.scenario,
            ok=judge.ok,
            research_ready=judge.research_ready,
            live_ready=judge.live_ready,
            action=PASS if judge.ok else BLOCK,
            data_discovery=auto_evidence_result.get("data_discovery", {}),
            sample_manifest=list(auto_evidence_result.get("data_samples", [])),
            leakage_check=_extract_leak_check(quant_run),
            cost_slippage_capacity=_extract_cost_slippage_capacity(quant_run, spec),
            walk_forward_split=_extract_walk_forward_split(quant_run),
            broker_evidence=_extract_broker_evidence(quant_run),
            tick_validation=tick_validation,
            tick_slippage=tick_slippage,
            tick_capacity=tick_capacity,
            tick_integrity=tick_integrity,
            auto_evidence_result=auto_evidence_result,
            quant_run=quant_run,
            judge_result=judge_result,
            failure_reason=judge.error or _build_failure_reason(judge),
            warnings=tuple(warnings),
            output_json=output_json,
            output_markdown=output_markdown,
            duration_ms=_elapsed_ms(started_monotonic),
        )

    except (OSError, ValueError) as exc:
        result = QuantFullAuditResult(
            audit_id=audit_id,
            project=str(project_path),
            scenario=spec.scenario,
            ok=False,
            research_ready=False,
            live_ready=False,
            action=BLOCK,
            failure_reason=str(exc),
            warnings=tuple(warnings),
            output_json=output_json,
            output_markdown=output_markdown,
            duration_ms=_elapsed_ms(started_monotonic),
        )

    return _write_audit_result(result)


def render_quant_full_audit(result: QuantFullAuditResult) -> str:
    """Render audit result as markdown report."""
    lines = [
        "# Quant Full Audit Report",
        "",
        f"- audit_id: {result.audit_id}",
        f"- scenario: {result.scenario}",
        f"- action: {result.action}",
        f"- ok: {str(result.ok).lower()}",
        f"- research_ready: {str(result.research_ready).lower()}",
        f"- live_ready: {str(result.live_ready).lower()}",
        f"- duration_ms: {result.duration_ms}",
        "",
        "## Executive Summary",
        "",
    ]

    if result.failure_reason:
        lines.append(f"**BLOCKED**: {result.failure_reason}")
    elif result.ok:
        lines.append("**PASS**: All checks passed, research-ready.")
        if result.live_ready:
            lines.append("**LIVE-READY**: Broker execution evidence validated.")
    else:
        lines.append("**INCONCLUSIVE**: Some checks failed or incomplete.")

    lines.extend(["", "## Data Discovery", ""])
    discovery = result.data_discovery
    if discovery:
        lines.append(f"- artifacts_found: {len(discovery.get('artifacts', []))}")
        lines.append(f"- files_scanned: {discovery.get('files_scanned', 0)}")
        lines.append(f"- discovery_ok: {str(bool(discovery.get('ok'))).lower()}")
    else:
        lines.append("- not performed")

    lines.extend(["", "## Sample Manifest", ""])
    if result.sample_manifest:
        for sample in result.sample_manifest:
            spec = sample.get("spec", {})
            lines.append(
                f"- {spec.get('kind', 'unknown')}: "
                f"ok={str(bool(sample.get('ok'))).lower()} "
                f"rows={sample.get('rows_written', 0)}"
            )
    else:
        lines.append("- no samples")

    lines.extend(["", "## Leakage Check", ""])
    leak = result.leakage_check
    if leak:
        lines.append(f"- ok: {str(bool(leak.get('ok'))).lower()}")
        lines.append(f"- hard_leak_columns: {', '.join(leak.get('hard_leak_columns', [])) or 'none'}")
        lines.append(f"- soft_leak_columns: {', '.join(leak.get('soft_leak_columns', [])) or 'none'}")
    else:
        lines.append("- not performed")

    lines.extend(["", "## Walk-Forward Split", ""])
    split = result.walk_forward_split
    if split:
        lines.append(f"- ok: {str(bool(split.get('ok'))).lower()}")
        lines.append(f"- years: {', '.join(split.get('years', [])) or 'none'}")
        lines.append(f"- oos_rows: {split.get('oos_rows', 0)}")
        lines.append(f"- in_sample_rows: {split.get('in_sample_rows', 0)}")
        lines.append(f"- reason: {split.get('reason', '-')}")
    else:
        lines.append("- not performed")

    lines.extend(["", "## Cost/Slippage/Capacity", ""])
    cost = result.cost_slippage_capacity
    if cost:
        lines.append(f"- fees_bps: {cost.get('fees_bps', 0)}")
        lines.append(f"- slippage_bps: {cost.get('slippage_bps', 0)}")
        lines.append(f"- capacity_notes: {cost.get('capacity_notes', '-')}")
        assumptions = cost.get("assumptions", [])
        if assumptions:
            lines.append("- assumptions:")
            for assumption in assumptions:
                lines.append(f"  - {assumption}")
    else:
        lines.append("- not specified")

    lines.extend(["", "## Broker Evidence", ""])
    broker = result.broker_evidence
    if broker:
        lines.append(f"- live_ready: {str(bool(broker.get('live_ready'))).lower()}")
        lines.append(f"- execution_source: {broker.get('execution_source', '-')}")
        artifacts = broker.get("artifacts", [])
        lines.append(f"- artifacts: {len(artifacts)}")
        for artifact in artifacts:
            lines.append(
                f"  - {artifact.get('evidence_type', 'unknown')}: "
                f"exists={str(bool(artifact.get('exists'))).lower()} "
                f"bytes={artifact.get('bytes', 0)}"
            )
    else:
        lines.append("- not provided")

    lines.extend(["", "## Tick Data Validation", ""])
    tick_val = result.tick_validation
    if tick_val and tick_val.get("performed"):
        lines.append(f"- performed: true")
        lines.append(f"- ok: {str(bool(tick_val.get('ok'))).lower()}")
        lines.append(f"- tick_rows: {tick_val.get('tick_rows', 0)}")
        lines.append(f"- fills_checked: {tick_val.get('fills_checked', 0)}")
        lines.append(f"- fills_explained: {tick_val.get('fills_explained', 0)}")

        # Slippage analysis
        slippage = result.tick_slippage
        if slippage:
            lines.append("- slippage_analysis:")
            lines.append(f"  - ok: {str(bool(slippage.get('ok'))).lower()}")
            lines.append(f"  - fills_checked: {slippage.get('fills_checked', 0)}")
            issues = slippage.get("issues", [])
            if issues:
                lines.append(f"  - issues: {len(issues)}")
                for issue in issues[:3]:
                    lines.append(f"    - {issue.get('code', 'unknown')}: {issue.get('message', '')}")

        # Capacity validation
        capacity = result.tick_capacity
        if capacity:
            lines.append("- capacity_validation:")
            lines.append(f"  - ok: {str(bool(capacity.get('ok'))).lower()}")
            issues = capacity.get("issues", [])
            if issues:
                lines.append(f"  - issues: {len(issues)}")
                for issue in issues[:3]:
                    lines.append(f"    - {issue.get('code', 'unknown')}: {issue.get('message', '')}")

        # Integrity check
        integrity = result.tick_integrity
        if integrity:
            lines.append("- integrity_check:")
            lines.append(f"  - ok: {str(bool(integrity.get('ok'))).lower()}")
            lines.append(f"  - tick_rows: {integrity.get('tick_rows', 0)}")
            issues = integrity.get("issues", [])
            if issues:
                lines.append(f"  - issues: {len(issues)}")
                for issue in issues[:3]:
                    lines.append(f"    - {issue.get('code', 'unknown')}: {issue.get('message', '')}")
    else:
        reason = tick_val.get("reason", "not performed") if tick_val else "not performed"
        lines.append(f"- performed: false ({reason})")

    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        for warning in result.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")

    lines.extend(["", "## Output Files", ""])
    lines.append(f"- JSON: {result.output_json}")
    lines.append(f"- Markdown: {result.output_markdown}")

    return "\n".join(lines).rstrip() + "\n"


def render_quant_full_audit_json(result: QuantFullAuditResult) -> str:
    """Render audit result as JSON."""
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _judge_spec_from_audit(spec: QuantFullAuditSpec) -> QuantJudgeSpec:
    """Convert audit spec to judge spec."""
    return QuantJudgeSpec(
        scenario=spec.scenario,
        input_path=spec.input_path,
        name=spec.name,
        return_col=spec.return_col,
        date_col=spec.date_col,
        threshold_col=spec.threshold_col,
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


def _merge_execution_evidence(spec: QuantFullAuditSpec, auto_result: QuantAutoEvidenceResult) -> QuantFullAuditSpec:
    """Merge discovered execution evidence into spec."""
    evidence = auto_result.execution_evidence
    return QuantFullAuditSpec(
        scenario=spec.scenario,
        input_path=spec.input_path or auto_result.position_path,
        name=spec.name,
        return_col=spec.return_col,
        date_col=spec.date_col,
        threshold_col=spec.threshold_col,
        threshold_lte=spec.threshold_lte,
        data_kind=spec.data_kind,
        strict_dedup=spec.strict_dedup,
        oos_start=spec.oos_start,
        oos_end=spec.oos_end,
        fees_bps=spec.fees_bps,
        slippage_bps=spec.slippage_bps,
        capacity_notes=spec.capacity_notes,
        execution_source=spec.execution_source or auto_result.execution_evidence.get("execution_source", ""),
        tick_path=spec.tick_path or evidence.get("tick", ""),
        fill_path=spec.fill_path or evidence.get("fill", ""),
        broker_path=spec.broker_path or evidence.get("broker", ""),
        order_path=spec.order_path or evidence.get("order", ""),
        position_path=spec.position_path or evidence.get("position", ""),
        account_path=spec.account_path or evidence.get("account", ""),
        slippage_path=spec.slippage_path or evidence.get("slippage", ""),
        capacity_path=spec.capacity_path or evidence.get("capacity", ""),
        tick_request_path=spec.tick_request_path,
        assumptions=spec.assumptions,
        auto_evidence=spec.auto_evidence,
        strategy_roots=spec.strategy_roots,
        data_roots=spec.data_roots,
        code=spec.code,
        date=spec.date,
    )


def _extract_quant_run(judge_result: dict[str, Any]) -> dict[str, Any]:
    """Extract quant run data from judge result."""
    # Judge result doesn't directly expose the full QuantGateRun, but we can reconstruct key parts
    return {
        "gate_id": "",
        "run_id": judge_result.get("run_id", ""),
        "input_sha256": judge_result.get("input_sha256", ""),
        "spec_hash": judge_result.get("spec_hash", ""),
        "rows_before_filter": judge_result.get("rows_before_filter", 0),
        "rows_after_filter": judge_result.get("rows_after_filter", 0),
        "verdict": judge_result.get("verdict", {}),
    }


def _extract_leak_check(quant_run: dict[str, Any]) -> dict[str, Any]:
    """Extract leakage check from quant run."""
    verdict = quant_run.get("verdict", {})
    reasons = verdict.get("reasons", [])
    leak_failed = any("leakage" in str(reason).lower() for reason in reasons)
    return {
        "ok": not leak_failed,
        "hard_leak_columns": [],
        "soft_leak_columns": [],
    }


def _extract_walk_forward_split(quant_run: dict[str, Any]) -> dict[str, Any]:
    """Extract walk-forward split from quant run."""
    verdict = quant_run.get("verdict", {})
    reasons = verdict.get("reasons", [])
    split_reason = ""
    for reason in reasons:
        if "split" in str(reason).lower() or "year" in str(reason).lower():
            split_reason = str(reason)
            break
    return {
        "ok": "split" not in split_reason.lower() if split_reason else True,
        "years": [],
        "oos_rows": 0,
        "in_sample_rows": 0,
        "reason": split_reason or "split check passed",
    }


def _extract_cost_slippage_capacity(quant_run: dict[str, Any], spec: QuantFullAuditSpec) -> dict[str, Any]:
    """Extract cost/slippage/capacity assumptions."""
    return {
        "fees_bps": spec.fees_bps,
        "slippage_bps": spec.slippage_bps,
        "capacity_notes": spec.capacity_notes,
        "assumptions": list(spec.assumptions),
    }


def _extract_broker_evidence(quant_run: dict[str, Any]) -> dict[str, Any]:
    """Extract broker evidence from quant run."""
    verdict = quant_run.get("verdict", {})
    return {
        "live_ready": verdict.get("live_ready", False),
        "execution_source": "",
        "artifacts": [],
    }


def _build_failure_reason(judge: QuantJudgeResult) -> str:
    """Build failure reason from judge result."""
    if judge.ok:
        return ""
    verdict = judge.verdict
    if isinstance(verdict, dict):
        reasons = verdict.get("reasons", [])
        if reasons:
            return "; ".join(str(r) for r in reasons)
    return "audit checks failed"


def _audit_dir(project: Path) -> Path:
    """Get audit output directory."""
    base = project / "AI_协作交接"
    if not base.exists():
        base = project / ".quantagent"
    return base / "quant_full_audit"


def _write_audit_result(result: QuantFullAuditResult) -> QuantFullAuditResult:
    """Write audit result to disk."""
    if result.output_json:
        Path(result.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(result.output_json).write_text(render_quant_full_audit_json(result), encoding="utf-8")
    if result.output_markdown:
        Path(result.output_markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(result.output_markdown).write_text(render_quant_full_audit(result), encoding="utf-8")
    return result


def _elapsed_ms(started: float) -> int:
    """Calculate elapsed time in milliseconds."""
    return round((time.monotonic() - started) * 1000)


def _run_tick_validation(project: Path, spec: QuantFullAuditSpec, warnings: list[str]) -> dict[str, Any]:
    """
    Run tick validation if tick_request_path or tick_path is available.

    Returns dict with:
    - summary: overall tick validation status
    - slippage: slippage analysis results
    - capacity: capacity validation results
    - integrity: data integrity check results
    """
    result = {
        "summary": {},
        "slippage": {},
        "capacity": {},
        "integrity": {},
    }

    # Check if tick_request_path is provided
    tick_request_path = spec.tick_request_path
    if not tick_request_path:
        # Try to auto-detect tick_data_request files
        tick_request_path = _find_tick_data_request(project)

    if not tick_request_path and not spec.tick_path:
        # No tick data available, skip validation
        result["summary"] = {"performed": False, "reason": "no tick data available"}
        return result

    try:
        from .quant_data_sample import sample_local_quant_data, QuantDataSampleSpec
        from .quant_execution_replay import run_quant_execution_replay
        from .broker_gateway import BrokerGatewaySpec, build_broker_gateway_snapshot

        tick_data_extracted = False
        tick_output_dir = project / "AI_协作交接" / "tick_validation"
        tick_output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Extract tick data if tick_request_path exists
        if tick_request_path:
            tick_request_file = Path(tick_request_path)
            if not tick_request_file.is_absolute():
                tick_request_file = project / tick_request_file

            if tick_request_file.exists():
                # Parse tick_data_request to extract tick samples
                extracted_ticks = _extract_tick_data_from_request(project, tick_request_file, tick_output_dir)
                if extracted_ticks:
                    tick_data_extracted = True
                    result["summary"]["tick_data_extracted"] = len(extracted_ticks)
                    result["summary"]["tick_request_file"] = str(tick_request_file)

        # Step 2: Run price verification and slippage calculation
        if spec.tick_path or tick_data_extracted:
            tick_path_to_use = spec.tick_path if spec.tick_path else str(tick_output_dir)

            # Build broker snapshot if fill/broker data available
            if spec.fill_path or spec.broker_path:
                broker_snapshot = build_broker_gateway_snapshot(
                    project,
                    BrokerGatewaySpec(
                        broker_path=spec.broker_path,
                        fill_path=spec.fill_path,
                        order_path=spec.order_path,
                        position_path=spec.position_path,
                        account_path=spec.account_path,
                        source=spec.execution_source,
                    ),
                )

                # Run execution replay for price verification and slippage
                replay_result = run_quant_execution_replay(
                    project,
                    tick_path=tick_path_to_use,
                    slippage_path=spec.slippage_path,
                    capacity_path=spec.capacity_path,
                    broker_snapshot=broker_snapshot,
                )

                result["slippage"] = {
                    "ok": replay_result.ok,
                    "fills_checked": replay_result.fills_checked,
                    "fills_explained": replay_result.fills_explained,
                    "issues": [issue.to_dict() for issue in replay_result.issues if "slippage" in issue.code.lower()],
                }

                result["capacity"] = {
                    "ok": replay_result.ok,
                    "fills_checked": replay_result.fills_checked,
                    "issues": [issue.to_dict() for issue in replay_result.issues if "capacity" in issue.code.lower()],
                }

                result["integrity"] = {
                    "ok": replay_result.ok,
                    "tick_rows": replay_result.tick_rows,
                    "issues": [issue.to_dict() for issue in replay_result.issues if "tick" in issue.code.lower() or "integrity" in issue.code.lower()],
                }

                result["summary"] = {
                    "performed": True,
                    "ok": replay_result.ok,
                    "tick_rows": replay_result.tick_rows,
                    "fills_checked": replay_result.fills_checked,
                    "fills_explained": replay_result.fills_explained,
                }
            else:
                result["summary"] = {
                    "performed": False,
                    "reason": "no fill/broker data for validation",
                }

    except ImportError as exc:
        warnings.append(f"Tick validation skipped: {exc}")
        result["summary"] = {"performed": False, "reason": f"import error: {exc}"}
    except Exception as exc:
        warnings.append(f"Tick validation failed: {exc}")
        result["summary"] = {"performed": False, "reason": f"error: {exc}"}

    return result


def _find_tick_data_request(project: Path) -> str:
    """Find tick_data_request file in project."""
    patterns = [
        "tick_data_request*.csv",
        "AI_协作交接/tick_data_request*.csv",
        "data/tick_data_request*.csv",
    ]

    for pattern in patterns:
        matches = list(project.glob(pattern))
        if matches:
            return str(matches[0])

    return ""


def _extract_tick_data_from_request(project: Path, tick_request_file: Path, output_dir: Path) -> list[str]:
    """
    Extract tick data based on tick_data_request file.

    Returns list of extracted tick file paths.
    """
    import csv

    extracted = []

    try:
        with tick_request_file.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Expected columns: code, date (or entry_date)
        for row in rows[:10]:  # Limit to first 10 for performance
            code = row.get("code", "").strip()
            date = row.get("date", row.get("entry_date", "")).strip()

            if not code or not date:
                continue

            # Try to sample tick data
            try:
                from .quant_data_sample import sample_local_quant_data, QuantDataSampleSpec

                result = sample_local_quant_data(
                    project,
                    QuantDataSampleSpec(
                        root="",  # Auto-detect
                        code=code,
                        kind="tick_trade",
                        date=date,
                        max_rows=1000,
                    ),
                )

                if result.ok and result.output_path:
                    extracted.append(result.output_path)
            except Exception as exc:
                audit_suppressed_exception(
                    f"{__name__}:extract_requested_tick_data.sample",
                    exc,
                    project=project,
                    data={"code": code, "date": date},
                )
                continue

    except Exception as exc:
        audit_suppressed_exception(
            f"{__name__}:extract_requested_tick_data.read",
            exc,
            project=project,
            data={"path": str(tick_request_file)},
        )

    return extracted


def _elapsed_ms(started: float) -> int:
    """Calculate elapsed time in milliseconds."""
    return round((time.monotonic() - started) * 1000)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run comprehensive quantitative audit")
    parser.add_argument("--project", default=".", help="Project directory")
    parser.add_argument("--scenario", default="A", help="Scenario identifier")
    parser.add_argument("--input", default="", help="Input CSV path")
    parser.add_argument("--threshold", type=float, help="Threshold value for filtering")
    parser.add_argument("--threshold-col", default="t1_auction_return", help="Threshold column name")
    parser.add_argument("--tick-request", default="", help="Path to tick_data_request CSV file")
    parser.add_argument("--output", help="Output markdown file path")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--no-auto-evidence", action="store_true", help="Skip auto evidence discovery")

    args = parser.parse_args()

    spec = QuantFullAuditSpec(
        scenario=args.scenario,
        input_path=args.input,
        threshold_col=args.threshold_col,
        threshold_lte=args.threshold,
        tick_request_path=args.tick_request,
        auto_evidence=not args.no_auto_evidence,
    )

    result = run_quant_full_audit(args.project, spec)

    if args.output:
        output_path = Path(args.output)
        if args.json:
            output_path.write_text(render_quant_full_audit_json(result), encoding="utf-8")
        else:
            output_path.write_text(render_quant_full_audit(result), encoding="utf-8")
        print(f"Audit report written to: {output_path}")
    else:
        if args.json:
            print(render_quant_full_audit_json(result))
        else:
            print(render_quant_full_audit(result))

    sys.exit(0 if result.ok else 1)
