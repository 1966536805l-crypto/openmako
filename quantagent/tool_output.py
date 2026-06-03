from __future__ import annotations

import os
import re
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


# Adapted from NousResearch/hermes-agent (MIT): preserve oversized tool output
# on disk and send the model a bounded preview plus a read-back path.
DEFAULT_MAX_CHARS = 50_000
DEFAULT_PREVIEW_CHARS = 6_000
DEFAULT_TURN_BUDGET_CHARS = 120_000
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"
DEFAULT_TURN_OUTPUT_KEYS = ("content", "output", "stdout", "stderr")


@dataclass(frozen=True)
class ToolOutputBudget:
    max_chars: int = DEFAULT_MAX_CHARS
    preview_chars: int = DEFAULT_PREVIEW_CHARS
    turn_budget_chars: int = DEFAULT_TURN_BUDGET_CHARS


@dataclass(frozen=True)
class ToolResultArtifact:
    artifact_id: str
    tool: str
    path: str
    sha256: str
    chars: int
    preview: str
    collapsed: bool
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "tool": self.tool,
            "path": self.path,
            "sha256": self.sha256,
            "chars": self.chars,
            "preview": self.preview,
            "collapsed": self.collapsed,
            "created_at_ms": self.created_at_ms,
        }


@dataclass(frozen=True)
class _OutputSlot:
    result_index: int
    path: tuple[str, ...]
    content: str


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def tool_output_budget() -> ToolOutputBudget:
    return ToolOutputBudget(
        max_chars=_positive_int_env("QUANTAGENT_TOOL_OUTPUT_MAX_CHARS", DEFAULT_MAX_CHARS),
        preview_chars=_positive_int_env("QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS", DEFAULT_PREVIEW_CHARS),
        turn_budget_chars=_positive_int_env("QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS", DEFAULT_TURN_BUDGET_CHARS),
    )


def generate_preview(content: str, max_chars: int) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False
    preview = content[:max_chars]
    last_newline = preview.rfind("\n")
    if last_newline > max_chars // 2:
        preview = preview[: last_newline + 1]
    return preview, True


def _safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value[:80].strip("._-") or "tool_output"


def tool_output_dir(project: Path) -> Path:
    return project / ".quantagent" / "tool_results"


def tool_result_manifest_path(project: Path) -> Path:
    return tool_output_dir(project) / "manifest.json"


def persist_tool_output(project: Path, content: str, tool_name: str, output_id: str) -> Path:
    directory = tool_output_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_safe_id(tool_name)}_{_safe_id(output_id)}.txt"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)
    return path


def store_tool_result_artifact(
    project: Path,
    content: str,
    *,
    tool_name: str,
    output_id: str,
    collapsed: bool | None = None,
    preview_chars: int | None = None,
) -> ToolResultArtifact:
    budget = tool_output_budget()
    preview, has_more = generate_preview(content, preview_chars or budget.preview_chars)
    path = persist_tool_output(project, content, tool_name, output_id)
    artifact = ToolResultArtifact(
        artifact_id=f"{_safe_id(tool_name)}-{_safe_id(output_id)}",
        tool=tool_name,
        path=str(path),
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        chars=len(content),
        preview=preview,
        collapsed=has_more if collapsed is None else collapsed,
        created_at_ms=int(time.time() * 1000),
    )
    _append_manifest(project, artifact)
    return artifact


def persisted_output_message(preview: str, has_more: bool, original_size: int, path: Path) -> str:
    kib = original_size / 1024
    size = f"{kib / 1024:.1f} MB" if kib >= 1024 else f"{kib:.1f} KB"
    suffix = "\n..." if has_more else ""
    return (
        f"{PERSISTED_OUTPUT_TAG}\n"
        f"This tool result was too large ({original_size:,} characters, {size}).\n"
        f"Full output saved to: {path}\n"
        "Use file_read/read_preview on that path when exact details are needed.\n\n"
        f"Preview (first {len(preview)} chars):\n"
        f"{preview}{suffix}\n"
        f"{PERSISTED_OUTPUT_CLOSING_TAG}"
    )


def maybe_persist_tool_output(
    project: Path,
    content: str,
    tool_name: str,
    output_id: str,
    *,
    threshold: int | None = None,
    preview_chars: int | None = None,
) -> str:
    budget = tool_output_budget()
    max_chars = threshold if threshold is not None else budget.max_chars
    if len(content) <= max_chars:
        return content
    preview, has_more = generate_preview(content, preview_chars or budget.preview_chars)
    artifact = store_tool_result_artifact(project, content, tool_name=tool_name, output_id=output_id, collapsed=has_more, preview_chars=preview_chars)
    return persisted_output_message(preview, has_more, len(content), Path(artifact.path))


def collapse_tool_result(
    project: Path,
    content: str,
    *,
    tool_name: str,
    output_id: str,
    threshold: int | None = None,
    preview_chars: int | None = None,
) -> tuple[str, ToolResultArtifact | None]:
    budget = tool_output_budget()
    max_chars = threshold if threshold is not None else budget.max_chars
    if len(content) <= max_chars:
        return content, None
    artifact = store_tool_result_artifact(project, content, tool_name=tool_name, output_id=output_id, collapsed=True, preview_chars=preview_chars)
    message = persisted_output_message(artifact.preview, artifact.collapsed, artifact.chars, Path(artifact.path))
    return message, artifact


def enforce_turn_tool_output_budget(
    results: list[Any],
    project: Path,
    *,
    budget_chars: int | None = None,
    preview_chars: int | None = None,
    content_keys: Sequence[str] = DEFAULT_TURN_OUTPUT_KEYS,
) -> list[Any]:
    """Collapse the largest tool outputs until a turn fits the aggregate budget.

    ``results`` is mutated in place and returned. String results are replaced
    directly. Dict results can expose output strings at top level or under a
    ``data`` dict; when a field is collapsed, the artifact metadata is appended
    to that result's ``artifacts`` list so replay code keeps the path and
    preview alongside the bounded output.
    """
    budget = tool_output_budget()
    max_total = budget.turn_budget_chars if budget_chars is None else max(0, budget_chars)
    effective_preview_chars = preview_chars if preview_chars is not None else budget.preview_chars
    slots = _collect_output_slots(results, content_keys)
    total_chars = sum(len(slot.content) for slot in slots)
    if total_chars <= max_total:
        return results

    candidates = [slot for slot in slots if slot.content and PERSISTED_OUTPUT_TAG not in slot.content]
    candidates.sort(key=lambda slot: len(slot.content), reverse=True)

    for slot in candidates:
        if total_chars <= max_total:
            break
        content = _get_slot_content(results, slot)
        if not content or PERSISTED_OUTPUT_TAG in content:
            continue
        tool_name = _slot_tool_name(results[slot.result_index], slot)
        output_id = _slot_output_id(slot, content)
        if not _persisted_replacement_is_smaller(project, content, tool_name, output_id, effective_preview_chars):
            continue
        replacement, artifact = collapse_tool_result(
            project,
            content,
            tool_name=tool_name,
            output_id=output_id,
            threshold=0,
            preview_chars=effective_preview_chars,
        )
        if artifact is None:
            continue
        _set_slot_content(results, slot, replacement)
        _append_slot_artifact(results[slot.result_index], slot, artifact)
        total_chars += len(replacement) - len(content)

    return results


def load_tool_result_manifest(project: Path) -> list[ToolResultArtifact]:
    path = tool_result_manifest_path(project)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    results: list[ToolResultArtifact] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        results.append(
            ToolResultArtifact(
                artifact_id=str(item.get("artifact_id") or ""),
                tool=str(item.get("tool") or ""),
                path=str(item.get("path") or ""),
                sha256=str(item.get("sha256") or ""),
                chars=int(item.get("chars") or 0),
                preview=str(item.get("preview") or ""),
                collapsed=bool(item.get("collapsed")),
                created_at_ms=int(item.get("created_at_ms") or 0),
            )
        )
    return results


def _append_manifest(project: Path, artifact: ToolResultArtifact) -> None:
    path = tool_result_manifest_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [item.to_dict() for item in load_tool_result_manifest(project)]
    records.append(artifact.to_dict())
    path.write_text(json.dumps(records[-500:], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _collect_output_slots(results: list[Any], content_keys: Sequence[str]) -> list[_OutputSlot]:
    slots: list[_OutputSlot] = []
    keys = tuple(content_keys)
    for index, result in enumerate(results):
        if isinstance(result, str):
            slots.append(_OutputSlot(index, (), result))
            continue
        if not isinstance(result, dict):
            continue
        for key in keys:
            value = result.get(key)
            if isinstance(value, str):
                slots.append(_OutputSlot(index, (key,), value))
        data = result.get("data")
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, str):
                    slots.append(_OutputSlot(index, ("data", key), value))
    return slots


def _get_slot_content(results: list[Any], slot: _OutputSlot) -> str:
    result = results[slot.result_index]
    if not slot.path:
        return result if isinstance(result, str) else ""
    if not isinstance(result, dict):
        return ""
    if len(slot.path) == 1:
        value = result.get(slot.path[0])
        return value if isinstance(value, str) else ""
    if len(slot.path) == 2 and slot.path[0] == "data" and isinstance(result.get("data"), dict):
        value = result["data"].get(slot.path[1])
        return value if isinstance(value, str) else ""
    return ""


def _set_slot_content(results: list[Any], slot: _OutputSlot, content: str) -> None:
    result = results[slot.result_index]
    if not slot.path:
        results[slot.result_index] = content
        return
    if not isinstance(result, dict):
        return
    if len(slot.path) == 1:
        result[slot.path[0]] = content
        return
    if len(slot.path) == 2 and slot.path[0] == "data" and isinstance(result.get("data"), dict):
        result["data"][slot.path[1]] = content


def _append_slot_artifact(result: Any, slot: _OutputSlot, artifact: ToolResultArtifact) -> None:
    if not isinstance(result, dict):
        return
    target = result
    if slot.path and slot.path[0] == "data" and isinstance(result.get("data"), dict):
        target = result["data"]
    artifacts = target.get("artifacts")
    if artifacts is None:
        target["artifacts"] = [artifact.to_dict()]
    elif isinstance(artifacts, list):
        artifacts.append(artifact.to_dict())


def _slot_tool_name(result: Any, slot: _OutputSlot) -> str:
    field_name = "_".join(slot.path) if slot.path else "content"
    if isinstance(result, dict):
        base = str(result.get("name") or result.get("tool") or "turn_tool_output")
    else:
        base = "turn_tool_output"
    return f"{_safe_id(base)}_{_safe_id(field_name)}"


def _slot_output_id(slot: _OutputSlot, content: str) -> str:
    field_name = "_".join(slot.path) if slot.path else "content"
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"turn_{slot.result_index}_{_safe_id(field_name)}_{digest}"


def _persisted_replacement_is_smaller(project: Path, content: str, tool_name: str, output_id: str, preview_chars: int) -> bool:
    preview, has_more = generate_preview(content, preview_chars)
    expected_path = tool_output_dir(project) / f"{_safe_id(tool_name)}_{_safe_id(output_id)}.txt"
    replacement = persisted_output_message(preview, has_more, len(content), expected_path)
    return len(replacement) < len(content)
