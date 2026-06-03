from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .quant_data_adapter import QuantDataArtifact, discover_quant_data
from .quant_data_sample import QuantDataSampleSpec, sample_local_quant_data
from .quant_expectations import run_quant_expectations


SEARCH_KINDS = ("market_bar", "minute_bar", "tick_trade")


@dataclass(frozen=True)
class QuantDataSearchMatch:
    kind: str
    artifact_kind: str
    path: str
    ok: bool
    score: tuple[int, int, str] = (99, 99, "")
    sample: dict[str, Any] = field(default_factory=dict)
    expectations: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = list(self.score)
        return payload


@dataclass(frozen=True)
class QuantDataSearchResult:
    search_id: str
    project: str
    task: str
    ok: bool
    code: str = ""
    date: str = ""
    freq: str = "1m"
    requested_kinds: tuple[str, ...] = ()
    roots: tuple[str, ...] = ()
    files_scanned: int = 0
    artifacts_found: int = 0
    matches: tuple[QuantDataSearchMatch, ...] = ()
    warnings: tuple[str, ...] = ()
    output_json: str = ""
    output_markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_id": self.search_id,
            "project": self.project,
            "task": self.task,
            "ok": self.ok,
            "code": self.code,
            "date": self.date,
            "freq": self.freq,
            "requested_kinds": list(self.requested_kinds),
            "roots": list(self.roots),
            "files_scanned": self.files_scanned,
            "artifacts_found": self.artifacts_found,
            "matches": [item.to_dict() for item in self.matches],
            "warnings": list(self.warnings),
            "output_json": self.output_json,
            "output_markdown": self.output_markdown,
        }


def run_quant_data_search(
    project: str | Path,
    task: str = "",
    *,
    roots: Iterable[str | Path] = (),
    code: str = "",
    date: str = "",
    kind: str = "auto",
    freq: str = "1m",
    max_files: int = 5000,
    sample_zip_members: int = 20,
    max_rows: int = 5,
) -> QuantDataSearchResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    search_id = "qdata-" + str(int(time.time() * 1000))
    output_dir = project_path / ".quantagent" / "data_search" / search_id
    sample_dir = output_dir / "samples"
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    parsed_code = _normalize_code(code) or _code_from_text(task)
    parsed_date = _normalize_date(date) or _date_from_text(task)
    parsed_freq = _freq_from_text(task) or freq or "1m"
    requested_kinds = _requested_kinds(kind, task)
    warnings: list[str] = []
    matches: list[QuantDataSearchMatch] = []

    if not parsed_code:
        warnings.append("code not found; pass --code or include a 6-digit stock code in task")

    discovery = discover_quant_data(project_path, roots, max_files=max_files, sample_zip_members=sample_zip_members)
    warnings.extend(discovery.warnings)

    selected = _select_artifacts(discovery.artifacts, requested_kinds, parsed_date)
    for sample_kind in requested_kinds:
        artifact = selected.get(sample_kind)
        if artifact is None:
            warnings.append(f"{sample_kind} artifact not found")
            continue
        match = _validate_artifact(
            project_path,
            artifact,
            sample_kind,
            code=parsed_code,
            date=parsed_date,
            freq=parsed_freq,
            output_path=sample_dir / f"{sample_kind}_{parsed_code or 'unknown'}_{(parsed_date or 'latest').replace('-', '')}.csv",
            max_rows=max_rows,
        )
        matches.append(match)
        if not match.ok and match.reason:
            warnings.append(match.reason)

    result = QuantDataSearchResult(
        search_id=search_id,
        project=str(project_path),
        task=task,
        ok=any(item.ok for item in matches),
        code=parsed_code,
        date=parsed_date,
        freq=parsed_freq,
        requested_kinds=tuple(requested_kinds),
        roots=tuple(discovery.roots),
        files_scanned=discovery.files_scanned,
        artifacts_found=len(discovery.artifacts),
        matches=tuple(sorted(matches, key=lambda item: item.score)),
        warnings=tuple(_dedupe(warnings)),
        output_json=str(output_dir / f"{search_id}.json"),
        output_markdown=str(output_dir / f"{search_id}.md"),
    )
    return _write_search_result(result)


def render_quant_data_search(result: QuantDataSearchResult) -> str:
    lines = [
        "# Quant Data Search",
        "",
        f"- search_id: {result.search_id}",
        f"- ok: {str(result.ok).lower()}",
        f"- code: {result.code or '-'}",
        f"- date: {result.date or '-'}",
        f"- freq: {result.freq or '-'}",
        f"- requested_kinds: {', '.join(result.requested_kinds) if result.requested_kinds else '-'}",
        f"- files_scanned: {result.files_scanned}",
        f"- artifacts_found: {result.artifacts_found}",
        f"- output_json: {result.output_json or '-'}",
        "",
        "## Matches",
        "",
    ]
    if not result.matches:
        lines.append("- none")
    for match in result.matches:
        sample = match.sample or {}
        lines.append(
            f"- {match.kind}: ok={str(match.ok).lower()} artifact={match.artifact_kind} "
            f"rows={sample.get('rows_written', 0)} path={match.path}"
        )
        if sample.get("output_path"):
            lines.append(f"  sample: {sample.get('output_path')}")
        if match.reason:
            lines.append(f"  reason: {match.reason}")
    lines.extend(["", "## Roots", ""])
    lines.extend(f"- {root}" for root in result.roots) if result.roots else lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result.warnings) if result.warnings else lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def _validate_artifact(
    project: Path,
    artifact: QuantDataArtifact,
    sample_kind: str,
    *,
    code: str,
    date: str,
    freq: str,
    output_path: Path,
    max_rows: int,
) -> QuantDataSearchMatch:
    if not code:
        return QuantDataSearchMatch(sample_kind, artifact.kind, artifact.path, False, _score_artifact(artifact, sample_kind, date), reason="cannot validate artifact without stock code")
    if sample_kind == "tick_trade" and artifact.kind.endswith("_7z_daily") and not date:
        return QuantDataSearchMatch(sample_kind, artifact.kind, artifact.path, False, _score_artifact(artifact, sample_kind, date), reason="tick_trade sampling requires a date")
    if artifact.format in {"zip", "7z"}:
        spec = QuantDataSampleSpec(
            root=artifact.path,
            code=code,
            kind=sample_kind,
            freq=freq,
            date=date if sample_kind in {"minute_bar", "tick_trade"} else "",
            start=date if sample_kind == "market_bar" else "",
            end=date if sample_kind == "market_bar" else "",
            max_rows=max(1, max_rows),
            output_path=str(output_path),
        )
        sample = sample_local_quant_data(project, spec).to_dict()
        ok = bool(sample.get("ok"))
        reason = "" if ok else "; ".join(str(item) for item in sample.get("warnings") or ("sample failed",))
        return QuantDataSearchMatch(sample_kind, artifact.kind, artifact.path, ok, _score_artifact(artifact, sample_kind, date), sample=sample, reason=reason)
    expectation_kind = _expectation_kind_for_artifact(artifact.kind)
    if expectation_kind:
        report = run_quant_expectations(artifact.path, kind=expectation_kind, sample_rows=max_rows).to_dict()
        return QuantDataSearchMatch(sample_kind, artifact.kind, artifact.path, bool(report.get("ok")), _score_artifact(artifact, sample_kind, date), expectations=report)
    return QuantDataSearchMatch(sample_kind, artifact.kind, artifact.path, False, _score_artifact(artifact, sample_kind, date), reason="artifact format cannot be validated")


def _select_artifacts(artifacts: Iterable[QuantDataArtifact], requested_kinds: Iterable[str], date: str) -> dict[str, QuantDataArtifact]:
    selected: dict[str, QuantDataArtifact] = {}
    by_kind = {kind: [] for kind in requested_kinds}
    for artifact in artifacts:
        sample_kind = _sample_kind_for_artifact(artifact.kind)
        if sample_kind in by_kind:
            by_kind[sample_kind].append(artifact)
    for sample_kind, items in by_kind.items():
        if items:
            selected[sample_kind] = sorted(items, key=lambda item: _score_artifact(item, sample_kind, date))[0]
    return selected


def _sample_kind_for_artifact(artifact_kind: str) -> str:
    if artifact_kind in {"market_bar_zip", "market_bar_csv"}:
        return "market_bar"
    if artifact_kind in {"minute_kline_zip", "minute_kline_csv"}:
        return "minute_bar"
    if artifact_kind in {"tick_trade_7z_daily", "tick_trade_csv"}:
        return "tick_trade"
    return ""


def _expectation_kind_for_artifact(artifact_kind: str) -> str:
    return {
        "market_bar_csv": "market_bar_csv",
        "minute_kline_csv": "minute_bar_csv",
        "tick_trade_csv": "tick_trade_csv",
    }.get(artifact_kind, "")


def _score_artifact(artifact: QuantDataArtifact, sample_kind: str, date: str) -> tuple[int, int, str]:
    format_score = {
        ("market_bar", "zip"): 0,
        ("minute_bar", "zip"): 0,
        ("tick_trade", "7z"): 0,
        ("market_bar", "csv"): 2,
        ("minute_bar", "csv"): 2,
        ("tick_trade", "csv"): 2,
    }.get((sample_kind, artifact.format), 5)
    date_score = 0 if date and (date in artifact.path or str(artifact.metadata.get("date") or "") == date) else (1 if date else 0)
    return (format_score, date_score, artifact.path)


def _requested_kinds(kind: str, task: str) -> list[str]:
    normalized = str(kind or "auto").strip()
    if normalized and normalized != "auto":
        return [normalized]
    text = str(task or "").lower()
    kinds: list[str] = []
    if any(token in task for token in ("日线", "日K", "日k", "复权")) or "daily" in text:
        kinds.append("market_bar")
    if any(token in task for token in ("分钟", "分时", "K线", "k线")) or re.search(r"\b(1m|5m|15m|30m|60m)\b", text):
        kinds.append("minute_bar")
    if any(token in task for token in ("逐笔", "成交明细")) or "tick" in text:
        kinds.append("tick_trade")
    return _dedupe(kinds) or list(SEARCH_KINDS)


def _code_from_text(text: str) -> str:
    match = re.search(r"(?<!\d)(?:sh|sz)?(\d{6})(?!\d)", str(text or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _date_from_text(text: str) -> str:
    raw = str(text or "")
    match = re.search(r"(20\d{2})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})", raw)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _freq_from_text(text: str) -> str:
    raw = str(text or "")
    match = re.search(r"\b(1|5|15|30|60)\s*(m|min|分钟)\b", raw, flags=re.IGNORECASE)
    return f"{match.group(1)}m" if match else ""


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-6:] if len(digits) >= 6 else digits


def _normalize_date(value: str) -> str:
    return _date_from_text(str(value or ""))


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _write_search_result(result: QuantDataSearchResult) -> QuantDataSearchResult:
    Path(result.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(result.output_json).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(result.output_markdown).write_text(render_quant_data_search(result), encoding="utf-8")
    return result
