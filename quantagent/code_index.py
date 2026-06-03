from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import py_compile
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}")
SYMBOL_RE = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+import|import\s+([A-Za-z_][A-Za-z0-9_\.]*))", re.MULTILINE)
TODO_RE = re.compile(r"\b(TODO|FIXME)\b[:\s-]*(.*)", re.IGNORECASE)
VECTOR_DIMENSIONS = 48
SEMANTIC_FINGERPRINT_LIMIT = 16
INDEXABLE_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
PYTHON_KEYWORDS = {
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "false",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "none",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "true",
    "try",
    "while",
    "with",
    "yield",
}
COMMON_TOKENS = {
    "args",
    "dict",
    "encoding",
    "error",
    "file",
    "item",
    "items",
    "json",
    "line",
    "list",
    "name",
    "none",
    "path",
    "project",
    "self",
    "str",
    "text",
    "true",
    "type",
    "value",
    "with",
}


@dataclass(frozen=True)
class CodeChunk:
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    text: str
    sha256: str
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    semantic_fingerprint: list[str] = field(default_factory=list)
    lexical_vector: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class CodeIndex:
    version: int
    project: str
    generated_at_ms: int
    chunks: list[CodeChunk]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeSearchHit:
    path: str
    start_line: int
    end_line: int
    score: float
    symbols: list[str]
    imports: list[str]
    preview: str


@dataclass(frozen=True)
class RelatedFileHit:
    path: str
    score: float
    shared_fingerprints: list[str]
    preview: str


@dataclass(frozen=True)
class CodeDiagnostic:
    path: str
    level: str
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    source: str = "code_index"


@dataclass(frozen=True)
class CodeIndexHealth:
    version: int
    generated_at_ms: int
    files: int
    chunks: int
    symbols: int
    imports: int
    diagnostics: list[CodeDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def index_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "code_index.json"


def build_code_index(project: str | Path, *, max_file_chars: int = 120_000, chunk_lines: int = 80) -> CodeIndex:
    project_path = Path(project).expanduser().resolve(strict=False)
    chunks: list[CodeChunk] = []
    for path in _iter_indexable_files(project_path):
        text = path.read_text(encoding="utf-8", errors="replace")[:max_file_chars]
        lines = text.splitlines()
        for start in range(0, len(lines), chunk_lines):
            block = "\n".join(lines[start : start + chunk_lines])
            if not block.strip():
                continue
            rel = str(path.relative_to(project_path))
            sha = hashlib.sha256(block.encode("utf-8")).hexdigest()
            symbols = SYMBOL_RE.findall(block)
            imports = _imports(block)
            semantic_text = " ".join([rel, block, " ".join(symbols), " ".join(imports)])
            chunks.append(
                CodeChunk(
                    chunk_id=f"{rel}:{start + 1}:{sha[:8]}",
                    path=rel,
                    start_line=start + 1,
                    end_line=min(len(lines), start + chunk_lines),
                    text=block,
                    sha256=sha,
                    symbols=symbols,
                    imports=imports,
                    semantic_fingerprint=semantic_fingerprint(semantic_text),
                    lexical_vector=lexical_vector(semantic_text),
                )
            )
    return CodeIndex(2, str(project_path), int(time.time() * 1000), chunks)


def write_code_index(project: str | Path, index: CodeIndex | None = None) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    index = index or build_code_index(project_path)
    path = index_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_code_index(project: str | Path) -> CodeIndex:
    payload = json.loads(index_path(project).read_text(encoding="utf-8"))
    chunks = [
        CodeChunk(
            chunk_id=str(item.get("chunk_id") or ""),
            path=str(item.get("path") or ""),
            start_line=int(item.get("start_line") or 1),
            end_line=int(item.get("end_line") or 1),
            text=str(item.get("text") or ""),
            sha256=str(item.get("sha256") or ""),
            symbols=[str(symbol) for symbol in item.get("symbols", [])],
            imports=[str(import_name) for import_name in item.get("imports", [])],
            semantic_fingerprint=[str(term) for term in item.get("semantic_fingerprint", [])] or semantic_fingerprint(str(item.get("text") or "")),
            lexical_vector=[float(value) for value in item.get("lexical_vector", [])] or lexical_vector(str(item.get("text") or "")),
        )
        for item in payload.get("chunks", [])
        if isinstance(item, dict)
    ]
    return CodeIndex(int(payload.get("version") or 1), str(payload.get("project") or project), int(payload.get("generated_at_ms") or 0), chunks)


def search_code_index(project: str | Path, query: str, *, limit: int = 8, rebuild: bool = False) -> list[CodeSearchHit]:
    path = index_path(project)
    index = build_code_index(project) if rebuild or not path.exists() else load_code_index(project)
    terms = _tokens(query)
    if not terms:
        return []
    doc_freq: Counter[str] = Counter()
    chunk_terms: list[Counter[str]] = []
    for chunk in index.chunks:
        counts = Counter(_tokens(chunk.text + " " + chunk.path + " " + " ".join(chunk.symbols) + " " + " ".join(chunk.imports)))
        chunk_terms.append(counts)
        for term in counts:
            doc_freq[term] += 1
    hits: list[CodeSearchHit] = []
    total = max(1, len(index.chunks))
    for chunk, counts in zip(index.chunks, chunk_terms):
        score = 0.0
        length_norm = 1 + sum(counts.values()) / 250
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log((total + 1) / (doc_freq[term] + 0.5)) + 1
            score += (tf * idf) / length_norm
        if score > 0:
            hits.append(CodeSearchHit(chunk.path, chunk.start_line, chunk.end_line, round(score, 4), chunk.symbols, chunk.imports, _preview(chunk.text)))
    return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


def similar_code_chunks(project: str | Path, query: str, *, limit: int = 8, rebuild: bool = False) -> list[CodeSearchHit]:
    path = index_path(project)
    index = build_code_index(project) if rebuild or not path.exists() else load_code_index(project)
    query_text = _query_text(project, query)
    query_vector = lexical_vector(query_text)
    query_fingerprint = set(semantic_fingerprint(query_text))
    hits: list[CodeSearchHit] = []
    for chunk in index.chunks:
        vector_score = _cosine(query_vector, chunk.lexical_vector)
        overlap_score = _fingerprint_overlap(query_fingerprint, set(chunk.semantic_fingerprint))
        score = (0.82 * vector_score) + (0.18 * overlap_score)
        if score <= 0:
            continue
        hits.append(
            CodeSearchHit(
                chunk.path,
                chunk.start_line,
                chunk.end_line,
                round(score, 4),
                chunk.symbols,
                chunk.imports,
                _preview(chunk.text),
            )
        )
    return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


def related_files(project: str | Path, path: str, *, limit: int = 8, rebuild: bool = False) -> list[RelatedFileHit]:
    index_file = index_path(project)
    index = build_code_index(project) if rebuild or not index_file.exists() else load_code_index(project)
    normalized = path.replace("\\", "/").strip("/")
    target_chunks = [chunk for chunk in index.chunks if chunk.path == normalized]
    if not target_chunks:
        return []
    target_vector = _average_vectors([chunk.lexical_vector for chunk in target_chunks])
    target_fingerprint = set().union(*(set(chunk.semantic_fingerprint) for chunk in target_chunks))
    by_path: dict[str, list[CodeChunk]] = {}
    for chunk in index.chunks:
        if chunk.path != normalized:
            by_path.setdefault(chunk.path, []).append(chunk)
    hits: list[RelatedFileHit] = []
    for rel, chunks in by_path.items():
        vector_score = _cosine(target_vector, _average_vectors([chunk.lexical_vector for chunk in chunks]))
        file_fingerprint = set().union(*(set(chunk.semantic_fingerprint) for chunk in chunks))
        shared = sorted(target_fingerprint & file_fingerprint)
        overlap_score = _fingerprint_overlap(target_fingerprint, file_fingerprint)
        score = (0.78 * vector_score) + (0.22 * overlap_score)
        if score <= 0:
            continue
        strongest = max(chunks, key=lambda chunk: _cosine(target_vector, chunk.lexical_vector))
        hits.append(RelatedFileHit(rel, round(score, 4), shared[:8], _preview(strongest.text)))
    return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


def diagnose_code_index(project: str | Path, *, rebuild: bool = False, include_editor_diagnostics: bool = False) -> CodeIndexHealth:
    project_path = Path(project).expanduser().resolve(strict=False)
    path = index_path(project_path)
    diagnostics: list[CodeDiagnostic] = []
    if rebuild or not path.exists():
        index = build_code_index(project_path)
        write_code_index(project_path, index)
        if not rebuild:
            diagnostics.append(CodeDiagnostic(str(path), "warn", "missing_index", "code index was missing and has been rebuilt"))
    else:
        index = load_code_index(project_path)
        fresh = build_code_index(project_path)
        current_ids = {chunk.chunk_id for chunk in index.chunks}
        fresh_ids = {chunk.chunk_id for chunk in fresh.chunks}
        missing_paths = _paths(index) - _paths(fresh)
        changed_paths = _changed_paths(index, fresh)
        new_paths = _paths(fresh) - _paths(index)
        for rel in sorted(missing_paths)[:20]:
            diagnostics.append(CodeDiagnostic(rel, "error", "indexed_file_missing", "file exists in the index but not on disk"))
        for rel in sorted(changed_paths)[:20]:
            diagnostics.append(CodeDiagnostic(rel, "warn", "stale_file_index", "file content changed since the index was written"))
        for rel in sorted(new_paths)[:20]:
            diagnostics.append(CodeDiagnostic(rel, "info", "unindexed_file", "file exists on disk but is not in the current index"))
        if current_ids != fresh_ids and not any(item.code == "stale_file_index" for item in diagnostics):
            diagnostics.append(CodeDiagnostic(str(path), "warn", "stale_index", "index chunk set differs from current project files"))
    diagnostics.extend(_duplicate_symbol_diagnostics(index))
    if include_editor_diagnostics:
        diagnostics.extend(editor_diagnostics(project_path))
    return CodeIndexHealth(
        version=index.version,
        generated_at_ms=index.generated_at_ms,
        files=len(_paths(index)),
        chunks=len(index.chunks),
        symbols=sum(len(chunk.symbols) for chunk in index.chunks),
        imports=sum(len(chunk.imports) for chunk in index.chunks),
        diagnostics=diagnostics,
    )


def dependency_graph(project: str | Path, *, rebuild: bool = False) -> dict[str, list[str]]:
    path = index_path(project)
    index = build_code_index(project) if rebuild or not path.exists() else load_code_index(project)
    graph: dict[str, set[str]] = {}
    for chunk in index.chunks:
        graph.setdefault(chunk.path, set()).update(chunk.imports)
    return {key: sorted(value) for key, value in sorted(graph.items())}


def editor_diagnostics(project: str | Path, *, include_todos: bool = True, include_imports: bool = True, limit: int = 200) -> list[CodeDiagnostic]:
    project_path = Path(project).expanduser().resolve(strict=False)
    local_modules = _local_python_modules(project_path)
    diagnostics: list[CodeDiagnostic] = []
    for path in _iter_indexable_files(project_path):
        rel = str(path.relative_to(project_path))
        text = path.read_text(encoding="utf-8", errors="replace")
        if include_todos:
            diagnostics.extend(_todo_diagnostics(rel, text))
        if path.suffix.lower() == ".py":
            syntax_diagnostic = _py_compile_diagnostic(path, rel)
            if syntax_diagnostic is not None:
                diagnostics.append(syntax_diagnostic)
            elif include_imports:
                diagnostics.extend(_unresolved_import_diagnostics(project_path, path, rel, text, local_modules))
        if len(diagnostics) >= limit:
            return diagnostics[:limit]
    return diagnostics


def render_code_search_hits(hits: list[CodeSearchHit]) -> str:
    if not hits:
        return "No code index hits.\n"
    lines = ["# Code Index Search", ""]
    for hit in hits:
        symbols = f" symbols={','.join(hit.symbols)}" if hit.symbols else ""
        imports = f" imports={','.join(hit.imports)}" if hit.imports else ""
        lines.append(f"- {hit.path}:{hit.start_line}-{hit.end_line} score={hit.score}{symbols}{imports}")
        lines.append(f"  {hit.preview}")
    return "\n".join(lines) + "\n"


def render_related_files(hits: list[RelatedFileHit]) -> str:
    if not hits:
        return "No related files.\n"
    lines = ["# Related Files", ""]
    for hit in hits:
        fingerprints = f" shared={','.join(hit.shared_fingerprints)}" if hit.shared_fingerprints else ""
        lines.append(f"- {hit.path} score={hit.score}{fingerprints}")
        lines.append(f"  {hit.preview}")
    return "\n".join(lines) + "\n"


def render_editor_diagnostics(diagnostics: list[CodeDiagnostic]) -> str:
    if not diagnostics:
        return "No editor diagnostics.\n"
    lines = ["# Editor Diagnostics", ""]
    for item in diagnostics:
        lines.append(f"- [{item.level}] {item.code} {_format_diagnostic_location(item)}: {item.message}")
    return "\n".join(lines) + "\n"


def render_code_index_health(health: CodeIndexHealth) -> str:
    lines = [
        "# Code Index Diagnostics",
        "",
        f"- version: {health.version}",
        f"- generated_at_ms: {health.generated_at_ms}",
        f"- files: {health.files}",
        f"- chunks: {health.chunks}",
        f"- symbols: {health.symbols}",
        f"- imports: {health.imports}",
        f"- diagnostics: {len(health.diagnostics)}",
        "",
    ]
    if health.diagnostics:
        lines.append("## Diagnostics")
        lines.append("")
        for item in health.diagnostics:
            lines.append(f"- [{item.level}] {item.code} {_format_diagnostic_location(item)}: {item.message}")
    return "\n".join(lines).rstrip() + "\n"


def semantic_fingerprint(text: str, *, limit: int = SEMANTIC_FINGERPRINT_LIMIT) -> list[str]:
    counts = Counter(_semantic_tokens(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ranked[:limit]]


def lexical_vector(text: str, *, dimensions: int = VECTOR_DIMENSIONS) -> list[float]:
    if dimensions <= 0:
        return []
    counts = Counter(_semantic_tokens(text))
    vector = [0.0 for _ in range(dimensions)]
    for term, count in counts.items():
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text):
        lowered = token.lower()
        tokens.append(lowered)
        for part in re.sub(r"([a-z])([A-Z])", r"\1 \2", token).replace("_", " ").split():
            if len(part) >= 2:
                tokens.append(part.lower())
    return tokens


def _semantic_tokens(text: str) -> list[str]:
    return [
        token
        for token in _tokens(text)
        if len(token) >= 3 and token not in PYTHON_KEYWORDS and token not in COMMON_TOKENS and not token.isdigit()
    ]


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _imports(text: str) -> list[str]:
    names: list[str] = []
    for left, right in IMPORT_RE.findall(text):
        name = left or right
        if name:
            names.append(name)
    return sorted(set(names))


def _iter_indexable_files(project: Path) -> list[Path]:
    return [
        path
        for path in sorted(project.rglob("*"))
        if path.is_file() and not _skip(path, project) and path.suffix.lower() in INDEXABLE_SUFFIXES
    ]


def _query_text(project: str | Path, query: str) -> str:
    project_path = Path(project).expanduser().resolve(strict=False)
    candidate = project_path / query
    if candidate.is_file() and not _skip(candidate, project_path):
        return candidate.read_text(encoding="utf-8", errors="replace")
    return query


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    return max(0.0, sum(left[index] * right[index] for index in range(size)))


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    vectors = [vector for vector in vectors if vector]
    if not vectors:
        return []
    dimensions = max(len(vector) for vector in vectors)
    averaged = [0.0 for _ in range(dimensions)]
    for vector in vectors:
        for index, value in enumerate(vector):
            averaged[index] += value
    averaged = [value / len(vectors) for value in averaged]
    norm = math.sqrt(sum(value * value for value in averaged))
    if not norm:
        return averaged
    return [round(value / norm, 6) for value in averaged]


def _fingerprint_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def _format_diagnostic_location(diagnostic: CodeDiagnostic) -> str:
    if diagnostic.line is None:
        return diagnostic.path
    if diagnostic.column is None:
        return f"{diagnostic.path}:{diagnostic.line}"
    return f"{diagnostic.path}:{diagnostic.line}:{diagnostic.column}"


def _todo_diagnostics(rel: str, text: str) -> list[CodeDiagnostic]:
    diagnostics: list[CodeDiagnostic] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not _looks_like_todo_comment(line):
            continue
        match = TODO_RE.search(line)
        if not match:
            continue
        marker = match.group(1).upper()
        detail = match.group(2).strip()
        diagnostics.append(
            CodeDiagnostic(
                rel,
                "warn" if marker == "FIXME" else "info",
                "fixme_comment" if marker == "FIXME" else "todo_comment",
                detail or f"{marker} marker left in source",
                line_number,
                max(1, match.start(1) + 1),
                "editor_diagnostics",
            )
        )
    return diagnostics


def _looks_like_todo_comment(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    comment_prefixes = ("#", "//", "/*", "*", "<!--", "--", ";")
    if stripped.startswith(comment_prefixes):
        return True
    return bool(re.match(r"^(?:TODO|FIXME)\b|^-\s+(?:TODO|FIXME)\b|^-\s+\[\s\]", stripped, re.IGNORECASE))


def _py_compile_diagnostic(path: Path, rel: str) -> CodeDiagnostic | None:
    try:
        with tempfile.NamedTemporaryFile(prefix="quantagent-pycompile-", suffix=".pyc") as compiled:
            py_compile.compile(str(path), cfile=compiled.name, dfile=rel, doraise=True)
    except py_compile.PyCompileError as exc:
        syntax_error = exc.exc_value if isinstance(exc.exc_value, SyntaxError) else None
        line = int(getattr(syntax_error, "lineno", 0) or 0) or None
        column = int(getattr(syntax_error, "offset", 0) or 0) or None
        message = str(getattr(syntax_error, "msg", "") or exc.msg or "python syntax error")
        return CodeDiagnostic(rel, "error", "python_syntax_error", message, line, column, "editor_diagnostics")
    return None


def _unresolved_import_diagnostics(project: Path, path: Path, rel: str, text: str, local_modules: set[str]) -> list[CodeDiagnostic]:
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return []
    diagnostics: list[CodeDiagnostic] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_resolves(alias.name, local_modules):
                    diagnostics.append(
                        CodeDiagnostic(
                            rel,
                            "warn",
                            "unresolved_import",
                            f"import {alias.name!r} could not be resolved by the lightweight static resolver",
                            node.lineno,
                            node.col_offset + 1,
                            "editor_diagnostics",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                if not _relative_import_resolves(project, path, node.level, module):
                    diagnostics.append(
                        CodeDiagnostic(
                            rel,
                            "warn",
                            "unresolved_import",
                            f"relative import {'.' * node.level}{module} could not be resolved by the lightweight static resolver",
                            node.lineno,
                            node.col_offset + 1,
                            "editor_diagnostics",
                        )
                    )
            elif module and not _module_resolves(module, local_modules):
                diagnostics.append(
                    CodeDiagnostic(
                        rel,
                        "warn",
                        "unresolved_import",
                        f"from {module!r} import ... could not be resolved by the lightweight static resolver",
                        node.lineno,
                        node.col_offset + 1,
                        "editor_diagnostics",
                    )
                )
    return diagnostics


def _local_python_modules(project: Path) -> set[str]:
    modules: set[str] = set()
    for path in sorted(project.rglob("*.py")):
        if not path.is_file() or _skip(path, project):
            continue
        rel = path.relative_to(project).with_suffix("")
        parts = list(rel.parts)
        if not parts:
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules.add(".".join(parts))
            modules.add(parts[0])
    return modules


def _module_resolves(name: str, local_modules: set[str]) -> bool:
    if not name:
        return True
    top_level = name.split(".", 1)[0]
    if name in local_modules or top_level in local_modules:
        return True
    if top_level in sys.builtin_module_names:
        return True
    stdlib_modules = getattr(sys, "stdlib_module_names", set())
    if top_level in stdlib_modules:
        return True
    try:
        return importlib.util.find_spec(top_level) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _relative_import_resolves(project: Path, path: Path, level: int, module: str) -> bool:
    base = path.parent
    for _ in range(max(0, level - 1)):
        if base == project:
            break
        base = base.parent
    target = base.joinpath(*module.split(".")) if module else base
    return target.with_suffix(".py").is_file() or (target / "__init__.py").is_file()


def _paths(index: CodeIndex) -> set[str]:
    return {chunk.path for chunk in index.chunks}


def _changed_paths(old: CodeIndex, fresh: CodeIndex) -> set[str]:
    old_hashes: dict[str, list[str]] = {}
    fresh_hashes: dict[str, list[str]] = {}
    for chunk in old.chunks:
        old_hashes.setdefault(chunk.path, []).append(chunk.sha256)
    for chunk in fresh.chunks:
        fresh_hashes.setdefault(chunk.path, []).append(chunk.sha256)
    changed: set[str] = set()
    for path, hashes in old_hashes.items():
        if path in fresh_hashes and hashes != fresh_hashes[path]:
            changed.add(path)
    return changed


def _duplicate_symbol_diagnostics(index: CodeIndex) -> list[CodeDiagnostic]:
    owners: dict[str, set[str]] = {}
    for chunk in index.chunks:
        for symbol in chunk.symbols:
            owners.setdefault(symbol, set()).add(chunk.path)
    diagnostics: list[CodeDiagnostic] = []
    for symbol, paths in sorted(owners.items()):
        if len(paths) <= 1 or not symbol[:1].isupper():
            continue
        diagnostics.append(
            CodeDiagnostic(
                ",".join(sorted(paths)[:6]),
                "warn",
                "duplicate_symbol",
                f"symbol {symbol!r} appears in {len(paths)} indexed file(s)",
            )
        )
    return diagnostics[:50]


def _skip(path: Path, project: Path) -> bool:
    rel = path.relative_to(project)
    skipped = {".git", ".quantagent", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    return any(part in skipped or part.startswith(".pytest_cache") for part in rel.parts)
