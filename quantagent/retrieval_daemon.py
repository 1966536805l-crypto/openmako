from __future__ import annotations

import json
import math
import os
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .code_index import (
    CodeChunk,
    build_code_index,
    index_path,
    lexical_vector,
    load_code_index,
    semantic_fingerprint,
    write_code_index,
)
from .embedding_provider import EmbeddingJob, EmbeddingProvider, LocalHashEmbeddingProvider, embed_batch


RETRIEVAL_VERSION = 1
DEFAULT_EMBEDDING_MODEL = "quantagent-local-hash-v1"


@dataclass(frozen=True)
class RetrievalEmbedding:
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    vector: list[float]
    fingerprints: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    text_preview: str = ""
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalIndex:
    version: int
    project: str
    generated_at_ms: int
    embedding_model: str
    dimensions: int
    records: list[RetrievalEmbedding] = field(default_factory=list)
    source_index_path: str = ""
    source_generated_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    score: float
    vector_score: float
    lexical_score: float
    fingerprint_score: float
    graph_score: float
    reasons: list[str] = field(default_factory=list)
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    query: str
    expanded_terms: list[str]
    seed_paths: list[str] = field(default_factory=list)
    include_symbols: bool = True
    include_import_graph: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalDaemonState:
    daemon_id: str
    project: str
    status: str
    pid: int | None = None
    started_at_ms: int = 0
    updated_at_ms: int = 0
    index_path: str = ""
    records: int = 0
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    note: str = "persistent retrieval state; local hash embeddings are process-independent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalHealth:
    ok: bool
    status: str
    records: int
    stale: bool = False
    diagnostics: list[str] = field(default_factory=list)
    index_path: str = ""
    daemon_state_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def retrieval_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "retrieval"


def retrieval_index_path(project: str | Path) -> Path:
    return retrieval_dir(project) / "index.json"


def retrieval_state_path(project: str | Path) -> Path:
    return retrieval_dir(project) / "daemon.json"


def build_retrieval_index(
    project: str | Path,
    *,
    rebuild_code_index: bool = False,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    provider: EmbeddingProvider | None = None,
) -> RetrievalIndex:
    project_path = Path(project).expanduser().resolve(strict=False)
    code_index_file = index_path(project_path)
    code_index = build_code_index(project_path) if rebuild_code_index or not code_index_file.exists() else load_code_index(project_path)
    if rebuild_code_index or not code_index_file.exists():
        write_code_index(project_path, code_index)
    provider = provider or LocalHashEmbeddingProvider(model=embedding_model)
    jobs = [
        EmbeddingJob(
            chunk.chunk_id,
            _chunk_embedding_text(chunk),
            {"path": chunk.path, "start_line": chunk.start_line, "end_line": chunk.end_line},
        )
        for chunk in code_index.chunks
    ]
    batch = embed_batch(project_path, provider, jobs) if jobs else None
    vectors = {record.job_id: record.vector for record in (batch.records if batch else [])}
    records = [_embedding_from_chunk(chunk, vector=vectors.get(chunk.chunk_id)) for chunk in code_index.chunks]
    dimensions = len(records[0].vector) if records else 0
    status = provider.status()
    return RetrievalIndex(
        version=RETRIEVAL_VERSION,
        project=str(project_path),
        generated_at_ms=_now_ms(),
        embedding_model=status.model,
        dimensions=dimensions,
        records=records,
        source_index_path=str(code_index_file),
        source_generated_at_ms=code_index.generated_at_ms,
    )


def write_retrieval_index(project: str | Path, index: RetrievalIndex | None = None) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    index = index or build_retrieval_index(project_path)
    path = retrieval_index_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_retrieval_index(project: str | Path) -> RetrievalIndex:
    path = retrieval_index_path(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = [
        RetrievalEmbedding(
            chunk_id=str(item.get("chunk_id") or ""),
            path=str(item.get("path") or ""),
            start_line=int(item.get("start_line") or 1),
            end_line=int(item.get("end_line") or 1),
            vector=[float(value) for value in item.get("vector", [])],
            fingerprints=[str(value) for value in item.get("fingerprints", [])],
            symbols=[str(value) for value in item.get("symbols", [])],
            imports=[str(value) for value in item.get("imports", [])],
            text_preview=str(item.get("text_preview") or ""),
            sha256=str(item.get("sha256") or ""),
        )
        for item in payload.get("records", [])
        if isinstance(item, dict)
    ]
    return RetrievalIndex(
        version=int(payload.get("version") or RETRIEVAL_VERSION),
        project=str(payload.get("project") or project),
        generated_at_ms=int(payload.get("generated_at_ms") or 0),
        embedding_model=str(payload.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
        dimensions=int(payload.get("dimensions") or (len(records[0].vector) if records else 0)),
        records=records,
        source_index_path=str(payload.get("source_index_path") or ""),
        source_generated_at_ms=int(payload.get("source_generated_at_ms") or 0),
    )


def ensure_retrieval_index(project: str | Path, *, rebuild: bool = False) -> RetrievalIndex:
    path = retrieval_index_path(project)
    if rebuild or not path.exists():
        index = build_retrieval_index(project, rebuild_code_index=rebuild)
        write_retrieval_index(project, index)
        return index
    return load_retrieval_index(project)


def search_retrieval_index(
    project: str | Path,
    query: str,
    *,
    limit: int = 8,
    seed_paths: Sequence[str | Path] = (),
    rebuild: bool = False,
) -> list[RetrievalHit]:
    project_path = Path(project).expanduser().resolve(strict=False)
    index = ensure_retrieval_index(project_path, rebuild=rebuild)
    plan = plan_retrieval_query(query, seed_paths=seed_paths)
    if not plan.expanded_terms:
        return []
    query_text = " ".join([plan.query, *plan.expanded_terms, *plan.seed_paths])
    query_vector = lexical_vector(query_text)
    query_fingerprints = set(semantic_fingerprint(query_text, limit=24))
    term_counts = Counter(_query_terms(query_text))
    doc_freq = _document_frequency(index.records)
    graph = _import_graph(index.records)
    seeds = {str(path).replace("\\", "/").strip("/") for path in seed_paths if str(path).strip()}
    hits: list[RetrievalHit] = []
    for record in index.records:
        vector_score = _cosine(query_vector, record.vector)
        lexical_score = _lexical_score(record, term_counts, doc_freq, total=max(1, len(index.records)))
        fingerprint_score = _fingerprint_score(query_fingerprints, set(record.fingerprints))
        graph_score = _graph_score(record, seeds, graph)
        symbol_boost = _symbol_boost(record, term_counts)
        path_boost = _path_boost(record, term_counts)
        score = (
            0.48 * vector_score
            + 0.27 * lexical_score
            + 0.17 * fingerprint_score
            + 0.08 * graph_score
            + symbol_boost
            + path_boost
        )
        if score <= 0:
            continue
        reasons = _hit_reasons(record, vector_score, lexical_score, fingerprint_score, graph_score, symbol_boost, path_boost)
        hits.append(
            RetrievalHit(
                chunk_id=record.chunk_id,
                path=record.path,
                start_line=record.start_line,
                end_line=record.end_line,
                score=round(score, 4),
                vector_score=round(vector_score, 4),
                lexical_score=round(lexical_score, 4),
                fingerprint_score=round(fingerprint_score, 4),
                graph_score=round(graph_score, 4),
                reasons=reasons,
                preview=record.text_preview,
            )
        )
    return sorted(hits, key=lambda item: (-item.score, item.path, item.start_line))[: max(0, limit)]


def related_retrieval_paths(
    project: str | Path,
    paths: Sequence[str | Path],
    *,
    limit: int = 8,
    rebuild: bool = False,
) -> list[RetrievalHit]:
    index = ensure_retrieval_index(project, rebuild=rebuild)
    wanted = {str(path).replace("\\", "/").strip("/") for path in paths if str(path).strip()}
    seed_records = [record for record in index.records if record.path in wanted]
    if not seed_records:
        return []
    seed_vector = _average([record.vector for record in seed_records])
    seed_fingerprints = set().union(*(set(record.fingerprints) for record in seed_records))
    graph = _import_graph(index.records)
    hits: list[RetrievalHit] = []
    for record in index.records:
        if record.path in wanted:
            continue
        vector_score = _cosine(seed_vector, record.vector)
        fingerprint_score = _fingerprint_score(seed_fingerprints, set(record.fingerprints))
        graph_score = _graph_score(record, wanted, graph)
        score = 0.58 * vector_score + 0.26 * fingerprint_score + 0.16 * graph_score
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                chunk_id=record.chunk_id,
                path=record.path,
                start_line=record.start_line,
                end_line=record.end_line,
                score=round(score, 4),
                vector_score=round(vector_score, 4),
                lexical_score=0.0,
                fingerprint_score=round(fingerprint_score, 4),
                graph_score=round(graph_score, 4),
                reasons=_hit_reasons(record, vector_score, 0.0, fingerprint_score, graph_score, 0.0, 0.0),
                preview=record.text_preview,
            )
        )
    return sorted(hits, key=lambda item: (-item.score, item.path, item.start_line))[: max(0, limit)]


def plan_retrieval_query(query: str, *, seed_paths: Sequence[str | Path] = ()) -> RetrievalQueryPlan:
    terms = _query_terms(query)
    expanded = list(terms)
    for term in terms:
        expanded.extend(_split_identifier(term))
    for path in seed_paths:
        expanded.extend(_query_terms(str(path)))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in expanded:
        if term in seen or len(term) < 2:
            continue
        seen.add(term)
        deduped.append(term)
        if len(deduped) >= 40:
            break
    return RetrievalQueryPlan(
        query=query,
        expanded_terms=deduped,
        seed_paths=[str(path).replace("\\", "/").strip("/") for path in seed_paths if str(path).strip()],
    )


def start_retrieval_daemon(project: str | Path, *, rebuild: bool = False) -> RetrievalDaemonState:
    project_path = Path(project).expanduser().resolve(strict=False)
    index = ensure_retrieval_index(project_path, rebuild=rebuild)
    previous = load_retrieval_daemon_state(project_path, missing_ok=True)
    state = RetrievalDaemonState(
        daemon_id=previous.daemon_id if previous else "retrieval-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        status="running",
        pid=os.getpid(),
        started_at_ms=previous.started_at_ms if previous and previous.status == "running" else _now_ms(),
        updated_at_ms=_now_ms(),
        index_path=str(retrieval_index_path(project_path)),
        records=len(index.records),
        embedding_model=index.embedding_model,
    )
    _write_retrieval_daemon_state(project_path, state)
    return state


def stop_retrieval_daemon(project: str | Path) -> RetrievalDaemonState:
    project_path = Path(project).expanduser().resolve(strict=False)
    previous = load_retrieval_daemon_state(project_path, missing_ok=True)
    state = RetrievalDaemonState(
        daemon_id=previous.daemon_id if previous else "retrieval-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        status="stopped",
        pid=None,
        started_at_ms=previous.started_at_ms if previous else 0,
        updated_at_ms=_now_ms(),
        index_path=str(retrieval_index_path(project_path)),
        records=len(load_retrieval_index(project_path).records) if retrieval_index_path(project_path).exists() else 0,
        embedding_model=previous.embedding_model if previous else DEFAULT_EMBEDDING_MODEL,
    )
    _write_retrieval_daemon_state(project_path, state)
    return state


def load_retrieval_daemon_state(project: str | Path, *, missing_ok: bool = False) -> RetrievalDaemonState | None:
    path = retrieval_state_path(project)
    if not path.exists():
        if missing_ok:
            return None
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RetrievalDaemonState(
        daemon_id=str(payload.get("daemon_id") or ""),
        project=str(payload.get("project") or project),
        status=str(payload.get("status") or "unknown"),
        pid=int(payload["pid"]) if payload.get("pid") is not None else None,
        started_at_ms=int(payload.get("started_at_ms") or 0),
        updated_at_ms=int(payload.get("updated_at_ms") or 0),
        index_path=str(payload.get("index_path") or ""),
        records=int(payload.get("records") or 0),
        embedding_model=str(payload.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
        note=str(payload.get("note") or "persistent retrieval state; local hash embeddings are process-independent"),
    )


def retrieval_health(project: str | Path) -> RetrievalHealth:
    project_path = Path(project).expanduser().resolve(strict=False)
    diagnostics: list[str] = []
    state = load_retrieval_daemon_state(project_path, missing_ok=True)
    index_file = retrieval_index_path(project_path)
    if not index_file.exists():
        return RetrievalHealth(
            False,
            state.status if state else "missing",
            0,
            stale=True,
            diagnostics=["retrieval index is missing"],
            index_path=str(index_file),
            daemon_state_path=str(retrieval_state_path(project_path)),
        )
    index = load_retrieval_index(project_path)
    source_path = Path(index.source_index_path) if index.source_index_path else index_path(project_path)
    if source_path.exists() and source_path.stat().st_mtime > index_file.stat().st_mtime:
        diagnostics.append("source code index is newer than retrieval index")
    if state and state.status == "running" and state.pid and not _pid_alive(state.pid):
        diagnostics.append(f"recorded daemon pid {state.pid} is not alive")
    ok = not diagnostics
    return RetrievalHealth(
        ok,
        state.status if state else "ready",
        len(index.records),
        stale=bool(diagnostics),
        diagnostics=diagnostics,
        index_path=str(index_file),
        daemon_state_path=str(retrieval_state_path(project_path)),
    )


def render_retrieval_hits(hits: Sequence[RetrievalHit]) -> str:
    if not hits:
        return "No retrieval hits.\n"
    lines = ["# Retrieval Hits", ""]
    for hit in hits:
        reasons = f" reasons={','.join(hit.reasons)}" if hit.reasons else ""
        lines.append(f"- {hit.path}:{hit.start_line}-{hit.end_line} score={hit.score}{reasons}")
        lines.append(f"  {hit.preview}")
    return "\n".join(lines) + "\n"


def render_retrieval_index(index: RetrievalIndex) -> str:
    by_path: dict[str, int] = defaultdict(int)
    for record in index.records:
        by_path[record.path] += 1
    lines = [
        "# Retrieval Index",
        "",
        f"- version: {index.version}",
        f"- project: {index.project}",
        f"- records: {len(index.records)}",
        f"- files: {len(by_path)}",
        f"- dimensions: {index.dimensions}",
        f"- embedding_model: {index.embedding_model}",
        f"- source_index_path: {index.source_index_path or '-'}",
    ]
    return "\n".join(lines) + "\n"


def render_retrieval_state(state: RetrievalDaemonState | RetrievalHealth) -> str:
    if isinstance(state, RetrievalHealth):
        lines = [
            "# Retrieval Health",
            "",
            f"- ok: {str(state.ok).lower()}",
            f"- status: {state.status}",
            f"- records: {state.records}",
            f"- stale: {str(state.stale).lower()}",
            f"- index_path: {state.index_path}",
            f"- daemon_state_path: {state.daemon_state_path}",
        ]
        if state.diagnostics:
            lines.extend(["", "## Diagnostics"])
            lines.extend(f"- {item}" for item in state.diagnostics)
        return "\n".join(lines) + "\n"
    return "\n".join(
        [
            "# Retrieval Daemon",
            "",
            f"- daemon_id: {state.daemon_id}",
            f"- status: {state.status}",
            f"- pid: {state.pid if state.pid is not None else '-'}",
            f"- records: {state.records}",
            f"- embedding_model: {state.embedding_model}",
            f"- index_path: {state.index_path or '-'}",
            f"- note: {state.note}",
        ]
    ) + "\n"


def _embedding_from_chunk(chunk: CodeChunk, *, vector: list[float] | None = None) -> RetrievalEmbedding:
    text = _chunk_embedding_text(chunk)
    return RetrievalEmbedding(
        chunk_id=chunk.chunk_id,
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        vector=vector or chunk.lexical_vector or lexical_vector(text),
        fingerprints=chunk.semantic_fingerprint or semantic_fingerprint(text),
        symbols=chunk.symbols,
        imports=chunk.imports,
        text_preview=_preview(chunk.text),
        sha256=chunk.sha256,
    )


def _chunk_embedding_text(chunk: CodeChunk) -> str:
    return "\n".join([chunk.path, " ".join(chunk.symbols), " ".join(chunk.imports), chunk.text])


def _document_frequency(records: Sequence[RetrievalEmbedding]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        terms = set(_record_terms(record))
        for term in terms:
            counts[term] += 1
    return counts


def _record_terms(record: RetrievalEmbedding) -> list[str]:
    return _query_terms(" ".join([record.path, " ".join(record.symbols), " ".join(record.imports), record.text_preview, " ".join(record.fingerprints)]))


def _query_terms(text: str) -> list[str]:
    terms: list[str] = []
    current = []
    for char in text:
        if char.isalnum() or char in {"_", "-", ".", "/"}:
            current.append(char)
        else:
            if current:
                terms.extend(_split_identifier("".join(current)))
                current.clear()
    if current:
        terms.extend(_split_identifier("".join(current)))
    return [term for term in terms if len(term) >= 2]


def _split_identifier(text: str) -> list[str]:
    normalized = text.replace("\\", "/").replace("-", "_").replace(".", "_").replace("/", "_")
    pieces: list[str] = []
    for part in normalized.split("_"):
        if not part:
            continue
        camel = []
        token = ""
        for char in part:
            if token and char.isupper() and not token[-1].isupper():
                camel.append(token)
                token = char
            else:
                token += char
        if token:
            camel.append(token)
        pieces.extend(item.lower() for item in camel if item)
    if text and text.lower() not in pieces:
        pieces.append(text.lower())
    return pieces


def _lexical_score(record: RetrievalEmbedding, terms: Counter[str], doc_freq: Counter[str], *, total: int) -> float:
    if not terms:
        return 0.0
    counts = Counter(_record_terms(record))
    raw = 0.0
    for term, weight in terms.items():
        tf = counts.get(term, 0)
        if not tf:
            continue
        idf = math.log((total + 1) / (doc_freq.get(term, 0) + 0.5)) + 1
        raw += min(3.0, tf) * idf * min(2.0, weight)
    return min(1.0, raw / 12.0)


def _symbol_boost(record: RetrievalEmbedding, terms: Counter[str]) -> float:
    if not terms:
        return 0.0
    symbols = set(_query_terms(" ".join(record.symbols)))
    overlap = symbols & set(terms)
    return min(0.08, len(overlap) * 0.03)


def _path_boost(record: RetrievalEmbedding, terms: Counter[str]) -> float:
    path_terms = set(_query_terms(record.path))
    overlap = path_terms & set(terms)
    return min(0.06, len(overlap) * 0.02)


def _fingerprint_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return min(1.0, len(left & right) / math.sqrt(len(left) * len(right)))


def _import_graph(records: Sequence[RetrievalEmbedding]) -> dict[str, set[str]]:
    modules_by_path = {_module_name(record.path): record.path for record in records}
    graph: dict[str, set[str]] = defaultdict(set)
    for record in records:
        source = record.path
        for import_name in record.imports:
            top = import_name.split(".", 1)[0]
            target = modules_by_path.get(top) or modules_by_path.get(import_name)
            if target and target != source:
                graph[source].add(target)
                graph[target].add(source)
    return graph


def _graph_score(record: RetrievalEmbedding, seeds: set[str], graph: dict[str, set[str]]) -> float:
    if not seeds:
        return 0.0
    if record.path in seeds:
        return 0.35
    neighbors = graph.get(record.path, set())
    if neighbors & seeds:
        return 1.0
    second_order = set().union(*(graph.get(path, set()) for path in neighbors)) if neighbors else set()
    if second_order & seeds:
        return 0.45
    return 0.0


def _hit_reasons(
    record: RetrievalEmbedding,
    vector_score: float,
    lexical_score: float,
    fingerprint_score: float,
    graph_score: float,
    symbol_boost: float,
    path_boost: float,
) -> list[str]:
    reasons: list[str] = []
    if lexical_score >= 0.12:
        reasons.append("lexical")
    if vector_score >= 0.25:
        reasons.append("vector")
    if fingerprint_score >= 0.12:
        reasons.append("fingerprint")
    if graph_score > 0:
        reasons.append("graph")
    if symbol_boost > 0:
        reasons.append("symbol")
    if path_boost > 0:
        reasons.append("path")
    if not reasons and record.symbols:
        reasons.append("context")
    return reasons[:6]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return max(0.0, sum(left[index] * right[index] for index in range(size)))


def _average(vectors: Sequence[list[float]]) -> list[float]:
    vectors = [vector for vector in vectors if vector]
    if not vectors:
        return []
    dimensions = max(len(vector) for vector in vectors)
    out = [0.0 for _ in range(dimensions)]
    for vector in vectors:
        for index, value in enumerate(vector):
            out[index] += value
    out = [value / len(vectors) for value in out]
    norm = math.sqrt(sum(value * value for value in out))
    return [round(value / norm, 6) for value in out] if norm else out


def _module_name(path: str) -> str:
    clean = path.replace("\\", "/")
    if clean.endswith(".py"):
        clean = clean[:-3]
    return clean.rsplit("/", 1)[-1]


def _preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _write_retrieval_daemon_state(project: Path, state: RetrievalDaemonState) -> Path:
    path = retrieval_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _now_ms() -> int:
    return int(time.time() * 1000)
