from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NewType, Sequence

from .file_ops import resolve_project_path


ReceiptId = NewType("ReceiptId", str)
FactId = NewType("FactId", str)
SymbolId = NewType("SymbolId", str)
SpanId = NewType("SpanId", str)
HunkHash = NewType("HunkHash", str)
VisaId = NewType("VisaId", str)
GateSignature = NewType("GateSignature", str)

_GATE_TOKEN = object()
DEFAULT_REPAIR_PATTERN = "model_repair"
TEST_APPROVAL_PATTERN = "explicit_test_approval"


@dataclass(frozen=True)
class TaintedModelOutput:
    raw_json: str


@dataclass(frozen=True)
class SpanReceipt:
    path: str
    start: int
    end: int
    span_hash: str


@dataclass(frozen=True)
class EvidenceReceipt:
    receipt_id: ReceiptId
    snapshot_hash: str
    verified_fact_ids: frozenset[FactId]
    suspect_scopes: frozenset[str]
    authorized_symbols: dict[SymbolId, str]
    authorized_spans: dict[SpanId, SpanReceipt]
    allowed_repair_patterns: frozenset[str]
    forbidden_shapes: frozenset[str]
    clean: bool = True


@dataclass(frozen=True)
class VisaRequest:
    receipt_id: ReceiptId
    fact_ids: tuple[FactId, ...]
    suspect_symbol_id: SymbolId | None = None
    authorized_span_id: SpanId | None = None
    repair_pattern_id: str = DEFAULT_REPAIR_PATTERN


@dataclass(frozen=True)
class HunkProposal:
    path: str
    old: str
    new: str
    visa_request: VisaRequest


@dataclass(frozen=True)
class RejectReason:
    hunk_hash: HunkHash
    code: str
    reason: str
    path: str = ""


@dataclass(frozen=True)
class RejectRecord:
    hunk_hash: HunkHash
    code: str
    reason: str
    path: str

    @classmethod
    def from_reason(cls, reason: RejectReason) -> "RejectRecord":
        return cls(reason.hunk_hash, reason.code, reason.reason, reason.path)


@dataclass(frozen=True)
class InternalAuditOnly:
    reject_records: tuple[RejectRecord, ...] = ()

    def redacted_summary(self) -> str:
        parts = [f"rejected_hunks={len(self.reject_records)}"]
        for record in self.reject_records[:8]:
            parts.append(f"{record.path}:{record.code}:{record.hunk_hash}")
        return " ".join(parts)


@dataclass(frozen=True)
class PatchVisa:
    visa_id: VisaId
    hunk_hash: HunkHash
    receipt_id: ReceiptId
    fact_ids: tuple[FactId, ...]
    authorized_path: str
    authorized_symbol_id: SymbolId | None = None
    authorized_span_id: SpanId | None = None
    repair_pattern_id: str = DEFAULT_REPAIR_PATTERN
    gate_signature: GateSignature = GateSignature("")
    _gate_token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._gate_token is not _GATE_TOKEN:
            raise TypeError("PatchVisa must be minted by mint_patch_visa")


@dataclass(frozen=True)
class VisaApprovedHunk:
    proposal: HunkProposal
    visa: PatchVisa


@dataclass(frozen=True)
class ClosureReject:
    reason: str


@dataclass(frozen=True)
class ChangeSetCandidate:
    approved_hunks: tuple[VisaApprovedHunk, ...]
    task: str = "visa-approved repair"
    test_command: tuple[str, ...] = ()
    max_attempts: int = 1
    allow_risky_tests: bool = False
    created_at: int = 0
    audit: InternalAuditOnly = field(default_factory=InternalAuditOnly)
    _gate_token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._gate_token is not _GATE_TOKEN:
            raise TypeError("ChangeSetCandidate must be created by closure_check")


@dataclass(frozen=True)
class CodeSnapshot:
    project: Path
    snapshot_hash: str


def build_receipt_from_paths(
    project: str | Path,
    paths: Sequence[str],
    *,
    verified_facts: Sequence[str] = (),
    allowed_repair_patterns: Sequence[str] = (),
    suspect_symbols: Sequence[str] = (),
) -> EvidenceReceipt:
    project_path = Path(project).expanduser().resolve(strict=False)
    spans: dict[SpanId, SpanReceipt] = {}
    scopes: list[str] = []
    for path_text in paths:
        span = _full_file_span(project_path, str(path_text))
        if span is None:
            continue
        span_id = SpanId(_stable_id("span", span.path, str(span.start), str(span.end), span.span_hash))
        spans[span_id] = span
        scopes.append(span.path)
    fact_ids = [FactId(_stable_id("fact", fact)) for fact in verified_facts if str(fact).strip()]
    if not fact_ids:
        fact_ids.append(FactId(_stable_id("fact", "current_failure")))
    symbols: dict[SymbolId, str] = {}
    for symbol in suspect_symbols:
        symbol_text = str(symbol).strip()
        if not symbol_text:
            continue
        symbols[SymbolId(_stable_id("symbol", symbol_text))] = symbol_text
    patterns = {DEFAULT_REPAIR_PATTERN, *(str(item).strip() for item in allowed_repair_patterns if str(item).strip())}
    snapshot_hash = _snapshot_hash(tuple(spans.values()))
    receipt_id = ReceiptId(_stable_id("receipt", snapshot_hash, *sorted(str(item) for item in fact_ids), *sorted(scopes)))
    return EvidenceReceipt(
        receipt_id=receipt_id,
        snapshot_hash=snapshot_hash,
        verified_fact_ids=frozenset(fact_ids),
        suspect_scopes=frozenset(scopes),
        authorized_symbols=symbols,
        authorized_spans=spans,
        allowed_repair_patterns=frozenset(patterns),
        forbidden_shapes=frozenset(
            {
                "test_change_without_approval",
                "delete_assertion",
                "weaken_assertion",
                "skip_only_test",
                "catch_all_or_swallow",
                "return_constant",
                "delete_failing_branch",
                "mock_over_failure",
                "large_formatting_with_logic",
                "unrelated_file",
                "stale_receipt",
                "outside_authorized_span",
            }
        ),
        clean=True,
    )


def build_receipt_from_spans(
    project: str | Path,
    spans: Sequence[tuple[str, int, int]],
    *,
    verified_facts: Sequence[str] = (),
    allowed_repair_patterns: Sequence[str] = (),
    suspect_symbols: Sequence[str] = (),
) -> EvidenceReceipt:
    project_path = Path(project).expanduser().resolve(strict=False)
    span_map: dict[SpanId, SpanReceipt] = {}
    scopes: list[str] = []
    for path_text, start, end in spans:
        span = _span_from_lines(project_path, str(path_text), int(start), int(end))
        if span is None:
            continue
        span_id = SpanId(_stable_id("span", span.path, str(span.start), str(span.end), span.span_hash))
        span_map[span_id] = span
        scopes.append(span.path)
    fact_ids = [FactId(_stable_id("fact", fact)) for fact in verified_facts if str(fact).strip()]
    if not fact_ids:
        fact_ids.append(FactId(_stable_id("fact", "current_failure")))
    symbols: dict[SymbolId, str] = {}
    for symbol in suspect_symbols:
        symbol_text = str(symbol).strip()
        if not symbol_text:
            continue
        symbols[SymbolId(_stable_id("symbol", symbol_text))] = symbol_text
    patterns = {DEFAULT_REPAIR_PATTERN, *(str(item).strip() for item in allowed_repair_patterns if str(item).strip())}
    snapshot_hash = _snapshot_hash(tuple(span_map.values()))
    receipt_id = ReceiptId(_stable_id("receipt", snapshot_hash, *sorted(str(item) for item in fact_ids), *sorted(scopes)))
    return EvidenceReceipt(
        receipt_id=receipt_id,
        snapshot_hash=snapshot_hash,
        verified_fact_ids=frozenset(fact_ids),
        suspect_scopes=frozenset(scopes),
        authorized_symbols=symbols,
        authorized_spans=span_map,
        allowed_repair_patterns=frozenset(patterns),
        forbidden_shapes=frozenset(
            {
                "test_change_without_approval",
                "delete_assertion",
                "weaken_assertion",
                "skip_only_test",
                "catch_all_or_swallow",
                "return_constant",
                "delete_failing_branch",
                "mock_over_failure",
                "large_formatting_with_logic",
                "unrelated_file",
                "stale_receipt",
                "outside_authorized_span",
            }
        ),
        clean=True,
    )


def build_current_snapshot(project: str | Path, receipt: EvidenceReceipt) -> CodeSnapshot:
    project_path = Path(project).expanduser().resolve(strict=False)
    spans: list[SpanReceipt] = []
    for span_id, span in receipt.authorized_spans.items():
        current = _current_span(project_path, span)
        if current is None:
            spans.append(SpanReceipt(span.path, span.start, span.end, ""))
        else:
            spans.append(current)
    return CodeSnapshot(project=project_path, snapshot_hash=_snapshot_hash(tuple(spans)))


def compute_hunk_hash(hunk: HunkProposal) -> HunkHash:
    payload = {
        "path": hunk.path,
        "old": hunk.old,
        "new": hunk.new,
        "visa_request": {
            "receipt_id": str(hunk.visa_request.receipt_id),
            "fact_ids": [str(item) for item in hunk.visa_request.fact_ids],
            "suspect_symbol_id": str(hunk.visa_request.suspect_symbol_id or ""),
            "authorized_span_id": str(hunk.visa_request.authorized_span_id or ""),
            "repair_pattern_id": hunk.visa_request.repair_pattern_id,
        },
    }
    return HunkHash(_digest_json(payload))


def parse_hunk_proposals(output: TaintedModelOutput) -> list[HunkProposal]:
    payload = _load_json(output.raw_json)
    raw_hunks = payload.get("hunks")
    if not isinstance(raw_hunks, list):
        raw_hunks = []
        for raw_candidate in payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []:
            if isinstance(raw_candidate, dict):
                raw_hunks.extend(raw_candidate.get("edits", []) if isinstance(raw_candidate.get("edits"), list) else [])
    proposals: list[HunkProposal] = []
    for raw in raw_hunks:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        old = str(raw.get("old") or "")
        new = str(raw.get("new") or "")
        if not path or not old:
            continue
        proposals.append(HunkProposal(path=path, old=old, new=new, visa_request=_visa_request_from_payload(raw.get("visa_request"))))
    return proposals


def mint_patch_visa(
    hunk: HunkProposal,
    receipt: EvidenceReceipt | None,
    current_snapshot: CodeSnapshot,
) -> PatchVisa | RejectReason:
    hunk_hash = compute_hunk_hash(hunk)
    if receipt is None:
        return _reject(hunk, hunk_hash, "missing_receipt", "receipt does not exist")
    if not receipt.clean:
        return _reject(hunk, hunk_hash, "unclean_receipt", "receipt is not clean")
    request = hunk.visa_request
    if not request.receipt_id or request.receipt_id != receipt.receipt_id:
        return _reject(hunk, hunk_hash, "stale_receipt", "receipt id does not match")
    if receipt.snapshot_hash != current_snapshot.snapshot_hash:
        return _reject(hunk, hunk_hash, "stale_receipt", "snapshot hash does not match")
    if not request.fact_ids:
        return _reject(hunk, hunk_hash, "missing_fact_ids", "visa request has no fact ids")
    if any(fact_id not in receipt.verified_fact_ids for fact_id in request.fact_ids):
        return _reject(hunk, hunk_hash, "unknown_fact_id", "visa request references unknown fact id")
    if hunk.path not in receipt.suspect_scopes:
        return _reject(hunk, hunk_hash, "unrelated_file", "path is outside suspect scope")
    if request.repair_pattern_id not in receipt.allowed_repair_patterns:
        return _reject(hunk, hunk_hash, "repair_pattern_not_allowed", "repair pattern is not allowed by receipt")
    span = _authorized_span_for_request(request, receipt)
    if span is None:
        return _reject(hunk, hunk_hash, "missing_authorized_span", "authorized span does not exist")
    if span.path != hunk.path:
        return _reject(hunk, hunk_hash, "span_path_mismatch", "authorized span is for a different path")
    current_span = _current_span(current_snapshot.project, span)
    if current_span is None or current_span.span_hash != span.span_hash:
        return _reject(hunk, hunk_hash, "span_hash_mismatch", "authorized span hash does not match current code")
    symbol_id = request.suspect_symbol_id
    if symbol_id is not None:
        symbol = receipt.authorized_symbols.get(symbol_id)
        if not symbol:
            return _reject(hunk, hunk_hash, "unknown_symbol", "suspect symbol id is not authorized")
        if not _symbol_exists(current_snapshot.project, symbol):
            return _reject(hunk, hunk_hash, "missing_symbol", "suspect symbol no longer exists")
    if not _old_text_inside_span(current_snapshot.project, span, hunk.old):
        return _reject(hunk, hunk_hash, "old_text_outside_span", "old text does not exist inside authorized span")
    if _old_text_outside_span(current_snapshot.project, span, hunk.old):
        return _reject(hunk, hunk_hash, "outside_authorized_span", "old text also exists outside authorized span")
    shape = _forbidden_shape(hunk, receipt)
    if shape:
        return _reject(hunk, hunk_hash, shape, "hunk matches forbidden shape")
    gate_signature = GateSignature(_digest_json({"hunk_hash": str(hunk_hash), "receipt_id": str(receipt.receipt_id), "path": hunk.path}))
    return PatchVisa(
        visa_id=VisaId(_stable_id("visa", str(hunk_hash), str(receipt.receipt_id), gate_signature)),
        hunk_hash=hunk_hash,
        receipt_id=receipt.receipt_id,
        fact_ids=request.fact_ids,
        authorized_path=hunk.path,
        authorized_symbol_id=symbol_id,
        authorized_span_id=request.authorized_span_id,
        repair_pattern_id=request.repair_pattern_id,
        gate_signature=gate_signature,
        _gate_token=_GATE_TOKEN,
    )


def filter_hunks(
    hunks: Sequence[HunkProposal],
    visa_results: Sequence[PatchVisa | RejectReason],
) -> tuple[list[VisaApprovedHunk], InternalAuditOnly]:
    visas_by_hash = {result.hunk_hash: result for result in visa_results if isinstance(result, PatchVisa)}
    rejects = [RejectRecord.from_reason(result) for result in visa_results if isinstance(result, RejectReason)]
    approved: list[VisaApprovedHunk] = []
    for hunk in hunks:
        hunk_hash = compute_hunk_hash(hunk)
        visa = visas_by_hash.get(hunk_hash)
        if visa is None:
            rejects.append(RejectRecord(hunk_hash, "unsigned_hunk", "hunk has no valid visa", hunk.path))
            continue
        approved.append(VisaApprovedHunk(hunk, visa))
    return approved, InternalAuditOnly(tuple(_dedupe_rejects(rejects)))


def closure_check(
    approved_hunks: Sequence[VisaApprovedHunk],
    receipt: EvidenceReceipt,
    current_snapshot: CodeSnapshot,
    *,
    task: str = "visa-approved repair",
    test_command: Sequence[str] = (),
    max_attempts: int = 1,
    allow_risky_tests: bool = False,
    audit: InternalAuditOnly | None = None,
) -> ChangeSetCandidate | ClosureReject:
    if not approved_hunks:
        return ClosureReject("no visa-approved hunks")
    if not receipt.clean or receipt.snapshot_hash != current_snapshot.snapshot_hash:
        return ClosureReject("receipt is not clean for current snapshot")
    seen: set[HunkHash] = set()
    for approved in approved_hunks:
        hunk_hash = compute_hunk_hash(approved.proposal)
        if approved.visa.hunk_hash != hunk_hash:
            return ClosureReject("visa hunk hash mismatch")
        if approved.visa.receipt_id != receipt.receipt_id:
            return ClosureReject("visa receipt mismatch")
        if hunk_hash in seen:
            return ClosureReject("duplicate hunk hash")
        seen.add(hunk_hash)
    return ChangeSetCandidate(
        approved_hunks=tuple(approved_hunks),
        task=task,
        test_command=tuple(str(item) for item in test_command),
        max_attempts=max(1, max_attempts),
        allow_risky_tests=allow_risky_tests,
        created_at=int(time.time() * 1000),
        audit=audit or InternalAuditOnly(),
        _gate_token=_GATE_TOKEN,
    )


def assert_changeset_candidate(candidate: Any) -> ChangeSetCandidate:
    if not isinstance(candidate, ChangeSetCandidate):
        raise TypeError("run_patch_plan accepts only visa ChangeSetCandidate or legacy PatchPlan")
    for approved in candidate.approved_hunks:
        if approved.visa.hunk_hash != compute_hunk_hash(approved.proposal):
            raise TypeError("PatchVisa hunk_hash does not match approved hunk")
    return candidate


def redacted_audit_summary(audit: InternalAuditOnly) -> str:
    return audit.redacted_summary()


def _visa_request_from_payload(raw: Any) -> VisaRequest:
    if not isinstance(raw, dict):
        return VisaRequest(ReceiptId(""), ())
    return VisaRequest(
        receipt_id=ReceiptId(str(raw.get("receipt_id") or "")),
        fact_ids=tuple(FactId(str(item)) for item in raw.get("fact_ids", ()) if str(item)),
        suspect_symbol_id=SymbolId(str(raw.get("suspect_symbol_id"))) if raw.get("suspect_symbol_id") else None,
        authorized_span_id=SpanId(str(raw.get("authorized_span_id"))) if raw.get("authorized_span_id") else None,
        repair_pattern_id=str(raw.get("repair_pattern_id") or DEFAULT_REPAIR_PATTERN),
    )


def _load_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(exc.msg) from exc
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return payload


def _reject(hunk: HunkProposal, hunk_hash: HunkHash, code: str, reason: str) -> RejectReason:
    return RejectReason(hunk_hash=hunk_hash, code=code, reason=reason, path=hunk.path)


def _authorized_span_for_request(request: VisaRequest, receipt: EvidenceReceipt) -> SpanReceipt | None:
    if request.authorized_span_id is not None:
        return receipt.authorized_spans.get(request.authorized_span_id)
    if request.suspect_symbol_id is not None:
        symbol = receipt.authorized_symbols.get(request.suspect_symbol_id)
        if symbol:
            symbol_path = symbol.split(":", 1)[0]
            for span in receipt.authorized_spans.values():
                if span.path == symbol_path:
                    return span
    return None


def _full_file_span(project: Path, relative_path: str) -> SpanReceipt | None:
    try:
        path = resolve_project_path(project, relative_path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    lines = text.splitlines()
    return SpanReceipt(relative_path, 1, max(1, len(lines)), _digest_text(text))


def _span_from_lines(project: Path, relative_path: str, start: int, end: int) -> SpanReceipt | None:
    try:
        path = resolve_project_path(project, relative_path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    lines = text.splitlines()
    safe_start = max(1, start)
    safe_end = min(max(safe_start, end), max(1, len(lines)))
    body = "\n".join(lines[safe_start - 1 : safe_end])
    if text.endswith("\n") and safe_end >= len(lines):
        body += "\n"
    return SpanReceipt(relative_path, safe_start, safe_end, _digest_text(body))


def _current_span(project: Path, span: SpanReceipt) -> SpanReceipt | None:
    try:
        path = resolve_project_path(project, span.path)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    start = max(1, span.start)
    end = min(max(start, span.end), max(1, len(lines)))
    body = "\n".join(lines[start - 1 : end])
    if path.read_text(encoding="utf-8", errors="replace").endswith("\n") and end == len(lines):
        body += "\n"
    return SpanReceipt(span.path, span.start, span.end, _digest_text(body))


def _snapshot_hash(spans: tuple[SpanReceipt, ...]) -> str:
    payload = [{"path": span.path, "start": span.start, "end": span.end, "span_hash": span.span_hash} for span in sorted(spans, key=lambda item: (item.path, item.start, item.end))]
    return _digest_json({"spans": payload})


def _old_text_inside_span(project: Path, span: SpanReceipt, old: str) -> bool:
    return old in _span_text(project, span)


def _old_text_outside_span(project: Path, span: SpanReceipt, old: str) -> bool:
    try:
        path = resolve_project_path(project, span.path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return True
    return text.count(old) > _span_text(project, span).count(old)


def _span_text(project: Path, span: SpanReceipt) -> str:
    try:
        path = resolve_project_path(project, span.path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    lines = text.splitlines()
    body = "\n".join(lines[max(0, span.start - 1) : min(len(lines), span.end)])
    if text.endswith("\n") and span.end >= len(lines):
        body += "\n"
    return body


def _symbol_exists(project: Path, symbol: str) -> bool:
    path_text, _, name = symbol.partition(":")
    try:
        path = resolve_project_path(project, path_text)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False
    if not name or name == path.name:
        return path.exists()
    if path.suffix != ".py":
        return name in text
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return name in text
    short = name.split(".")[-1]
    for node in ast.walk(tree):
        node_name = getattr(node, "name", None)
        if isinstance(node_name, str) and node_name in {name, short}:
            return True
    return False


def _forbidden_shape(hunk: HunkProposal, receipt: EvidenceReceipt) -> str:
    path = hunk.path.replace("\\", "/")
    old = hunk.old
    new = hunk.new
    if (path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py") or path.startswith("test_")) and TEST_APPROVAL_PATTERN not in receipt.allowed_repair_patterns:
        return "test_change_without_approval"
    if _contains_assertion(old) and not _contains_assertion(new):
        return "delete_assertion"
    if _weakened_assertion(old, new):
        return "weaken_assertion"
    if re.search(r"(@pytest\.mark\.skip|\bskip\(|\.only\(|\bfit\(|\bfdescribe\()", new):
        return "skip_only_test"
    if re.search(r"except\s*(Exception|BaseException)?\s*:", new) and ("pass" in new or "return" in new):
        return "catch_all_or_swallow"
    if re.search(r"^\s*return\s+([0-9]+|True|False|None|['\"][^'\"]*['\"])\s*$", new, re.MULTILINE) and not re.search(r"^\s*return\s+([0-9]+|True|False|None|['\"][^'\"]*['\"])\s*$", old, re.MULTILINE):
        return "return_constant"
    if re.search(r"^\s*(if|elif)\b", old, re.MULTILINE) and not re.search(r"^\s*(if|elif)\b", new, re.MULTILINE):
        return "delete_failing_branch"
    if re.search(r"\b(mock|MagicMock|monkeypatch)\b", new, re.IGNORECASE) and not re.search(r"\b(mock|MagicMock|monkeypatch)\b", old, re.IGNORECASE):
        return "mock_over_failure"
    if max(len(old.splitlines()), len(new.splitlines())) > 60:
        return "large_formatting_with_logic"
    return ""


def _contains_assertion(text: str) -> bool:
    return bool(re.search(r"\b(assert|expect|assertEqual|assertTrue|assertFalse)\b", text))


def _weakened_assertion(old: str, new: str) -> bool:
    if "assert" not in old and "expect" not in old:
        return False
    return any(pattern in new for pattern in ("assert True", "assertIsNotNone", ">= 0", "toBeTruthy", "not None")) and new != old


def _dedupe_rejects(records: Sequence[RejectRecord]) -> list[RejectRecord]:
    selected: dict[HunkHash, RejectRecord] = {}
    for record in records:
        selected.setdefault(record.hunk_hash, record)
    return list(selected.values())


def _stable_id(prefix: str, *parts: str) -> str:
    return prefix + "-" + _digest_text("\0".join(parts))[:16]


def _digest_text(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _digest_json(payload: dict[str, Any]) -> str:
    return _digest_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
