from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import platform
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .code_index import editor_diagnostics, render_editor_diagnostics, render_related_files, render_code_search_hits, related_files, search_code_index
from .diff_review import create_diff_review, render_diff_review_report
from .memory_store import MemoryStore, render_memories
from .project_rules import match_project_rules, render_project_rules
from .task_runtime import read_task_output, refresh_runtime_tasks


REF_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_-]*)(?::(\"[^\"]+\"|'[^']+'|\S+))?")


@dataclass(frozen=True)
class ContextProviderRequest:
    provider: str
    argument: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ContextProviderResult:
    provider: str
    title: str
    body: str
    ok: bool = True
    sources: list[str] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


ALIASES = {
    "currentfile": "file",
    "current-file": "file",
    "codebase": "search",
    "repo_map": "repo-map",
    "repomap": "repo-map",
    "gitdiff": "diff",
    "git-diff": "diff",
}


def parse_context_refs(text: str) -> list[ContextProviderRequest]:
    refs: list[ContextProviderRequest] = []
    for match in REF_RE.finditer(text):
        provider = _normalize_provider(match.group(1))
        argument = _clean_arg(match.group(2) or "")
        refs.append(ContextProviderRequest(provider, argument))
    return refs


def gather_context_providers(
    project: str | Path,
    refs: Iterable[ContextProviderRequest | str],
    *,
    limit: int = 8,
) -> list[ContextProviderResult]:
    project_path = Path(project).expanduser().resolve(strict=False)
    requests = [_coerce_request(item) for item in refs]
    results: list[ContextProviderResult] = []
    for request in requests:
        try:
            results.append(_run_provider(project_path, request, limit=limit))
        except Exception as exc:
            results.append(
                ContextProviderResult(
                    request.provider,
                    f"@{request.provider}",
                    f"{type(exc).__name__}: {exc}",
                    ok=False,
                    meta={"argument": request.argument},
                )
            )
    return results


def render_context_provider_results(results: Iterable[ContextProviderResult]) -> str:
    rows = list(results)
    if not rows:
        return "No context providers requested.\n"
    lines = ["# Context Providers", ""]
    for result in rows:
        mark = "ok" if result.ok else "failed"
        lines.extend([f"## [{mark}] {result.title}", "", result.body.rstrip() or "(empty)", ""])
        if result.sources:
            lines.append("sources: " + ", ".join(result.sources[:8]))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _run_provider(project: Path, request: ContextProviderRequest, *, limit: int) -> ContextProviderResult:
    provider = request.provider
    arg = request.argument
    if provider == "diff":
        paths = _split_paths(arg)
        report = create_diff_review(project, paths or None, max_diff_lines=180)
        return ContextProviderResult("diff", "@diff", render_diff_review_report(report, include_diff=True), sources=report.paths)
    if provider == "file":
        return _file_provider(project, arg)
    if provider == "folder":
        return _folder_provider(project, arg or ".")
    if provider == "tree":
        return _tree_provider(project, arg or ".", limit=limit * 40)
    if provider == "search":
        hits = search_code_index(project, arg, limit=limit, rebuild=False) if arg else []
        return ContextProviderResult("search", f"@search:{arg}", render_code_search_hits(hits), sources=[hit.path for hit in hits])
    if provider == "problems":
        diagnostics = editor_diagnostics(project, limit=limit * 20)
        return ContextProviderResult("problems", "@problems", render_editor_diagnostics(diagnostics), sources=[item.path for item in diagnostics])
    if provider == "repo-map":
        return _repo_map_provider(project, arg, limit=limit * 4)
    if provider == "terminal":
        return _terminal_provider(project, arg)
    if provider == "rules":
        paths = _split_paths(arg)
        rules = match_project_rules(project, paths)
        return ContextProviderResult("rules", f"@rules:{arg}" if arg else "@rules", render_project_rules(rules), sources=[rule.source for rule in rules])
    if provider == "memory":
        return _memory_provider(project, arg, limit=limit)
    if provider == "docs":
        return _docs_provider(project, arg)
    if provider == "os":
        return ContextProviderResult("os", "@os", _os_context())
    if provider == "related":
        hits = related_files(project, arg, limit=limit) if arg else []
        return ContextProviderResult("related", f"@related:{arg}", render_related_files(hits), sources=[hit.path for hit in hits])
    raise ValueError(f"unknown context provider: @{provider}")


def _file_provider(project: Path, arg: str) -> ContextProviderResult:
    if not arg:
        raise ValueError("@file requires a path")
    path = _inside_project_path(project, arg)
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = _rel(project, path)
    return ContextProviderResult("file", f"@file:{rel}", _trim(text, 12_000), sources=[rel])


def _folder_provider(project: Path, arg: str) -> ContextProviderResult:
    root = _inside_project_path(project, arg)
    if not root.is_dir():
        raise ValueError(f"not a folder: {arg}")
    lines: list[str] = []
    sources: list[str] = []
    for path in _iter_files(root, project)[:80]:
        rel = _rel(project, path)
        sources.append(rel)
        lines.append(f"- {rel} ({path.stat().st_size} bytes)")
    return ContextProviderResult("folder", f"@folder:{_rel(project, root)}", "\n".join(lines) or "(empty)", sources=sources)


def _tree_provider(project: Path, arg: str, *, limit: int) -> ContextProviderResult:
    root = _inside_project_path(project, arg)
    if not root.is_dir():
        raise ValueError(f"not a folder: {arg}")
    lines = []
    for path in _iter_files(root, project)[:limit]:
        rel = _rel(project, path)
        depth = max(0, len(Path(rel).parts) - 1)
        lines.append("  " * depth + "- " + Path(rel).name)
    return ContextProviderResult("tree", f"@tree:{_rel(project, root)}", "\n".join(lines) or "(empty)")


def _repo_map_provider(project: Path, arg: str, *, limit: int) -> ContextProviderResult:
    del arg
    from .code_index import build_code_index, index_path, load_code_index, write_code_index

    path = index_path(project)
    index = load_code_index(project) if path.exists() else build_code_index(project)
    if not path.exists():
        write_code_index(project, index)
    lines: list[str] = []
    sources: list[str] = []
    for chunk in index.chunks:
        if not chunk.symbols:
            continue
        sources.append(chunk.path)
        lines.append(f"- {chunk.path}:{chunk.start_line}-{chunk.end_line} symbols={', '.join(chunk.symbols[:8])}")
        if len(lines) >= limit:
            break
    return ContextProviderResult("repo-map", "@repo-map", "\n".join(lines) or "No symbols found.", sources=sources)


def _terminal_provider(project: Path, arg: str) -> ContextProviderResult:
    tasks = refresh_runtime_tasks(project)
    task = next((item for item in tasks if item.id == arg), None) if arg else None
    if task is None:
        candidates = [item for item in reversed(tasks) if item.output_path or item.error_path]
        task = candidates[0] if candidates else None
    if task is None:
        return ContextProviderResult("terminal", "@terminal", "No terminal task output found.", ok=True)
    output = read_task_output(project, task.id, tail_chars=8000)
    return ContextProviderResult("terminal", f"@terminal:{task.id}", output or "(empty)", sources=[task.output_path, task.error_path])


def _memory_provider(project: Path, arg: str, *, limit: int) -> ContextProviderResult:
    store = MemoryStore(project)
    try:
        entries = store.search(arg, limit=limit) if arg else store.recent(limit=limit)
        return ContextProviderResult("memory", f"@memory:{arg}" if arg else "@memory", render_memories(entries), sources=[f"memory:{entry.id}" for entry in entries])
    finally:
        store.close()


def _docs_provider(project: Path, arg: str) -> ContextProviderResult:
    if not arg:
        index = project / ".quantagent" / "docs.json"
        if not index.exists():
            return ContextProviderResult("docs", "@docs", "No .quantagent/docs.json configured.")
        return ContextProviderResult("docs", "@docs", _trim(index.read_text(encoding="utf-8", errors="replace"), 12_000), sources=[_rel(project, index)])
    path = _inside_project_path(project, arg)
    return ContextProviderResult("docs", f"@docs:{_rel(project, path)}", _trim(path.read_text(encoding="utf-8", errors="replace"), 16_000), sources=[_rel(project, path)])


def _os_context() -> str:
    payload = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    try:
        result = subprocess.run(["uname", "-a"], capture_output=True, text=True, check=False, timeout=2)
        payload["uname"] = result.stdout.strip()
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:236", exc)
        pass
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _coerce_request(item: ContextProviderRequest | str) -> ContextProviderRequest:
    if isinstance(item, ContextProviderRequest):
        return item
    parsed = parse_context_refs(item)
    if parsed:
        return parsed[0]
    if ":" in item:
        provider, argument = item.split(":", 1)
        return ContextProviderRequest(_normalize_provider(provider.lstrip("@")), _clean_arg(argument))
    return ContextProviderRequest(_normalize_provider(item.lstrip("@")), "")


def _normalize_provider(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    return ALIASES.get(key, key)


def _clean_arg(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[:1] == text[-1:] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _split_paths(arg: str) -> list[str]:
    if not arg:
        return []
    return [item.strip() for item in re.split(r",", arg) if item.strip()]


def _inside_project_path(project: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    target = path if path.is_absolute() else project / path
    target = target.resolve(strict=False)
    project_real = project.resolve(strict=False)
    try:
        target.relative_to(project_real)
    except ValueError as exc:
        raise ValueError(f"path is outside project: {raw}") from exc
    return target


def _iter_files(root: Path, project: Path) -> list[Path]:
    skipped = {".git", ".quantagent", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.resolve(strict=False).relative_to(project.resolve(strict=False))
        if any(part in skipped or part.startswith(".pytest_cache") for part in rel.parts):
            continue
        rows.append(path)
    return rows


def _rel(project: Path, path: Path | str) -> str:
    target = Path(path)
    try:
        return str(target.resolve(strict=False).relative_to(project.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 24)].rstrip() + "\n[context trimmed]\n"
