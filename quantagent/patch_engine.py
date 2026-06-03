from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .file_ops import DEFAULT_DIFF_LINES, FileOpResult, resolve_project_path


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    text: str


def _display_path(project: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(Path(project).expanduser().resolve(strict=False)))
    except ValueError:
        return str(path)


def _read_file(project: Path, path: str | Path) -> tuple[Path, str, str]:
    target = resolve_project_path(project, path)
    if not target.exists():
        raise FileNotFoundError(_display_path(project, target))
    if not target.is_file():
        raise IsADirectoryError(_display_path(project, target))
    return target, target.read_text(encoding="utf-8", errors="replace"), _display_path(project, target)


def _trim_lines(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]) + "\n[diff trimmed]", True


def _diff_for_text(rel: str, old_text: str, new_text: str, context: int, max_lines: int) -> tuple[str, bool, bool]:
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
        return "", False, False
    preview, trimmed = _trim_lines(diff, max(1, max_lines))
    return preview, True, trimmed


def _matching_offsets(text: str, old: str) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        index = text.find(old, start)
        if index < 0:
            return offsets
        offsets.append(index)
        start = index + max(1, len(old))


def _offsets_with_context(text: str, offsets: list[int], old: str, before: str | None, after: str | None) -> list[int]:
    matches: list[int] = []
    for offset in offsets:
        before_ok = before is None or text[:offset].endswith(before)
        after_ok = after is None or text[offset + len(old) :].startswith(after)
        if before_ok and after_ok:
            matches.append(offset)
    return matches


def _planned_replace(
    text: str,
    old: str,
    new: str,
    expected_count: int,
    before: str | None,
    after: str | None,
) -> tuple[bool, str, str, dict[str, Any]]:
    if old == "":
        return False, "old text is empty", text, {}

    offsets = _matching_offsets(text, old)
    if before is not None or after is not None:
        contextual_offsets = _offsets_with_context(text, offsets, old, before, after)
        if len(contextual_offsets) != expected_count:
            return (
                False,
                f"expected {expected_count} contextual occurrence(s), found {len(contextual_offsets)}",
                text,
                {"occurrences": len(offsets), "contextual_occurrences": len(contextual_offsets)},
            )
        offset_set = set(contextual_offsets)
        pieces: list[str] = []
        cursor = 0
        replaced = 0
        for offset in offsets:
            if offset not in offset_set:
                continue
            pieces.append(text[cursor:offset])
            pieces.append(new)
            cursor = offset + len(old)
            replaced += 1
        pieces.append(text[cursor:])
        return True, f"planned {replaced} contextual replacement(s)", "".join(pieces), {
            "occurrences": len(offsets),
            "contextual_occurrences": replaced,
        }

    if len(offsets) != expected_count:
        return (
            False,
            f"expected {expected_count} occurrence(s), found {len(offsets)}",
            text,
            {"occurrences": len(offsets)},
        )
    return True, f"planned {len(offsets)} replacement(s)", text.replace(old, new, expected_count), {
        "occurrences": len(offsets)
    }


def snapshot_file(project: Path, path: str | Path) -> FileOpResult:
    try:
        _target, text, rel = _read_file(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"snapshot failed: {exc}")
    snapshot = FileSnapshot(rel, text)
    return FileOpResult(True, f"snapshot captured for {rel}", rel, {"snapshot": snapshot, "chars": len(text)})


def restore_snapshot(project: Path, snapshot: FileSnapshot) -> FileOpResult:
    try:
        target = resolve_project_path(project, snapshot.path)
        if target.exists() and not target.is_file():
            return FileOpResult(False, f"restore failed: target is not a file: {snapshot.path}", snapshot.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snapshot.text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"restore failed: {exc}", snapshot.path)
    return FileOpResult(True, f"restored {snapshot.path}", snapshot.path, {"chars": len(snapshot.text)})


def preview_replace(
    project: Path,
    path: str | Path,
    old: str,
    new: str,
    *,
    before: str | None = None,
    after: str | None = None,
    expected_count: int = 1,
    context: int = 3,
    max_lines: int = DEFAULT_DIFF_LINES,
) -> FileOpResult:
    try:
        _target, text, rel = _read_file(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"replace preview failed: {exc}")

    ok, summary, new_text, data = _planned_replace(text, old, new, expected_count, before, after)
    if not ok:
        return FileOpResult(False, f"replace preview failed: {summary}", rel, data)

    diff, changed, trimmed = _diff_for_text(rel, text, new_text, context, max_lines)
    data.update({"diff": diff, "changed": changed, "trimmed": trimmed})
    return FileOpResult(True, f"replace preview for {rel}", rel, data)


def apply_replace(
    project: Path,
    path: str | Path,
    old: str,
    new: str,
    *,
    before: str | None = None,
    after: str | None = None,
    expected_count: int = 1,
    context: int = 3,
    max_lines: int = DEFAULT_DIFF_LINES,
) -> FileOpResult:
    try:
        target, text, rel = _read_file(project, path)
    except (OSError, ValueError) as exc:
        return FileOpResult(False, f"replace failed: {exc}")

    ok, summary, new_text, data = _planned_replace(text, old, new, expected_count, before, after)
    if not ok:
        return FileOpResult(False, f"replace failed: {summary}", rel, data)

    snapshot = FileSnapshot(rel, text)
    diff, changed, trimmed = _diff_for_text(rel, text, new_text, context, max_lines)
    data.update({"snapshot": snapshot, "diff": diff, "changed": changed, "trimmed": trimmed})
    try:
        target.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        target.write_text(text, encoding="utf-8")
        return FileOpResult(False, f"replace failed and restored snapshot: {exc}", rel, data)

    return FileOpResult(True, f"replaced in {rel}: {summary}", rel, data)
