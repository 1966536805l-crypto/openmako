from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .quant_data_adapter import QuantDataAdapterResult, QuantDataArtifact, discover_quant_data, inspect_quant_data_file
from .quant_data_sample import QuantDataSampleSpec, sample_local_quant_data
from .quant_expectations import QuantExpectationReport, run_quant_expectations
from .quant_run_gate import BLOCK, QuantRunSpec, build_quant_run_verdict, render_quant_verdict, run_quant_gate


_EXECUTION_EVIDENCE_ROLES = ("tick", "fill", "broker", "order", "position", "account", "slippage", "capacity")
_BROKER_BUNDLE_REQUIRED_ROLES = ("fill", "broker")


@dataclass(frozen=True)
class QuantStrategyInputCandidate:
    path: str
    kind: str
    date_col: str
    return_col: str
    data_kind: str
    strict_dedup: bool
    score: tuple[int, int, str] = (99, 99, "")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = list(self.score)
        return payload


@dataclass(frozen=True)
class QuantStrategyProfile:
    code: str = ""
    sample_date: str = ""
    rows_sampled: int = 0
    codes: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["codes"] = list(self.codes)
        payload["dates"] = list(self.dates)
        return payload


@dataclass(frozen=True)
class QuantAutoEvidenceResult:
    auto_id: str
    project: str
    task: str
    ok: bool
    action: str
    research_ready: bool
    live_ready: bool
    position_path: str = ""
    position_kind: str = ""
    profile: QuantStrategyProfile = field(default_factory=QuantStrategyProfile)
    data_discovery: dict[str, Any] = field(default_factory=dict)
    data_samples: tuple[dict[str, Any], ...] = ()
    expectations: tuple[dict[str, Any], ...] = ()
    execution_evidence: dict[str, str] = field(default_factory=dict)
    run_spec: dict[str, Any] = field(default_factory=dict)
    quant_run: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    output_json: str = ""
    output_markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_id": self.auto_id,
            "project": self.project,
            "task": self.task,
            "ok": self.ok,
            "action": self.action,
            "research_ready": self.research_ready,
            "live_ready": self.live_ready,
            "position_path": self.position_path,
            "position_kind": self.position_kind,
            "profile": self.profile.to_dict(),
            "data_discovery": self.data_discovery,
            "data_samples": list(self.data_samples),
            "expectations": list(self.expectations),
            "execution_evidence": dict(self.execution_evidence),
            "run_spec": self.run_spec,
            "quant_run": self.quant_run,
            "verdict": self.verdict,
            "warnings": list(self.warnings),
            "output_json": self.output_json,
            "output_markdown": self.output_markdown,
        }


def run_quant_auto_evidence(
    project: str | Path,
    task: str = "",
    *,
    input_path: str | Path = "",
    strategy_roots: Iterable[str | Path] = (),
    data_roots: Iterable[str | Path] = (),
    code: str = "",
    date: str = "",
    execution_source: str = "",
    max_files: int = 5000,
    sample_zip_members: int = 20,
    max_rows: int = 1000,
    strict_dedup: bool = True,
) -> QuantAutoEvidenceResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    auto_id = "qauto-" + str(int(time.time() * 1000))
    output_dir = _auto_evidence_dir(project_path) / auto_id
    sample_dir = output_dir / "data_samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    expectations: list[dict[str, Any]] = []
    data_samples: list[dict[str, Any]] = []
    execution_evidence: dict[str, str] = {}

    candidate = find_strategy_input_candidate(
        project_path,
        input_path=input_path,
        roots=strategy_roots,
        strict_dedup=strict_dedup,
        max_files=max_files,
    )
    if candidate is None:
        warnings.append("no position/backtest CSV or strategy output candidate found")
        return _write_auto_result(
            QuantAutoEvidenceResult(
                auto_id=auto_id,
                project=str(project_path),
                task=task,
                ok=False,
                action=BLOCK,
                research_ready=False,
                live_ready=False,
                warnings=tuple(warnings),
                output_json=str(output_dir / f"{auto_id}.json"),
                output_markdown=str(output_dir / f"{auto_id}.md"),
            )
        )

    profile = profile_strategy_input(candidate, override_code=code, override_date=date)
    if strict_dedup and not candidate.strict_dedup and candidate.kind == "position_csv":
        warnings.append("selected strategy CSV is not dedup-marked; auto-evidence treats it as strategy output, not a clean dedup baseline")
    strategy_expectations = run_quant_expectations(candidate.path, kind=candidate.data_kind, sample_rows=max_rows)
    expectations.append(_expectation_record("strategy_input", strategy_expectations))

    target_data_roots = _quant_data_roots(project_path, data_roots)
    discovery = discover_quant_data(
        project_path,
        target_data_roots,
        max_files=max_files,
        sample_zip_members=sample_zip_members,
    )
    if discovery.warnings:
        warnings.extend(discovery.warnings)

    if profile.code and profile.sample_date:
        sampled, sample_warnings = _sample_quant_data_roots(project_path, target_data_roots, profile, sample_dir, max_rows=max_rows)
        existing_kinds = {str(item.get("spec", {}).get("kind") or "") for item in sampled if isinstance(item.get("spec"), dict)}
        discovered_sampled, discovered_warnings = _sample_discovered_data(
            project_path,
            discovery,
            profile,
            sample_dir,
            max_rows=max_rows,
            skip_kinds=existing_kinds,
        )
        sampled.extend(discovered_sampled)
        data_samples.extend(sampled)
        warnings.extend(sample_warnings)
        warnings.extend(discovered_warnings)
        for sample in sampled:
            sample_expectations = sample.get("expectations")
            if isinstance(sample_expectations, dict):
                role = "data_sample:" + str(sample.get("spec", {}).get("kind") or sample.get("expectation_kind") or "unknown")
                expectations.append({"role": role, **sample_expectations})
            kind = str(sample.get("spec", {}).get("kind") or "")
            if kind == "tick_trade" and sample.get("ok") and sample.get("output_path"):
                execution_evidence.setdefault("tick", str(sample["output_path"]))
    else:
        missing = []
        if not profile.code:
            missing.append("code")
        if not profile.sample_date:
            missing.append("date")
        warnings.append("data sampling skipped; strategy input did not expose " + "/".join(missing))

    direct_expectations, direct_execution = _expect_direct_data_artifacts(discovery)
    expectations.extend(direct_expectations)
    execution_evidence.update({key: value for key, value in direct_execution.items() if key not in execution_evidence})
    generic_execution = _find_execution_evidence_files(project_path, _strategy_roots(project_path, strategy_roots), max_files=max_files)
    broker_bundle_execution = _find_broker_evidence_bundle(project_path, max_files=max_files)
    execution_evidence.update(generic_execution)
    execution_evidence.update(broker_bundle_execution)

    run_spec = _build_run_spec(
        candidate,
        profile,
        execution_evidence,
        execution_source=execution_source,
    )
    run = run_quant_gate(project_path, run_spec)
    verdict = build_quant_run_verdict(run.evidence_bundle, task=task)
    result = QuantAutoEvidenceResult(
        auto_id=auto_id,
        project=str(project_path),
        task=task,
        ok=verdict.ok,
        action=verdict.action,
        research_ready=verdict.research_ready,
        live_ready=verdict.live_ready,
        position_path=candidate.path,
        position_kind=candidate.kind,
        profile=profile,
        data_discovery=discovery.to_dict(),
        data_samples=tuple(data_samples),
        expectations=tuple(expectations),
        execution_evidence=execution_evidence,
        run_spec=run_spec.to_dict(),
        quant_run=run.to_dict(),
        verdict=verdict.to_dict(),
        warnings=tuple(_dedupe(warnings)),
        output_json=str(output_dir / f"{auto_id}.json"),
        output_markdown=str(output_dir / f"{auto_id}.md"),
    )
    return _write_auto_result(result)


def find_strategy_input_candidate(
    project: str | Path,
    *,
    input_path: str | Path = "",
    roots: Iterable[str | Path] = (),
    strict_dedup: bool = True,
    max_files: int = 5000,
) -> QuantStrategyInputCandidate | None:
    project_path = Path(project).expanduser().resolve(strict=False)
    explicit_input = _resolve_optional_path(project_path, input_path)
    if explicit_input:
        return _candidate_from_csv(project_path, explicit_input, strict_dedup=strict_dedup)
    scan_roots = _strategy_roots(project_path, roots)
    candidates: list[QuantStrategyInputCandidate] = []
    seen: set[Path] = set()
    scanned = 0
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if path in seen or _is_generated_path(path):
                continue
            seen.add(path)
            scanned += 1
            if scanned > max_files:
                break
            candidate = _candidate_from_csv(project_path, path, strict_dedup=strict_dedup)
            if candidate is not None:
                candidates.append(candidate)
        if scanned > max_files:
            break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.score)
    return candidates[0]


def profile_strategy_input(
    candidate: QuantStrategyInputCandidate,
    *,
    override_code: str = "",
    override_date: str = "",
    max_rows: int = 500,
) -> QuantStrategyProfile:
    path = Path(candidate.path)
    code_values: list[str] = []
    date_values: list[str] = []
    pair_values: list[tuple[str, str]] = []
    rows_sampled = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [name for name in (reader.fieldnames or []) if name]
            code_col = _role_column(columns, "code")
            date_col = candidate.date_col if candidate.date_col in columns else _role_column(columns, "date")
            for _, row in zip(range(max_rows), reader):
                rows_sampled += 1
                normalized = ""
                normalized_date = ""
                if code_col:
                    normalized = _normalize_code(str(row.get(code_col) or ""))
                    if normalized:
                        code_values.append(normalized)
                if date_col:
                    normalized_date = _normalize_date(str(row.get(date_col) or ""))
                    if normalized_date:
                        date_values.append(normalized_date)
                if normalized and normalized_date:
                    pair_values.append((normalized_date, normalized))
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = [name for name in (reader.fieldnames or []) if name]
            code_col = _role_column(columns, "code")
            date_col = candidate.date_col if candidate.date_col in columns else _role_column(columns, "date")
            for _, row in zip(range(max_rows), reader):
                rows_sampled += 1
                normalized = ""
                normalized_date = ""
                if code_col:
                    normalized = _normalize_code(str(row.get(code_col) or ""))
                    if normalized:
                        code_values.append(normalized)
                if date_col:
                    normalized_date = _normalize_date(str(row.get(date_col) or ""))
                    if normalized_date:
                        date_values.append(normalized_date)
                if normalized and normalized_date:
                    pair_values.append((normalized_date, normalized))
    file_code = _normalize_code(path.name)
    override_code_norm = _normalize_code(override_code)
    override_date_norm = _normalize_date(override_date)
    pairs = sorted(_dedupe_pairs(pair_values))
    selected_date = override_date_norm or (pairs[-1][0] if pairs else "")
    selected_code = override_code_norm
    if not selected_code and selected_date:
        for pair_date, pair_code in reversed(pairs):
            if pair_date == selected_date and pair_code:
                selected_code = pair_code
                break
    if not selected_code:
        selected_code = (pairs[-1][1] if pairs else "") or file_code
    if not selected_date:
        selected_date = pairs[-1][0] if pairs else ""
    codes = tuple(_dedupe([selected_code, override_code_norm, *code_values, file_code]))
    dates = tuple(sorted(_dedupe([selected_date, override_date_norm, *date_values])))
    return QuantStrategyProfile(
        code=selected_code or (codes[0] if codes else ""),
        sample_date=selected_date or (dates[-1] if dates else ""),
        rows_sampled=rows_sampled,
        codes=codes,
        dates=dates,
    )


def render_quant_auto_evidence(result: QuantAutoEvidenceResult) -> str:
    lines = [
        "# Quant Auto Evidence",
        "",
        f"- auto_id: {result.auto_id}",
        f"- action: {result.action}",
        f"- ok: {str(result.ok).lower()}",
        f"- research_ready: {str(result.research_ready).lower()}",
        f"- live_ready: {str(result.live_ready).lower()}",
        f"- position: {result.position_path or '-'}",
        f"- position_kind: {result.position_kind or '-'}",
        f"- code: {result.profile.code or '-'}",
        f"- sample_date: {result.profile.sample_date or '-'}",
        f"- gate_id: {result.quant_run.get('gate_id') or '-'}",
        f"- output_json: {result.output_json or '-'}",
        "",
        "## Data Samples",
        "",
    ]
    if not result.data_samples:
        lines.append("- none")
    for sample in result.data_samples:
        spec = sample.get("spec") if isinstance(sample.get("spec"), dict) else {}
        lines.append(
            "- "
            + f"{spec.get('kind') or sample.get('expectation_kind') or 'unknown'} "
            + f"ok={str(bool(sample.get('ok'))).lower()} "
            + f"rows={sample.get('rows_written', 0)} "
            + f"output={sample.get('output_path') or '-'}"
        )
    lines.extend(["", "## Expectations", ""])
    if not result.expectations:
        lines.append("- none")
    for item in result.expectations:
        findings = item.get("findings") if isinstance(item.get("findings"), list) else []
        block_count = sum(1 for finding in findings if isinstance(finding, dict) and finding.get("level") == BLOCK)
        lines.append(
            f"- {item.get('role') or 'expectation'} kind={item.get('kind') or '-'} "
            f"ok={str(bool(item.get('ok'))).lower()} blocks={block_count} path={item.get('path') or '-'}"
        )
    lines.extend(["", "## Execution Evidence", ""])
    if not result.execution_evidence:
        lines.append("- none")
    for key in ("tick", "fill", "broker", "order", "position", "account", "slippage", "capacity"):
        if key in result.execution_evidence:
            lines.append(f"- {key}: {result.execution_evidence[key]}")
    lines.extend(["", "## Verdict", ""])
    if result.verdict:
        lines.append(render_quant_verdict_dict(result.verdict).rstrip())
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_quant_verdict_dict(verdict: dict[str, Any]) -> str:
    class _Verdict:
        action = str(verdict.get("action") or BLOCK)
        ok = bool(verdict.get("ok"))
        research_ready = bool(verdict.get("research_ready"))
        live_ready = bool(verdict.get("live_ready"))
        reasons = tuple(str(item) for item in verdict.get("reasons") or ())
        allowed_conclusions = tuple(str(item) for item in verdict.get("allowed_conclusions") or ())
        blocked_conclusions = tuple(str(item) for item in verdict.get("blocked_conclusions") or ())

    return render_quant_verdict(_Verdict())  # type: ignore[arg-type]


def _candidate_from_csv(project: Path, path: Path, *, strict_dedup: bool) -> QuantStrategyInputCandidate | None:
    try:
        artifact = inspect_quant_data_file(path)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    columns = list(artifact.columns)
    if not columns:
        return None
    lowered = path.name.lower()
    date_col = _role_column(columns, "entry_date") or _role_column(columns, "date")
    return_col = _role_column(columns, "return")
    if artifact.kind in {"position_dedup_csv", "position_csv"} or (date_col and return_col and ("position" in lowered or "dedup" in lowered)):
        data_kind = "trade_csv"
        kind = artifact.kind if artifact.kind != "unknown" else "position_csv"
        score = _candidate_score(project, path, kind)
        candidate_strict_dedup = strict_dedup and ("dedup" in lowered or "check_dedup" in lowered)
        return QuantStrategyInputCandidate(
            path=str(path.resolve(strict=False)),
            kind=kind,
            date_col=date_col or "entry_date",
            return_col=return_col or "net_return",
            data_kind=data_kind,
            strict_dedup=candidate_strict_dedup,
            score=score,
        )
    if artifact.kind == "backtest_return_csv" or (date_col and return_col and any(token in lowered for token in ("return", "backtest", "strategy", "pnl"))):
        score = _candidate_score(project, path, artifact.kind if artifact.kind != "unknown" else "backtest_return_csv")
        return QuantStrategyInputCandidate(
            path=str(path.resolve(strict=False)),
            kind=artifact.kind if artifact.kind != "unknown" else "backtest_return_csv",
            date_col=date_col or "date",
            return_col=return_col or "return",
            data_kind="return_series",
            strict_dedup=False,
            score=score,
        )
    return None


def _candidate_score(project: Path, path: Path, kind: str) -> tuple[int, int, str]:
    lowered = path.name.lower()
    kind_score = {
        "position_dedup_csv": 0,
        "position_csv": 2,
        "backtest_return_csv": 3,
    }.get(kind, 4)
    if "dedup" in lowered:
        kind_score -= 8
    if "preferred" in lowered or "best" in lowered:
        kind_score -= 5
    if "true" in lowered or "audited" in lowered:
        kind_score -= 3
    if "portfolio" in lowered:
        kind_score -= 2
    if "trades" in lowered or "trade" in lowered:
        kind_score -= 2
    if "summary" in lowered:
        kind_score += 5
    if "feature" in lowered or "prediction" in lowered or "event" in lowered:
        kind_score += 4
    if "diagnostic" in lowered or "stress" in lowered:
        kind_score += 2
    root_score = 0 if path == project or project in path.parents else 2
    if project / "AI_协作交接" in path.parents:
        root_score = 0
    return (kind_score, root_score, str(path))


def _sample_discovered_data(
    project: Path,
    discovery: QuantDataAdapterResult,
    profile: QuantStrategyProfile,
    sample_dir: Path,
    *,
    max_rows: int,
    skip_kinds: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    skip = skip_kinds or set()
    selected = _select_sample_artifacts(discovery.artifacts, profile.sample_date)
    for kind, artifact in selected.items():
        if kind in skip:
            continue
        output = sample_dir / f"{kind}_{profile.code}_{profile.sample_date.replace('-', '')}.csv"
        spec = QuantDataSampleSpec(
            root=artifact.path,
            code=profile.code,
            kind=kind,
            date=profile.sample_date if kind in {"minute_bar", "tick_trade"} else "",
            start=profile.sample_date if kind == "market_bar" else "",
            end=profile.sample_date if kind == "market_bar" else "",
            max_rows=max_rows,
            output_path=str(output),
        )
        result = sample_local_quant_data(project, spec)
        samples.append(result.to_dict())
        if not result.ok:
            warnings.append(f"{kind} data-sample failed: " + "; ".join(result.warnings or ("unknown error",)))
    return samples, warnings


def _sample_quant_data_roots(
    project: Path,
    roots: Iterable[Path],
    profile: QuantStrategyProfile,
    sample_dir: Path,
    *,
    max_rows: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    sampled_kinds: set[str] = set()
    for root in roots:
        kind = _kind_from_data_root(root)
        if not kind or kind in sampled_kinds:
            continue
        output = sample_dir / f"{kind}_{profile.code}_{profile.sample_date.replace('-', '')}.csv"
        spec = QuantDataSampleSpec(
            root=str(root),
            code=profile.code,
            kind=kind,
            date=profile.sample_date if kind in {"minute_bar", "tick_trade"} else "",
            start=profile.sample_date if kind == "market_bar" else "",
            end=profile.sample_date if kind == "market_bar" else "",
            max_rows=max_rows,
            output_path=str(output),
        )
        result = sample_local_quant_data(project, spec)
        if result.ok:
            samples.append(result.to_dict())
            sampled_kinds.add(kind)
        elif kind != "tick_trade":
            warnings.append(f"{kind} data-sample failed from root {root}: " + "; ".join(result.warnings or ("unknown error",)))
    return samples, warnings


def _select_sample_artifacts(artifacts: Iterable[QuantDataArtifact], sample_date: str) -> dict[str, QuantDataArtifact]:
    selected: dict[str, QuantDataArtifact] = {}
    for artifact in artifacts:
        if artifact.kind == "market_bar_zip":
            selected.setdefault("market_bar", artifact)
        elif artifact.kind == "minute_kline_zip":
            selected.setdefault("minute_bar", artifact)
        elif artifact.kind == "tick_trade_7z_daily":
            artifact_date = str(artifact.metadata.get("date") or "")
            if not artifact_date or artifact_date == sample_date:
                selected.setdefault("tick_trade", artifact)
    return selected


def _expect_direct_data_artifacts(discovery: QuantDataAdapterResult) -> tuple[list[dict[str, Any]], dict[str, str]]:
    expectations: list[dict[str, Any]] = []
    execution: dict[str, str] = {}
    kind_map = {
        "market_bar_csv": "market_bar_csv",
        "minute_kline_csv": "minute_bar_csv",
        "tick_trade_csv": "tick_trade_csv",
    }
    seen: set[str] = set()
    inspected = 0
    for artifact in discovery.artifacts:
        expectation_kind = kind_map.get(artifact.kind)
        if not expectation_kind or artifact.path in seen:
            continue
        if artifact.bytes > 8 * 1024 * 1024:
            continue
        if inspected >= 8:
            break
        seen.add(artifact.path)
        report = run_quant_expectations(artifact.path, kind=expectation_kind)
        inspected += 1
        expectations.append(_expectation_record("data_artifact:" + artifact.kind, report))
        if artifact.kind == "tick_trade_csv" and report.ok:
            execution.setdefault("tick", artifact.path)
    return expectations, execution


def _find_execution_evidence_files(project: Path, roots: Iterable[str | Path], *, max_files: int) -> dict[str, str]:
    evidence: dict[str, str] = {}
    scanned = 0
    for root in _execution_roots(project, roots):
        if not root.exists():
            continue
        files = [root] if root.is_file() else root.rglob("*")
        for path in files:
            if not path.is_file() or path.suffix.lower() not in {".csv", ".json"} or _is_generated_path(path):
                continue
            scanned += 1
            if scanned > max_files:
                return evidence
            role = _classify_execution_file(path)
            if role and role not in evidence:
                evidence[role] = str(path.resolve(strict=False))
    return evidence


def _find_broker_evidence_bundle(project: Path, *, max_files: int) -> dict[str, str]:
    root = project / ".quantagent" / "broker_evidence"
    if not root.exists() or not root.is_dir():
        return {}
    candidates: list[tuple[int, int, float, str, dict[str, str]]] = []
    for bundle_dir in sorted(item for item in root.iterdir() if item.is_dir()):
        evidence = _collect_execution_evidence_from_root(bundle_dir, max_files=max_files)
        if not _has_broker_execution_evidence(evidence):
            continue
        complete_default = all(evidence.get(key) for key in ("tick", "fill", "broker", "slippage", "capacity"))
        candidates.append(
            (
                1 if complete_default else 0,
                sum(1 for key in _EXECUTION_EVIDENCE_ROLES if evidence.get(key)),
                _execution_bundle_mtime(bundle_dir, evidence),
                bundle_dir.name,
                evidence,
            )
        )
    if not candidates:
        return {}
    return max(candidates)[4]


def _collect_execution_evidence_from_root(root: Path, *, max_files: int) -> dict[str, str]:
    evidence: dict[str, str] = {}
    scanned = 0
    files = [root] if root.is_file() else sorted(root.rglob("*"), key=_execution_file_sort_key)
    for path in files:
        if not path.is_file() or path.suffix.lower() not in {".csv", ".json"} or _is_generated_path(path):
            continue
        scanned += 1
        if scanned > max_files:
            return evidence
        role = _classify_execution_file(path)
        if role and role not in evidence:
            evidence[role] = str(path.resolve(strict=False))
    return evidence


def _execution_file_sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem.lower()
    exact_role_rank = {role: index for index, role in enumerate(_EXECUTION_EVIDENCE_ROLES)}
    return (exact_role_rank.get(stem, len(exact_role_rank)), str(path))


def _execution_bundle_mtime(bundle_dir: Path, evidence: dict[str, str]) -> float:
    mtimes: list[float] = []
    for raw_path in evidence.values():
        try:
            mtimes.append(Path(raw_path).stat().st_mtime)
        except OSError:
            continue
    if mtimes:
        return max(mtimes)
    try:
        return bundle_dir.stat().st_mtime
    except OSError:
        return 0.0


def _has_broker_execution_evidence(evidence: dict[str, str]) -> bool:
    return all(bool(evidence.get(key)) for key in _BROKER_BUNDLE_REQUIRED_ROLES)


def _classify_execution_file(path: Path) -> str:
    lowered = path.name.lower()
    columns = _read_header(path)
    if not columns and path.suffix.lower() == ".json":
        if "broker" in lowered or "account" in lowered:
            return "broker"
        return ""
    has_time = bool(_role_column(columns, "time") or _role_column(columns, "date"))
    has_code = bool(_role_column(columns, "code"))
    has_price = bool(_role_column(columns, "price"))
    has_volume = bool(_role_column(columns, "volume"))
    has_order_id = bool(_role_column(columns, "order_id"))
    has_status = bool(_role_column(columns, "status"))
    has_position = bool(_role_column(columns, "position"))
    has_account = bool(_role_column(columns, "account"))
    if ("order" in lowered or "委托" in path.name) and has_order_id and has_code:
        return "order"
    if ("position" in lowered or "持仓" in path.name) and has_code and has_position:
        return "position"
    if ("account" in lowered or "资金" in path.name) and has_account and (_role_column(columns, "balance") or _role_column(columns, "available")):
        return "account"
    if ("fill" in lowered or "trade" in lowered or "成交" in path.name) and has_time and has_code and has_price and has_volume:
        return "fill"
    if ("tick" in lowered or "逐笔" in str(path)) and has_time and has_price and has_volume:
        return "tick"
    if ("broker" in lowered or "account" in lowered or "券商" in path.name) and (_role_column(columns, "broker") or _role_column(columns, "account")):
        return "broker"
    if ("slippage" in lowered or "滑点" in path.name) and _role_column(columns, "slippage"):
        return "slippage"
    if ("capacity" in lowered or "容量" in path.name) and _role_column(columns, "capacity"):
        return "capacity"
    return ""


def _build_run_spec(
    candidate: QuantStrategyInputCandidate,
    profile: QuantStrategyProfile,
    execution_evidence: dict[str, str],
    *,
    execution_source: str,
) -> QuantRunSpec:
    has_execution = _has_broker_execution_evidence(execution_evidence)
    source = execution_source or ("auto-evidence local execution files" if has_execution else "")
    return QuantRunSpec(
        name=Path(candidate.path).stem,
        input_path=candidate.path,
        return_col=candidate.return_col,
        date_col=candidate.date_col,
        data_kind=candidate.data_kind,
        strict_dedup=candidate.strict_dedup,
        execution_source=source,
        tick_path=execution_evidence.get("tick", ""),
        fill_path=execution_evidence.get("fill", ""),
        broker_path=execution_evidence.get("broker", "") or execution_evidence.get("account", ""),
        order_path=execution_evidence.get("order", ""),
        position_path=execution_evidence.get("position", ""),
        account_path=execution_evidence.get("account", ""),
        slippage_path=execution_evidence.get("slippage", ""),
        capacity_path=execution_evidence.get("capacity", ""),
        assumptions=tuple(
            item
            for item in (
                f"auto-evidence sampled code={profile.code}" if profile.code else "",
                f"auto-evidence sampled date={profile.sample_date}" if profile.sample_date else "",
            )
            if item
        ),
    )


def _expectation_record(role: str, report: QuantExpectationReport) -> dict[str, Any]:
    payload = report.to_dict()
    payload["role"] = role
    return payload


def _execution_roots(project: Path, roots: Iterable[str | Path]) -> list[Path]:
    explicit = [Path(root).expanduser() for root in roots if str(root).strip()]
    if explicit:
        return [(item if item.is_absolute() else project / item).resolve(strict=False) for item in explicit]
    result = []
    for item in (project / "AI_协作交接", project):
        if item.exists() and item not in result:
            result.append(item)
    return result


def _resolve_optional_path(project: Path, raw: str | Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return (path if path.is_absolute() else project / path).resolve(strict=False)


def _strategy_roots(project: Path, roots: Iterable[str | Path]) -> list[Path]:
    explicit = [Path(root).expanduser() for root in roots if str(root).strip()]
    if explicit:
        return [(item if item.is_absolute() else project / item).resolve(strict=False) for item in explicit]
    home = Path.home()
    candidates = [
        project / "AI_协作交接",
        project,
        home / "Desktop" / "智能动态仓位系统",
    ]
    result: list[Path] = []
    for item in candidates:
        resolved = item.resolve(strict=False)
        if resolved.exists() and resolved not in result:
            result.append(resolved)
    return result


def _quant_data_roots(project: Path, roots: Iterable[str | Path]) -> list[Path]:
    explicit = [Path(root).expanduser() for root in roots if str(root).strip()]
    if explicit:
        return [(item if item.is_absolute() else project / item).resolve(strict=False) for item in explicit]
    home = Path.home()
    local_markers = (
        project / "2061票更新至4.30",
        project / "分钟K线-股票241",
        project / "A股_逐笔成交",
        project / "榜单数据",
    )
    if any(item.exists() for item in local_markers):
        return [project.resolve(strict=False)]
    candidates = [
        project,
        home / "Desktop" / "2061票更新至4.30",
        home / "Downloads" / "分钟K线-股票241",
        home / "Downloads" / "A股_逐笔成交",
        home / "Desktop" / "榜单数据",
        home / "Downloads" / "榜单数据",
    ]
    result: list[Path] = []
    for item in candidates:
        resolved = item.resolve(strict=False)
        if resolved.exists() and resolved not in result:
            result.append(resolved)
    return result


def _kind_from_data_root(root: Path) -> str:
    text = str(root)
    suffix = root.suffix.lower()
    if "逐笔" in text or suffix == ".7z":
        return "tick_trade"
    if "分钟" in text or "k线" in text.lower():
        return "minute_bar"
    if "2061票" in text or any(token in text for token in ("前复权", "后复权", "不复权")):
        return "market_bar"
    if suffix == ".zip":
        lowered = root.name.lower()
        if "minute" in lowered or "1m" in lowered:
            return "minute_bar"
        return "market_bar"
    return ""


def _read_header(path: Path) -> list[str]:
    if path.suffix.lower() != ".csv":
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [name for name in (csv.DictReader(handle).fieldnames or []) if name]
    except UnicodeDecodeError:
        with path.open("r", encoding="gb18030", newline="") as handle:
            return [name for name in (csv.DictReader(handle).fieldnames or []) if name]
    except OSError:
        return []


def _role_column(columns: Iterable[str], role: str) -> str:
    aliases = {_norm(column): column for column in columns}
    for alias in _aliases_for_role(role):
        column = aliases.get(_norm(alias))
        if column:
            return column
    return ""


def _aliases_for_role(role: str) -> tuple[str, ...]:
    return {
        "date": ("date", "datetime", "timestamp", "日期", "交易日期", "时间"),
        "entry_date": ("entry_date", "entrydate", "date", "日期", "买入日期", "开仓日期"),
        "time": ("time", "timestamp", "datetime", "date_time", "trade_time", "成交时间", "时间", "日期"),
        "code": ("code", "symbol", "vt_symbol", "证券代码", "股票代码", "代码", "合约代码"),
        "price": ("price", "成交价", "成交价格", "价格", "fill_price"),
        "volume": ("volume", "qty", "quantity", "成交量", "成交量(股)", "成交量（股）", "成交数量", "数量", "fill_volume"),
        "order_id": ("order_id", "orderid", "vt_orderid", "local_orderid", "委托编号", "合同编号", "订单号"),
        "status": ("status", "order_status", "state", "状态", "委托状态"),
        "position": ("quantity", "volume", "position", "持仓", "持仓数量", "证券数量", "当前持仓"),
        "return": ("return", "net_return", "收益", "收益率", "涨幅", "涨跌幅"),
        "broker": ("broker", "broker_name", "gateway", "gateway_name", "券商", "通道"),
        "account": ("account", "account_id", "accountid", "资金账号", "账户", "账户号"),
        "balance": ("balance", "asset", "equity", "资金余额", "总资产", "账户权益"),
        "available": ("available", "cash", "可用", "可用资金"),
        "slippage": ("slippage", "slippage_bps", "滑点", "滑点bps"),
        "capacity": ("capacity", "max_notional", "成交额", "容量", "最大成交额"),
    }.get(role, (role,))


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _normalize_date(value: str) -> str:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:19]).date().isoformat()
    except ValueError:
        return ""


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _is_generated_path(path: Path) -> bool:
    parts = set(path.parts)
    return ".quantagent" in parts and (
        "quant_auto_evidence" in parts
        or "data_samples" in parts
        or "quant_run_gate" in parts
        or "runs" in parts
    )


def _auto_evidence_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    if not base.exists():
        base = project / ".quantagent"
    return base / "quant_auto_evidence"


def _write_auto_result(result: QuantAutoEvidenceResult) -> QuantAutoEvidenceResult:
    if result.output_json:
        Path(result.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(result.output_json).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if result.output_markdown:
        Path(result.output_markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(result.output_markdown).write_text(render_quant_auto_evidence(result), encoding="utf-8")
    return result


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_pairs(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for date_text, code in items:
        item = (str(date_text or "").strip(), str(code or "").strip())
        if not item[0] or not item[1] or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
