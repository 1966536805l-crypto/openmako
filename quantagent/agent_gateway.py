from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from .channel_gateway import list_channel_bindings, list_channel_gateway_events
from .runtime_store import list_runtime_queue_items
from .skills import list_skill_registry


@dataclass(frozen=True)
class AgentGatewayStatus:
    project: str
    generated_at: str
    bindings: tuple[dict[str, Any], ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    queues: tuple[dict[str, Any], ...] = ()
    skills: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "generated_at": self.generated_at,
            "bindings": list(self.bindings),
            "events": list(self.events),
            "queues": list(self.queues),
            "skills": list(self.skills),
            "warnings": list(self.warnings),
        }


def build_agent_gateway_status(
    project: str | Path,
    *,
    event_limit: int = 50,
    queue_limit: int = 50,
    skill_limit: int = 50,
) -> AgentGatewayStatus:
    project_path = Path(project).expanduser().resolve(strict=False)
    warnings: list[str] = []
    bindings = tuple(binding.to_dict() for binding in list_channel_bindings(project_path))
    events = tuple(event.to_dict() for event in list_channel_gateway_events(project_path, limit=event_limit))
    queue_names = ["channel_gateway", *(f"channel_gateway:{binding['agent_id']}" for binding in bindings if binding.get("agent_id") and binding.get("agent_id") != "main")]
    queues: list[dict[str, Any]] = []
    for queue in sorted(set(queue_names)):
        try:
            items = list_runtime_queue_items(project_path, queue=queue, limit=queue_limit)
        except Exception as exc:
            warnings.append(f"queue {queue} unavailable: {type(exc).__name__}: {exc}")
            continue
        queues.append(
            {
                "queue": queue,
                "items": [item.to_dict() for item in items],
                "count": len(items),
            }
        )
    skills = tuple(record.to_dict() for record in list_skill_registry(project_path)[: max(1, int(skill_limit))])
    return AgentGatewayStatus(
        project=str(project_path),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        bindings=bindings,
        events=events,
        queues=tuple(queues),
        skills=skills,
        warnings=tuple(warnings),
    )


def render_agent_gateway_json(status: AgentGatewayStatus) -> str:
    return json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_agent_gateway_html(status: AgentGatewayStatus) -> str:
    payload = status.to_dict()
    bindings = payload["bindings"]
    queues = payload["queues"]
    events = payload["events"][-20:]
    skills = payload["skills"][:30]
    rows = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Mako Agent Gateway</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;background:#f7f7f4;color:#222}",
        "header{padding:18px 24px;background:#1f2933;color:white}",
        "main{padding:20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}",
        "section{background:white;border:1px solid #ddd;border-radius:8px;padding:14px}",
        "h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px}",
        "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #eee;padding:6px;text-align:left;vertical-align:top}",
        "code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}",
        ".muted{color:#667085}.bad{color:#b42318}.ok{color:#027a48}",
        "</style></head><body>",
        f"<header><h1>Mako Agent Gateway</h1><div class=\"muted\">{escape(payload['project'])} · {escape(payload['generated_at'])}</div></header>",
        "<main>",
        _table_section("Bindings", ("channel", "sender", "owner_key", "agent_id"), bindings),
        _queue_section(queues),
        _table_section("Recent Events", ("event_type", "status", "channel", "sender"), events),
        _table_section("Skills", ("name", "source", "approved", "license"), skills),
        "</main></body></html>",
    ]
    return "\n".join(rows) + "\n"


def write_agent_gateway_html(status: AgentGatewayStatus, output_path: str | Path) -> str:
    path = Path(output_path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_agent_gateway_html(status), encoding="utf-8")
    return str(path)


def _table_section(title: str, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    out = [f"<section><h2>{escape(title)}</h2>"]
    if not rows:
        out.append("<div class=\"muted\">none</div></section>")
        return "".join(out)
    out.append("<table><thead><tr>")
    out.extend(f"<th>{escape(column)}</th>" for column in columns)
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for column in columns:
            value = row.get(column, "")
            klass = "ok" if column == "approved" and value else "bad" if column == "approved" else ""
            out.append(f"<td class=\"{klass}\">{escape(str(value))}</td>")
        out.append("</tr>")
    out.append("</tbody></table></section>")
    return "".join(out)


def _queue_section(queues: list[dict[str, Any]]) -> str:
    out = ["<section><h2>Queues</h2>"]
    if not queues:
        return "<section><h2>Queues</h2><div class=\"muted\">none</div></section>"
    for queue in queues:
        out.append(f"<h3><code>{escape(str(queue.get('queue') or ''))}</code> <span class=\"muted\">{int(queue.get('count') or 0)}</span></h3>")
        items = queue.get("items") or []
        if not items:
            out.append("<div class=\"muted\">empty</div>")
            continue
        out.append("<table><thead><tr><th>task_id</th><th>status</th><th>task</th></tr></thead><tbody>")
        for item in items[:20]:
            out.append(
                "<tr>"
                f"<td><code>{escape(str(item.get('task_id') or item.get('id') or ''))}</code></td>"
                f"<td>{escape(str(item.get('status') or ''))}</td>"
                f"<td>{escape(str(item.get('task') or ''))}</td>"
                "</tr>"
            )
        out.append("</tbody></table>")
    out.append("</section>")
    return "".join(out)
