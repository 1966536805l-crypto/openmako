from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .agent_context_runtime import AgentRuntimeContext
from .tool_execution import ToolExecutionResult
from .tool_transcript import ToolCallTranscript, load_tool_transcript, list_tool_transcripts


@dataclass(frozen=True)
class ToolCallPhase:
    name: str
    status: str
    summary: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCallTrace:
    invocation_id: str
    tool: str
    status: str
    mode: str = ""
    profile: str = ""
    approval_id: str = ""
    checkpoint_id: str = ""
    error_kind: str = ""
    duration_ms: int | None = None
    phases: tuple[ToolCallPhase, ...] = ()
    args: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    output_preview: str = ""
    context_summary: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phases"] = [phase.to_dict() for phase in self.phases]
        return payload


def trace_from_execution(
    result: ToolExecutionResult,
    *,
    context: AgentRuntimeContext | None = None,
    args: dict[str, Any] | None = None,
) -> ToolCallTrace:
    phases = [
        ToolCallPhase(
            "mode_context",
            "ok" if context is None or context.ok else "warn",
            _context_summary(context) if context is not None else "no runtime context attached",
            data=context.to_dict() if context is not None else {},
        ),
        ToolCallPhase(
            "permission",
            "ok" if result.policy.get("allowed", result.ok) else "blocked",
            str(result.policy.get("summary") or result.policy.get("policy_reason") or "policy evaluated"),
            data=result.policy,
        ),
        ToolCallPhase(
            "execution",
            "ok" if result.ok else "failed",
            result.summary,
            data={
                "blocked": result.blocked,
                "error_kind": result.error_kind,
                "duration_ms": result.duration_ms,
                "approval_id": result.approval_id,
                "invocation_id": result.invocation_id,
            },
        ),
    ]
    return ToolCallTrace(
        invocation_id=result.invocation_id or str(result.data.get("invocation_id") or ""),
        tool=result.name,
        status="ok" if result.ok else "failed",
        mode=context.mode if context is not None else str(result.policy.get("profile") or ""),
        profile=context.profile if context is not None else str(result.policy.get("profile") or ""),
        approval_id=result.approval_id or str(result.data.get("approval_id") or ""),
        checkpoint_id=str(result.data.get("checkpoint_id") or result.policy.get("checkpoint_id") or ""),
        error_kind=result.error_kind,
        duration_ms=result.duration_ms,
        phases=tuple(phases),
        args=args or {},
        policy=result.policy,
        output_preview=_output_preview(result),
        context_summary=_context_summary(context),
    )


def load_tool_call_trace(project: str | Path, invocation_id: str) -> ToolCallTrace:
    return trace_from_transcript(load_tool_transcript(project, invocation_id))


def list_tool_call_traces(project: str | Path, *, limit: int = 30) -> list[ToolCallTrace]:
    return [trace_from_transcript(item) for item in list_tool_transcripts(project, limit=limit)]


def trace_from_transcript(transcript: ToolCallTranscript) -> ToolCallTrace:
    phases = [
        ToolCallPhase("permission", "ok" if transcript.status == "ok" else "failed", "stored policy envelope", data=transcript.policy),
        ToolCallPhase(
            "execution",
            "ok" if transcript.status == "ok" else "failed",
            transcript.summary,
            data={"error_kind": transcript.error_kind, "duration_ms": transcript.duration_ms},
        ),
    ]
    return ToolCallTrace(
        invocation_id=transcript.invocation_id,
        tool=transcript.tool,
        status=transcript.status,
        mode=str(transcript.policy.get("profile") or ""),
        profile=str(transcript.policy.get("profile") or ""),
        approval_id=transcript.approval_id,
        checkpoint_id=transcript.checkpoint_id,
        error_kind=transcript.error_kind,
        duration_ms=transcript.duration_ms,
        phases=tuple(phases),
        args=transcript.args,
        policy=transcript.policy,
        output_preview=transcript.output_preview,
        context_summary="loaded from runtime transcript store",
    )


def render_tool_call_traces(traces: Iterable[ToolCallTrace]) -> str:
    items = list(traces)
    if not items:
        return "No tool-call traces.\n"
    lines = ["# Tool-Call Traces", ""]
    for trace in items:
        mode = f" mode={trace.mode}" if trace.mode else ""
        approval = f" approval={trace.approval_id}" if trace.approval_id else ""
        checkpoint = f" checkpoint={trace.checkpoint_id}" if trace.checkpoint_id else ""
        duration = f" {trace.duration_ms}ms" if trace.duration_ms is not None else ""
        lines.append(f"- {trace.invocation_id}: {trace.tool} [{trace.status}]{mode}{duration}{approval}{checkpoint} - {trace.context_summary or trace.error_kind or '-'}")
    return "\n".join(lines) + "\n"


def render_tool_call_trace(trace: ToolCallTrace) -> str:
    lines = [
        "# Tool-Call Trace",
        "",
        f"- invocation_id: {trace.invocation_id or '-'}",
        f"- tool: {trace.tool}",
        f"- status: {trace.status}",
        f"- mode: {trace.mode or '-'}",
        f"- profile: {trace.profile or '-'}",
        f"- approval_id: {trace.approval_id or '-'}",
        f"- checkpoint_id: {trace.checkpoint_id or '-'}",
        f"- duration_ms: {trace.duration_ms if trace.duration_ms is not None else '-'}",
        f"- error_kind: {trace.error_kind or '-'}",
        f"- context: {trace.context_summary or '-'}",
        "",
        "## Phases",
        "",
    ]
    for phase in trace.phases:
        lines.append(f"- [{phase.status}] {phase.name}: {phase.summary}")
    lines.extend(
        [
            "",
            "## Policy",
            "```json",
            json.dumps(trace.policy, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Args",
            "```json",
            json.dumps(trace.args, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    if trace.output_preview:
        lines.extend(["", "## Output Preview", trace.output_preview])
    return "\n".join(lines) + "\n"


def _context_summary(context: AgentRuntimeContext | None) -> str:
    if context is None:
        return ""
    warn_count = sum(1 for section in context.sections if section.status == "warn")
    return f"mode={context.mode}, sections={len(context.sections)}, warn={warn_count}, route={context.route.confidence:.2f}"


def _output_preview(result: ToolExecutionResult) -> str:
    pieces = []
    for key in ("stdout", "stderr", "report", "markdown", "preview", "text_preview"):
        value = result.data.get(key)
        if isinstance(value, str) and value:
            pieces.append(f"{key}:\n{value}")
    if not pieces:
        pieces.append(result.summary)
    text = "\n\n".join(pieces).strip()
    if len(text) <= 3000:
        return text
    return text[:2920].rstrip() + "\n\n[trimmed]"
