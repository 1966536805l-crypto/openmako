from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .runtime_store import ToolInvocationRecord, get_tool_invocation, list_tool_invocations


@dataclass(frozen=True)
class ToolCallTranscript:
    invocation_id: str
    tool: str
    status: str
    args_hash: str
    args: dict[str, Any]
    policy: dict[str, Any]
    approval_id: str = ""
    checkpoint_id: str = ""
    output_preview: str = ""
    summary: str = ""
    error_kind: str = ""
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_tool_transcript(project: str | Path, invocation_id: str) -> ToolCallTranscript:
    record = get_tool_invocation(project, invocation_id)
    if record is None:
        raise KeyError(f"tool invocation not found: {invocation_id}")
    return _from_record(record)


def list_tool_transcripts(project: str | Path, *, limit: int = 30) -> list[ToolCallTranscript]:
    return [_from_record(record) for record in list_tool_invocations(project, limit=limit)]


def render_tool_transcripts(transcripts: list[ToolCallTranscript]) -> str:
    if not transcripts:
        return "No tool-call transcripts.\n"
    lines = ["# Tool-Call Transcripts", ""]
    for item in transcripts:
        approval = f" approval={item.approval_id}" if item.approval_id else ""
        checkpoint = f" checkpoint={item.checkpoint_id}" if item.checkpoint_id else ""
        elapsed = f" {item.duration_ms}ms" if item.duration_ms is not None else ""
        lines.append(f"- {item.invocation_id}: {item.tool} [{item.status}]{elapsed}{approval}{checkpoint} - {item.summary}")
    return "\n".join(lines) + "\n"


def render_tool_transcript(transcript: ToolCallTranscript) -> str:
    lines = [
        "# Tool-Call Transcript",
        "",
        f"- invocation_id: {transcript.invocation_id}",
        f"- tool: {transcript.tool}",
        f"- status: {transcript.status}",
        f"- args_hash: {transcript.args_hash}",
        f"- approval_id: {transcript.approval_id or '-'}",
        f"- checkpoint_id: {transcript.checkpoint_id or '-'}",
        f"- duration_ms: {transcript.duration_ms if transcript.duration_ms is not None else '-'}",
        f"- error_kind: {transcript.error_kind or '-'}",
        f"- summary: {transcript.summary}",
        "",
        "## Policy",
        "```json",
        json.dumps(transcript.policy, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Args",
        "```json",
        json.dumps(transcript.args, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    if transcript.output_preview:
        lines.extend(["", "## Output Preview", transcript.output_preview])
    return "\n".join(lines) + "\n"


def _from_record(record: ToolInvocationRecord) -> ToolCallTranscript:
    return ToolCallTranscript(
        invocation_id=record.invocation_id,
        tool=record.tool,
        status=record.status,
        args_hash=record.args_hash,
        args=_json(record.args_json),
        policy=_json(record.policy_json),
        approval_id=record.approval_id or "",
        checkpoint_id=record.checkpoint_id or "",
        output_preview=record.output_preview,
        summary=record.summary,
        error_kind=record.error_kind,
        duration_ms=record.duration_ms,
    )


def _json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
