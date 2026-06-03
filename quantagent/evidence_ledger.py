from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .tool_result_classification import FILE_MUTATING_TOOL_NAMES, file_mutation_result_landed


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    claim: str
    value: str = ""
    evidence_type: str = "unknown"
    source: str = ""
    command: str = ""
    path: str = ""
    tool: str = ""
    timestamp_ms: int = 0
    confidence: float = 1.0
    verified: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence_ledger_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "evidence_ledger.jsonl"


def create_evidence_record(
    *,
    claim: str,
    value: str = "",
    evidence_type: str = "runtime",
    source: str = "",
    command: str = "",
    path: str = "",
    tool: str = "",
    confidence: float = 1.0,
    verified: bool = True,
    metadata: dict[str, Any] | None = None,
) -> EvidenceRecord:
    now = int(time.time() * 1000)
    seed = json.dumps(
        {
            "claim": claim,
            "value": value,
            "evidence_type": evidence_type,
            "source": source,
            "command": command,
            "path": path,
            "tool": tool,
            "timestamp_ms": now,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return EvidenceRecord(
        evidence_id="ev-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:14],
        claim=claim.strip(),
        value=str(value).strip(),
        evidence_type=evidence_type.strip() or "runtime",
        source=source.strip(),
        command=command.strip(),
        path=path.strip(),
        tool=tool.strip(),
        timestamp_ms=now,
        confidence=max(0.0, min(1.0, float(confidence))),
        verified=bool(verified),
        metadata=metadata or {},
    )


def append_evidence(project: str | Path, record: EvidenceRecord) -> Path:
    path = evidence_ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def record_evidence(project: str | Path, **kwargs: Any) -> EvidenceRecord:
    record = create_evidence_record(**kwargs)
    append_evidence(project, record)
    return record


def load_evidence(project: str | Path, *, limit: int = 200) -> list[EvidenceRecord]:
    path = evidence_ledger_path(project)
    if not path.exists():
        return []
    records: list[EvidenceRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(_record_from_dict(payload))
    return records[-max(0, limit) :]


def find_evidence(
    project: str | Path,
    claim: str,
    *,
    value: str = "",
    records: Iterable[EvidenceRecord] = (),
    limit: int = 5,
) -> list[EvidenceRecord]:
    haystack = list(records) or load_evidence(project)
    claim_norm = _norm(claim)
    value_norm = _norm(value)
    scored: list[tuple[int, EvidenceRecord]] = []
    for record in haystack:
        if not record.verified:
            continue
        score = _match_score(claim_norm, value_norm, record)
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], -item[1].timestamp_ms))
    return [record for _score, record in scored[:limit]]


def render_evidence(records: Iterable[EvidenceRecord]) -> str:
    items = list(records)
    if not items:
        return "No evidence records.\n"
    lines = ["# Evidence Ledger", ""]
    for record in items:
        value = f" value={record.value}" if record.value else ""
        src = record.source or record.path or record.command or record.tool or "-"
        mark = "verified" if record.verified else "unverified"
        lines.append(f"- {record.evidence_id}: {record.claim}{value} [{record.evidence_type}, {mark}, confidence={record.confidence:.2f}] source={src}")
    return "\n".join(lines) + "\n"


def evidence_from_tool_result(tool: str, summary: str, data: dict[str, Any]) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    if summary:
        records.append(create_evidence_record(claim=f"{tool} summary", value=summary, evidence_type="tool_result", tool=tool, source="tool_result.summary"))
    raw_payload = _raw_tool_payload(data)
    if tool in FILE_MUTATING_TOOL_NAMES and raw_payload:
        landed = file_mutation_result_landed(tool, raw_payload)
        records.append(
            create_evidence_record(
                claim=f"{tool}.mutation_landed",
                value=str(landed).lower(),
                evidence_type="tool_result",
                tool=tool,
                source="tool_result.classifier",
                confidence=0.5 if landed else 0.0,
                verified=False,
                metadata={"classifier": "file_mutation_result_landed", "trust": "tool_self_report"},
            )
        )
    for key in ("returncode", "stdout", "stderr", "report", "markdown", "estimated_tokens", "invocation_id", "duration_ms"):
        value = data.get(key)
        if value in (None, "", [], {}):
            continue
        text = str(value)
        records.append(create_evidence_record(claim=f"{tool}.{key}", value=text[:500], evidence_type="tool_result", tool=tool, source=f"tool_result.{key}"))
    return records


def _raw_tool_payload(data: dict[str, Any]) -> str:
    for key in ("result", "raw_result", "payload"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _record_from_dict(data: dict[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=str(data.get("evidence_id") or ""),
        claim=str(data.get("claim") or ""),
        value=str(data.get("value") or ""),
        evidence_type=str(data.get("evidence_type") or "unknown"),
        source=str(data.get("source") or ""),
        command=str(data.get("command") or ""),
        path=str(data.get("path") or ""),
        tool=str(data.get("tool") or ""),
        timestamp_ms=int(data.get("timestamp_ms") or 0),
        confidence=float(data.get("confidence") if data.get("confidence") is not None else 1.0),
        verified=bool(data.get("verified", True)),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )


def _match_score(claim_norm: str, value_norm: str, record: EvidenceRecord) -> int:
    record_text = _norm(" ".join([record.claim, record.value, record.source, record.command, record.path, record.tool]))
    score = 0
    if value_norm and value_norm in record_text:
        score += 10
    claim_terms = set(claim_norm.split())
    record_terms = set(record_text.split())
    overlap = claim_terms & record_terms
    score += min(8, len(overlap))
    if claim_norm and claim_norm in record_text:
        score += 6
    return score


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace("_", " ").replace("-", " ").split())
