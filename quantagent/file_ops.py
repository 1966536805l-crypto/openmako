from __future__ import annotations

import difflib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PREVIEW_CHARS = 8000
DEFAULT_DIFF_LINES = 240
DEFAULT_SEARCH_RESULTS = 50


@dataclass(frozen=True)
class FileOpResult:
    ok: bool
    summary: str
    path: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class PathSafetyError(ValueError):
    pass


def _real(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, parent: Path) -> bool:
    path_real = _real(path)
    parent_real = _real(parent)
    return path_real == parent_real or parent_real in path_real.parents


def _display_path(project: Path, path: Path) -> str:
    try:
        return str(_real(path).relative_to(_real(project)))
    except ValueError:
        return str(path)


def resolve_project_path(project: Path, path: str | Path) -> Path:
    """Resolve a user path and require it to stay inside the project."""
    project_real = _real(project)
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = project_real / target
    target_real = _real(target)
    if not _inside(target_real, project_real):
        raise PathSafetyError(f"path escapes project: {path}")
    return target_real


def _read_project_text(project: Path, path: str | Path) -> tuple[Path, str]:
    target = resolve_project_path(project, path)
    if not target.exists():
        raise FileNotFoundError(_display_path(project, target))
    if not target.is_file():
        raise IsADirectoryError(_display_path(project, target))
    return target, target.read_text(encoding="utf-8", errors="replace")


def _trim_lines(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]) + "\n[diff trimmed]", True


def read_preview(project: Path, path: str | Path, max_chars: int = DEFAULT_PREVIEW_CHARS) -> FileOpResult:
    try:
        target, text = _read_project_text(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"read failed: {exc}")

    preview = text[: max(0, max_chars)]
    trimmed = len(text) > len(preview)
    rel = _display_path(project, target)
    return FileOpResult(
        True,
        f"read {rel}" + (" (preview trimmed)" if trimmed else ""),
        rel,
        {
            "preview": preview,
            "chars": len(text),
            "preview_chars": len(preview),
            "trimmed": trimmed,
        },
    )


def unified_diff_preview(
    project: Path,
    path: str | Path,
    new_text: str,
    context: int = 3,
    max_lines: int = DEFAULT_DIFF_LINES,
) -> FileOpResult:
    try:
        target, old_text = _read_project_text(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"diff failed: {exc}")

    rel = _display_path(project, target)
    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=max(0, context),
            lineterm="\n",
        )
    )
    if not diff:
        return FileOpResult(True, f"no changes for {rel}", rel, {"diff": "", "changed": False, "trimmed": False})

    preview, trimmed = _trim_lines(diff, max(1, max_lines))
    return FileOpResult(
        True,
        f"diff preview for {rel}" + (" (trimmed)" if trimmed else ""),
        rel,
        {"diff": preview, "changed": True, "trimmed": trimmed},
    )


def diff_exact_replace_preview(
    project: Path,
    path: str | Path,
    old: str,
    new: str,
    expected_count: int = 1,
    max_lines: int = DEFAULT_DIFF_LINES,
) -> FileOpResult:
    try:
        target, text = _read_project_text(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"replace preview failed: {exc}")

    count = text.count(old)
    rel = _display_path(project, target)
    if old == "":
        return FileOpResult(False, "replace preview failed: old text is empty", rel)
    if count != expected_count:
        return FileOpResult(
            False,
            f"replace preview failed: expected {expected_count} occurrence(s), found {count}",
            rel,
            {"occurrences": count},
        )
    return unified_diff_preview(project, target, text.replace(old, new, expected_count), max_lines=max_lines)


def replace_exact(
    project: Path,
    path: str | Path,
    old: str,
    new: str,
    expected_count: int = 1,
) -> FileOpResult:
    try:
        target, text = _read_project_text(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"replace failed: {exc}")

    rel = _display_path(project, target)
    if old == "":
        return FileOpResult(False, "replace failed: old text is empty", rel)
    count = text.count(old)
    if count != expected_count:
        return FileOpResult(
            False,
            f"replace failed: expected {expected_count} occurrence(s), found {count}",
            rel,
            {"occurrences": count},
        )

    new_text = text.replace(old, new, expected_count)
    target.write_text(new_text, encoding="utf-8")
    return FileOpResult(True, f"replaced {count} occurrence(s) in {rel}", rel, {"occurrences": count})


def write_text(project: Path, path: str | Path, text: str, create_parents: bool = True) -> FileOpResult:
    try:
        target = resolve_project_path(project, path)
    except ValueError as exc:
        return FileOpResult(False, f"write failed: {exc}")

    rel = _display_path(project, target)
    try:
        if target.exists() and not target.is_file():
            return FileOpResult(False, f"write failed: target is not a file: {rel}", rel)
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        return FileOpResult(False, f"write failed: {exc}", rel)

    return FileOpResult(True, f"wrote {rel}", rel, {"chars": len(text)})


def _search_with_rg(
    project: Path,
    pattern: str,
    paths: list[Path],
    max_results: int,
    glob: str | None,
    case_sensitive: bool,
) -> FileOpResult:
    rg = shutil.which("rg")
    if not rg:
        return FileOpResult(False, "search failed: rg not found")

    command = [rg, "--json", "--color", "never"]
    if not case_sensitive:
        command.append("--ignore-case")
    if glob:
        command.extend(["--glob", glob])
    command.extend(["--", pattern])
    command.extend(str(path) for path in paths)

    completed = subprocess.run(command, cwd=_real(project), text=True, capture_output=True, timeout=30)
    if completed.returncode not in {0, 1}:
        return FileOpResult(False, completed.stderr.strip() or "search failed")

    matches: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if len(matches) >= max_results:
            break
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "match":
            continue
        data = payload.get("data") or {}
        path_text = ((data.get("path") or {}).get("text") or "")
        line_text = ((data.get("lines") or {}).get("text") or "").rstrip("\n")
        matches.append(
            {
                "path": _display_path(project, Path(path_text)),
                "line": data.get("line_number"),
                "preview": line_text,
            }
        )

    summary = f"{len(matches)} match(es)" + (" (truncated)" if len(matches) >= max_results else "")
    return FileOpResult(True, summary, data={"matches": matches, "truncated": len(matches) >= max_results})


def search_text(
    project: Path,
    pattern: str,
    path: str | Path = ".",
    max_results: int = DEFAULT_SEARCH_RESULTS,
    glob: str | None = None,
    case_sensitive: bool = True,
) -> FileOpResult:
    if not pattern:
        return FileOpResult(False, "search failed: pattern is empty")
    try:
        target = resolve_project_path(project, path)
    except ValueError as exc:
        return FileOpResult(False, f"search failed: {exc}")
    if not target.exists():
        return FileOpResult(False, f"search failed: path not found: {_display_path(project, target)}")

    result = _search_with_rg(project, pattern, [target], max(1, max_results), glob, case_sensitive)
    if result.ok:
        return result

    return result
