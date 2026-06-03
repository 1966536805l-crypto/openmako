from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .memory_extract import MemoryCandidate, extract_memory_candidates
from .memory_store import MemoryStore, blocked_memory_placeholder, memory_dir, prepare_memory_text


PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"


@dataclass(frozen=True)
class MemoryProposal:
    proposal_id: str
    kind: str
    text: str
    source: str
    confidence: float
    status: str = PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    decided_at: str = ""
    reason: str = ""
    memory_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def memory_proposal_path(project: str | Path) -> Path:
    return memory_dir(Path(project).expanduser().resolve(strict=False)) / "memory_proposals.json"


def propose_memories(
    project: str | Path,
    value: object,
    *,
    source: str = "sidecar",
    min_confidence: float = 0.75,
) -> list[MemoryProposal]:
    return propose_memory_candidates(
        project,
        extract_memory_candidates(value, source=source),
        min_confidence=min_confidence,
    )


def propose_memory_candidates(
    project: str | Path,
    candidates: Iterable[MemoryCandidate],
    *,
    min_confidence: float = 0.75,
) -> list[MemoryProposal]:
    project_path = Path(project).expanduser().resolve(strict=False)
    existing = load_memory_proposals(project_path)
    existing_keys = {(item.kind, item.text) for item in existing}
    proposals = list(existing)
    added: list[MemoryProposal] = []
    for candidate in candidates:
        if candidate.confidence < min_confidence:
            continue
        prepared_text, safety = prepare_memory_text(candidate.text)
        if not safety.ok:
            prepared_text = blocked_memory_placeholder(safety)
        key = (candidate.kind, prepared_text)
        if key in existing_keys:
            continue
        proposal = _proposal_from_candidate(candidate, text=prepared_text)
        if not safety.ok:
            proposal = MemoryProposal(
                **(
                    proposal.to_dict()
                    | {
                        "status": DENIED,
                        "decided_at": datetime.now().isoformat(timespec="seconds"),
                        "reason": "blocked_memory_safety:" + ",".join(safety.reasons),
                    }
                )
            )
        proposals.append(proposal)
        added.append(proposal)
        existing_keys.add(key)
    save_memory_proposals(project_path, proposals)
    return added


def load_memory_proposals(project: str | Path, *, status: str | None = None) -> list[MemoryProposal]:
    path = memory_proposal_path(project)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("proposals", []) if isinstance(payload, dict) else []
    proposals = [_proposal_from_payload(item) for item in rows if isinstance(item, dict)]
    if status:
        proposals = [item for item in proposals if item.status == status]
    return proposals


def save_memory_proposals(project: str | Path, proposals: Iterable[MemoryProposal]) -> Path:
    path = memory_proposal_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"proposals": [item.to_dict() for item in proposals]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def approve_memory_proposal(project: str | Path, proposal_id: str, *, reason: str = "") -> MemoryProposal:
    project_path = Path(project).expanduser().resolve(strict=False)
    proposals = load_memory_proposals(project_path)
    updated: list[MemoryProposal] = []
    selected: MemoryProposal | None = None
    store = MemoryStore(project_path)
    try:
        for proposal in proposals:
            if proposal.proposal_id != proposal_id:
                updated.append(proposal)
                continue
            if proposal.status == DENIED:
                raise ValueError(f"memory proposal is denied: {proposal.reason or proposal.proposal_id}")
            entry = store.add(
                proposal.text,
                kind=proposal.kind,
                source=proposal.source,
                meta={"confidence": proposal.confidence, "proposal_id": proposal.proposal_id, "approved_reason": reason},
            )
            selected = MemoryProposal(**(proposal.to_dict() | {"status": APPROVED, "decided_at": datetime.now().isoformat(timespec="seconds"), "reason": reason, "memory_id": entry.id}))
            updated.append(selected)
    finally:
        store.close()
    if selected is None:
        raise KeyError(f"memory proposal not found: {proposal_id}")
    save_memory_proposals(project_path, updated)
    return selected


def deny_memory_proposal(project: str | Path, proposal_id: str, *, reason: str = "") -> MemoryProposal:
    proposals = load_memory_proposals(project)
    updated: list[MemoryProposal] = []
    selected: MemoryProposal | None = None
    for proposal in proposals:
        if proposal.proposal_id == proposal_id:
            selected = MemoryProposal(**(proposal.to_dict() | {"status": DENIED, "decided_at": datetime.now().isoformat(timespec="seconds"), "reason": reason}))
            updated.append(selected)
        else:
            updated.append(proposal)
    if selected is None:
        raise KeyError(f"memory proposal not found: {proposal_id}")
    save_memory_proposals(project, updated)
    return selected


def render_memory_proposals(proposals: Iterable[MemoryProposal]) -> str:
    rows = list(proposals)
    if not rows:
        return "No memory proposals.\n"
    lines = ["# Memory Proposals", ""]
    for proposal in rows:
        text = proposal.text.replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        memory = f" memory=#{proposal.memory_id}" if proposal.memory_id else ""
        lines.append(f"- [{proposal.status}] {proposal.proposal_id} [{proposal.kind}] confidence={proposal.confidence:.2f}{memory}: {text}")
    return "\n".join(lines) + "\n"


def _proposal_from_candidate(candidate: MemoryCandidate, *, text: str | None = None) -> MemoryProposal:
    return MemoryProposal(
        proposal_id="memprop-" + uuid.uuid4().hex[:12],
        kind=candidate.kind,
        text=candidate.text if text is None else text,
        source=candidate.source,
        confidence=round(float(candidate.confidence), 3),
    )


def _proposal_from_payload(raw: dict[str, object]) -> MemoryProposal:
    return MemoryProposal(
        proposal_id=str(raw.get("proposal_id") or ""),
        kind=str(raw.get("kind") or "note"),
        text=str(raw.get("text") or ""),
        source=str(raw.get("source") or ""),
        confidence=float(raw.get("confidence") or 0.0),
        status=str(raw.get("status") or PENDING),
        created_at=str(raw.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        decided_at=str(raw.get("decided_at") or ""),
        reason=str(raw.get("reason") or ""),
        memory_id=int(raw["memory_id"]) if raw.get("memory_id") is not None else None,
    )
