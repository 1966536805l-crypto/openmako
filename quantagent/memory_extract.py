from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from .memory_store import MemoryEntry, MemoryStore, prepare_memory_text


@dataclass(frozen=True)
class MemoryCandidate:
    kind: str
    text: str
    source: str
    confidence: float


DOMAIN_RE = re.compile(
    r"\b(?:P4|PF|profit\s*factor|slippage|capacity|tick|raw|hash|evidence|sample|broker)\b"
    r"|(?:agent|subagent|skill|memory|runtime|query|trajectory|MCP|TDD|test|review|debug|tool)\b"
    r"|(?:逐笔|滑点|容量|证据|哈希|样本|原始|成交|券商|资金|子agent|技能|记忆|运行时|轨迹|测试|审查|调试|工具)",
    re.IGNORECASE,
)
RULE_RE = re.compile(
    r"\b(?:must|should|required?|requirement|always|never|policy|gate|guardrail|do not|don't)\b"
    r"|(?:必须|应该|需要|要求|规则|门禁|不要|不能)",
    re.IGNORECASE,
)
EVIDENCE_RE = re.compile(
    r"\b(?:evidence|verify|verified|validation|provenance|hash|checksum|audit|proof|must include)\b"
    r"|(?:证据|验证|校验|哈希|审计|来源|溯源)",
    re.IGNORECASE,
)
BLOCKER_RE = re.compile(
    r"\b(?:blocker|blocked|blocking|failed|failure|error|missing|cannot|can't|unavailable|needs evidence|no evidence)\b"
    r"|(?:阻塞|失败|错误|缺少|无法|没有证据|需要证据)",
    re.IGNORECASE,
)
CLAIM_RE = re.compile(
    r"\b(?:P4|PF|profit\s*factor|slippage|capacity|tick|1253(?:[- ]?sample)?)\b"
    r"|(?:逐笔|滑点|容量|样本|成交)",
    re.IGNORECASE,
)
HASH_RE = re.compile(r"\b(?:sha(?:256|1)?[:= ]*)?([a-fA-F0-9]{32}|[a-fA-F0-9]{40}|[a-fA-F0-9]{64})\b")
PATH_RE = re.compile(
    r"(?<![\w.-])("
    r"(?:\.{1,2}/|/)?(?:[A-Za-z0-9_.\-\u4e00-\u9fff]+/)+[A-Za-z0-9_.\-\u4e00-\u9fff ]+"
    r"|[A-Za-z0-9_.\-\u4e00-\u9fff ]+\.(?:py|md|json|csv|txt|yaml|yml|parquet|feather|db|sqlite|png|html)"
    r")"
)


def extract_from_messages(messages: Iterable[Any], source: str = "session") -> list[MemoryCandidate]:
    chunks: list[tuple[str, str]] = []
    for index, message in enumerate(messages, start=1):
        item = _to_mapping(message)
        role = str(item.get("role") or "message")
        content = str(item.get("content") or "")
        if content.strip():
            chunks.append((f"{source}:{role}:{index}", content))
        meta = item.get("meta")
        if isinstance(meta, dict) and meta:
            chunks.append((f"{source}:{role}:{index}:meta", json.dumps(meta, ensure_ascii=False, sort_keys=True)))
    return _extract_chunks(chunks)


def extract_from_report(report: str, source: str = "report") -> list[MemoryCandidate]:
    return _extract_chunks([(source, report)])


def extract_from_tool_loop(result: Any, source: str = "tool_loop") -> list[MemoryCandidate]:
    chunks: list[tuple[str, str]] = []
    item = _to_mapping(result)
    for key in ("task", "stage", "summary"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append((f"{source}:{key}", value))
    for index, tool_result in enumerate(item.get("tool_results") or [], start=1):
        tool = _to_mapping(tool_result)
        name = str(tool.get("name") or tool.get("tool") or f"tool_{index}")
        summary = str(tool.get("summary") or "")
        if summary.strip():
            chunks.append((f"{source}:{name}:{index}", summary))
        data = tool.get("data")
        if isinstance(data, dict) and data:
            chunks.append((f"{source}:{name}:{index}:data", json.dumps(data, ensure_ascii=False, sort_keys=True)))
    return _extract_chunks(chunks)


def extract_memory_candidates(value: Any, source: str = "input") -> list[MemoryCandidate]:
    if isinstance(value, str):
        return extract_from_report(value, source=source)
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        return extract_from_messages(value, source=source)
    mapping = _to_mapping(value)
    if "tool_results" in mapping or {"task", "summary"} & set(mapping):
        return extract_from_tool_loop(mapping, source=source)
    return _extract_chunks([(source, json.dumps(mapping, ensure_ascii=False, sort_keys=True))])


def add_candidates_to_store(project: Path, candidates: Iterable[MemoryCandidate]) -> list[MemoryEntry]:
    added: list[MemoryEntry] = []
    store = MemoryStore(project)
    try:
        for candidate in candidates:
            text = _clean_text(candidate.text)
            if not text:
                continue
            try:
                text, safety = prepare_memory_text(text)
            except ValueError:
                continue
            if not safety.ok or not text:
                continue
            row = store.conn.execute("SELECT id FROM memories WHERE text = ? LIMIT 1", (text,)).fetchone()
            if row:
                continue
            added.append(
                store.add(
                    text,
                    kind=candidate.kind,
                    source=candidate.source,
                    meta={"confidence": candidate.confidence, "extractor": "memory_extract"},
                )
            )
    finally:
        store.close()
    return added


def _extract_chunks(chunks: Iterable[tuple[str, str]]) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    for source, text in chunks:
        candidates.extend(_extract_chunk(text, source))
    return _dedupe_candidates(candidates)


def _extract_chunk(text: str, source: str) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    normalized = _clean_text(text)
    if not normalized:
        return candidates

    for hash_value in _ordered_unique(match.group(1).lower() for match in HASH_RE.finditer(normalized)):
        candidates.append(MemoryCandidate("hash", f"Evidence hash: {hash_value}", source, 0.92))

    for path in _ordered_unique(_normalize_path(match.group(1)) for match in PATH_RE.finditer(normalized)):
        if _looks_like_path(path):
            confidence = 0.82 if "/" in path else 0.72
            candidates.append(MemoryCandidate("path", f"Path reference: {path}", source, confidence))

    for sentence in _sentences(normalized):
        lower = sentence.lower()
        has_domain = bool(DOMAIN_RE.search(sentence))
        if RULE_RE.search(sentence) and has_domain:
            candidates.append(MemoryCandidate("rule", sentence, source, 0.86))
        if EVIDENCE_RE.search(sentence) and (has_domain or "evidence" in lower or "证据" in sentence):
            candidates.append(MemoryCandidate("evidence_requirement", f"Evidence requirement: {sentence}", source, 0.88))
        if BLOCKER_RE.search(sentence) and (has_domain or _contains_pathish(sentence)):
            candidates.append(MemoryCandidate("blocker", f"Blocker: {sentence}", source, 0.84))
        if CLAIM_RE.search(sentence):
            confidence = 0.78
            if EVIDENCE_RE.search(sentence) or HASH_RE.search(sentence):
                confidence = 0.88
            candidates.append(MemoryCandidate("quant_claim", f"Quant claim: {sentence}", source, confidence))

    return candidates


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+|(?:^|\n)\s*[-*]\s+", text)
    out: list[str] = []
    for part in parts:
        cleaned = _clean_text(part.strip(" -\t\r\n"))
        if 12 <= len(cleaned) <= 500:
            out.append(cleaned)
        elif len(cleaned) > 500:
            out.append(cleaned[:497].rstrip() + "...")
    return out


def _dedupe_candidates(candidates: Iterable[MemoryCandidate]) -> list[MemoryCandidate]:
    best_by_key: dict[tuple[str, str], MemoryCandidate] = {}
    for candidate in candidates:
        text = _clean_text(candidate.text)
        if not text:
            continue
        normalized = MemoryCandidate(candidate.kind, text, candidate.source, round(float(candidate.confidence), 3))
        key = (normalized.kind, normalized.text)
        old = best_by_key.get(key)
        if old is None or normalized.confidence > old.confidence:
            best_by_key[key] = normalized
    return list(best_by_key.values())


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        try:
            converted = value.to_dict()
            if isinstance(converted, dict):
                return converted
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:202", exc)
            pass
    return {}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = _clean_text(value)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _normalize_path(path: str) -> str:
    path = _clean_text(path).strip(".,;:)]}\"'")
    path = re.split(r"\s+-\s+|\s+\|\s+", path, maxsplit=1)[0].strip()
    match = re.search(r"^(.+\.(?:py|md|json|csv|txt|yaml|yml|parquet|feather|db|sqlite|png|html))\b", path)
    return match.group(1) if match else path


def _looks_like_path(path: str) -> bool:
    if "://" in path:
        return False
    stripped = path.lstrip("/")
    if stripped.startswith(("github.com/", "www.", "http")):
        return False
    has_extension = bool(re.search(r"\.(?:py|md|json|csv|txt|yaml|yml|parquet|feather|db|sqlite|png|html)$", path))
    if has_extension:
        return True
    if re.search(r"\s", path):
        return False
    if "/" not in path:
        return False
    return path.startswith(("./", "../", "/")) or path.count("/") >= 2


def _contains_pathish(text: str) -> bool:
    return bool(PATH_RE.search(text))
