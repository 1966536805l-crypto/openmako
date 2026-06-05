from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import time
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .desktop_agent import default_stop_file
from .desktop_control import DesktopResult, desktop_dir, screenshot, _image_size
from .desktop_daemon_policy import authorize_daemon_action, classify_goal_risk
from .desktop_daemon_evidence import write_daemon_failure_autopsy
from .desktop_workflow import (
    DesktopElement,
    DesktopStep,
    DesktopTextBlock,
    SomTarget,
    _execute_step,
    ax_snapshot,
    build_grid_payload_for_image,
    build_som_targets,
    load_ax_elements,
    load_ocr_blocks,
    ocr_image,
    search_url,
)
from .exception_audit import audit_suppressed_exception
from .gui_patterns import GuiTarget, classify_gui_action
from .query_runtime import QueryRuntime
from .trajectory import record_action, record_observation


CONTROL_ACTIONS = {"activate", "open", "click", "grid-click", "som-click", "move", "type", "hotkey"}
PREACTION_REVALIDATE_ACTIONS = {"click", "move", "type", "hotkey"}
MAX_CENTER_DRIFT_PX = 4.0
MAX_BBOX_DRIFT_PX = 4
ACTION_LOCK_ACTIONS = CONTROL_ACTIONS
ACTION_LOCK_TIMEOUT_SECONDS = 60.0
ACTION_LOCK_POLL_SECONDS = 0.05
_SESSION_ACTION_THREAD_LOCK = threading.RLock()
HIGH_RISK_RE = re.compile(
    r"(转账|付款|支付|下单|买入|卖出|交易|提现|充值|购买|银行卡|密码|验证码|身份证|"
    r"发消息|发送消息|删除|格式化|rm\s+-rf|"
    r"\b(pay|purchase|transfer|trade|buy|sell|delete|format|password|otp|2fa)\b)",
    re.IGNORECASE,
)
SUBMIT_ACTION_RE = re.compile(
    r"(发送|提交|发布|回复|评论|确认|"
    r"\b(send|submit|post|publish|reply|comment|confirm)\b)",
    re.IGNORECASE,
)
SUBMIT_HOTKEYS = {"return", "enter"}
SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)(['\"\s:=]+)[^,'\"\s}]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
)
CLICK_RE = re.compile(r"(?:点击|点|click)\s*[:：]?\s*(.+)", re.IGNORECASE)
COORD_RE = re.compile(r"^\s*(\d{1,5})\s*[,， ]\s*(\d{1,5})\s*$")
TYPE_RE = re.compile(r"(?:输入|type)\s+(.+)", re.IGNORECASE)
HOTKEY_RE = re.compile(r"(?:快捷键|hotkey|按)\s+([a-z0-9+,\- ]{1,80})", re.IGNORECASE)
SEARCH_RE = re.compile(r"(?:搜索|搜|search)\s+(.+)", re.IGNORECASE)
OPEN_RE = re.compile(r"(?:打开|启动|open)\s+([A-Za-z][A-Za-z0-9 ._-]{1,60})", re.IGNORECASE)
TEXT_INPUT_ROLE_RE = re.compile(r"(text\s*field|textfield|textarea|search\s*field|searchfield|combo\s*box|combobox)", re.IGNORECASE)


def _redact_sensitive_text(value: object) -> str:
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: "".join(group or "" for group in match.groups()) + "[REDACTED]" if match.groups() else "[REDACTED]", text)
    return text


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if re.search(r"(?i)(password|secret|token|api[_-]?key|otp|2fa)", str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_payload(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_payload(item) for item in value)
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    return value


@dataclass(frozen=True)
class DesktopToken:
    token_id: str
    text: str
    role: str
    source: str
    bbox: tuple[int, int, int, int] | None = None
    center: tuple[int, int] | None = None
    clickable: bool = False
    confidence: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["text"] = _redact_sensitive_payload(payload["text"])
        payload["raw"] = _redact_sensitive_payload(payload["raw"])
        if self.bbox:
            payload["bbox"] = list(self.bbox)
        if self.center:
            payload["center"] = list(self.center)
        payload["target_hash"] = _token_hash(self)
        return payload


@dataclass(frozen=True)
class DesktopTokenization:
    ok: bool
    status: str
    summary: str
    image_path: str
    width: int
    height: int
    tokens: tuple[DesktopToken, ...]
    errors: tuple[str, ...] = ()
    sources: dict[str, Any] = field(default_factory=dict)
    path: str = ""
    observation_id: str = ""
    screen_hash: str = ""
    created_at: str = ""
    front_app: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": _redact_sensitive_text(self.summary),
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "tokens": [token.to_payload() for token in self.tokens],
            "errors": _redact_sensitive_payload(list(self.errors)),
            "sources": _redact_sensitive_payload(self.sources),
            "path": self.path,
            "observation_id": self.observation_id,
            "screen_hash": self.screen_hash,
            "created_at": self.created_at,
            "front_app": _redact_sensitive_text(self.front_app),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class DesktopDecision:
    ok: bool
    status: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    target_id: str = ""
    reason: str = ""
    requires_review: bool = False
    needs: tuple[str, ...] = ()
    confidence: float = 0.0
    step: DesktopStep | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "action": self.action,
            "args": _redact_sensitive_payload(self.args),
            "target_id": self.target_id,
            "reason": _redact_sensitive_text(self.reason),
            "requires_review": self.requires_review,
            "needs": list(self.needs),
            "confidence": self.confidence,
            "step": _redact_sensitive_payload(self.step.to_payload()) if self.step else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class DesktopDaemonRecord:
    step: int
    phase: str
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return _redact_sensitive_payload(asdict(self))


@dataclass(frozen=True)
class DesktopDaemonResult:
    ok: bool
    status: str
    summary: str
    goal: str
    records: tuple[DesktopDaemonRecord, ...]
    results: tuple[DesktopResult, ...]
    query_events_path: str
    trajectory_path: str
    stop_file: str
    state_path: str
    autopsy_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": _redact_sensitive_text(self.summary),
            "goal": _redact_sensitive_text(self.goal),
            "records": [record.to_payload() for record in self.records],
            "results": [_redact_sensitive_payload(asdict(result)) for result in self.results],
            "query_events_path": self.query_events_path,
            "trajectory_path": self.trajectory_path,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
            "autopsy_path": self.autopsy_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class DesktopActionVerification:
    ok: bool
    status: str
    summary: str
    tokenization: DesktopTokenization | None = None
    data: dict[str, Any] = field(default_factory=dict)


def desktop_intelligence_dir(project: str | Path) -> Path:
    directory = desktop_dir(Path(project)) / "intelligence"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def latest_desktop_tokenization(project: str | Path) -> Path | None:
    directory = desktop_intelligence_dir(project)
    pointer = directory / "latest_tokenize.json"
    if pointer.exists():
        return pointer
    snapshots = sorted(directory.glob("tokenize_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def desktop_action_lock_path() -> Path:
    uid = str(os.getuid()) if hasattr(os, "getuid") else "nouid"
    return Path(tempfile.gettempdir()) / f"quantagent_desktop_action_{uid}.lock"


def load_desktop_tokenization(path: str | Path) -> DesktopTokenization:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return tokenization_from_payload(payload)


def tokenization_from_payload(payload: dict[str, Any]) -> DesktopTokenization:
    tokens: list[DesktopToken] = []
    for index, raw in enumerate(payload.get("tokens", [])):
        if not isinstance(raw, dict):
            continue
        tokens.append(_token_from_payload(raw, index))
    return DesktopTokenization(
        ok=bool(payload.get("ok", True)),
        status=str(payload.get("status") or ("ok" if tokens else "empty")),
        summary=str(payload.get("summary") or f"{len(tokens)} desktop token(s)"),
        image_path=str(payload.get("image_path") or ""),
        width=int(payload.get("width") or 0),
        height=int(payload.get("height") or 0),
        tokens=tuple(tokens),
        errors=tuple(str(item) for item in payload.get("errors", []) if item),
        sources=dict(payload.get("sources") or {}),
        path=str(payload.get("path") or ""),
        observation_id=str(payload.get("observation_id") or ""),
        screen_hash=str(payload.get("screen_hash") or ""),
        created_at=str(payload.get("created_at") or ""),
        front_app=str(payload.get("front_app") or ""),
    )


def build_desktop_tokenization(
    project: str | Path,
    *,
    image_path: str | Path | None = None,
    include_ax: bool = True,
    include_ocr: bool = True,
    include_som: bool = True,
    include_grid: bool = False,
    cols: int = 12,
    rows: int = 8,
    limit: int = 240,
    name: str | None = None,
    skip_screenshot_if_ax_only: bool = False,
) -> DesktopTokenization:
    project_path = Path(project).expanduser().resolve(strict=False)
    errors: list[str] = []
    sources: dict[str, Any] = {}

    image = _resolve_image(project_path, image_path)
    if image is None:
        if skip_screenshot_if_ax_only and _ax_only_tokenization_requested(include_ax, include_ocr, include_som, include_grid):
            sources["screenshot"] = {"skipped": True, "reason": "ax_only_tokenization"}
        else:
            shot = screenshot(project_path, name=f"tokenize_shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            sources["screenshot"] = shot.data
            if not shot.ok:
                errors.append(shot.summary)
                return _write_tokenization(
                    project_path,
                    DesktopTokenization(False, "failed", f"tokenize screenshot failed: {shot.summary}", "", 0, 0, (), tuple(errors), sources),
                    name=name,
                )
            image = Path(str(shot.data["path"]))
    elif not image.exists():
        errors.append(f"image not found: {image}")
        return _write_tokenization(
            project_path,
            DesktopTokenization(False, "failed", f"image not found: {image}", str(image), 0, 0, (), tuple(errors), sources),
            name=name,
        )

    width = height = 0
    if image is not None:
        try:
            width, height = _image_size(image)
        except Exception as exc:
            errors.append(f"image size failed: {type(exc).__name__}: {exc}")

    ax_elements: list[DesktopElement] = []
    ocr_blocks: list[DesktopTextBlock] = []
    grid_payload: dict[str, Any] | None = None
    som_targets: list[SomTarget] = []
    cached_ax_tokens: list[DesktopToken] = []

    if include_ax:
        try:
            ax = ax_snapshot(project_path)
        except Exception as exc:
            summary = f"AX snapshot exception: {type(exc).__name__}: {exc}"
            sources["ax"] = {"status": "exception", "error_type": type(exc).__name__, "summary": summary}
            errors.append(summary)
        else:
            sources["ax"] = ax.data | {"ok": ax.ok, "summary": ax.summary}
            if ax.ok and isinstance(ax.data.get("path"), str):
                try:
                    ax_elements = load_ax_elements(Path(str(ax.data["path"])))
                except Exception as exc:
                    errors.append(f"AX load failed: {type(exc).__name__}: {exc}")
            else:
                errors.append(ax.summary)
        if not ax_elements and errors:
            cached_ax_tokens = _cached_ax_tokens(project_path, errors, sources)

    if include_ocr:
        try:
            ocr = ocr_image(project_path, image)
        except Exception as exc:
            summary = f"OCR exception: {type(exc).__name__}: {exc}"
            sources["ocr"] = {"status": "exception", "error_type": type(exc).__name__, "summary": summary}
            errors.append(summary)
        else:
            sources["ocr"] = ocr.data | {"ok": ocr.ok, "summary": ocr.summary}
            if ocr.ok and isinstance(ocr.data.get("path"), str):
                try:
                    ocr_blocks = load_ocr_blocks(Path(str(ocr.data["path"])))
                except Exception as exc:
                    errors.append(f"OCR load failed: {type(exc).__name__}: {exc}")
            else:
                errors.append(ocr.summary)

    if include_grid and width > 0 and height > 0:
        grid_payload = build_grid_payload_for_image(image, width, height, cols=cols, rows=rows)
        sources["grid"] = {"cols": grid_payload.get("cols"), "rows": grid_payload.get("rows"), "cells": len(grid_payload.get("cells", []))}

    if include_som and width > 0 and height > 0:
        try:
            som_targets = build_som_targets(
                image_path=image,
                width=width,
                height=height,
                ax_elements=ax_elements,
                ocr_blocks=ocr_blocks,
                grid_payload=grid_payload,
                include_grid=include_grid,
                limit=limit,
            )
            sources["som"] = {"targets": len(som_targets), "derived": True}
        except Exception as exc:
            errors.append(f"SoM build failed: {type(exc).__name__}: {exc}")

    raw_tokens: list[DesktopToken] = []
    raw_tokens.extend(tokens_from_ax(ax_elements))
    raw_tokens.extend(cached_ax_tokens)
    raw_tokens.extend(tokens_from_ocr(ocr_blocks))
    if grid_payload:
        raw_tokens.extend(tokens_from_grid(grid_payload))
    raw_tokens.extend(tokens_from_som(som_targets))
    tokens = dedupe_desktop_tokens(raw_tokens, limit=limit)
    status = "ok" if tokens else "empty"
    image_label = str(image) if image is not None else "ax-only observation"
    summary = f"{len(tokens)} desktop token(s) from {image_label}"
    created_at = datetime.now().isoformat(timespec="seconds")
    screen_hash = _file_sha256(image) if image is not None else ""
    observation_id = _observation_id(image, screen_hash, created_at) if image is not None else _source_observation_id(tokens, created_at)
    return _write_tokenization(
        project_path,
        DesktopTokenization(
            bool(tokens),
            status,
            summary,
            str(image or ""),
            width,
            height,
            tuple(tokens),
            tuple(errors),
            sources,
            observation_id=observation_id,
            screen_hash=screen_hash,
            created_at=created_at,
            front_app=_front_app_from_sources(sources),
        ),
        name=name,
    )


def _cached_ax_tokens(project: Path, errors: list[str], sources: dict[str, Any]) -> list[DesktopToken]:
    latest = latest_desktop_tokenization(project)
    if latest is None:
        return []
    try:
        cached = load_desktop_tokenization(latest)
    except Exception as exc:
        errors.append(f"AX fallback cache load failed: {type(exc).__name__}: {exc}")
        return []
    tokens = [token for token in cached.tokens if token.source == "ax"]
    if not tokens:
        return []
    recovered: list[DesktopToken] = []
    for token in tokens:
        raw = dict(token.raw)
        raw.setdefault("recovered_from", "cached_ax")
        raw.setdefault("cached_observation_id", cached.observation_id)
        raw.setdefault("cached_token_path", str(latest))
        recovered.append(
            DesktopToken(
                token.token_id,
                token.text,
                token.role,
                token.source,
                token.bbox,
                token.center,
                False,
                min(float(token.confidence or 0.0), 0.25),
                raw,
            )
        )
    fallback = {"kind": "cached_ax", "tokens": len(recovered), "path": str(latest), "observation_id": cached.observation_id}
    ax_source = sources.get("ax")
    if isinstance(ax_source, dict):
        ax_source["fallback"] = fallback
    else:
        sources["ax"] = {"fallback": fallback}
    errors.append(f"AX fallback used cached_ax tokenization: {len(recovered)} token(s)")
    return recovered


def _ax_only_tokenization_requested(include_ax: bool, include_ocr: bool, include_som: bool, include_grid: bool) -> bool:
    return bool(include_ax and not include_ocr and not include_som and not include_grid)


def tokens_from_ax(elements: Iterable[DesktopElement]) -> list[DesktopToken]:
    tokens: list[DesktopToken] = []
    for element in elements:
        label = element.label or element.role or element.element_id
        if not label and not element.bounds:
            continue
        bbox = _ax_bbox(element.bounds)
        center = element.center()
        enabled = element.enabled.strip().lower()
        clickable = _role_clickable(element.role) and enabled not in {"false", "0", "no"}
        tokens.append(
            DesktopToken(
                token_id=element.element_id,
                text=label,
                role=element.role or "ax_element",
                source="ax",
                bbox=bbox,
                center=center,
                clickable=clickable,
                confidence=0.85 if clickable else 0.65,
                raw=element.to_payload(),
            )
        )
    return tokens


def tokens_from_ocr(blocks: Iterable[DesktopTextBlock]) -> list[DesktopToken]:
    tokens: list[DesktopToken] = []
    for block in blocks:
        center = block.center()
        tokens.append(
            DesktopToken(
                token_id=block.block_id,
                text=block.text,
                role="text",
                source="ocr",
                bbox=block.bounds,
                center=center,
                clickable=center is not None,
                confidence=max(0.05, min(float(block.confidence), 1.0)),
                raw=block.to_payload(),
            )
        )
    return tokens


def tokens_from_som(targets: Iterable[SomTarget]) -> list[DesktopToken]:
    tokens: list[DesktopToken] = []
    for target in targets:
        center = target.target.center()
        tokens.append(
            DesktopToken(
                token_id=target.mark_id,
                text=target.label or target.mark_id,
                role=f"som_{target.source}",
                source="som",
                bbox=target.target.bounds,
                center=center,
                clickable=center is not None,
                confidence=max(0.05, min(float(target.target.confidence or 0.75), 1.0)),
                raw=target.to_payload(),
            )
        )
    return tokens


def tokens_from_grid(grid_payload: dict[str, Any]) -> list[DesktopToken]:
    tokens: list[DesktopToken] = []
    for cell in grid_payload.get("cells", []):
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id") or "").upper()
        bounds = _payload_bbox(cell.get("bounds"))
        center = (int(cell.get("x") or 0), int(cell.get("y") or 0)) if cell.get("x") is not None and cell.get("y") is not None else None
        if not cell_id:
            continue
        tokens.append(
            DesktopToken(
                token_id=f"GRID_{cell_id}",
                text=cell_id,
                role="grid_cell",
                source="grid",
                bbox=bounds,
                center=center,
                clickable=center is not None,
                confidence=0.35,
                raw=dict(cell),
            )
        )
    return tokens


def dedupe_desktop_tokens(tokens: Iterable[DesktopToken], *, limit: int = 240) -> list[DesktopToken]:
    priority = {"ax": 0, "som": 1, "ocr": 2, "grid": 3}
    ordered = sorted(
        tokens,
        key=lambda item: (
            0 if item.clickable and item.center else 1 if item.center else 2,
            priority.get(item.source, 9),
            -item.confidence,
            item.token_id,
        ),
    )
    deduped: list[DesktopToken] = []
    seen: set[tuple[int, int, str]] = set()
    for token in ordered:
        key = _token_key(token)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(token)
        if len(deduped) >= max(1, limit):
            break
    return deduped


def decide_desktop_action(
    goal: str,
    tokenization: DesktopTokenization | dict[str, Any],
    *,
    last_action: str = "",
    last_result: str = "",
    browser: str = "Safari",
    engine: str = "google",
) -> DesktopDecision:
    text = " ".join(goal.strip().split())
    observed = _tokenization_from_any(tokenization)
    tokens = observed.tokens
    if not text:
        return _decision(False, "skipped", "", {}, "empty goal")
    risk = _high_risk_reason(text)
    if risk:
        return _decision(False, "blocked", "", {}, f"high-risk goal term: {risk}", needs=("human_review",))
    lowered = text.lower()
    if _observe_only(text):
        return _decision(True, "hold", "", {}, "observe-only goal; no desktop side effect")

    typed = _type_text(text)
    if typed:
        typed_risk = _high_risk_reason(typed)
        if typed_risk:
            return _decision(False, "blocked", "type", {"text": typed}, f"high-risk input text term: {typed_risk}", needs=("human_review",))
        safety, reason = classify_gui_action("type", text=typed)
        if safety == "deny":
            return _decision(False, "blocked", "type", {"text": typed}, reason)
        args: dict[str, Any] = {"text": typed}
        target = _focused_text_target(observed)
        target_id = ""
        if target is not None:
            args |= _target_fence_args(target, observed)
            target_id = target.token_id
            reason = f"type requested text into focused target {target.token_id}: {target.text}"
        else:
            reason = "type requested text"
        return _decision(True, "action", "type", args, reason, target_id=target_id, requires_review=True, confidence=0.88)

    keys = _hotkey_keys(text)
    if keys:
        return _decision(True, "action", "hotkey", {"keys": keys}, "press requested hotkey", requires_review=True, confidence=0.82)

    click = CLICK_RE.search(text)
    if click:
        target_text = _strip_tail(click.group(1))
        coord = COORD_RE.match(target_text)
        if coord:
            x, y = int(coord.group(1)), int(coord.group(2))
            target = GuiTarget("coordinate", (x, y))
            safety, reason = classify_gui_action("click", target=target)
            if safety == "deny":
                return _decision(False, "blocked", "click", {"x": x, "y": y}, reason)
            return _decision(True, "action", "click", {"x": x, "y": y}, reason, requires_review=True, confidence=0.7)
        match = best_token_match(tokens, target_text, clickable_first=True)
        if match is None or match.center is None:
            return _decision(True, "no_match", "", {}, f"no token matched click target: {target_text}")
        target_risk = _high_risk_reason(match.text)
        if target_risk:
            return _decision(
                False,
                "blocked",
                "click",
                {"target_id": match.token_id, "target_text": match.text},
                f"high-risk click target term: {target_risk}",
                target_id=match.token_id,
                needs=("human_review",),
            )
        x, y = match.center
        return _decision(
            True,
            "action",
            "click",
            {
                "x": x,
                "y": y,
                "target_id": match.token_id,
                "target_text": match.text,
                "target_hash": _token_hash(match),
                "observation_id": observed.observation_id,
            },
            f"click matched token {match.token_id}: {match.text}",
            target_id=match.token_id,
            requires_review=True,
            confidence=match.confidence,
        )

    query = _search_query(text)
    if query:
        return _decide_search(query, observed, last_action=last_action, browser=_browser_from_text(text, default=browser), engine=engine)

    app = _open_app(text)
    if app and not last_action:
        return _decision(
            True,
            "action",
            "open",
            {"kind": "app", "label": app, "command": ["open", "-a", app]},
            f"open requested app: {app}",
            requires_review=True,
            confidence=0.78,
        )
    if app and last_action.startswith("open"):
        return _decision(True, "action", "wait", {"seconds": 0.5}, "wait after open", confidence=0.65)
    if app and last_action.startswith("wait"):
        return _decision(True, "hold", "", {}, "open flow already reached wait state")

    if "wait" in lowered or "等待" in text:
        return _decision(True, "action", "wait", {"seconds": 1.0}, "wait requested", confidence=0.6)
    return _decision(True, "skipped", "", {}, "no deterministic rule matched; model_decider_not_configured")


def best_token_match(tokens: Sequence[DesktopToken], query: str, *, clickable_first: bool = False) -> DesktopToken | None:
    normalized_query = _normalize(query)
    query_terms = _terms(query)
    if not normalized_query and not query_terms:
        return None
    scored: list[tuple[float, DesktopToken]] = []
    for token in tokens:
        haystack = _normalize(" ".join([token.text, token.role, token.source, token.token_id]))
        score = _match_score(normalized_query, query_terms, haystack)
        if score <= 0:
            continue
        if clickable_first and token.clickable:
            score += 20
        if token.source == "ax":
            score += 8
        elif token.source == "som":
            score += 6
        score += max(0.0, min(token.confidence, 1.0)) * 10.0
        scored.append((score, token))
    if not scored:
        return None
    return sorted(scored, key=lambda item: (-item[0], item[1].token_id))[0][1]


def run_desktop_daemon(
    project: str | Path,
    goal: str,
    *,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    browser: str = "Safari",
    engine: str = "google",
    max_steps: int = 20,
    delay: float = 1.0,
    stop_file: str | Path | None = None,
    include_grid: bool = False,
    token_limit: int = 240,
) -> DesktopDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    run_dir = desktop_intelligence_dir(project_path) / "daemon"
    run_dir.mkdir(parents=True, exist_ok=True)
    query_events_path = run_dir / "query_events.jsonl"
    trajectory_path = run_dir / "trajectory.jsonl"
    state_path = run_dir / "latest_state.json"
    stop_path = Path(stop_file).expanduser() if stop_file else default_stop_file(project_path)
    if not stop_path.is_absolute():
        stop_path = project_path / stop_path

    bounded_steps = max(1, min(int(max_steps), 1000))
    bounded_delay = max(0.0, min(float(delay), 3600.0))
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    redacted_goal = _redact_sensitive_text(goal)
    runtime.start(
        redacted_goal,
        mode="desktop_daemon",
        data={
            "execute": execute,
            "reviewed": reviewed,
            "allow_actions": allow_actions,
            "max_steps": bounded_steps,
            "stop_file": str(stop_path),
        },
    )

    records: list[DesktopDaemonRecord] = []
    results: list[DesktopResult] = []
    last_action = ""
    last_result = ""
    loop_history: list[tuple[str, str]] = []

    for step_no in range(1, bounded_steps + 1):
        if stop_path.exists():
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="stopped",
                summary=f"STOP file present before daemon step {step_no}: {stop_path}",
                failure_class="stopped",
            )

        tokenized = _safe_build_desktop_tokenization(project_path, include_grid=include_grid, limit=token_limit)
        records.append(
            DesktopDaemonRecord(
                step_no,
                "tokenize",
                tokenized.status,
                _redact_sensitive_text(tokenized.summary),
                _tokenization_record_data(tokenized),
            )
        )
        record_observation(
            trajectory_path,
            f"desktop-daemon step {step_no} tokenize: {_redact_sensitive_text(tokenized.summary)}",
            step=step_no,
            ok=tokenized.ok,
            phase="tokenize",
            tokens=len(tokenized.tokens),
            artifact_path=tokenized.path,
        )
        runtime.post_tool(
            "desktop_tokenize",
            step=step_no,
            ok=tokenized.ok,
            summary=_redact_sensitive_text(tokenized.summary),
            data=_tokenization_record_data(tokenized),
        )
        if tokenized.status == "failed" and not tokenized.tokens and not _high_risk_reason(goal):
            _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="failed", summary=tokenized.summary)
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="failed",
                summary=f"daemon tokenize failed at step {step_no}: {tokenized.summary}",
                failure_class="desktop_tokenize_failed",
            )

        decision = decide_desktop_action(goal, tokenized, last_action=last_action, last_result=last_result, browser=browser, engine=engine)
        records.append(DesktopDaemonRecord(step_no, "decide", decision.status, _redact_sensitive_text(decision.reason), decision.to_payload()))
        record_action(
            trajectory_path,
            f"desktop-daemon step {step_no} decide: {decision.status}/{decision.action or 'none'}",
            step=step_no,
            ok=decision.ok,
            phase="decide",
            decision=decision.to_payload(),
        )
        _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="running", summary=decision.reason)

        if decision.status == "action" and decision.step is not None:
            action_risk = _decision_policy_block(decision, goal=goal)
            if action_risk:
                records.append(DesktopDaemonRecord(step_no, "policy", "blocked", action_risk, {"decision": decision.to_payload()}))
                _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="blocked", summary=action_risk)
                return _finish_daemon(
                    project_path,
                    run_dir,
                    runtime,
                    redacted_goal,
                    records,
                    results,
                    query_events_path,
                    trajectory_path,
                    stop_path,
                    state_path,
                    ok=False,
                    status="blocked",
                    summary=action_risk,
                    failure_class="desktop_policy_blocked",
                )
            sequence_risk = _sequence_policy_block(records, decision, tokenized)
            if sequence_risk:
                records.append(DesktopDaemonRecord(step_no, "sequence_policy", "blocked", sequence_risk, {"decision": decision.to_payload()}))
                _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="blocked", summary=sequence_risk)
                return _finish_daemon(
                    project_path,
                    run_dir,
                    runtime,
                    redacted_goal,
                    records,
                    results,
                    query_events_path,
                    trajectory_path,
                    stop_path,
                    state_path,
                    ok=False,
                    status="blocked",
                    summary=sequence_risk,
                    failure_class="desktop_sequence_policy_blocked",
                )
            loop_key = (_action_signature(decision), _token_signature(tokenized))
            loop_history.append(loop_key)
            if _loop_detected(loop_history):
                summary = f"loop detected; replan_needed before repeating {decision.action}"
                records.append(DesktopDaemonRecord(step_no, "loop", "blocked", summary, {"action_signature": loop_key[0], "token_signature": loop_key[1]}))
                _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="blocked", summary=summary)
                return _finish_daemon(
                    project_path,
                    run_dir,
                    runtime,
                    redacted_goal,
                    records,
                    results,
                    query_events_path,
                    trajectory_path,
                    stop_path,
                    state_path,
                    ok=False,
                    status="blocked",
                    summary=summary,
                    failure_class="desktop_loop_detected",
                )

        if decision.status == "blocked":
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="blocked",
                summary=decision.reason,
                failure_class="desktop_decision_blocked",
            )
        if decision.status in {"skipped", "no_match"}:
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=True,
                status=decision.status,
                summary=decision.reason,
            )
        if decision.status == "hold" or decision.step is None:
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=True,
                status="completed",
                summary=decision.reason or "daemon reached hold state",
            )

        needs = _action_needs(decision.step, execute=execute, reviewed=reviewed, allow_actions=allow_actions)
        if needs:
            marked = DesktopDaemonRecord(
                step_no,
                "act",
                "skipped",
                f"side-effect action skipped; needs {', '.join(needs)}",
                {"needs": needs, "decision": decision.to_payload()},
            )
            records.append(marked)
            _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="skipped", summary=marked.summary)
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=True,
                status="skipped",
                summary=marked.summary,
            )

        try:
            with _desktop_action_lock(decision.step) as lock_data:
                if lock_data.get("locked"):
                    summary = f"desktop action lock acquired for {decision.step.action}"
                    records.append(DesktopDaemonRecord(step_no, "action_lock", "acquired", summary, lock_data))
                    record_observation(
                        trajectory_path,
                        f"desktop-daemon step {step_no} action-lock: {summary}",
                        step=step_no,
                        ok=True,
                        phase="action_lock",
                        **lock_data,
                    )

                stale = _preflight_target_check(project_path, decision, tokenized, include_grid=include_grid, token_limit=token_limit)
                records.append(DesktopDaemonRecord(step_no, "stale_check", stale.status, _redact_sensitive_text(stale.summary), stale.data))
                record_observation(
                    trajectory_path,
                    f"desktop-daemon step {step_no} stale-check: {_redact_sensitive_text(stale.summary)}",
                    step=step_no,
                    ok=stale.ok,
                    phase="stale_check",
                    **stale.data,
                )
                if not stale.ok:
                    return _finish_daemon(
                        project_path,
                        run_dir,
                        runtime,
                        redacted_goal,
                        records,
                        results,
                        query_events_path,
                        trajectory_path,
                        stop_path,
                        state_path,
                        ok=False,
                        status="blocked",
                        summary=stale.summary,
                        failure_class="desktop_target_stale",
                    )

                runtime.pre_tool("desktop_daemon", step=step_no, args=_redact_sensitive_payload({"action": decision.step.action, "args": decision.step.args}))
                result = _safe_execute_step(project_path, decision.step)
                results.append(result)
                runtime.post_tool(
                    "desktop_daemon",
                    step=step_no,
                    ok=result.ok,
                    summary=_redact_sensitive_text(result.summary),
                    data=_redact_sensitive_payload({"action": decision.step.action, "result": result.data}),
                )
                records.append(DesktopDaemonRecord(step_no, "act", "ok" if result.ok else "failed", _redact_sensitive_text(result.summary), _redact_sensitive_payload(asdict(result))))
                record_observation(
                    trajectory_path,
                    f"desktop-daemon step {step_no} act/{decision.step.action}: {_redact_sensitive_text(result.summary)}",
                    step=step_no,
                    ok=result.ok,
                    phase="act",
                    action=decision.step.action,
                    result=_redact_sensitive_payload(result.data),
                )
                _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status="running", summary=result.summary)
                if not result.ok:
                    return _finish_daemon(
                        project_path,
                        run_dir,
                        runtime,
                        redacted_goal,
                        records,
                        results,
                        query_events_path,
                        trajectory_path,
                        stop_path,
                        state_path,
                        ok=False,
                        status="failed",
                        summary=f"daemon action failed at step {step_no}: {result.summary}",
                        failure_class="desktop_action_failed",
                    )

                last_action = desktop_decision_marker(decision)
                last_result = result.summary
                if decision.step.action in CONTROL_ACTIONS:
                    verification = _verify_action_semantics(project_path, decision, tokenized, result, include_grid=include_grid, token_limit=token_limit)
                    records.append(
                        DesktopDaemonRecord(
                            step_no,
                            "verify",
                            verification.status,
                            _redact_sensitive_text(verification.summary),
                            verification.data,
                        )
                    )
                    record_observation(
                        trajectory_path,
                        f"desktop-daemon step {step_no} verify: {_redact_sensitive_text(verification.summary)}",
                        step=step_no,
                        ok=verification.ok,
                        phase="verify",
                        **verification.data,
                    )
                    if not verification.ok:
                        return _finish_daemon(
                            project_path,
                            run_dir,
                            runtime,
                            redacted_goal,
                            records,
                            results,
                            query_events_path,
                            trajectory_path,
                            stop_path,
                            state_path,
                            ok=False,
                            status="verify_failed",
                            summary=f"daemon semantic verify failed at step {step_no}: {verification.summary}",
                            failure_class="desktop_verify_failed",
                        )
        except TimeoutError as exc:
            summary = f"desktop action lock timeout at step {step_no}: {exc}"
            data = {"action": decision.step.action, "lock_path": str(desktop_action_lock_path()), "error_type": type(exc).__name__}
            records.append(DesktopDaemonRecord(step_no, "action_lock", "failed", summary, data))
            record_observation(trajectory_path, summary, step=step_no, ok=False, phase="action_lock", **data)
            return _finish_daemon(
                project_path,
                run_dir,
                runtime,
                redacted_goal,
                records,
                results,
                query_events_path,
                trajectory_path,
                stop_path,
                state_path,
                ok=False,
                status="failed",
                summary=summary,
                failure_class="desktop_action_lock_timeout",
            )
        if step_no < bounded_steps and bounded_delay > 0:
            time.sleep(bounded_delay)

    return _finish_daemon(
        project_path,
        run_dir,
        runtime,
        redacted_goal,
        records,
        results,
        query_events_path,
        trajectory_path,
        stop_path,
        state_path,
        ok=True,
        status="step_budget_exhausted",
        summary=f"daemon exhausted {bounded_steps} step(s) without terminal hold",
    )


def desktop_decision_marker(decision: DesktopDecision) -> str:
    if not decision.action:
        return decision.status
    if decision.action == "hotkey":
        keys = _normalized_hotkey_keys(decision.args.get("keys"))
        return "hotkey:" + "+".join(str(key).lower() for key in keys)
    if decision.action == "type":
        return "type:" + str(decision.args.get("text") or "")
    return decision.action


def render_desktop_tokenization(result: DesktopTokenization) -> str:
    lines = [
        "# Desktop Tokenization",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"Image: {result.image_path or '-'}",
        f"Output: {result.path or '-'}",
        "",
        "Tokens:",
    ]
    for token in result.tokens[:20]:
        center = f" @{token.center[0]},{token.center[1]}" if token.center else ""
        click = " clickable" if token.clickable else ""
        lines.append(f"- {token.token_id} [{token.source}/{token.role}{click}]{center}: {token.text}")
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend(f"- {error}" for error in result.errors[:10])
    return "\n".join(lines).rstrip() + "\n"


def render_desktop_decision(decision: DesktopDecision) -> str:
    lines = [
        "# Desktop Decision",
        "",
        f"Status: {decision.status}",
        f"OK: {str(decision.ok).lower()}",
        f"Action: {decision.action or '-'}",
        f"Reason: {decision.reason}",
    ]
    if decision.args:
        lines.append(f"Args: {json.dumps(decision.args, ensure_ascii=False)}")
    if decision.target_id:
        lines.append(f"Target: {decision.target_id}")
    if decision.needs:
        lines.append("Needs: " + ", ".join(decision.needs))
    return "\n".join(lines).rstrip() + "\n"


def render_desktop_daemon_result(result: DesktopDaemonResult) -> str:
    lines = [
        "# Desktop Daemon",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"Stop file: {result.stop_file}",
        f"State: {result.state_path}",
        f"Query events: {result.query_events_path}",
        f"Trajectory: {result.trajectory_path}",
        "",
        "Records:",
    ]
    for record in result.records[-30:]:
        lines.append(f"- step {record.step} {record.phase}/{record.status}: {record.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _write_tokenization(project: Path, result: DesktopTokenization, *, name: str | None = None) -> DesktopTokenization:
    directory = desktop_intelligence_dir(project)
    stem = name or f"tokenize_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    path = directory / (stem if stem.endswith(".json") else f"{stem}.json")
    payload = result.to_payload()
    payload["path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = directory / "latest_tokenize.json"
    latest.write_text(json.dumps(payload | {"path": str(latest)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DesktopTokenization(
        result.ok,
        result.status,
        result.summary,
        result.image_path,
        result.width,
        result.height,
        result.tokens,
        result.errors,
        result.sources,
        str(path),
        result.observation_id,
        result.screen_hash,
        result.created_at,
        result.front_app,
    )


def _finish_daemon(
    project: Path,
    run_dir: Path,
    runtime: QueryRuntime,
    goal: str,
    records: list[DesktopDaemonRecord],
    results: list[DesktopResult],
    query_events_path: Path,
    trajectory_path: Path,
    stop_path: Path,
    state_path: Path,
    *,
    ok: bool,
    status: str,
    summary: str,
    failure_class: str = "",
) -> DesktopDaemonResult:
    redacted_goal = _redact_sensitive_text(goal)
    redacted_summary = _redact_sensitive_text(summary)
    _write_daemon_state(state_path, redacted_goal, records, results, stop_path, status=status, summary=redacted_summary)
    autopsy = ""
    if ok:
        runtime.stop("desktop daemon completed", ok=True)
    else:
        runtime.stop(_redact_sensitive_text("desktop daemon failed"), ok=False, failure_class=failure_class or status)
        autopsy = str(write_daemon_failure_autopsy(
            project,
            goal=redacted_goal,
            status=status,
            summary=redacted_summary,
            trajectory_path=trajectory_path,
            query_events_path=query_events_path,
            failed_at=status,
            failure_class=failure_class or status,
            sources=(state_path,),
        ))
    return DesktopDaemonResult(
        ok,
        status,
        redacted_summary,
        redacted_goal,
        tuple(records),
        tuple(results),
        str(query_events_path),
        str(trajectory_path),
        str(stop_path),
        str(state_path),
        autopsy,
    )


def _write_daemon_state(
    path: Path,
    goal: str,
    records: list[DesktopDaemonRecord],
    results: list[DesktopResult],
    stop_path: Path,
    *,
    status: str,
    summary: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
                "summary": _redact_sensitive_text(summary),
                "goal": _redact_sensitive_text(goal),
                "stop_file": str(stop_path),
                "records": [record.to_payload() for record in records[-300:]],
                "results": [_redact_sensitive_payload(asdict(result)) for result in results[-300:]],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _decision(
    ok: bool,
    status: str,
    action: str,
    args: dict[str, Any],
    reason: str,
    *,
    target_id: str = "",
    requires_review: bool = False,
    needs: tuple[str, ...] = (),
    confidence: float = 0.0,
) -> DesktopDecision:
    step = DesktopStep(action, args, reason, requires_review=requires_review) if action else None
    return DesktopDecision(ok, status, action, args, target_id, reason, requires_review, needs, confidence, step)


def _decide_search(query: str, observed: DesktopTokenization, *, last_action: str, browser: str, engine: str) -> DesktopDecision:
    url = search_url(query, engine=engine)
    marker = last_action.strip().lower()
    if not marker:
        return _decision(True, "action", "activate", {"app": browser}, f"focus browser for search: {browser}", requires_review=True, confidence=0.72)
    if marker.startswith("activate"):
        return _decision(True, "action", "hotkey", {"keys": ["cmd", "l"]}, "focus address/search bar", requires_review=True, confidence=0.78)
    if marker == "hotkey:cmd+l":
        args: dict[str, Any] = {"text": url}
        target = _focused_text_target(observed)
        target_id = ""
        reason = "type deterministic search URL"
        if target is not None:
            args |= _target_fence_args(target, observed)
            target_id = target.token_id
            reason = f"type deterministic search URL into focused target {target.token_id}: {target.text}"
        return _decision(True, "action", "type", args, reason, target_id=target_id, requires_review=True, confidence=0.82)
    if marker.startswith("type:"):
        return _decision(True, "action", "hotkey", {"keys": ["return"]}, "submit search", requires_review=True, confidence=0.8)
    if marker == "hotkey:return":
        return _decision(True, "action", "wait", {"seconds": 1.0}, "wait for browser navigation", confidence=0.65)
    if marker.startswith("wait"):
        return _decision(True, "hold", "", {}, "search flow reached verification hold")
    return _decision(True, "skipped", "", {}, f"search flow cannot continue from last_action={last_action!r}")


def _action_needs(step: DesktopStep, *, execute: bool, reviewed: bool, allow_actions: bool) -> list[str]:
    if not step.side_effect:
        return []
    needs: list[str] = []
    if not execute:
        needs.append("--execute")
    if not reviewed:
        needs.append("--reviewed")
    if step.action in CONTROL_ACTIONS and not allow_actions:
        needs.append("--allow-actions")
    return needs


def _decision_policy_block(decision: DesktopDecision, *, goal: str) -> str:
    if decision.step is None:
        return ""
    args = dict(decision.step.args)
    if decision.target_id and "target_id" not in args:
        args["target_id"] = decision.target_id
    if decision.action == "click" and "target_text" not in args:
        target_text = _target_text_from_reason(decision.reason)
        if target_text:
            args["target_text"] = target_text
    policy = authorize_daemon_action(
        {"action": decision.step.action, "args": args},
        goal=goal,
        execute=True,
        reviewed=True,
        allow_actions=True,
    )
    if policy.allowed or policy.status != "blocked":
        return ""
    return policy.reason


def _sequence_policy_block(records: Sequence[DesktopDaemonRecord], decision: DesktopDecision, tokenized: DesktopTokenization) -> str:
    if decision.step is None or not _is_submit_decision(decision):
        return ""
    type_args = _recent_type_args(records)
    typed_text = str(type_args.get("text") or "").strip()
    if not typed_text or _is_navigation_text(typed_text):
        return ""
    if _is_command_search_confirmation(decision, type_args, tokenized):
        return ""
    if _is_textarea_newline(decision, type_args, tokenized):
        return ""
    return "cumulative desktop action risk: typed text followed by submit action"


def _recent_type_args(records: Sequence[DesktopDaemonRecord], *, window: int = 24) -> dict[str, Any]:
    for record in reversed(records[-window:]):
        if record.phase != "decide" or record.status != "action":
            continue
        decision = record.data
        if str(decision.get("action") or "").strip().lower() != "type":
            continue
        args = decision.get("args") or {}
        if not isinstance(args, dict):
            continue
        text = str(args.get("text") or "").strip()
        if text:
            return dict(args)
    return {}


def _is_submit_decision(decision: DesktopDecision) -> bool:
    action = (decision.step.action if decision.step else decision.action).strip().lower()
    args = decision.step.args if decision.step else decision.args
    if action == "hotkey":
        keys = _normalized_hotkey_keys(args.get("keys"))
        return any(key in SUBMIT_HOTKEYS for key in keys)
    if action in {"click", "grid-click", "som-click"}:
        return _submit_text_from_payload(args) or bool(SUBMIT_ACTION_RE.search(decision.reason or ""))
    return False


def _submit_text_from_payload(args: Mapping[str, Any]) -> bool:
    for key in ("target_text", "target", "label", "title", "name", "button", "menu_item", "text"):
        value = args.get(key)
        if value is not None and SUBMIT_ACTION_RE.search(str(value)):
            return True
    return False


def _is_textarea_newline(decision: DesktopDecision, type_args: Mapping[str, Any], tokenized: DesktopTokenization) -> bool:
    if decision.step is None or decision.step.action != "hotkey":
        return False
    keys = _normalized_hotkey_keys(decision.step.args.get("keys"))
    if not any(key in SUBMIT_HOTKEYS for key in keys):
        return False
    target_id = str(decision.step.args.get("target_id") or decision.target_id or "")
    typed_target_id = str(type_args.get("target_id") or "")
    if not target_id or not typed_target_id or target_id != typed_target_id:
        return False
    target = _find_token(tokenized, target_id)
    if target is None:
        return False
    expected_hash = str(decision.step.args.get("target_hash") or "")
    if expected_hash and _token_hash(target) != expected_hash:
        return False
    role = str(target.role or target.raw.get("role") or "").strip().lower()
    return role == "axtextarea"


def _is_command_search_confirmation(decision: DesktopDecision, type_args: Mapping[str, Any], tokenized: DesktopTokenization) -> bool:
    if decision.step is None or decision.step.action != "hotkey":
        return False
    keys = _normalized_hotkey_keys(decision.step.args.get("keys"))
    if set(keys) - SUBMIT_HOTKEYS or not any(key in SUBMIT_HOTKEYS for key in keys):
        return False
    target_id = str(decision.step.args.get("target_id") or decision.target_id or "")
    typed_target_id = str(type_args.get("target_id") or "")
    if not target_id or not typed_target_id or target_id != typed_target_id:
        return False
    target = _find_token(tokenized, target_id)
    if target is None:
        return False
    expected_hash = str(decision.step.args.get("target_hash") or "")
    if expected_hash and _token_hash(target) != expected_hash:
        return False
    role = str(target.role or target.raw.get("role") or "").strip().lower()
    if role not in {"axtextfield", "axsearchfield", "searchfield"}:
        return False
    label = " ".join(str(part or "") for part in (target.text, target.raw.get("label"), target.raw.get("placeholder"), target.raw.get("title"))).lower()
    if not any(term in label for term in ("search", "spotlight", "command", "palette", "apps", "应用", "搜索", "命令")):
        return False
    typed_text = str(type_args.get("text") or "").strip()
    return bool(re.match(r"^[\w .+\-]{1,80}$", typed_text))


def _is_navigation_text(text: str) -> bool:
    value = str(text or "").strip().lower()
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", value) or value.startswith("www."))


def _preflight_target_check(
    project: Path,
    decision: DesktopDecision,
    previous: DesktopTokenization,
    *,
    include_grid: bool,
    token_limit: int,
) -> DesktopActionVerification:
    step = decision.step
    if step is None or step.action not in PREACTION_REVALIDATE_ACTIONS | {"grid-click", "som-click"}:
        return DesktopActionVerification(True, "ok", "no target-fence required for this action", data={"action": decision.action})
    target_id = decision.target_id or str(decision.args.get("target_id") or "")
    expected_hash = str(decision.args.get("target_hash") or "")
    source_observation = str(decision.args.get("observation_id") or "")
    if step.action == "hotkey" and not target_id and not expected_hash and not source_observation:
        return DesktopActionVerification(True, "ok", "global hotkey has no target-fence", data={"action": step.action})
    if step.action in PREACTION_REVALIDATE_ACTIONS and (not target_id or not expected_hash or not source_observation):
        return DesktopActionVerification(
            False,
            "stale_target",
            f"target action {step.action} missing observation fence",
            data={"action": step.action, "target_id": target_id, "source_observation": source_observation},
        )
    if step.action not in PREACTION_REVALIDATE_ACTIONS:
        return DesktopActionVerification(True, "ok", "non-token target action allowed after review", data={"action": step.action})
    if source_observation != previous.observation_id:
        return DesktopActionVerification(
            False,
            "stale_target",
            f"observation fence mismatch before action: expected {previous.observation_id or '<missing>'}, got {source_observation or '<missing>'}",
            data={
                "action": step.action,
                "target_id": target_id,
                "source_observation": source_observation,
                "previous_observation": previous.observation_id,
            },
        )
    previous_token = _find_token(previous, target_id)
    if previous_token is None:
        return DesktopActionVerification(
            False,
            "stale_target",
            f"source target missing before action: {target_id}",
            data={"action": step.action, "target_id": target_id, "source_observation": source_observation},
        )
    previous_hash = _token_hash(previous_token)
    if previous_hash != expected_hash:
        return DesktopActionVerification(
            False,
            "stale_target",
            f"decision target hash mismatches source observation: {target_id}",
            data={
                "action": step.action,
                "target_id": target_id,
                "source_observation": source_observation,
                "expected_target_hash": _short_hash(expected_hash),
                "source_target_hash": _short_hash(previous_hash),
            },
        )
    current = _safe_build_desktop_tokenization(
        project,
        **_preflight_tokenization_kwargs(previous_token, include_grid=include_grid, token_limit=token_limit, skip_screenshot_if_ax_only=True),
    )
    current_token = _find_token(current, target_id)
    data = {
        "action": step.action,
        "target_id": target_id,
        "source_observation": source_observation,
        "current_observation": current.observation_id,
        "source_screen_hash": _short_hash(previous.screen_hash),
        "current_screen_hash": _short_hash(current.screen_hash),
        "artifact_path": current.path,
        "tokens": len(current.tokens),
        "previous_center": list(previous_token.center) if previous_token.center else None,
        "previous_bbox": list(previous_token.bbox) if previous_token.bbox else None,
    }
    if not current.ok and not current.tokens:
        return DesktopActionVerification(False, "stale_target", f"fresh target observation failed: {current.summary}", current, data)
    if current_token is None:
        return DesktopActionVerification(False, "stale_target", f"target disappeared before action: {target_id}", current, data)
    if _token_is_cached_ax(current_token):
        data["cached_ax_fallback"] = True
        return DesktopActionVerification(False, "stale_target", f"fresh target observation used cached AX fallback: {target_id}", current, data)
    current_hash = _token_hash(current_token)
    data["expected_target_hash"] = _short_hash(expected_hash)
    data["current_target_hash"] = _short_hash(current_hash)
    data["current_center"] = list(current_token.center) if current_token.center else None
    data["current_bbox"] = list(current_token.bbox) if current_token.bbox else None
    center_drift = _center_drift(previous_token.center, current_token.center)
    bbox_drift = _bbox_drift(previous_token.bbox, current_token.bbox)
    data["center_drift_px"] = center_drift
    data["bbox_drift_px"] = bbox_drift
    if current_hash != expected_hash:
        drift_summary = _drift_summary(center_drift, bbox_drift)
        suffix = f"; {drift_summary}" if drift_summary else ""
        return DesktopActionVerification(False, "stale_target", f"target changed before action: {target_id}{suffix}", current, data)
    if center_drift is None or bbox_drift is None:
        return DesktopActionVerification(False, "stale_target", f"target geometry missing before action: {target_id}", current, data)
    if center_drift > MAX_CENTER_DRIFT_PX or bbox_drift > MAX_BBOX_DRIFT_PX:
        return DesktopActionVerification(False, "stale_target", f"target drifted before action: {target_id}; {_drift_summary(center_drift, bbox_drift)}", current, data)
    return DesktopActionVerification(True, "ok", f"target fresh: {target_id}", current, data)


def _preflight_tokenization_kwargs(
    previous_token: DesktopToken,
    *,
    include_grid: bool,
    token_limit: int,
    skip_screenshot_if_ax_only: bool = False,
) -> dict[str, Any]:
    source = str(previous_token.source or "").strip().lower()
    if source == "ax":
        return {
            "include_ax": True,
            "include_ocr": False,
            "include_som": False,
            "include_grid": False,
            "limit": token_limit,
            "skip_screenshot_if_ax_only": skip_screenshot_if_ax_only,
        }
    if source == "ocr":
        return {"include_ax": False, "include_ocr": True, "include_som": False, "include_grid": False, "limit": token_limit}
    if source == "som":
        return {"include_ax": True, "include_ocr": True, "include_som": True, "include_grid": include_grid, "limit": token_limit}
    return {"include_grid": include_grid, "limit": token_limit}


def _safe_build_desktop_tokenization(project: Path, **kwargs: Any) -> DesktopTokenization:
    try:
        return build_desktop_tokenization(project, **kwargs)
    except Exception as exc:
        summary = f"tokenize exception: {type(exc).__name__}: {exc}"
        return DesktopTokenization(False, "failed", summary, "", 0, 0, (), errors=(summary,))


def _verify_action_semantics(
    project: Path,
    decision: DesktopDecision,
    previous: DesktopTokenization,
    result: DesktopResult,
    *,
    include_grid: bool,
    token_limit: int,
) -> DesktopActionVerification:
    fast_type_verification = _verify_type_with_fast_ax_path(
        project,
        decision,
        previous,
        result,
        include_grid=include_grid,
        token_limit=token_limit,
    )
    if fast_type_verification is not None and fast_type_verification.ok:
        return fast_type_verification

    verify_kwargs = _verification_tokenization_kwargs(decision, previous, include_grid=include_grid, token_limit=token_limit)
    verified = _safe_build_desktop_tokenization(project, **verify_kwargs)
    data, comparable_sources = _verification_record_data(verified, verify_kwargs, previous, decision, result)
    if fast_type_verification is not None:
        data["fast_type_verify"] = fast_type_verification.data.get("fast_type_verify", {})

    targetless_hotkey = decision.action == "hotkey" and not decision.target_id and not decision.args.get("target_id")
    if not verified.ok and not verified.tokens and not targetless_hotkey:
        return DesktopActionVerification(False, "verify_failed", verified.summary, verified, data)
    if decision.action == "type":
        typed = str(decision.args.get("text") or "")
        if typed and _tokens_contain_text(verified.tokens, typed):
            return DesktopActionVerification(True, "ok", f"semantic verify passed: typed text visible", verified, data)
        if _post_action_progress(previous, verified, decision, sources=comparable_sources):
            return DesktopActionVerification(True, "ok", "semantic verify passed: desktop state changed after type", verified, data)
        return DesktopActionVerification(False, "verify_failed", f"semantic verify failed: typed text not visible: {typed}", verified, data)
    if decision.action in {"click", "move"}:
        target_id = decision.target_id or str(decision.args.get("target_id") or "")
        expected_hash = str(decision.args.get("target_hash") or "")
        current_token = _find_token(verified, target_id) if target_id else None
        data["target_id"] = target_id
        if _tokenization_uses_cached_ax(verified):
            data["cached_ax_fallback"] = True
            return DesktopActionVerification(
                False,
                "verify_failed",
                "semantic verify failed: fresh AX verification used cached AX fallback",
                verified,
                data,
            )
        if target_id and current_token is None:
            return DesktopActionVerification(True, "ok", f"semantic verify passed: target disappeared: {target_id}", verified, data)
        if current_token is not None and expected_hash and _token_hash(current_token) != expected_hash:
            return DesktopActionVerification(True, "ok", f"semantic verify passed: target changed: {target_id}", verified, data)
        if _post_action_progress(previous, verified, decision, sources=comparable_sources):
            return DesktopActionVerification(True, "ok", "semantic verify passed: desktop tokens changed", verified, data)
        return DesktopActionVerification(False, "verify_failed", "semantic verify failed: no visible progress after target action", verified, data)
    if decision.action == "hotkey":
        if not decision.target_id and not decision.args.get("target_id"):
            return DesktopActionVerification(True, "ok", "capture verify passed for global hotkey", verified, data)
        if _post_action_progress(previous, verified, decision, sources=comparable_sources):
            return DesktopActionVerification(True, "ok", "semantic verify passed: desktop state changed after hotkey", verified, data)
        return DesktopActionVerification(False, "verify_failed", "semantic verify failed: no visible progress after hotkey", verified, data)
    return DesktopActionVerification(True, "ok", f"capture verify passed for {decision.action}", verified, data)


def _verify_type_with_fast_ax_path(
    project: Path,
    decision: DesktopDecision,
    previous: DesktopTokenization,
    result: DesktopResult,
    *,
    include_grid: bool,
    token_limit: int,
) -> DesktopActionVerification | None:
    if decision.action != "type":
        return None
    typed = str(decision.args.get("text") or "")
    target_id = decision.target_id or str(decision.args.get("target_id") or "")
    previous_token = _find_token(previous, target_id) if target_id else None
    if not typed or previous_token is None or str(previous_token.source or "").strip().lower() != "ax":
        return None

    verify_kwargs = _preflight_tokenization_kwargs(
        previous_token,
        include_grid=include_grid,
        token_limit=token_limit,
        skip_screenshot_if_ax_only=True,
    )
    verified = _safe_build_desktop_tokenization(project, **verify_kwargs)
    data, _comparable_sources = _verification_record_data(verified, verify_kwargs, previous, decision, result)
    fast_data = {
        "mode": "ax_only",
        "fallback_required": True,
        "artifact_path": verified.path,
        "tokens": len(verified.tokens),
        "screen_hash": _short_hash(verified.screen_hash),
    }
    data["fast_type_verify"] = fast_data
    if not verified.ok and not verified.tokens:
        fast_data["fallback_reason"] = "ax_tokenization_failed"
        return DesktopActionVerification(False, "needs_fallback", f"fast AX type verify needs OCR fallback: {verified.summary}", verified, data)
    if _tokenization_uses_cached_ax(verified):
        data["cached_ax_fallback"] = True
        fast_data["fallback_reason"] = "cached_ax_fallback"
        return DesktopActionVerification(False, "needs_fallback", "fast AX type verify needs OCR fallback: cached AX fallback", verified, data)
    current_token = _find_token(verified, target_id)
    if current_token is not None and _tokens_contain_text((current_token,), typed):
        fast_data["fallback_required"] = False
        return DesktopActionVerification(True, "ok", "semantic verify passed: typed text visible in AX", verified, data)
    fast_data["fallback_reason"] = "typed_text_not_visible_in_target_ax"
    return DesktopActionVerification(False, "needs_fallback", f"fast AX type verify needs OCR fallback: typed text not visible in target AX: {typed}", verified, data)


def _verification_record_data(
    verified: DesktopTokenization,
    verify_kwargs: Mapping[str, Any],
    previous: DesktopTokenization,
    decision: DesktopDecision,
    result: DesktopResult,
) -> tuple[dict[str, Any], set[str]]:
    comparable_sources = _comparable_token_sources(verified, verify_kwargs)
    previous_token_signature = _token_signature(previous, sources=comparable_sources)
    current_token_signature = _token_signature(verified, sources=comparable_sources)
    previous_focus_signature = _focus_signature(previous, sources=comparable_sources)
    current_focus_signature = _focus_signature(verified, sources=comparable_sources)
    data = _tokenization_record_data(verified) | {
        "action": decision.action,
        "result_ok": result.ok,
        "previous_observation": previous.observation_id,
        "previous_screen_hash": _short_hash(previous.screen_hash),
        "current_screen_hash": _short_hash(verified.screen_hash),
        "screen_hash_changed": bool(previous.screen_hash and verified.screen_hash and previous.screen_hash != verified.screen_hash),
        "previous_token_signature": _short_hash(previous_token_signature),
        "current_token_signature": _short_hash(current_token_signature),
        "token_tree_changed": previous_token_signature != current_token_signature,
        "previous_focus_signature": _short_hash(previous_focus_signature),
        "current_focus_signature": _short_hash(current_focus_signature),
        "focus_changed": previous_focus_signature != current_focus_signature,
        "verification_sources": sorted(comparable_sources),
    }
    return data, comparable_sources


def _verification_tokenization_kwargs(
    decision: DesktopDecision,
    previous: DesktopTokenization,
    *,
    include_grid: bool,
    token_limit: int,
) -> dict[str, Any]:
    target_id = decision.target_id or str(decision.args.get("target_id") or "")
    previous_token = _find_token(previous, target_id) if target_id else None
    if decision.action == "type":
        return {"include_ax": True, "include_ocr": True, "include_som": False, "include_grid": False, "limit": token_limit}
    if decision.action in {"click", "move", "hotkey"} and previous_token is not None:
        return _preflight_tokenization_kwargs(
            previous_token,
            include_grid=include_grid,
            token_limit=token_limit,
            skip_screenshot_if_ax_only=decision.action in {"click", "move"},
        )
    if decision.action == "hotkey":
        return {"include_ax": False, "include_ocr": False, "include_som": False, "include_grid": False, "limit": token_limit}
    return {"include_grid": include_grid, "limit": token_limit}


def _comparable_token_sources(tokenization: DesktopTokenization, kwargs: Mapping[str, Any]) -> set[str]:
    sources = {str(token.source or "").strip().lower() for token in tokenization.tokens if str(token.source or "").strip()}
    if sources:
        return sources
    requested: set[str] = set()
    if kwargs.get("include_ax", True):
        requested.add("ax")
    if kwargs.get("include_ocr", True):
        requested.add("ocr")
    if kwargs.get("include_som", True):
        requested.add("som")
    if kwargs.get("include_grid", False):
        requested.add("grid")
    return requested

@contextlib.contextmanager
def _desktop_action_lock(step: DesktopStep) -> Iterator[dict[str, Any]]:
    if step.action not in ACTION_LOCK_ACTIONS:
        yield {"locked": False, "action": step.action}
        return

    lock_path = desktop_action_lock_path()
    start = time.monotonic()
    deadline = start + ACTION_LOCK_TIMEOUT_SECONDS
    if not _SESSION_ACTION_THREAD_LOCK.acquire(timeout=ACTION_LOCK_TIMEOUT_SECONDS):
        raise TimeoutError(f"thread lock timeout for desktop action {step.action}")

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _process_action_lock(lock_path, deadline):
            yield {
                "locked": True,
                "action": step.action,
                "lock_path": str(lock_path),
                "wait_seconds": round(max(0.0, time.monotonic() - start), 6),
            }
    finally:
        _SESSION_ACTION_THREAD_LOCK.release()


@contextlib.contextmanager
def _process_action_lock(path: Path, deadline: float) -> Iterator[None]:
    try:
        import fcntl  # type: ignore
    except ImportError:
        with _fallback_process_action_lock(path, deadline):
            yield
        return

    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"process lock timeout: {path}")
                time.sleep(ACTION_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _fallback_process_action_lock(path: Path, deadline: float) -> Iterator[None]:
    held_path = path.with_suffix(path.suffix + ".held")
    fd = -1
    while True:
        try:
            fd = os.open(str(held_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"process lock timeout: {held_path}")
            time.sleep(ACTION_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            held_path.unlink()


def _safe_execute_step(project: Path, step: DesktopStep) -> DesktopResult:
    try:
        return _execute_step(project, step)
    except TimeoutExpired as exc:
        return DesktopResult(
            step.action or "desktop",
            False,
            f"desktop action timeout: {exc}",
            {"action": step.action, "error_type": type(exc).__name__, "timeout": exc.timeout, "cmd": str(exc.cmd)},
        )
    except Exception as exc:
        audit_suppressed_exception(
            "desktop_intelligence._safe_execute_step",
            exc,
            project=project,
            data={"action": step.action},
        )
        return DesktopResult(
            step.action or "desktop",
            False,
            f"desktop action exception: {type(exc).__name__}: {exc}",
            {"action": step.action, "error_type": type(exc).__name__},
        )


def _resolve_image(project: Path, image_path: str | Path | None) -> Path | None:
    if image_path is None:
        return None
    image = Path(image_path).expanduser()
    if image.is_absolute():
        return image
    direct = project / image
    if direct.exists():
        return direct
    return desktop_dir(project) / image


def _token_from_payload(raw: dict[str, Any], index: int) -> DesktopToken:
    bbox = _payload_bbox(raw.get("bbox") or raw.get("bounds"))
    center = _payload_center(raw.get("center"))
    return DesktopToken(
        token_id=str(raw.get("token_id") or raw.get("id") or f"T{index + 1:04d}"),
        text=str(raw.get("text") or raw.get("label") or ""),
        role=str(raw.get("role") or ""),
        source=str(raw.get("source") or ""),
        bbox=bbox,
        center=center,
        clickable=bool(raw.get("clickable")),
        confidence=float(raw.get("confidence") or 0.0),
        raw=dict(raw.get("raw") or {}),
    )


def _tokens_from_any(tokenization: DesktopTokenization | dict[str, Any]) -> tuple[DesktopToken, ...]:
    return _tokenization_from_any(tokenization).tokens


def _tokenization_from_any(tokenization: DesktopTokenization | dict[str, Any]) -> DesktopTokenization:
    if isinstance(tokenization, DesktopTokenization):
        return tokenization
    return tokenization_from_payload(tokenization)


def _ax_bbox(bounds: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    if not bounds:
        return None
    x, y, w, h = bounds
    return x, y, x + w, y + h


def _payload_bbox(raw: Any) -> tuple[int, int, int, int] | None:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 4:
        try:
            x1, y1, x2, y2 = [int(item) for item in raw]
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    return None


def _payload_center(raw: Any) -> tuple[int, int] | None:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return None
    return None


def _role_clickable(role: str) -> bool:
    lowered = role.lower()
    return any(
        item in lowered
        for item in (
            "button",
            "link",
            "menu",
            "checkbox",
            "radio",
            "textfield",
            "text field",
            "tab",
            "cell",
            "row",
            "combo",
            "popup",
        )
    )


def _token_key(token: DesktopToken) -> tuple[int, int, str]:
    center = token.center or (0, 0)
    text = _normalize(token.text or token.role or token.token_id)[:40]
    return round(center[0] / 10), round(center[1] / 10), text


def _token_hash(token: DesktopToken) -> str:
    raw = token.raw if isinstance(token.raw, dict) else {}
    payload = {
        "token_id": token.token_id,
        "text": token.text,
        "role": token.role,
        "source": token.source,
        "bbox": list(token.bbox) if token.bbox else None,
        "center": list(token.center) if token.center else None,
        "clickable": token.clickable,
        "state": {
            key: str(raw.get(key) or "")
            for key in ("value", "enabled", "focused", "selected", "checked", "expanded")
            if raw.get(key) not in (None, "")
        },
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _token_signature(tokenization: DesktopTokenization, *, sources: set[str] | None = None) -> str:
    wanted = {str(source).strip().lower() for source in sources or set() if str(source).strip()}
    payload = [
        _token_hash(token)
        for token in tokenization.tokens
        if not wanted or str(token.source or "").strip().lower() in wanted
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _focus_signature(tokenization: DesktopTokenization, *, sources: set[str] | None = None) -> str:
    wanted = {str(source).strip().lower() for source in sources or set() if str(source).strip()}
    focused: list[dict[str, Any]] = []
    for token in tokenization.tokens:
        if wanted and str(token.source or "").strip().lower() not in wanted:
            continue
        raw = token.raw if isinstance(token.raw, dict) else {}
        if _truthy_state(raw.get("focused") or raw.get("focus") or raw.get("selected")):
            focused.append(
                {
                    "token_id": token.token_id,
                    "text": token.text,
                    "role": token.role,
                    "source": token.source,
                    "center": list(token.center) if token.center else None,
                }
            )
    return hashlib.sha256(json.dumps(focused, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _post_action_progress(
    previous: DesktopTokenization,
    current: DesktopTokenization,
    decision: DesktopDecision,
    *,
    sources: set[str] | None = None,
) -> bool:
    if previous.screen_hash and current.screen_hash and previous.screen_hash != current.screen_hash:
        return True
    if _token_signature(previous, sources=sources) != _token_signature(current, sources=sources):
        return True
    if _focus_signature(previous, sources=sources) != _focus_signature(current, sources=sources):
        return True
    target_id = decision.target_id or str(decision.args.get("target_id") or "")
    expected_hash = str(decision.args.get("target_hash") or "")
    if target_id:
        current_token = _find_token(current, target_id)
        if current_token is None:
            return True
        if expected_hash and _token_hash(current_token) != expected_hash:
            return True
    return False


def _truthy_state(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "selected", "focused"}


def _action_signature(decision: DesktopDecision) -> str:
    payload = {
        "action": decision.action,
        "args": decision.args,
        "target_id": decision.target_id,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _loop_detected(history: list[tuple[str, str]], *, window: int = 3) -> bool:
    if len(history) < window:
        return False
    recent = history[-window:]
    return all(item == recent[0] for item in recent)


def _find_token(tokenization: DesktopTokenization, token_id: str) -> DesktopToken | None:
    wanted = token_id.strip()
    if not wanted:
        return None
    return next((token for token in tokenization.tokens if token.token_id == wanted), None)


def _token_is_cached_ax(token: DesktopToken) -> bool:
    raw = token.raw if isinstance(token.raw, dict) else {}
    return str(token.source or "").strip().lower() == "ax" and str(raw.get("recovered_from") or "").strip().lower() == "cached_ax"


def _tokenization_uses_cached_ax(tokenization: DesktopTokenization) -> bool:
    return any(_token_is_cached_ax(token) for token in tokenization.tokens)


def _center_drift(previous: tuple[int, int] | None, current: tuple[int, int] | None) -> float | None:
    if previous is None or current is None:
        return None
    dx = float(current[0] - previous[0])
    dy = float(current[1] - previous[1])
    return round((dx * dx + dy * dy) ** 0.5, 3)


def _bbox_drift(previous: tuple[int, int, int, int] | None, current: tuple[int, int, int, int] | None) -> int | None:
    if previous is None or current is None:
        return None
    return max(abs(current_value - previous_value) for previous_value, current_value in zip(previous, current))


def _drift_summary(center_drift: float | None, bbox_drift: int | None) -> str:
    parts: list[str] = []
    if center_drift is not None:
        parts.append(f"center drift {center_drift:g}px")
    if bbox_drift is not None:
        parts.append(f"bbox drift {bbox_drift}px")
    return ", ".join(parts)


def _tokens_contain_text(tokens: Sequence[DesktopToken], text: str) -> bool:
    needle = _normalize(text)
    if not needle:
        return True
    return any(needle in _normalize(token.text) for token in tokens)


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _observation_id(image: Path, screen_hash: str, created_at: str) -> str:
    if not screen_hash:
        return ""
    seed = f"{image}|{screen_hash}|{created_at}"
    return "obs-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _source_observation_id(tokens: Sequence[DesktopToken], created_at: str) -> str:
    if not tokens:
        return ""
    payload = [_token_hash(token) for token in tokens]
    seed = json.dumps({"tokens": payload, "created_at": created_at}, ensure_ascii=False, sort_keys=True)
    return "obs-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _front_app_from_sources(sources: dict[str, Any]) -> str:
    ax = sources.get("ax")
    if isinstance(ax, dict):
        for key in ("app", "frontmost", "front_app"):
            value = ax.get(key)
            if value:
                return str(value)
    return ""


def _tokenization_record_data(tokenization: DesktopTokenization) -> dict[str, Any]:
    return {
        "artifact_path": tokenization.path,
        "tokens": len(tokenization.tokens),
        "errors": list(tokenization.errors),
        "observation_id": tokenization.observation_id,
        "screen_hash": _short_hash(tokenization.screen_hash),
        "front_app": tokenization.front_app,
    }


def _focused_text_target(tokenization: DesktopTokenization) -> DesktopToken | None:
    candidates: list[DesktopToken] = []
    for token in tokenization.tokens:
        raw = token.raw if isinstance(token.raw, dict) else {}
        if not token.center or not token.bbox:
            continue
        if not _truthy_state(raw.get("focused") or raw.get("focus")):
            continue
        role_text = " ".join(str(part or "") for part in (token.role, raw.get("role"), raw.get("subrole")))
        if not TEXT_INPUT_ROLE_RE.search(role_text):
            continue
        candidates.append(token)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            0 if str(item.source or "").strip().lower() == "ax" else 1,
            -float(item.confidence or 0.0),
            item.token_id,
        ),
    )[0]


def _target_fence_args(token: DesktopToken, tokenization: DesktopTokenization) -> dict[str, Any]:
    return {
        "target_id": token.token_id,
        "target_text": token.text,
        "target_hash": _token_hash(token),
        "observation_id": tokenization.observation_id,
    }


def _short_hash(value: str) -> str:
    return str(value or "")[:12]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _terms(text: str) -> list[str]:
    return [item for item in re.split(r"[\s,，。:：/\\|]+", _normalize(text)) if item]


def _match_score(query: str, terms: Sequence[str], haystack: str) -> float:
    if not query and not terms:
        return 0.0
    if query and query == haystack:
        return 100.0
    if query and query in haystack:
        return 80.0 + min(10, len(query))
    score = 0.0
    for term in terms:
        if term and term in haystack:
            score += 25.0
    return score


def _observe_only(text: str) -> bool:
    lowered = text.lower()
    return any(item in text for item in ("截图", "截屏", "只看", "观察", "记录")) or any(item in lowered for item in ("screenshot", "observe", "capture only"))


def _type_text(text: str) -> str:
    match = TYPE_RE.search(text)
    if not match:
        return ""
    return _strip_tail(match.group(1))


def _hotkey_keys(text: str) -> list[str]:
    match = HOTKEY_RE.search(text)
    if not match:
        return []
    return _hotkey_list(match.group(1))


def _hotkey_list(value: str) -> list[str]:
    return [item for item in re.split(r"[+, ]+", value.strip()) if item]


def _normalized_hotkey_keys(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [key.strip().lower() for key in _hotkey_list(value) if key.strip()]
    if isinstance(value, Mapping):
        return []
    try:
        items = iter(value)
    except TypeError:
        key = str(value).strip().lower()
        return [key] if key else []
    return [key for key in (str(item).strip().lower() for item in items) if key]


def _search_query(text: str) -> str:
    match = SEARCH_RE.search(text)
    if not match:
        return ""
    query = _strip_tail(match.group(1))
    query = re.sub(r"^(?:一下|一下子)\s*", "", query)
    return query.strip(" ：:，,。.")


def _strip_tail(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"\s*(?:并|然后|and)\s*(?:截图|截屏|screenshot|等待|wait).*$", "", value, flags=re.IGNORECASE)
    return value.strip(" ：:，,。.")


def _target_text_from_reason(reason: str) -> str:
    match = re.search(r":\s*(.+)$", str(reason or ""))
    if not match:
        return ""
    return match.group(1).strip(" ：:，,。.")


def _browser_from_text(text: str, *, default: str) -> str:
    lowered = text.lower()
    if "chrome" in lowered:
        return "Google Chrome"
    if "edge" in lowered:
        return "Microsoft Edge"
    if "safari" in lowered:
        return "Safari"
    return default


def _open_app(text: str) -> str:
    match = OPEN_RE.search(text)
    if not match:
        return ""
    app = match.group(1).strip(" ：:，,。.")
    lowered = app.lower()
    if lowered.startswith(("http", "search")) or app.startswith(("搜索", "搜")):
        return ""
    return _browser_from_text(app, default=app)


def _high_risk_reason(goal: str) -> str:
    finding = classify_goal_risk(goal)
    return finding.matched if finding.blocked else ""
