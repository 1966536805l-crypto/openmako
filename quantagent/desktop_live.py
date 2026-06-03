from __future__ import annotations

import json
import os
import time
from html import escape
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .branding import PRODUCT_NAME, PRIMARY_CLI
from .desktop_control import DesktopResult, desktop_dir, front_window, frontmost_app, screenshot
from .desktop_workflow import ax_snapshot
from .ux_status import UXApprovalStatus, UXToolStatus, build_ux_status


@dataclass(frozen=True)
class DesktopArtifactStatus:
    kind: str
    path: str
    updated_at: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopProbeStatus:
    name: str
    ok: bool
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopLiveState:
    project: str
    generated_at: str
    desktop_dir: str
    artifacts: tuple[DesktopArtifactStatus, ...] = ()
    approvals: tuple[UXApprovalStatus, ...] = ()
    tools: tuple[UXToolStatus, ...] = ()
    status: str = "idle"
    readiness: tuple[DesktopProbeStatus, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "generated_at": self.generated_at,
            "desktop_dir": self.desktop_dir,
            "status": self.status,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "approvals": [asdict(item) for item in self.approvals],
            "tools": [asdict(item) for item in self.tools],
            "readiness": [item.to_dict() for item in self.readiness],
        }


def build_desktop_live_state(
    project: str | Path,
    *,
    limit: int = 8,
    probe: bool = False,
    probe_network_url: str = "",
) -> DesktopLiveState:
    project_path = Path(project).expanduser().resolve(strict=False)
    directory = desktop_dir(project_path)
    ux = build_ux_status(project_path, task="desktop live", limit=limit, include_context_pack=False)
    artifacts = tuple(_scan_desktop_artifacts(directory, limit=limit))
    readiness = tuple(build_desktop_readiness_probes(project_path, include_permissions=probe, network_url=probe_network_url)) if probe or probe_network_url else ()
    has_blocker = bool(ux.approvals)
    failed_tools = [tool for tool in ux.tools if tool.tool.startswith("desktop.") and tool.status != "ok"]
    readiness_status = _readiness_status(readiness)
    status = (
        "blocked"
        if has_blocker or readiness_status == "blocked"
        else "warn"
        if failed_tools or readiness_status == "warn"
        else "active"
        if artifacts or readiness
        else "idle"
    )
    return DesktopLiveState(
        project=str(project_path),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        desktop_dir=str(directory),
        artifacts=artifacts,
        approvals=tuple(ux.approvals),
        tools=tuple(tool for tool in ux.tools if tool.tool.startswith("desktop.")),
        status=status,
        readiness=readiness,
    )


def render_desktop_live_state(state: DesktopLiveState, *, width: int = 100, color: bool = True) -> str:
    width = max(72, min(width, 160))
    palette = _Palette(color)
    lines: list[str] = []
    lines.append(palette.bold(f"{PRODUCT_NAME} Desktop Live [{state.status}]"))
    lines.append(_rule(width))
    lines.append(f"Project: {_shorten(state.project, width - 9)}")
    lines.append(f"Updated: {state.generated_at}")
    lines.append(f"Desktop artifacts: {_shorten(state.desktop_dir, width - 19)}")
    lines.append("")

    if state.readiness:
        lines.append(palette.title("Live Readiness"))
        for probe in state.readiness:
            marker = palette.ok(probe.status) if probe.ok else palette.warn(probe.status)
            lines.append(f"  [{marker}] {probe.name} - {_shorten(probe.summary, width - 24)}")
        lines.append("")

    lines.append(palette.title("Screen Artifacts"))
    if state.artifacts:
        for artifact in state.artifacts:
            lines.append(_artifact_line(artifact, width, palette))
    else:
        lines.append(f"  none yet. Try: {PRIMARY_CLI} desktop som --include-grid")
    lines.append("")

    lines.append(palette.title("Pending Approvals"))
    if state.approvals:
        for item in state.approvals[:6]:
            lines.append("  " + palette.warn(f"{item.approval_id} {item.tool} {item.action}") + _suffix(item.reason, width - 42))
    else:
        lines.append("  none")
    lines.append("")

    lines.append(palette.title("Recent Desktop Tools"))
    if state.tools:
        for item in state.tools[:8]:
            marker = palette.ok("ok") if item.status == "ok" else palette.warn(item.status)
            duration = f" {item.duration_ms}ms" if item.duration_ms is not None else ""
            approval = f" approval={item.approval_id}" if item.approval_id else ""
            summary = _shorten(item.summary, width - 32)
            lines.append(f"  [{marker}] {item.tool}{duration}{approval} - {summary}")
    else:
        lines.append("  none")
    lines.append("")

    lines.append(palette.title("Operator Commands"))
    commands = (
        f"{PRIMARY_CLI} desktop som --include-grid",
        f"{PRIMARY_CLI} desktop find \"Run\" --source all --refresh-som",
        f"{PRIMARY_CLI} desktop find-click \"Run\" --execute --reviewed --verify-after",
        f"{PRIMARY_CLI} approval --project PROJECT list",
    )
    for command in commands:
        lines.append("  " + command)
    lines.append(_rule(width))
    lines.append("Ctrl-C exits live view. Side-effect actions still require explicit reviewed execution.")
    return "\n".join(lines).rstrip() + "\n"


def render_desktop_live_json(state: DesktopLiveState) -> str:
    return json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_desktop_live_html(state: DesktopLiveState) -> str:
    status_class = "blocked" if state.status == "blocked" else ("warn" if state.status == "warn" else "ok")
    artifacts = "\n".join(_html_artifact_row(item) for item in state.artifacts) or "<tr><td colspan=\"4\">No screen artifacts yet.</td></tr>"
    approvals = "\n".join(
        f"<tr><td>{escape(item.approval_id)}</td><td>{escape(item.tool)}</td><td>{escape(item.action)}</td><td>{escape(item.reason)}</td></tr>"
        for item in state.approvals[:20]
    ) or "<tr><td colspan=\"4\">None</td></tr>"
    readiness = "\n".join(
        f"<tr><td>{escape(item.name)}</td><td><span class=\"badge {('ok' if item.ok else 'blocked')}\">{escape(item.status)}</span></td><td>{escape(item.summary)}</td></tr>"
        for item in state.readiness
    ) or "<tr><td colspan=\"3\">Not probed</td></tr>"
    tools = "\n".join(
        f"<tr><td>{escape(item.tool)}</td><td>{escape(item.status)}</td><td>{'' if item.duration_ms is None else item.duration_ms}</td><td>{escape(item.summary)}</td></tr>"
        for item in state.tools[:30]
    ) or "<tr><td colspan=\"4\">None</td></tr>"
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>{escape(PRODUCT_NAME)} Desktop Live</title>\n"
        "  <style>\n"
        "    :root{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#172026;background:#f6f7f8;}\n"
        "    body{margin:0;padding:24px;}\n"
        "    main{max-width:1180px;margin:0 auto;}\n"
        "    header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px;}\n"
        "    h1{font-size:24px;margin:0 0 8px;letter-spacing:0;}\n"
        "    h2{font-size:15px;margin:22px 0 8px;letter-spacing:0;text-transform:uppercase;color:#52616b;}\n"
        "    .meta{color:#52616b;font-size:13px;line-height:1.6;}\n"
        "    .badge{display:inline-block;border-radius:6px;padding:4px 8px;font-weight:700;font-size:12px;background:#e7ecf0;color:#172026;}\n"
        "    .badge.ok{background:#dcefe3;color:#14532d;}.badge.warn{background:#fff1c2;color:#7a4b00;}.badge.blocked{background:#ffe2df;color:#8f1d16;}\n"
        "    table{width:100%;border-collapse:collapse;background:white;border:1px solid #d9dee3;border-radius:8px;overflow:hidden;}\n"
        "    th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #edf0f2;font-size:13px;vertical-align:top;}\n"
        "    th{background:#eef2f5;color:#34424c;font-weight:700;}\n"
        "    tr:last-child td{border-bottom:0;}\n"
        "    code{font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;}\n"
        "  </style>\n"
        "</head>\n"
        "<body><main>\n"
        "  <header>\n"
        "    <div>\n"
        f"      <h1>{escape(PRODUCT_NAME)} Desktop Live</h1>\n"
        f"      <div class=\"meta\">Project: <code>{escape(state.project)}</code><br>Generated: {escape(state.generated_at)}<br>Artifacts: <code>{escape(state.desktop_dir)}</code></div>\n"
        "    </div>\n"
        f"    <span class=\"badge {status_class}\">{escape(state.status)}</span>\n"
        "  </header>\n"
        "  <h2>Readiness</h2><table><thead><tr><th>Probe</th><th>Status</th><th>Summary</th></tr></thead><tbody>\n"
        f"{readiness}\n"
        "  </tbody></table>\n"
        "  <h2>Screen Artifacts</h2><table><thead><tr><th>Kind</th><th>Updated</th><th>Summary</th><th>Path</th></tr></thead><tbody>\n"
        f"{artifacts}\n"
        "  </tbody></table>\n"
        "  <h2>Pending Approvals</h2><table><thead><tr><th>ID</th><th>Tool</th><th>Action</th><th>Reason</th></tr></thead><tbody>\n"
        f"{approvals}\n"
        "  </tbody></table>\n"
        "  <h2>Recent Desktop Tools</h2><table><thead><tr><th>Tool</th><th>Status</th><th>Duration ms</th><th>Summary</th></tr></thead><tbody>\n"
        f"{tools}\n"
        "  </tbody></table>\n"
        "</main></body></html>\n"
    )


def write_desktop_live_html(state: DesktopLiveState, output: str | Path | None = None) -> Path:
    if output is None:
        path = Path(state.desktop_dir) / "desktop_live.html"
    else:
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = Path(state.project) / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_desktop_live_html(state), encoding="utf-8")
    return path


def run_desktop_live(
    project: str | Path,
    *,
    interval: float = 1.0,
    limit: int = 8,
    once: bool = False,
    color: bool = True,
    probe: bool = False,
    probe_network_url: str = "",
    stream: TextIO | None = None,
) -> int:
    stream = stream or os.sys.stdout
    interval = max(0.2, min(float(interval), 10.0))
    try:
        while True:
            state = build_desktop_live_state(project, limit=limit, probe=probe, probe_network_url=probe_network_url)
            if not once:
                stream.write("\033[2J\033[H")
            stream.write(render_desktop_live_state(state, color=color and not once))
            stream.flush()
            if once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        stream.write("\n")
        stream.flush()
        return 130


def _html_artifact_row(item: DesktopArtifactStatus) -> str:
    return (
        "<tr>"
        f"<td>{escape(item.kind)}</td>"
        f"<td>{escape(item.updated_at)}</td>"
        f"<td>{escape(item.summary)}</td>"
        f"<td><code>{escape(item.path)}</code></td>"
        "</tr>"
    )


def build_desktop_readiness_probes(
    project: str | Path,
    *,
    include_permissions: bool = False,
    network_url: str = "",
    network_timeout: float = 3.0,
) -> list[DesktopProbeStatus]:
    project_path = Path(project).expanduser().resolve(strict=False)
    probes: list[DesktopProbeStatus] = []
    probes.append(_desktop_result_probe("frontmost_app", frontmost_app()))
    probes.append(_desktop_result_probe("front_window", front_window(), permission_kind="accessibility"))
    if include_permissions:
        probes.append(_desktop_result_probe("screenshot_permission", screenshot(project_path, name="live_probe_screenshot.png"), permission_kind="screen_recording"))
        probes.append(_desktop_result_probe("accessibility_snapshot", ax_snapshot(project_path, max_depth=1, limit=8, name="live_probe_ax.json"), permission_kind="accessibility"))
    if network_url:
        probes.append(_network_probe(network_url, timeout=network_timeout))
    return probes


def _desktop_result_probe(name: str, result: DesktopResult, *, permission_kind: str = "") -> DesktopProbeStatus:
    status = "ok" if result.ok else "failed"
    data = dict(result.data)
    if not result.ok and _permission_required(result):
        status = "permission_required"
        data["permission_kind"] = permission_kind or _permission_kind(result)
    return DesktopProbeStatus(name, result.ok, status, result.summary, data)


def _permission_required(result: DesktopResult) -> bool:
    text = " ".join([result.summary, json.dumps(result.data, ensure_ascii=False, default=str)]).lower()
    return any(
        marker in text
        for marker in (
            "permission is missing",
            "privacy_screen",
            "privacy_accessibility",
            "assistive access",
            "辅助访问",
            "screen recording",
            "could not create image from display",
            "-25211",
        )
    )


def _permission_kind(result: DesktopResult) -> str:
    text = " ".join([result.summary, json.dumps(result.data, ensure_ascii=False, default=str)]).lower()
    if "screen recording" in text or "screencapture" in text or "could not create image from display" in text:
        return "screen_recording"
    if "accessibility" in text or "assistive access" in text or "辅助访问" in text or "-25211" in text:
        return "accessibility"
    return "permission"


def _network_probe(url: str, *, timeout: float) -> DesktopProbeStatus:
    target = str(url or "").strip()
    if not target:
        return DesktopProbeStatus("network", True, "skipped", "network probe skipped")
    started = time.monotonic()
    try:
        request = Request(target, method="HEAD", headers={"User-Agent": f"{PRODUCT_NAME}/desktop-live-probe"})
        with urlopen(request, timeout=max(0.5, min(float(timeout), 30.0))) as response:
            status_code = int(getattr(response, "status", 0) or 0)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        ok = 200 <= status_code < 500
        return DesktopProbeStatus("network", ok, "ok" if ok else "failed", f"network probe HTTP {status_code}", {"url": target, "status_code": status_code, "duration_ms": elapsed_ms})
    except HTTPError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        status_code = int(getattr(exc, "code", 0) or 0)
        ok = 400 <= status_code < 500
        return DesktopProbeStatus("network", ok, "ok" if ok else "failed", f"network probe HTTP {status_code}", {"url": target, "status_code": status_code, "duration_ms": elapsed_ms})
    except (OSError, TimeoutError, URLError) as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return DesktopProbeStatus("network", False, "network_failed", f"network probe failed: {type(exc).__name__}: {exc}", {"url": target, "duration_ms": elapsed_ms, "error_type": type(exc).__name__})


def _readiness_status(probes: Sequence[DesktopProbeStatus]) -> str:
    if any(probe.status == "permission_required" for probe in probes):
        return "blocked"
    if any(not probe.ok for probe in probes):
        return "warn"
    return "ok" if probes else ""


def _scan_desktop_artifacts(directory: Path, *, limit: int) -> list[DesktopArtifactStatus]:
    if not directory.exists():
        return []
    candidates = [path for path in directory.iterdir() if path.is_file() and _artifact_kind(path)]
    ordered = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)
    return [_artifact_status(path) for path in ordered[:limit]]


def _artifact_kind(path: Path) -> str:
    name = path.name
    if name.startswith("som_") and path.suffix == ".json":
        return "som"
    if name.startswith("ocr_") and path.suffix == ".json":
        return "ocr"
    if name.startswith("ax_") and path.suffix == ".json":
        return "ax"
    if name.startswith("find_") and path.suffix == ".json":
        return "find"
    if name.startswith("run_") and path.suffix == ".json":
        return "run"
    if name.endswith(".grid.json"):
        return "grid"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"} and (name.startswith("screenshot_") or name.startswith("som_shot_") or name.startswith("verify_") or name.startswith("grid_")):
        return "image"
    return ""


def _artifact_status(path: Path) -> DesktopArtifactStatus:
    kind = _artifact_kind(path)
    updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    data: dict[str, Any] = {}
    summary = path.name
    if path.suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            data = _artifact_data(kind, payload)
            summary = _artifact_summary(kind, payload, path.name)
        except Exception as exc:
            data = {"error": f"{type(exc).__name__}: {exc}"}
            summary = f"{path.name} unreadable"
    else:
        data = {"bytes": path.stat().st_size}
        summary = f"{path.name} image {path.stat().st_size} bytes"
    return DesktopArtifactStatus(kind=kind, path=str(path), updated_at=updated_at, summary=summary, data=data)


def _artifact_data(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "som":
        return {
            "targets": len(payload.get("targets", []) if isinstance(payload.get("targets"), list) else []),
            "image_path": payload.get("image_path", ""),
            "errors": payload.get("errors", []),
        }
    if kind == "ocr":
        return {
            "blocks": len(payload.get("blocks", []) if isinstance(payload.get("blocks"), list) else []),
            "image_path": payload.get("image_path", ""),
        }
    if kind == "ax":
        return {"elements": len(payload.get("elements", []) if isinstance(payload.get("elements"), list) else []), "app": payload.get("app", "")}
    if kind == "find":
        return {"query": payload.get("query", ""), "hits": len(payload.get("hits", []) if isinstance(payload.get("hits"), list) else []), "errors": payload.get("errors", [])}
    if kind == "run":
        return {"status": payload.get("status", ""), "ok": payload.get("ok"), "results": len(payload.get("results", []) if isinstance(payload.get("results"), list) else [])}
    if kind == "grid":
        return {"cells": len(payload.get("cells", []) if isinstance(payload.get("cells"), list) else []), "image_path": payload.get("image_path", "")}
    return {}


def _artifact_summary(kind: str, payload: dict[str, Any], fallback: str) -> str:
    data = _artifact_data(kind, payload)
    if kind == "som":
        return f"SoM targets={data.get('targets', 0)} image={Path(str(data.get('image_path') or '')).name}"
    if kind == "ocr":
        return f"OCR blocks={data.get('blocks', 0)} image={Path(str(data.get('image_path') or '')).name}"
    if kind == "ax":
        return f"AX app={data.get('app') or '-'} elements={data.get('elements', 0)}"
    if kind == "find":
        return f"find query={data.get('query')!r} hits={data.get('hits', 0)}"
    if kind == "run":
        return f"run status={data.get('status') or '-'} ok={data.get('ok')} results={data.get('results', 0)}"
    if kind == "grid":
        return f"grid cells={data.get('cells', 0)} image={Path(str(data.get('image_path') or '')).name}"
    return fallback


def _artifact_line(artifact: DesktopArtifactStatus, width: int, palette: "_Palette") -> str:
    kind = palette.badge(artifact.kind or "artifact")
    summary = _shorten(artifact.summary, width - 34)
    return f"  {kind} {artifact.updated_at} - {summary}"


def _rule(width: int) -> str:
    return "-" * width


def _suffix(text: str, limit: int) -> str:
    if not text:
        return ""
    return " - " + _shorten(text, max(10, limit))


def _shorten(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"


class _Palette:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def bold(self, text: str) -> str:
        return self._wrap(text, "1")

    def title(self, text: str) -> str:
        return self._wrap(text, "1;36")

    def ok(self, text: str) -> str:
        return self._wrap(text, "32")

    def warn(self, text: str) -> str:
        return self._wrap(text, "33")

    def badge(self, text: str) -> str:
        return self._wrap(f"{text:>5}", "36")

    def _wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"
