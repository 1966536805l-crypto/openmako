from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


DEFAULT_LOCAL_MODEL = "quantagent-local-hash-v1"
DEFAULT_LOCAL_DIMENSIONS = 64
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_SENTENCE_TRANSFORMERS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    model: str
    available: bool
    dimensions: int
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmbeddingJob:
    job_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_sha256(self) -> str:
        return text_sha256(self.text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmbeddingRecord:
    job_id: str
    text_sha256: str
    provider: str
    model: str
    dimensions: int
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at_ms: int = 0
    from_cache: bool = False

    @property
    def cache_key(self) -> str:
        return embedding_cache_key(self.text_sha256, self.provider, self.model, self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmbeddingBatch:
    provider: str
    model: str
    dimensions: int
    jobs: list[EmbeddingJob] = field(default_factory=list)
    records: list[EmbeddingRecord] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    unavailable: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def status(self) -> ProviderStatus:
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class LocalHashEmbeddingProvider:
    name = "local-hash"

    def __init__(self, model: str = DEFAULT_LOCAL_MODEL, dimensions: int = DEFAULT_LOCAL_DIMENSIONS) -> None:
        self.model = model
        self.dimensions = max(1, int(dimensions))

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, self.model, True, self.dimensions)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [hash_embedding(text, self.dimensions) for text in texts]


class OpenAICompatibleEmbeddingProvider:
    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_OPENAI_MODEL,
        dimensions: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY") or os.environ.get("QUANTAGENT_OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or os.environ.get("QUANTAGENT_OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.dimensions = int(dimensions)
        self.timeout = timeout

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, self.dimensions, "OPENAI_API_KEY or QUANTAGENT_OPENAI_API_KEY is not set")
        return ProviderStatus(self.name, self.model, True, self.dimensions)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.reason)
        payload = json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"embedding request failed: {exc}") from exc
        vectors = [item.get("embedding", []) for item in body.get("data", []) if isinstance(item, dict)]
        if len(vectors) != len(texts):
            raise RuntimeError(f"embedding response count mismatch: expected {len(texts)}, got {len(vectors)}")
        return [[float(value) for value in vector] for vector in vectors]


class SentenceTransformersEmbeddingProvider:
    name = "sentence-transformers"

    def __init__(self, model: str = DEFAULT_SENTENCE_TRANSFORMERS_MODEL, dimensions: int = 384) -> None:
        self.model = model
        self.dimensions = int(dimensions)
        self._model: Any | None = None

    def status(self) -> ProviderStatus:
        if importlib.util.find_spec("sentence_transformers") is None:
            return ProviderStatus(self.name, self.model, False, self.dimensions, "sentence-transformers is not installed")
        return ProviderStatus(self.name, self.model, True, self.dimensions)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.reason)
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model)
        encoded = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in encoded]


class EmbeddingCache:
    def __init__(self, project: str | Path) -> None:
        self.project = Path(project).expanduser().resolve(strict=False)
        self.path = embedding_cache_path(self.project)
        self._records: dict[str, EmbeddingRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._records = {}
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records: dict[str, EmbeddingRecord] = {}
        for key, item in payload.get("records", {}).items():
            if not isinstance(item, dict):
                continue
            record = record_from_dict(item)
            records[str(key)] = record
        self._records = records

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at_ms": _now_ms(),
            "records": {key: record.to_dict() for key, record in sorted(self._records.items())},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return self.path

    def get(self, text_sha: str, provider: str, model: str, dimensions: int) -> EmbeddingRecord | None:
        return self._records.get(embedding_cache_key(text_sha, provider, model, dimensions))

    def put(self, record: EmbeddingRecord) -> None:
        self._records[record.cache_key] = record

    def __len__(self) -> int:
        return len(self._records)


def embedding_cache_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "embeddings" / "cache.json"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_cache_key(text_sha: str, provider: str, model: str, dimensions: int) -> str:
    return "|".join([provider, model, str(int(dimensions)), text_sha])


def embed_batch(
    project: str | Path,
    provider: EmbeddingProvider,
    jobs: Sequence[EmbeddingJob],
    *,
    cache: EmbeddingCache | None = None,
    save_cache: bool = True,
) -> EmbeddingBatch:
    cache = cache or EmbeddingCache(project)
    status = provider.status()
    if not status.available:
        return EmbeddingBatch(status.name, status.model, status.dimensions, list(jobs), unavailable=True, reason=status.reason)

    records: list[EmbeddingRecord] = []
    misses: list[EmbeddingJob] = []
    cache_hits = 0
    for job in jobs:
        cached = cache.get(job.text_sha256, status.name, status.model, status.dimensions)
        if cached is None:
            misses.append(job)
            continue
        cache_hits += 1
        records.append(
            EmbeddingRecord(
                job_id=job.job_id,
                text_sha256=cached.text_sha256,
                provider=cached.provider,
                model=cached.model,
                dimensions=cached.dimensions,
                vector=cached.vector,
                metadata={**cached.metadata, **job.metadata},
                generated_at_ms=cached.generated_at_ms,
                from_cache=True,
            )
        )

    if misses:
        vectors = provider.embed([job.text for job in misses])
        for job, vector in zip(misses, vectors):
            dimensions = len(vector) or status.dimensions
            record = EmbeddingRecord(
                job_id=job.job_id,
                text_sha256=job.text_sha256,
                provider=status.name,
                model=status.model,
                dimensions=dimensions,
                vector=[float(value) for value in vector],
                metadata=dict(job.metadata),
                generated_at_ms=_now_ms(),
                from_cache=False,
            )
            cache.put(record)
            records.append(record)

    records_by_job = {record.job_id: record for record in records}
    ordered = [records_by_job[job.job_id] for job in jobs if job.job_id in records_by_job]
    if save_cache and misses:
        cache.save()
    return EmbeddingBatch(status.name, status.model, status.dimensions, list(jobs), ordered, cache_hits=cache_hits, cache_misses=len(misses))


def incremental_embedding_batch(
    project: str | Path,
    provider: EmbeddingProvider,
    texts: Sequence[str],
    *,
    previous_text_shas: Iterable[str] = (),
    cache: EmbeddingCache | None = None,
) -> EmbeddingBatch:
    previous = set(previous_text_shas)
    jobs = [
        EmbeddingJob(f"text-{index}", text, {"index": index})
        for index, text in enumerate(texts)
        if text_sha256(text) not in previous
    ]
    return embed_batch(project, provider, jobs, cache=cache)


def render_embedding_status(status: ProviderStatus | EmbeddingBatch, *, fmt: str = "markdown") -> str:
    payload = status.to_dict()
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if isinstance(status, ProviderStatus):
        lines = [
            "# Embedding Provider",
            "",
            f"- provider: {status.name}",
            f"- model: {status.model}",
            f"- available: {str(status.available).lower()}",
            f"- dimensions: {status.dimensions}",
        ]
        if status.reason:
            lines.append(f"- reason: {status.reason}")
        return "\n".join(lines) + "\n"
    lines = [
        "# Embedding Batch",
        "",
        f"- provider: {status.provider}",
        f"- model: {status.model}",
        f"- dimensions: {status.dimensions}",
        f"- jobs: {len(status.jobs)}",
        f"- records: {len(status.records)}",
        f"- cache_hits: {status.cache_hits}",
        f"- cache_misses: {status.cache_misses}",
        f"- unavailable: {str(status.unavailable).lower()}",
    ]
    if status.reason:
        lines.append(f"- reason: {status.reason}")
    return "\n".join(lines) + "\n"


def hash_embedding(text: str, dimensions: int = DEFAULT_LOCAL_DIMENSIONS) -> list[float]:
    vector = [0.0] * max(1, int(dimensions))
    tokens = _tokens(text)
    if not tokens:
        tokens = [text or " "]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % len(vector)
        sign = -1.0 if digest[4] % 2 else 1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def record_from_dict(item: dict[str, Any]) -> EmbeddingRecord:
    return EmbeddingRecord(
        job_id=str(item.get("job_id") or ""),
        text_sha256=str(item.get("text_sha256") or ""),
        provider=str(item.get("provider") or ""),
        model=str(item.get("model") or ""),
        dimensions=int(item.get("dimensions") or len(item.get("vector", []))),
        vector=[float(value) for value in item.get("vector", [])],
        metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {},
        generated_at_ms=int(item.get("generated_at_ms") or 0),
        from_cache=bool(item.get("from_cache", False)),
    )


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in text.lower():
        if char.isalnum() or char == "_":
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tokens


def _now_ms() -> int:
    return int(time.time() * 1000)
