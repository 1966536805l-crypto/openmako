from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}")
INDEXABLE_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
SKIP_PARTS = {".git", ".quantagent", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
PAGERANK_DAMPING = 0.85
PAGERANK_ITERATIONS = 30


@dataclass(frozen=True)
class RepoSymbol:
    name: str
    kind: str
    path: str
    line: int
    end_line: int
    qualname: str = ""
    doc: str = ""
    refs: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["refs"] = list(self.refs)
        payload["calls"] = list(self.calls)
        return payload


@dataclass(frozen=True)
class RepoFileSummary:
    path: str
    language: str
    sha256: str
    lines: int
    imports: tuple[str, ...] = ()
    symbols: tuple[RepoSymbol, ...] = ()
    tokens: tuple[str, ...] = ()
    headings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "sha256": self.sha256,
            "lines": self.lines,
            "imports": list(self.imports),
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "tokens": list(self.tokens),
            "headings": list(self.headings),
        }


@dataclass(frozen=True)
class RepoMap:
    version: int
    project: str
    generated_at_ms: int
    files: tuple[RepoFileSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project,
            "generated_at_ms": self.generated_at_ms,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True)
class RepoMapHit:
    path: str
    score: float
    reason: str
    symbols: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = list(self.symbols)
        payload["imports"] = list(self.imports)
        return payload


def repo_map_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "repo_map.json"


def build_repo_map(project: str | Path, *, max_file_chars: int = 160_000) -> RepoMap:
    project_path = Path(project).expanduser().resolve(strict=False)
    files: list[RepoFileSummary] = []
    for path in _iter_repo_files(project_path):
        text = path.read_text(encoding="utf-8", errors="replace")[:max_file_chars]
        rel = _rel(project_path, path)
        if path.suffix.lower() == ".py":
            files.append(_python_file_summary(rel, text))
        else:
            files.append(_text_file_summary(rel, text, path.suffix.lower().lstrip(".") or "text"))
    return RepoMap(1, str(project_path), int(time.time() * 1000), tuple(files))


def write_repo_map(project: str | Path, repo_map: RepoMap | None = None) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    repo_map = repo_map or build_repo_map(project_path)
    path = repo_map_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(repo_map.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_repo_map(project: str | Path) -> RepoMap:
    payload = json.loads(repo_map_path(project).read_text(encoding="utf-8"))
    files = tuple(_file_summary_from_dict(item) for item in payload.get("files", []) if isinstance(item, dict))
    return RepoMap(
        version=int(payload.get("version") or 1),
        project=str(payload.get("project") or project),
        generated_at_ms=int(payload.get("generated_at_ms") or 0),
        files=files,
    )


def ensure_repo_map(project: str | Path, *, rebuild: bool = False) -> RepoMap:
    path = repo_map_path(project)
    if rebuild or not path.exists():
        repo_map = build_repo_map(project)
        write_repo_map(project, repo_map)
        return repo_map
    return load_repo_map(project)


def search_repo_map(project: str | Path, query: str, *, limit: int = 8, rebuild: bool = False) -> list[RepoMapHit]:
    repo_map = ensure_repo_map(project, rebuild=rebuild)
    query_terms = _tokens(query)
    if not query_terms:
        return []
    graph_scores, graph_reasons = _aider_graph_scores(repo_map, mentioned_idents=set(query_terms))
    doc_freq: Counter[str] = Counter()
    file_terms: list[Counter[str]] = []
    for item in repo_map.files:
        counts = Counter(_summary_terms(item))
        file_terms.append(counts)
        for term in counts:
            doc_freq[term] += 1
    total = max(1, len(repo_map.files))
    hit_by_path: dict[str, RepoMapHit] = {}
    for item, counts in zip(repo_map.files, file_terms):
        score = 0.0
        reasons: list[str] = []
        for term in query_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log((total + 1) / (doc_freq[term] + 0.5)) + 1
            score += tf * idf
            if term in _symbol_terms(item):
                reasons.append(f"symbol:{term}")
            elif term in _import_terms(item):
                reasons.append(f"import:{term}")
            else:
                reasons.append(term)
        graph_score = graph_scores.get(item.path, 0.0)
        graph_reason_terms = set(graph_reasons.get(item.path, ())) & set(query_terms)
        if graph_score > 0 and (score > 0 or graph_reason_terms):
            score += graph_score * 8.0
            reasons.extend(f"aider_graph:{ident}" for ident in graph_reasons.get(item.path, ())[:3])
        if score <= 0:
            continue
        hit_by_path[item.path] = RepoMapHit(
            path=item.path,
            score=round(score / (1 + item.lines / 500), 4),
            reason=", ".join(dict.fromkeys(reasons[:7])),
            symbols=tuple(symbol.qualname or symbol.name for symbol in item.symbols[:8]),
            imports=item.imports[:8],
            preview=_file_preview(item),
        )
    for item in repo_map.files:
        if item.path in hit_by_path:
            continue
        graph_score = graph_scores.get(item.path, 0.0)
        graph_reason_terms = set(graph_reasons.get(item.path, ())) & set(query_terms)
        if graph_score <= 0 or not graph_reason_terms:
            continue
        hit_by_path[item.path] = RepoMapHit(
            path=item.path,
            score=round(graph_score * 8.0 / (1 + item.lines / 500), 4),
            reason=", ".join(f"aider_graph:{ident}" for ident in graph_reasons.get(item.path, ())[:5]),
            symbols=tuple(symbol.qualname or symbol.name for symbol in item.symbols[:8]),
            imports=item.imports[:8],
            preview=_file_preview(item),
        )
    return sorted(hit_by_path.values(), key=lambda hit: hit.score, reverse=True)[:limit]


def related_repo_paths(project: str | Path, path: str, *, limit: int = 8, rebuild: bool = False) -> list[RepoMapHit]:
    repo_map = ensure_repo_map(project, rebuild=rebuild)
    normalized = path.replace("\\", "/").strip("/")
    source = next((item for item in repo_map.files if item.path == normalized), None)
    if source is None:
        return []
    source_terms = set(_summary_terms(source))
    source_imports = set(source.imports)
    source_symbols = {symbol.name for symbol in source.symbols}
    graph_scores, graph_reasons = _aider_graph_scores(
        repo_map,
        chat_paths={source.path},
        mentioned_idents=source_terms | set(_tokens(" ".join(source.imports))),
    )
    hits: list[RepoMapHit] = []
    for item in repo_map.files:
        if item.path == source.path:
            continue
        terms = set(_summary_terms(item))
        shared_terms = sorted(source_terms & terms)
        import_overlap = sorted(source_imports & set(item.imports))
        symbol_overlap = sorted(source_symbols & {symbol.name for symbol in item.symbols})
        score = len(shared_terms) / max(1.0, math.sqrt(len(source_terms) * len(terms)))
        score += 0.5 * len(import_overlap)
        score += 0.7 * len(symbol_overlap)
        graph_score = graph_scores.get(item.path, 0.0)
        if graph_score > 0:
            score += graph_score * 6.0
        if score <= 0:
            continue
        reason_parts = []
        if graph_score > 0:
            reason_parts.append("aider_graph=" + ",".join(graph_reasons.get(item.path, ())[:4]))
        if import_overlap:
            reason_parts.append("imports=" + ",".join(import_overlap[:4]))
        if symbol_overlap:
            reason_parts.append("symbols=" + ",".join(symbol_overlap[:4]))
        if shared_terms:
            reason_parts.append("shared=" + ",".join(shared_terms[:4]))
        hits.append(
            RepoMapHit(
                path=item.path,
                score=round(score, 4),
                reason="; ".join(reason_parts),
                symbols=tuple(symbol.qualname or symbol.name for symbol in item.symbols[:8]),
                imports=item.imports[:8],
                preview=_file_preview(item),
            )
        )
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def render_repo_map(repo_map: RepoMap, *, max_files: int = 80) -> str:
    symbol_count = sum(len(item.symbols) for item in repo_map.files)
    import_count = sum(len(item.imports) for item in repo_map.files)
    lines = [
        "# Mako Repo Map",
        "",
        f"- project: {repo_map.project}",
        f"- files: {len(repo_map.files)}",
        f"- symbols: {symbol_count}",
        f"- imports: {import_count}",
        f"- generated_at_ms: {repo_map.generated_at_ms}",
        "",
        "## Files",
        "",
    ]
    for item in repo_map.files[:max_files]:
        symbols = ", ".join(symbol.qualname or symbol.name for symbol in item.symbols[:6])
        imports = ", ".join(item.imports[:5])
        suffix = []
        if symbols:
            suffix.append(f"symbols={symbols}")
        if imports:
            suffix.append(f"imports={imports}")
        detail = f" ({'; '.join(suffix)})" if suffix else ""
        lines.append(f"- {item.path} [{item.language}, {item.lines} lines]{detail}")
    return "\n".join(lines) + "\n"


def render_repo_map_hits(hits: Iterable[RepoMapHit]) -> str:
    items = list(hits)
    if not items:
        return "No repo map hits.\n"
    lines = ["# Repo Map Hits", ""]
    for hit in items:
        lines.append(f"- {hit.path} score={hit.score} reason={hit.reason}")
        if hit.symbols:
            lines.append(f"  symbols: {', '.join(hit.symbols)}")
        if hit.imports:
            lines.append(f"  imports: {', '.join(hit.imports)}")
        if hit.preview:
            lines.append(f"  {hit.preview}")
    return "\n".join(lines) + "\n"


def render_repo_context(
    project: str | Path,
    query: str,
    *,
    budget_chars: int = 6000,
    rebuild: bool = False,
) -> str:
    repo_map = ensure_repo_map(project, rebuild=rebuild)
    hits = search_repo_map(project, query, limit=20, rebuild=False)
    lines = [
        "# Repo Context Map",
        "",
        f"- query: {query}",
        f"- files: {len(repo_map.files)}",
        "",
    ]
    used = len("\n".join(lines))
    for hit in hits:
        item = next((candidate for candidate in repo_map.files if candidate.path == hit.path), None)
        if item is None:
            continue
        block = _context_block(item, hit)
        if used + len(block) > budget_chars:
            break
        lines.append(block.rstrip())
        used += len(block)
    return "\n\n".join(lines).rstrip() + "\n"


def _python_file_summary(rel: str, text: str) -> RepoFileSummary:
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    imports: set[str] = set()
    symbols: list[RepoSymbol] = []
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return _text_file_summary(rel, text, "python")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(("." * node.level) + node.module)
    for node in tree.body:
        symbols.extend(_symbols_from_node(node, rel, parent=""))
    terms = _top_terms(" ".join([rel, text, " ".join(imports)]), limit=40)
    return RepoFileSummary(
        path=rel,
        language="python",
        sha256=sha,
        lines=len(text.splitlines()),
        imports=tuple(sorted(imports)),
        symbols=tuple(symbols),
        tokens=tuple(terms),
    )


def _symbols_from_node(node: ast.AST, rel: str, *, parent: str) -> list[RepoSymbol]:
    symbols: list[RepoSymbol] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        name = node.name
        qualname = f"{parent}.{name}" if parent else name
        refs, calls = _refs_and_calls(node)
        symbols.append(
            RepoSymbol(
                name=name,
                kind="class" if isinstance(node, ast.ClassDef) else "function",
                path=rel,
                line=int(getattr(node, "lineno", 1) or 1),
                end_line=int(getattr(node, "end_lineno", getattr(node, "lineno", 1)) or 1),
                qualname=qualname,
                doc=(ast.get_docstring(node) or "").splitlines()[0][:180] if ast.get_docstring(node) else "",
                refs=tuple(sorted(refs)[:40]),
                calls=tuple(sorted(calls)[:40]),
            )
        )
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                symbols.extend(_symbols_from_node(child, rel, parent=qualname))
    return symbols


def _refs_and_calls(node: ast.AST) -> tuple[set[str], set[str]]:
    refs: set[str] = set()
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            refs.add(child.id)
        elif isinstance(child, ast.Attribute):
            refs.add(child.attr)
        elif isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name:
                calls.add(name)
    return refs, calls


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _text_file_summary(rel: str, text: str, language: str) -> RepoFileSummary:
    headings = tuple(line.lstrip("# ").strip() for line in text.splitlines() if line.lstrip().startswith("#"))[:20]
    return RepoFileSummary(
        path=rel,
        language=language,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        lines=len(text.splitlines()),
        tokens=tuple(_top_terms(rel + "\n" + text, limit=40)),
        headings=headings,
    )


def _file_summary_from_dict(data: dict[str, Any]) -> RepoFileSummary:
    return RepoFileSummary(
        path=str(data.get("path") or ""),
        language=str(data.get("language") or ""),
        sha256=str(data.get("sha256") or ""),
        lines=int(data.get("lines") or 0),
        imports=tuple(str(item) for item in data.get("imports") or ()),
        symbols=tuple(_symbol_from_dict(item) for item in data.get("symbols") or () if isinstance(item, dict)),
        tokens=tuple(str(item) for item in data.get("tokens") or ()),
        headings=tuple(str(item) for item in data.get("headings") or ()),
    )


def _symbol_from_dict(data: dict[str, Any]) -> RepoSymbol:
    return RepoSymbol(
        name=str(data.get("name") or ""),
        kind=str(data.get("kind") or ""),
        path=str(data.get("path") or ""),
        line=int(data.get("line") or 1),
        end_line=int(data.get("end_line") or data.get("line") or 1),
        qualname=str(data.get("qualname") or ""),
        doc=str(data.get("doc") or ""),
        refs=tuple(str(item) for item in data.get("refs") or ()),
        calls=tuple(str(item) for item in data.get("calls") or ()),
    )


def _context_block(item: RepoFileSummary, hit: RepoMapHit) -> str:
    lines = [f"## {item.path}", f"score={hit.score}; reason={hit.reason}"]
    if item.imports:
        lines.append("imports: " + ", ".join(item.imports[:12]))
    if item.headings:
        lines.append("headings: " + " | ".join(item.headings[:8]))
    for symbol in item.symbols[:12]:
        doc = f" - {symbol.doc}" if symbol.doc else ""
        calls = f" calls={','.join(symbol.calls[:8])}" if symbol.calls else ""
        lines.append(f"- {symbol.kind} {symbol.qualname or symbol.name}:{symbol.line}-{symbol.end_line}{calls}{doc}")
    return "\n".join(lines) + "\n"


def _summary_terms(item: RepoFileSummary) -> list[str]:
    chunks = [item.path, item.language, " ".join(item.imports), " ".join(item.tokens), " ".join(item.headings)]
    for symbol in item.symbols:
        chunks.append(" ".join([symbol.name, symbol.qualname, symbol.kind, symbol.doc, " ".join(symbol.refs), " ".join(symbol.calls)]))
    return _tokens(" ".join(chunks))


def _aider_graph_scores(
    repo_map: RepoMap,
    *,
    chat_paths: Iterable[str] = (),
    mentioned_fnames: Iterable[str] = (),
    mentioned_idents: Iterable[str] = (),
) -> tuple[dict[str, float], dict[str, tuple[str, ...]]]:
    """Aider-style definition/reference graph rank, ported without networkx.

    The original Aider repo-map ranks definition tags by building a graph from
    references to definitions, then running PageRank. This stdlib version keeps
    that mechanism but uses Mako's AST summaries as its tag source.
    """

    files = [item.path for item in repo_map.files]
    if not files:
        return {}, {}
    chat = {_normalize_repo_path(path) for path in chat_paths}
    mentioned_files = {_normalize_repo_path(path) for path in mentioned_fnames}
    mentioned = set(mentioned_idents)
    mentioned.update(_tokens(" ".join(mentioned_idents)))

    defines: dict[str, set[str]] = defaultdict(set)
    references: dict[str, list[str]] = defaultdict(list)
    definition_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    personalization: dict[str, float] = {}
    default_personalization = 100.0 / len(files)

    for item in repo_map.files:
        current = 0.0
        if item.path in chat:
            current += default_personalization
        if item.path in mentioned_files or Path(item.path).name in mentioned_files:
            current = max(current, default_personalization)
        path_terms = set(_tokens(item.path))
        if path_terms & mentioned:
            current += default_personalization
        if current > 0:
            personalization[item.path] = current

        for symbol in item.symbols:
            for ident in _identifier_aliases(symbol.name, symbol.qualname):
                defines[ident].add(item.path)
                definition_names[(item.path, ident)].add(symbol.name)
            for ref in (*symbol.refs, *symbol.calls):
                for ident in _identifier_aliases(ref):
                    references[ident].append(item.path)
        for imported in item.imports:
            for ident in _identifier_aliases(imported):
                references[ident].append(item.path)

    if not references:
        references = {name: list(paths) for name, paths in defines.items()}

    edges: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for ident, definers in defines.items():
        if ident not in references:
            for definer in definers:
                edges[definer].append((definer, 0.1, ident))

    for ident in set(defines) & set(references):
        definers = defines[ident]
        multiplier = _aider_ident_multiplier(ident, mentioned, len(definers))
        for referencer, count in Counter(references[ident]).items():
            for definer in definers:
                weight = multiplier * math.sqrt(count)
                if referencer in chat:
                    weight *= 50.0
                edges[referencer].append((definer, weight, ident))

    for ident in mentioned & set(defines):
        for definer in defines[ident]:
            edges[definer].append((definer, 3.0, ident))

    if not edges:
        return {}, {}

    node_scores = _weighted_pagerank(files, edges, personalization)
    incoming_rank: dict[str, float] = defaultdict(float)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for source, outgoing in edges.items():
        total_weight = sum(weight for _dst, weight, _ident in outgoing)
        if total_weight <= 0:
            continue
        source_rank = node_scores.get(source, 0.0)
        for destination, weight, ident in outgoing:
            rank = source_rank * weight / total_weight
            incoming_rank[destination] += rank
            reasons[destination][ident] += rank

    scores: dict[str, float] = {}
    reason_payload: dict[str, tuple[str, ...]] = {}
    for path, score in incoming_rank.items():
        if path in chat:
            continue
        scores[path] = score
        reason_payload[path] = tuple(ident for ident, _rank in reasons[path].most_common(6))
    return scores, reason_payload


def _weighted_pagerank(
    nodes: list[str],
    edges: dict[str, list[tuple[str, float, str]]],
    personalization: dict[str, float],
) -> dict[str, float]:
    node_set = set(nodes) | set(edges)
    for outgoing in edges.values():
        node_set.update(dst for dst, _weight, _ident in outgoing)
    ordered = sorted(node_set)
    if not ordered:
        return {}
    if personalization:
        total_personalization = sum(personalization.get(node, 0.0) for node in ordered) or 1.0
        personal = {node: personalization.get(node, 0.0) / total_personalization for node in ordered}
    else:
        personal = {node: 1.0 / len(ordered) for node in ordered}
    ranks = {node: 1.0 / len(ordered) for node in ordered}
    for _ in range(PAGERANK_ITERATIONS):
        new_ranks = {node: (1.0 - PAGERANK_DAMPING) * personal[node] for node in ordered}
        dangling = sum(ranks[node] for node in ordered if not edges.get(node))
        if dangling:
            for node in ordered:
                new_ranks[node] += PAGERANK_DAMPING * dangling * personal[node]
        for source, outgoing in edges.items():
            total_weight = sum(weight for _dst, weight, _ident in outgoing)
            if total_weight <= 0:
                continue
            for destination, weight, _ident in outgoing:
                new_ranks[destination] += PAGERANK_DAMPING * ranks.get(source, 0.0) * weight / total_weight
        ranks = new_ranks
    return ranks


def _aider_ident_multiplier(ident: str, mentioned: set[str], definer_count: int) -> float:
    multiplier = 1.0
    is_snake = "_" in ident and any(char.isalpha() for char in ident)
    is_kebab = "-" in ident and any(char.isalpha() for char in ident)
    is_camel = any(char.isupper() for char in ident) and any(char.islower() for char in ident)
    if ident in mentioned:
        multiplier *= 10.0
    if (is_snake or is_kebab or is_camel) and len(ident) >= 8:
        multiplier *= 10.0
    if ident.startswith("_"):
        multiplier *= 0.1
    if definer_count > 5:
        multiplier *= 0.1
    return multiplier


def _identifier_aliases(*values: str) -> set[str]:
    aliases: set[str] = set()
    for value in values:
        if not value:
            continue
        text = str(value)
        aliases.add(text.lower())
        for part in re.split(r"[.\s:/\\]+", text):
            if part:
                aliases.add(part.lower())
        aliases.update(_tokens(text))
    return {alias for alias in aliases if len(alias) >= 2}


def _normalize_repo_path(path: str) -> str:
    return str(path).replace("\\", "/").strip("/")


def _symbol_terms(item: RepoFileSummary) -> set[str]:
    return set(_tokens(" ".join(symbol.qualname or symbol.name for symbol in item.symbols)))


def _import_terms(item: RepoFileSummary) -> set[str]:
    return set(_tokens(" ".join(item.imports)))


def _file_preview(item: RepoFileSummary) -> str:
    if item.symbols:
        return "; ".join(f"{symbol.kind} {symbol.qualname or symbol.name}:{symbol.line}" for symbol in item.symbols[:4])
    if item.headings:
        return "headings: " + " | ".join(item.headings[:4])
    return ", ".join(item.tokens[:12])


def _iter_repo_files(project: Path) -> list[Path]:
    return [
        path
        for path in sorted(project.rglob("*"))
        if path.is_file() and path.suffix.lower() in INDEXABLE_SUFFIXES and not _skip(path, project)
    ]


def _skip(path: Path, project: Path) -> bool:
    rel = path.relative_to(project)
    return any(part in SKIP_PARTS or part.startswith(".pytest_cache") for part in rel.parts)


def _rel(project: Path, path: Path) -> str:
    return str(path.relative_to(project)).replace("\\", "/")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text):
        tokens.append(token.lower())
        tokens.extend(part.lower() for part in re.sub(r"([a-z])([A-Z])", r"\1 \2", token).replace("_", " ").split() if len(part) >= 2)
    return [token for token in tokens if len(token) >= 2]


def _top_terms(text: str, *, limit: int) -> list[str]:
    counts = Counter(token for token in _tokens(text) if len(token) >= 3 and not token.isdigit())
    return [term for term, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]
