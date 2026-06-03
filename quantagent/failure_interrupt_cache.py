from __future__ import annotations

import ast
import hashlib
import json
import platform
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .file_ops import resolve_project_path


CACHE_VERSION = 1
CACHE_RELATIVE_PATH = Path(".quantagent") / "failure_interrupt_cache.json"
MAX_FAILURE_CHARS = 6000
MAX_CACHE_ENTRIES = 256


@dataclass(frozen=True)
class FailureFrame:
    path: str
    line: int
    function: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "function": self.function}


@dataclass(frozen=True)
class SourceSpan:
    path: str
    kind: str
    name: str
    start: int
    end: int
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class FailureInterrupt:
    signature: str
    failure_class: str
    exception: str
    frames: tuple[FailureFrame, ...]
    source_spans: tuple[SourceSpan, ...]
    normalized: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "failure_class": self.failure_class,
            "exception": self.exception,
            "frames": [frame.to_dict() for frame in self.frames],
            "source_spans": [span.to_dict() for span in self.source_spans],
            "normalized": self.normalized,
        }


@dataclass(frozen=True)
class DiagnosisAsset:
    failure_signature: str
    invalidation_keys: dict[str, str]
    failure_class: str = ""
    evidence_facts: tuple[str, ...] = ()
    suspect_symbols: tuple[str, ...] = ()
    successful_fix_pattern: str = ""
    validation_result: dict[str, Any] = field(default_factory=dict)
    hits: int = 0
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_signature": self.failure_signature,
            "invalidation_keys": dict(self.invalidation_keys),
            "failure_class": self.failure_class,
            "evidence_facts": list(self.evidence_facts),
            "suspect_symbols": list(self.suspect_symbols),
            "successful_fix_pattern": self.successful_fix_pattern,
            "validation_result": self.validation_result,
            "hits": self.hits,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class EvidenceCheck:
    fact_id: str
    fact_type: str
    expected: str
    actual: str | None
    is_core: bool
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "expected": self.expected,
            "actual": self.actual,
            "is_core": self.is_core,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EvidenceReceipt:
    status: str
    allowed_payload: dict[str, Any] = field(default_factory=dict)
    blocked_payload: dict[str, Any] = field(default_factory=dict)
    checks: list[EvidenceCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "allowed_payload": self.allowed_payload,
            "blocked_payload": self.blocked_payload,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class EvidenceRecheckResult:
    status: str
    checks: list[EvidenceCheck] = field(default_factory=list)
    receipt: EvidenceReceipt | None = None
    reason: str = ""

    @property
    def matched_facts(self) -> list[str]:
        return [check.expected for check in self.checks if check.status == "MATCHED"]

    @property
    def contradicted_facts(self) -> list[str]:
        return [check.expected for check in self.checks if check.status == "CONTRADICTED"]

    @property
    def missing_facts(self) -> list[str]:
        return [check.expected for check in self.checks if check.status == "MISSING"]


def cache_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / CACHE_RELATIVE_PATH


def build_failure_interrupt(
    source_project: str | Path,
    failure_output: str,
    *,
    failure_class: str = "",
    planned_paths: Sequence[str | Path] = (),
) -> FailureInterrupt:
    project = Path(source_project).expanduser().resolve(strict=False)
    text = _trim_failure(failure_output)
    frames = tuple(_extract_frames(project, text))
    exception = _extract_exception(text)
    spans = tuple(_source_spans(project, frames, planned_paths))
    normalized = {
        "failure_class": failure_class or _classify_failure_text(text),
        "exception": exception,
        "frames": [frame.to_dict() for frame in frames[:4]],
        "source_spans": [span.to_dict() for span in spans],
        "assertion": _assertion_fingerprint(text),
    }
    signature = _digest_json(normalized)
    return FailureInterrupt(
        signature=signature,
        failure_class=str(normalized["failure_class"]),
        exception=exception,
        frames=frames,
        source_spans=spans,
        normalized=normalized,
    )


def find_diagnosis_asset(
    cache_project: str | Path,
    source_project: str | Path,
    failure_output: str,
    *,
    failure_class: str = "",
    planned_paths: Sequence[str | Path] = (),
) -> tuple[FailureInterrupt, DiagnosisAsset | None]:
    interrupt = build_failure_interrupt(
        source_project,
        failure_output,
        failure_class=failure_class,
        planned_paths=planned_paths,
    )
    payload = _load_cache(cache_project)
    raw = _entries(payload).get(interrupt.signature)
    if not isinstance(raw, dict):
        return interrupt, None
    asset = _asset_from_payload(raw)
    if not _invalidation_matches(source_project, interrupt, asset):
        return interrupt, None
    _touch_entry(cache_project, interrupt.signature)
    return interrupt, asset


def record_diagnosis_asset(
    cache_project: str | Path,
    source_project: str | Path,
    failure_output: str,
    *,
    failure_class: str = "",
    planned_paths: Sequence[str | Path] = (),
    evidence_facts: Sequence[str] = (),
    suspect_symbols: Sequence[str] = (),
    successful_fix_pattern: str = "",
    validation_result: dict[str, Any] | None = None,
    invalidation_keys: dict[str, str] | None = None,
) -> FailureInterrupt:
    interrupt = build_failure_interrupt(
        source_project,
        failure_output,
        failure_class=failure_class,
        planned_paths=planned_paths,
    )
    record_diagnosis_asset_for_interrupt(
        cache_project,
        source_project,
        interrupt,
        evidence_facts=evidence_facts,
        suspect_symbols=suspect_symbols,
        successful_fix_pattern=successful_fix_pattern,
        validation_result=validation_result,
        invalidation_keys=invalidation_keys,
    )
    return interrupt


def record_diagnosis_asset_for_interrupt(
    cache_project: str | Path,
    source_project: str | Path,
    interrupt: FailureInterrupt,
    *,
    evidence_facts: Sequence[str] = (),
    suspect_symbols: Sequence[str] = (),
    successful_fix_pattern: str = "",
    validation_result: dict[str, Any] | None = None,
    invalidation_keys: dict[str, str] | None = None,
) -> None:
    now = int(time.time() * 1000)
    payload = _load_cache(cache_project)
    entries = _entries(payload)
    previous = entries.get(interrupt.signature)
    hits = int(previous.get("hits", 0)) if isinstance(previous, dict) else 0
    previous_created_at = int(previous.get("created_at", now)) if isinstance(previous, dict) else now
    entry = DiagnosisAsset(
        failure_signature=interrupt.signature,
        invalidation_keys=dict(invalidation_keys or build_invalidation_keys(source_project, interrupt)),
        failure_class=interrupt.failure_class,
        evidence_facts=tuple(_dedupe_strings(evidence_facts)),
        suspect_symbols=tuple(_dedupe_strings(suspect_symbols or _suspect_symbols_from_interrupt(interrupt))),
        successful_fix_pattern=" ".join(successful_fix_pattern.split())[:240],
        validation_result=dict(validation_result or {}),
        hits=hits,
        created_at=previous_created_at,
        updated_at=now,
    )
    entries[interrupt.signature] = entry.to_dict()
    _prune_entries(entries)
    _write_cache(cache_project, payload)


def build_invalidation_keys(source_project: str | Path, interrupt: FailureInterrupt) -> dict[str, str]:
    project = Path(source_project).expanduser().resolve(strict=False)
    return {
        "suspect_span_hash": _digest_json({"source_spans": [span.to_dict() for span in interrupt.source_spans]}),
        "stack_trace_hash": _digest_json({"frames": [frame.to_dict() for frame in interrupt.frames]}),
        "lock_hash": _lock_hash(project),
        "recent_diff_hash": _recent_diff_hash(project),
        "runtime_info": _runtime_info(),
    }


def recheck_diagnosis_asset(asset: DiagnosisAsset, current_facts: dict[str, Any]) -> EvidenceRecheckResult:
    """Quarantine cached diagnosis evidence before it can influence prompts."""
    project = Path(str(current_facts.get("project") or ".")).expanduser().resolve(strict=False)
    current_fact_set = set(_dedupe_strings(str(item) for item in current_facts.get("facts", ()) if str(item)))
    checks = _dedupe_evidence_checks(
        [
            *_checks_from_asset_failure_class(asset, current_fact_set, current_facts),
            *_checks_from_evidence_facts(asset, project, current_fact_set, current_facts),
            *_checks_from_suspect_symbols(asset, project),
            *_checks_from_validation_result(asset, current_facts),
        ]
    )
    status, reason = _evidence_status(checks)
    receipt = _build_evidence_receipt(asset, status, checks, reason)
    return EvidenceRecheckResult(status=status, checks=checks, receipt=receipt, reason=reason)


def _load_cache(project: str | Path) -> dict[str, Any]:
    path = cache_path(project)
    if not path.exists():
        return {"version": CACHE_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": CACHE_VERSION, "entries": {}}
    if not isinstance(payload, dict):
        return {"version": CACHE_VERSION, "entries": {}}
    payload.setdefault("version", CACHE_VERSION)
    payload.setdefault("entries", {})
    return payload


def _write_cache(project: str | Path, payload: dict[str, Any]) -> None:
    path = cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _entries(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        payload["entries"] = entries
    return entries


def _touch_entry(project: str | Path, signature: str) -> None:
    payload = _load_cache(project)
    raw = _entries(payload).get(signature)
    if not isinstance(raw, dict):
        return
    raw["hits"] = int(raw.get("hits", 0)) + 1
    now = int(time.time() * 1000)
    raw["updated_at"] = now
    raw["last_used_at"] = now
    _write_cache(project, payload)


def _asset_from_payload(raw: dict[str, Any]) -> DiagnosisAsset:
    validation = raw.get("validation_result")
    return DiagnosisAsset(
        failure_signature=str(raw.get("failure_signature") or raw.get("signature") or ""),
        invalidation_keys={str(key): str(value) for key, value in dict(raw.get("invalidation_keys") or {}).items()},
        failure_class=str(raw.get("failure_class") or ""),
        evidence_facts=tuple(str(item) for item in raw.get("evidence_facts", []) if str(item)),
        suspect_symbols=tuple(str(item) for item in raw.get("suspect_symbols", []) if str(item)),
        successful_fix_pattern=str(raw.get("successful_fix_pattern") or ""),
        validation_result=validation if isinstance(validation, dict) else {},
        hits=int(raw.get("hits", 0) or 0),
        created_at=int(raw.get("created_at", 0) or 0),
        updated_at=int(raw.get("updated_at", raw.get("last_used_at", 0)) or 0),
    )


def _span_from_payload(raw: dict[str, Any]) -> SourceSpan:
    return SourceSpan(
        path=str(raw.get("path") or ""),
        kind=str(raw.get("kind") or ""),
        name=str(raw.get("name") or ""),
        start=int(raw.get("start", 0) or 0),
        end=int(raw.get("end", 0) or 0),
        digest=str(raw.get("digest") or ""),
    )


def _prune_entries(entries: dict[str, Any]) -> None:
    if len(entries) <= MAX_CACHE_ENTRIES:
        return
    ordered = sorted(
        entries.items(),
        key=lambda item: int(item[1].get("updated_at", item[1].get("last_used_at", item[1].get("created_at", 0)))) if isinstance(item[1], dict) else 0,
    )
    for key, _value in ordered[: max(0, len(entries) - MAX_CACHE_ENTRIES)]:
        entries.pop(key, None)


def _invalidation_matches(source_project: str | Path, interrupt: FailureInterrupt, asset: DiagnosisAsset) -> bool:
    if not asset.invalidation_keys:
        return False
    current = build_invalidation_keys(source_project, interrupt)
    for key in ("suspect_span_hash", "stack_trace_hash", "lock_hash", "recent_diff_hash", "runtime_info"):
        if current.get(key, "") != asset.invalidation_keys.get(key, ""):
            return False
    return True


def _checks_from_asset_failure_class(asset: DiagnosisAsset, current_fact_set: set[str], current_facts: dict[str, Any]) -> list[EvidenceCheck]:
    if not asset.failure_class:
        return []
    return [_failure_class_check(asset.failure_class, current_fact_set, current_facts, fact_id="asset.failure_class")]


def _checks_from_evidence_facts(asset: DiagnosisAsset, project: Path, current_fact_set: set[str], current_facts: dict[str, Any]) -> list[EvidenceCheck]:
    checks: list[EvidenceCheck] = []
    for index, raw_fact in enumerate(asset.evidence_facts):
        fact = " ".join(str(raw_fact).split())
        if not fact:
            continue
        fact_id = f"evidence_facts[{index}]"
        if fact.startswith("failure_class="):
            checks.append(_failure_class_check(fact.removeprefix("failure_class=").strip(), current_fact_set, current_facts, fact_id=fact_id, expected_fact=fact))
        elif fact.startswith("context_paths="):
            for path in _split_csv(fact.removeprefix("context_paths=")):
                checks.append(_path_check("CONTEXT_PATH_EXISTS", fact_id=f"{fact_id}:{path}", project=project, path=path, current_paths=current_facts.get("context_paths", ()), is_core=True))
        elif fact.startswith("python_file="):
            path = fact.removeprefix("python_file=").strip()
            checks.append(_path_check("PYTHON_FILE_EXISTS", fact_id=fact_id, project=project, path=path, current_paths=(), is_core=False, expected_label=fact))
        elif fact.startswith("imports["):
            checks.append(_import_check(project, fact, fact_id=fact_id))
        elif fact.startswith("suspect_symbol="):
            symbol = fact.removeprefix("suspect_symbol=").strip()
            checks.append(_suspect_symbol_check(project, symbol, fact_id=fact_id))
        elif fact.startswith("targeted_test_command="):
            expected = fact.removeprefix("targeted_test_command=").strip()
            checks.append(_command_match_check("TARGETED_TEST_COMMAND_MATCH", fact_id, expected, current_facts.get("targeted_test_command"), is_core=False))
        elif fact.startswith("full_test_command="):
            expected = fact.removeprefix("full_test_command=").strip()
            checks.append(_command_match_check("FULL_TEST_COMMAND_MATCH", fact_id, expected, current_facts.get("full_test_command"), is_core=_asset_full_test_passed(asset)))
        elif fact == "full_test=passed":
            checks.append(_validation_allowed_check("full_test=passed", current_facts, is_core=True))
        elif fact == "targeted_test=passed":
            checks.append(_validation_allowed_check("targeted_test=passed", current_facts, is_core=False))
    return checks


def _checks_from_suspect_symbols(asset: DiagnosisAsset, project: Path) -> list[EvidenceCheck]:
    return [_suspect_symbol_check(project, symbol, fact_id=f"suspect_symbols[{index}]") for index, symbol in enumerate(asset.suspect_symbols)]


def _checks_from_validation_result(asset: DiagnosisAsset, current_facts: dict[str, Any]) -> list[EvidenceCheck]:
    validation = asset.validation_result if isinstance(asset.validation_result, dict) else {}
    checks: list[EvidenceCheck] = []
    targeted = validation.get("targeted_test")
    if isinstance(targeted, dict) and targeted.get("command"):
        checks.append(_command_match_check("TARGETED_TEST_COMMAND_MATCH", "validation_result.targeted_test.command", str(targeted.get("command") or ""), current_facts.get("targeted_test_command"), is_core=False))
    full = validation.get("full_test")
    if isinstance(full, dict) and full.get("command"):
        checks.append(_command_match_check("FULL_TEST_COMMAND_MATCH", "validation_result.full_test.command", str(full.get("command") or ""), current_facts.get("full_test_command"), is_core=full.get("ok") is True))
    if isinstance(full, dict) and full.get("ok") is True:
        checks.append(_validation_allowed_check("validation_result.full_test.ok", current_facts, is_core=True))
    return checks


def _failure_class_check(expected: str, current_fact_set: set[str], current_facts: dict[str, Any], *, fact_id: str, expected_fact: str | None = None) -> EvidenceCheck:
    expected = expected.strip()
    actual = str(current_facts.get("failure_class") or _fact_value(current_fact_set, "failure_class") or "").strip()
    if actual and expected and actual != expected:
        return EvidenceCheck(fact_id, "FAILURE_CLASS_MATCH", expected_fact or f"failure_class={expected}", actual, True, "CONTRADICTED", "failure class changed")
    if actual == expected and expected:
        return EvidenceCheck(fact_id, "FAILURE_CLASS_MATCH", expected_fact or f"failure_class={expected}", actual, True, "MATCHED", "failure class matches")
    return EvidenceCheck(fact_id, "FAILURE_CLASS_MATCH", expected_fact or f"failure_class={expected}", actual or None, True, "MISSING", "current failure class is unavailable")


def _path_check(fact_type: str, *, fact_id: str, project: Path, path: str, current_paths: Any, is_core: bool, expected_label: str | None = None) -> EvidenceCheck:
    path_text = str(path).strip()
    expected = expected_label or path_text
    exists = _path_exists(project, path_text)
    current = {str(item) for item in current_paths or ()}
    if not exists and is_core:
        return EvidenceCheck(fact_id, fact_type, expected, None, is_core, "CONTRADICTED", "core path is missing")
    if exists and (not current or path_text in current):
        return EvidenceCheck(fact_id, fact_type, expected, path_text, is_core, "MATCHED", "path exists")
    if exists:
        return EvidenceCheck(fact_id, fact_type, expected, path_text, is_core, "MISSING", "path exists but is not in current context facts")
    return EvidenceCheck(fact_id, fact_type, expected, None, is_core, "MISSING", "path is missing")


def _import_check(project: Path, fact: str, *, fact_id: str) -> EvidenceCheck:
    match = re.match(r"imports\[([^\]]+)\]=(.*)$", fact)
    if not match:
        return EvidenceCheck(fact_id, "IMPORT_STILL_PRESENT", fact, None, False, "UNVERIFIED", "import fact is malformed")
    path_text, import_name = match.groups()
    expected = f"{path_text.strip()}:{import_name.strip()}"
    try:
        path = resolve_project_path(project, path_text.strip())
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        return EvidenceCheck(fact_id, "IMPORT_STILL_PRESENT", expected, None, False, "MISSING", f"import file unavailable: {exc}")
    present, reason = _python_import_present(text, import_name.strip(), path.suffix)
    return EvidenceCheck(fact_id, "IMPORT_STILL_PRESENT", expected, import_name.strip() if present else None, False, "MATCHED" if present else "MISSING", reason)


def _suspect_symbol_check(project: Path, symbol: str, *, fact_id: str) -> EvidenceCheck:
    symbol = str(symbol).strip()
    exists, reason = _symbol_exists(project, symbol)
    return EvidenceCheck(
        fact_id,
        "SUSPECT_SYMBOL_EXISTS",
        "suspect_symbol=" + symbol,
        symbol if exists else None,
        True,
        "MATCHED" if exists else "CONTRADICTED",
        reason or "suspect symbol exists",
    )


def _command_match_check(fact_type: str, fact_id: str, expected: str, actual_command: Any, *, is_core: bool) -> EvidenceCheck:
    expected_text = _normalize_command_text(expected)
    actual_text = _normalize_command_text(_command_text(actual_command))
    if not actual_text:
        return EvidenceCheck(fact_id, fact_type, expected_text, None, is_core, "MISSING", "current command is unavailable")
    if actual_text == expected_text:
        return EvidenceCheck(fact_id, fact_type, expected_text, actual_text, is_core, "MATCHED", "command matches")
    return EvidenceCheck(fact_id, fact_type, expected_text, actual_text, is_core, "MISSING", "current command differs")


def _validation_allowed_check(fact_id: str, current_facts: dict[str, Any], *, is_core: bool) -> EvidenceCheck:
    command_text = _command_text(current_facts.get("full_test_command"))
    if not command_text:
        status = "CONTRADICTED" if is_core else "MISSING"
        return EvidenceCheck(fact_id, "VALIDATION_COMMAND_STILL_ALLOWED", "full_test_command runnable", None, is_core, status, "full test command is missing")
    if bool(current_facts.get("full_test_command_blocked")):
        status = "CONTRADICTED" if is_core else "MISSING"
        return EvidenceCheck(fact_id, "VALIDATION_COMMAND_STILL_ALLOWED", "full_test_command runnable", command_text, is_core, status, "full test command is blocked")
    if current_facts.get("full_test_command_available") is False:
        status = "CONTRADICTED" if is_core else "MISSING"
        return EvidenceCheck(fact_id, "VALIDATION_COMMAND_STILL_ALLOWED", "full_test_command runnable", command_text, is_core, status, "full test command is not runnable")
    return EvidenceCheck(fact_id, "VALIDATION_COMMAND_STILL_ALLOWED", "full_test_command runnable", command_text, is_core, "MATCHED", "validation command is runnable and allowed")


def _evidence_status(checks: Sequence[EvidenceCheck]) -> tuple[str, str]:
    if any(check.is_core and check.status == "CONTRADICTED" for check in checks):
        return "CONTRADICTED", "core evidence check is contradicted"
    if any(check.fact_type == "VALIDATION_COMMAND_STILL_ALLOWED" and check.status == "CONTRADICTED" for check in checks):
        return "CONTRADICTED", "cached full-test evidence no longer has a runnable validation command"
    if any(check.is_core and check.status == "MATCHED" for check in checks):
        return "VALID", "cached diagnosis core evidence still matches"
    if any(check.status in {"MATCHED", "MISSING"} for check in checks):
        return "WEAKENED", "cached diagnosis evidence is incomplete but not contradicted"
    return "UNVERIFIED", "asset has no deterministic evidence that can be verified"


def _build_evidence_receipt(asset: DiagnosisAsset, status: str, checks: Sequence[EvidenceCheck], reason: str) -> EvidenceReceipt:
    matched_evidence_facts = _matched_evidence_facts(asset, checks)
    matched_symbols = _matched_suspect_symbols_from_checks(asset, checks)
    allowed: dict[str, Any] = {}
    if status == "VALID":
        if matched_evidence_facts:
            allowed["evidence_facts"] = matched_evidence_facts
        if matched_symbols:
            allowed["suspect_symbols"] = matched_symbols
        if asset.successful_fix_pattern:
            allowed["successful_fix_pattern"] = asset.successful_fix_pattern
    elif status == "WEAKENED":
        if matched_symbols:
            allowed["suspect_symbols"] = matched_symbols
        if asset.successful_fix_pattern:
            allowed["successful_fix_pattern"] = asset.successful_fix_pattern

    blocked_facts = [fact for fact in asset.evidence_facts if fact not in set(allowed.get("evidence_facts", []))]
    blocked_symbols = [symbol for symbol in asset.suspect_symbols if symbol not in set(allowed.get("suspect_symbols", []))]
    blocked: dict[str, Any] = {"reason": reason}
    if blocked_facts:
        blocked["evidence_facts"] = blocked_facts
    if blocked_symbols:
        blocked["suspect_symbols"] = blocked_symbols
    return EvidenceReceipt(status=status, allowed_payload=allowed, blocked_payload=blocked, checks=list(checks))


def _matched_evidence_facts(asset: DiagnosisAsset, checks: Sequence[EvidenceCheck]) -> list[str]:
    facts: list[str] = []
    for index, raw in enumerate(asset.evidence_facts):
        fact_id = f"evidence_facts[{index}]"
        related = [check for check in checks if check.fact_id == fact_id or check.fact_id.startswith(fact_id + ":")]
        if related and all(check.status == "MATCHED" for check in related):
            facts.append(raw)
    return _dedupe_strings(facts)


def _matched_suspect_symbols_from_checks(asset: DiagnosisAsset, checks: Sequence[EvidenceCheck]) -> list[str]:
    matched = {check.expected.removeprefix("suspect_symbol=").strip() for check in checks if check.fact_type == "SUSPECT_SYMBOL_EXISTS" and check.status == "MATCHED"}
    return [symbol for symbol in asset.suspect_symbols if symbol in matched]


def _dedupe_evidence_checks(checks: Sequence[EvidenceCheck]) -> list[EvidenceCheck]:
    selected: dict[tuple[str, str, str], EvidenceCheck] = {}
    for check in checks:
        key = (check.fact_type, check.fact_id, check.expected)
        current = selected.get(key)
        if current is None or _check_status_rank(check.status) > _check_status_rank(current.status):
            selected[key] = check
    return list(selected.values())


def _check_status_rank(status: str) -> int:
    return {"CONTRADICTED": 4, "MATCHED": 3, "MISSING": 2, "UNVERIFIED": 1}.get(status, 0)


def _asset_full_test_passed(asset: DiagnosisAsset) -> bool:
    full = asset.validation_result.get("full_test") if isinstance(asset.validation_result, dict) else None
    if isinstance(full, dict) and full.get("ok") is True:
        return True
    return any(str(fact).strip() == "full_test=passed" for fact in asset.evidence_facts)


def _path_exists(project: Path, relative_path: str) -> bool:
    try:
        return resolve_project_path(project, relative_path).exists()
    except (OSError, ValueError):
        return False


def _symbol_exists(project: Path, symbol: str) -> tuple[bool, str]:
    path_text, name = _split_symbol(symbol)
    if not path_text:
        return False, "empty symbol path"
    try:
        path = resolve_project_path(project, path_text)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if not path.exists():
        return False, "file missing"
    if not name or name == path.name:
        return True, ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, str(exc)
    if path.suffix == ".py":
        return _python_symbol_exists(text, name), "symbol missing"
    return (name in text), "symbol text missing"


def _split_symbol(symbol: str) -> tuple[str, str]:
    cleaned = str(symbol).strip()
    if ":" not in cleaned:
        return cleaned, ""
    path, name = cleaned.split(":", 1)
    return path.strip(), name.strip()


def _python_symbol_exists(text: str, name: str) -> bool:
    target = name.strip()
    if not target:
        return True
    short_target = target.split(".")[-1]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return target in text
    for node in ast.walk(tree):
        node_name = getattr(node, "name", None)
        if isinstance(node_name, str) and node_name in {target, short_target}:
            return True
        if isinstance(node, ast.alias) and (node.asname == target or node.name == target):
            return True
        if isinstance(node, ast.Name) and node.id in {target, short_target} and isinstance(node.ctx, ast.Store):
            return True
    return False


def _python_import_present(text: str, import_name: str, suffix: str) -> tuple[bool, str]:
    target = import_name.strip()
    if not target:
        return False, "empty import target"
    if suffix != ".py":
        return False, "import facts are only verified for Python files"
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False, "python file could not be parsed"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names = {alias.name, alias.name.split(".")[0]}
                if alias.asname:
                    names.add(alias.asname)
                if target in names:
                    return True, "import still present"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            module_parts = {module, module.split(".")[0]} if module else set()
            for alias in node.names:
                names = set(module_parts) | {alias.name, f"{module}.{alias.name}" if module else alias.name}
                if alias.asname:
                    names.add(alias.asname)
                if target in names:
                    return True, "import still present"
    return False, "import is not present"


def _fact_value(facts: set[str], key: str) -> str:
    prefix = key + "="
    for fact in facts:
        if fact.startswith(prefix):
            return fact.removeprefix(prefix).strip()
    return ""


def _split_csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _command_text(command: Any) -> str:
    if isinstance(command, str):
        return " ".join(command.split())
    if isinstance(command, (list, tuple)):
        return shlex.join([str(item) for item in command])
    return ""


def _normalize_command_text(command: Any) -> str:
    return " ".join(str(command or "").split())


def _extract_frames(project: Path, text: str) -> list[FailureFrame]:
    frames: list[FailureFrame] = []
    pattern = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([A-Za-z_][A-Za-z0-9_]*))?')
    for match in pattern.finditer(text):
        raw_path, raw_line, function = match.groups()
        rel = _relative_path(project, raw_path)
        if not rel:
            continue
        frames.append(FailureFrame(rel, int(raw_line), function or ""))
    return _dedupe_frames(frames)


def _relative_path(project: Path, raw_path: str) -> str:
    path = Path(raw_path)
    try:
        if path.is_absolute():
            return str(path.resolve(strict=False).relative_to(project))
    except ValueError:
        return ""
    cleaned = str(path).replace("\\", "/")
    if cleaned.startswith("../") or cleaned.startswith("/"):
        return ""
    return cleaned


def _dedupe_frames(frames: Sequence[FailureFrame]) -> list[FailureFrame]:
    seen: set[tuple[str, int, str]] = set()
    deduped: list[FailureFrame] = []
    for frame in frames:
        key = (frame.path, frame.line, frame.function)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(frame)
    return deduped


def _source_spans(project: Path, frames: Sequence[FailureFrame], planned_paths: Sequence[str | Path]) -> list[SourceSpan]:
    spans: list[SourceSpan] = []
    for frame in frames[:6]:
        span = _span_for_frame(project, frame)
        if span is not None:
            spans.append(span)
    if spans:
        return _dedupe_spans(spans)
    for path in list(planned_paths)[:4]:
        span = _span_for_path(project, str(path))
        if span is not None:
            spans.append(span)
    return _dedupe_spans(spans)


def _dedupe_spans(spans: Sequence[SourceSpan]) -> list[SourceSpan]:
    seen: set[tuple[str, str, str, int, int]] = set()
    deduped: list[SourceSpan] = []
    for span in spans:
        key = (span.path, span.kind, span.name, span.start, span.end)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _span_for_frame(project: Path, frame: FailureFrame) -> SourceSpan | None:
    try:
        path = resolve_project_path(project, frame.path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    lines = text.splitlines()
    if not lines:
        return None
    if path.suffix == ".py":
        ast_span = _python_ast_span(text, frame.line)
        if ast_span is not None:
            kind, name, start, end = ast_span
            body = "\n".join(lines[max(0, start - 1) : min(len(lines), end)])
            return SourceSpan(frame.path, kind, name, start, end, _digest_text(body))
    start = max(1, frame.line - 12)
    end = min(len(lines), frame.line + 12)
    body = "\n".join(lines[start - 1 : end])
    return SourceSpan(frame.path, "window", frame.function or Path(frame.path).name, start, end, _digest_text(body))


def _span_for_path(project: Path, relative_path: str) -> SourceSpan | None:
    try:
        path = resolve_project_path(project, relative_path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    lines = text.splitlines()
    body = "\n".join(lines[:80])
    return SourceSpan(relative_path, "file_head", Path(relative_path).name, 1, min(len(lines), 80), _digest_text(body))


def _python_ast_span(text: str, line: int) -> tuple[str, str, int, int] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    best: tuple[int, str, str, int, int] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = int(getattr(node, "lineno", 0) or 0)
        end = int(getattr(node, "end_lineno", start) or start)
        if start <= line <= end:
            width = end - start
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            name = str(getattr(node, "name", ""))
            candidate = (width, kind, name, start, end)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return None
    _width, kind, name, start, end = best
    return kind, name, start, end


def _extract_exception(text: str) -> str:
    for line in reversed(text.splitlines()):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))\b", line)
        if match:
            return match.group(1)
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))\b", text)
    return match.group(1) if match else ""


def _classify_failure_text(text: str) -> str:
    lowered = text.lower()
    if "syntaxerror" in lowered or "indentationerror" in lowered:
        return "syntax"
    if "modulenotfounderror" in lowered or "importerror" in lowered or "cannot import name" in lowered:
        return "import"
    if "assertionerror" in lowered or "assert " in lowered:
        return "assertion"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "permission denied" in lowered:
        return "env"
    return "unknown"


def _assertion_fingerprint(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(marker in stripped for marker in ("AssertionError", "assert ", "==", "!=", "E   ")):
            lines.append(_normalize_numbers(stripped))
        if len(lines) >= 8:
            break
    return "\n".join(lines)


def _normalize_numbers(text: str) -> str:
    return re.sub(r"\b\d+\b", "#", text)


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        compact = " ".join(str(value).split())
        if not compact or compact in seen:
            continue
        seen.add(compact)
        result.append(compact)
    return result


def _suspect_symbols_from_interrupt(interrupt: FailureInterrupt) -> list[str]:
    symbols: list[str] = []
    for span in interrupt.source_spans:
        symbols.append(span.path)
        if span.name:
            symbols.append(f"{span.path}:{span.name}")
    for frame in interrupt.frames:
        symbols.append(frame.path)
        if frame.function:
            symbols.append(f"{frame.path}:{frame.function}")
    return _dedupe_strings(symbols)


def _lock_hash(project: Path) -> str:
    names = (
        "poetry.lock",
        "Pipfile.lock",
        "requirements.txt",
        "requirements-dev.txt",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
    )
    chunks: list[str] = []
    for name in names:
        path = project / name
        if not path.exists() or not path.is_file():
            continue
        try:
            chunks.append(name + "\0" + path.read_text(encoding="utf-8", errors="replace")[:200_000])
        except OSError:
            continue
    return _digest_text("\n".join(chunks)) if chunks else ""


def _recent_diff_hash(project: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--", "."],
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return _digest_text(result.stdout[:200_000]) if result.stdout else ""


def _runtime_info() -> str:
    return f"python={sys.version_info.major}.{sys.version_info.minor};platform={platform.system().lower()}"


def _trim_failure(text: str) -> str:
    return str(text)[-MAX_FAILURE_CHARS:]


def _digest_text(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _digest_json(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest_text(data)
