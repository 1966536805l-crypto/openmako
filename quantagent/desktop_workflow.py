from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any, Iterable, Sequence
from urllib.parse import quote_plus

from .approvals import ApprovalCheck, ensure_approval_for_policy
from .branding import PRODUCT_NAME
from .desktop_control import (
    DesktopResult,
    activate_app,
    click_grid_cell,
    desktop_dir,
    helper_dir,
    hotkey,
    latest_grid,
    pointer,
    screenshot,
    screenshot_grid,
    type_text,
    _image_size,
    _osascript,
    _run,
)
from .gui_patterns import GuiTarget, classify_gui_action


DESKTOP_APPROVAL_ACTIONS = frozenset({"activate", "open", "click", "grid-click", "som-click", "move", "type", "hotkey"})


AX_SCRIPT = r'''
on cleanText(v)
    try
        set t to v as text
    on error
        return ""
    end try
    if t is "missing value" then return ""
    set t to my replaceText(t, tab, " ")
    set t to my replaceText(t, linefeed, " ")
    set t to my replaceText(t, return, " ")
    return t
end cleanText

on replaceText(theText, findText, replaceText)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to findText
    set parts to text items of theText
    set AppleScript's text item delimiters to replaceText
    set joined to parts as text
    set AppleScript's text item delimiters to oldDelimiters
    return joined
end replaceText

on safeProp(e, propName)
    try
        if propName is "role" then
            tell application "System Events" to return my cleanText(role of e)
        end if
        if propName is "name" then
            tell application "System Events" to return my cleanText(name of e)
        end if
        if propName is "value" then
            tell application "System Events" to return my cleanText(value of e)
        end if
        if propName is "description" then
            tell application "System Events" to return my cleanText(description of e)
        end if
        if propName is "help" then
            tell application "System Events" to return my cleanText(value of attribute "AXHelp" of e)
        end if
        if propName is "enabled" then
            tell application "System Events" to return my cleanText(enabled of e)
        end if
        if propName is "focused" then
            tell application "System Events" to return my cleanText(focused of e)
        end if
    on error
        return ""
    end try
    return ""
end safeProp

on rowFor(e, depthValue)
    set roleText to my safeProp(e, "role")
    set nameText to my safeProp(e, "name")
    set valueText to my safeProp(e, "value")
    set descText to my safeProp(e, "description")
    set helpText to my safeProp(e, "help")
    set enabledText to my safeProp(e, "enabled")
    set focusedText to my safeProp(e, "focused")
    set xText to ""
    set yText to ""
    set wText to ""
    set hText to ""
    try
        tell application "System Events" to set p to position of e
        set xText to item 1 of p as text
        set yText to item 2 of p as text
    end try
    try
        tell application "System Events" to set s to size of e
        set wText to item 1 of s as text
        set hText to item 2 of s as text
    end try
    return (depthValue as text) & tab & roleText & tab & nameText & tab & valueText & tab & descText & tab & helpText & tab & enabledText & tab & focusedText & tab & xText & tab & yText & tab & wText & tab & hText
end rowFor

on walk(e, depthValue, maxDepth)
    set rowsText to my rowFor(e, depthValue)
    if depthValue < maxDepth then
        try
            tell application "System Events" to set childElements to UI elements of e
            repeat with childElement in childElements
                set rowsText to rowsText & linefeed & my walk(childElement, depthValue + 1, maxDepth)
            end repeat
        end try
    end if
    return rowsText
end walk

tell application "System Events"
    set appName to name of first application process whose frontmost is true
    set header to "depth" & tab & "role" & tab & "title" & tab & "value" & tab & "description" & tab & "help" & tab & "enabled" & tab & "focused" & tab & "x" & tab & "y" & tab & "w" & tab & "h"
    return appName & linefeed & header & linefeed & my walk(process appName, 0, __MAX_DEPTH__)
end tell
'''


OCR_SWIFT_HELPER = r'''
import Foundation
import Vision
import CoreGraphics
import ImageIO

func fail(_ message: String) -> Never {
    fputs(message + "\n", stderr)
    exit(2)
}

if CommandLine.arguments.count < 2 {
    fail("usage: quantagent_ocr IMAGE_PATH")
}

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else {
    fail("could not open image")
}
guard let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fail("could not decode image")
}

let width = Double(image.width)
let height = Double(image.height)
var blocks: [[String: Any]] = []
var requestError: Error?

let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        requestError = error
        return
    }
    let observations = request.results as? [VNRecognizedTextObservation] ?? []
    for observation in observations {
        guard let top = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox
        let x = max(0.0, box.origin.x * width)
        let y = max(0.0, (1.0 - box.origin.y - box.height) * height)
        let w = max(1.0, box.width * width)
        let h = max(1.0, box.height * height)
        blocks.append([
            "text": top.string,
            "confidence": top.confidence,
            "bounds": [Int(x.rounded()), Int(y.rounded()), Int((x + w).rounded()), Int((y + h).rounded())]
        ])
    }
}

request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

do {
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
} catch {
    fail(error.localizedDescription)
}

if let error = requestError {
    fail(error.localizedDescription)
}

let payload: [String: Any] = [
    "image_path": path,
    "width": Int(width),
    "height": Int(height),
    "blocks": blocks
]

let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)
'''


@dataclass(frozen=True)
class DesktopElement:
    element_id: str
    app: str
    depth: int
    role: str = ""
    title: str = ""
    value: str = ""
    description: str = ""
    help: str = ""
    enabled: str = ""
    focused: str = ""
    bounds: tuple[int, int, int, int] | None = None
    source: str = "ax"

    @property
    def label(self) -> str:
        return " ".join(part for part in (self.title, self.value, self.description, self.help) if part).strip()

    def center(self) -> tuple[int, int] | None:
        if not self.bounds:
            return None
        x, y, w, h = self.bounds
        return x + max(1, round(w / 2)), y + max(1, round(h / 2))

    def to_target(self) -> GuiTarget | None:
        center = self.center()
        if center is None:
            return None
        x, y, w, h = self.bounds or (center[0], center[1], 0, 0)
        return GuiTarget(
            kind="coordinate",
            value=center,
            label=self.label or self.role or self.element_id,
            bounds=(x, y, x + w, y + h),
            confidence=0.75,
            source=f"ax:{self.element_id}",
        )

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.bounds:
            payload["bounds"] = list(self.bounds)
        payload["center"] = list(self.center()) if self.center() else None
        payload["label"] = self.label
        return payload


@dataclass(frozen=True)
class DesktopSearchHit:
    source: str
    score: int
    label: str
    target: GuiTarget | None = None
    element: DesktopElement | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "score": self.score,
            "label": self.label,
            "target": self.target.to_payload() if self.target else None,
            "element": self.element.to_payload() if self.element else None,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class DesktopTextBlock:
    block_id: str
    text: str
    bounds: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    source: str = "ocr"

    def center(self) -> tuple[int, int] | None:
        if not self.bounds:
            return None
        x1, y1, x2, y2 = self.bounds
        return round((x1 + x2) / 2), round((y1 + y2) / 2)

    def to_target(self) -> GuiTarget | None:
        center = self.center()
        if center is None:
            return None
        return GuiTarget(
            kind="coordinate",
            value=center,
            label=self.text,
            bounds=self.bounds,
            confidence=max(0.05, min(float(self.confidence), 1.0)),
            source=f"ocr:{self.block_id}",
        )

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.bounds:
            payload["bounds"] = list(self.bounds)
        payload["center"] = list(self.center()) if self.center() else None
        return payload


@dataclass(frozen=True)
class SomTarget:
    mark_id: str
    source: str
    label: str
    target: GuiTarget
    score_hint: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "mark_id": self.mark_id,
            "source": self.source,
            "label": self.label,
            "target": self.target.to_payload(),
            "score_hint": self.score_hint,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class DesktopStep:
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    requires_review: bool = True

    @property
    def side_effect(self) -> bool:
        return self.action in {"activate", "open", "click", "grid-click", "som-click", "move", "type", "hotkey", "wait"}

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopPlan:
    objective: str
    steps: tuple[DesktopStep, ...]
    safety_note: str = "Dry-run by default. Use --execute --reviewed for side effects."
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_payload(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "safety_note": self.safety_note,
            "created_at": self.created_at,
            "steps": [step.to_payload() for step in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class DesktopRun:
    ok: bool
    status: str
    summary: str
    plan: DesktopPlan
    results: tuple[DesktopResult, ...] = ()
    log_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "plan": self.plan.to_payload(),
            "results": [asdict(result) for result in self.results],
            "log_path": self.log_path,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def desktop_step_requires_action_approval(step: DesktopStep) -> bool:
    return step.action in DESKTOP_APPROVAL_ACTIONS


def ensure_desktop_step_approval(
    project: str | Path,
    step: DesktopStep,
    *,
    goal: str = "",
    approval_id: str | None = None,
    expires_at: int | None = None,
) -> ApprovalCheck:
    if not desktop_step_requires_action_approval(step):
        return ApprovalCheck(None, True, False, "desktop approval not required")
    return ensure_approval_for_policy(
        project,
        tool="desktop.step",
        args={
            "goal": " ".join(goal.split()),
            "step": {
                "action": step.action,
                "args": _approval_safe_step_args(step),
                "reason": step.reason,
                "requires_review": step.requires_review,
            },
        },
        policy={
            "profile": "desktop",
            "tool": "desktop.step",
            "action": "ask",
            "policy_reason": "desktop side-effect action requires explicit per-action approval",
        },
        reason=f"desktop side-effect action requires approval: {step.action}",
        approval_id=approval_id,
        expires_at=expires_at,
    )


def plan_open_target(
    project: Path,
    target: str,
    *,
    kind: str = "auto",
    browser: str = "",
    cwd: str = "",
) -> DesktopPlan:
    resolved_kind, args = _resolve_open_target(project, target, kind=kind, browser=browser, cwd=cwd)
    label = args.get("label") or target or resolved_kind
    return DesktopPlan(
        f"open {label}",
        (
            DesktopStep("open", args, f"open {resolved_kind}: {label}"),
            DesktopStep("wait", {"seconds": 0.5}, "wait for app/window", requires_review=False),
            DesktopStep("screenshot", {}, "capture after open", requires_review=False),
        ),
    )


def open_target(
    project: Path,
    target: str,
    *,
    kind: str = "auto",
    browser: str = "",
    cwd: str = "",
    execute: bool = False,
    reviewed: bool = False,
) -> DesktopRun:
    plan = plan_open_target(project, target, kind=kind, browser=browser, cwd=cwd)
    return execute_desktop_plan(project, plan, execute=execute, reviewed=reviewed)


def ax_snapshot(project: Path, *, max_depth: int = 4, limit: int = 500, name: str | None = None) -> DesktopResult:
    depth = max(1, min(max_depth, 8))
    script = AX_SCRIPT.replace("__MAX_DEPTH__", str(depth))
    timeout = 25
    try:
        proc = _osascript(script, timeout=timeout)
    except TimeoutExpired as exc:
        return DesktopResult(
            "ax",
            False,
            f"AX snapshot timed out after {float(exc.timeout or timeout):g}s",
            {"status": "timeout", "timeout": float(exc.timeout or timeout), "permission_kind": "accessibility"},
        )
    except OSError as exc:
        return DesktopResult(
            "ax",
            False,
            f"AX snapshot failed: {type(exc).__name__}: {exc}",
            {"status": "error", "error_type": type(exc).__name__, "permission_kind": "accessibility"},
        )
    if proc.returncode != 0:
        return DesktopResult("ax", False, proc.stderr.strip() or proc.stdout.strip() or "AX snapshot failed")

    elements = parse_ax_snapshot(proc.stdout, limit=limit)
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    filename = name or f"ax_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = directory / filename
    path.write_text(
        json.dumps(
            {
                "app": elements[0].app if elements else "",
                "max_depth": depth,
                "limit": limit,
                "elements": [element.to_payload() for element in elements],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return DesktopResult("ax", True, f"ax snapshot: {path}", {"path": str(path), "elements": len(elements)})


def parse_ax_snapshot(text: str, *, limit: int = 500) -> list[DesktopElement]:
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    app = lines[0].strip()
    elements: list[DesktopElement] = []
    for index, line in enumerate(lines[2:]):
        fields = (line.split("\t") + [""] * 12)[:12]
        depth, role, title, value, description, help_text, enabled, focused, x, y, w, h = fields
        bounds = _bounds_from_fields(x, y, w, h)
        elements.append(
            DesktopElement(
                element_id=f"AX{index + 1:04d}",
                app=app,
                depth=_safe_int(depth, 0),
                role=role.strip(),
                title=title.strip(),
                value=value.strip(),
                description=description.strip(),
                help=help_text.strip(),
                enabled=enabled.strip(),
                focused=focused.strip(),
                bounds=bounds,
            )
        )
        if len(elements) >= limit:
            break
    return elements


def latest_ax(project: Path) -> Path | None:
    directory = desktop_dir(project)
    if not directory.exists():
        return None
    snapshots = sorted(directory.glob("ax_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def load_ax_elements(path: Path) -> list[DesktopElement]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    app = str(payload.get("app", "") or "")
    elements: list[DesktopElement] = []
    for index, raw in enumerate(payload.get("elements", [])):
        if not isinstance(raw, dict):
            continue
        bounds_raw = raw.get("bounds")
        bounds = None
        if isinstance(bounds_raw, list) and len(bounds_raw) == 4:
            bounds = tuple(int(item) for item in bounds_raw)  # type: ignore[assignment]
        elements.append(
            DesktopElement(
                element_id=str(raw.get("element_id") or f"AX{index + 1:04d}"),
                app=str(raw.get("app") or app),
                depth=int(raw.get("depth") or 0),
                role=str(raw.get("role") or ""),
                title=str(raw.get("title") or ""),
                value=str(raw.get("value") or ""),
                description=str(raw.get("description") or ""),
                help=str(raw.get("help") or ""),
                enabled=str(raw.get("enabled") or ""),
                focused=str(raw.get("focused") or ""),
                bounds=bounds,
                source=str(raw.get("source") or "ax"),
            )
        )
    return elements


def ensure_ocr_helper(project: Path) -> Path:
    directory = helper_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "quantagent_ocr.swift"
    binary = directory / "quantagent_ocr"
    if binary.exists():
        return binary
    source.write_text(OCR_SWIFT_HELPER.strip() + "\n", encoding="utf-8")
    proc = _run(["swiftc", source, "-o", binary], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "swiftc failed")
    return binary


def ocr_image(project: Path, image_path: str | Path | None = None, *, name: str | None = None) -> DesktopResult:
    if image_path is None:
        shot = screenshot(project)
        if not shot.ok:
            return shot
        image = Path(str(shot.data["path"]))
    else:
        image = Path(image_path).expanduser()
        if not image.is_absolute():
            image = desktop_dir(project) / image
    if not image.exists():
        return DesktopResult("ocr", False, f"image not found: {image}")
    try:
        helper = ensure_ocr_helper(project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:532", exc)
        return DesktopResult("ocr", False, f"OCR helper unavailable: {exc}", {"image_path": str(image)})
    proc = _run([helper, image], timeout=60)
    if proc.returncode != 0:
        return DesktopResult("ocr", False, proc.stderr.strip() or proc.stdout.strip() or "OCR failed", {"image_path": str(image)})
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return DesktopResult("ocr", False, f"OCR returned invalid JSON: {exc}", {"stdout": proc.stdout[:1000], "image_path": str(image)})
    blocks = parse_ocr_payload(payload)
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    filename = name or f"ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = directory / filename
    width = int(payload.get("width") or 0)
    height = int(payload.get("height") or 0)
    if width <= 0 or height <= 0:
        try:
            width, height = _image_size(image)
        except Exception:
            width = height = 0
    path.write_text(
        json.dumps(
            {
                "image_path": str(image),
                "width": width,
                "height": height,
                "blocks": [block.to_payload() for block in blocks],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return DesktopResult("ocr", True, f"OCR: {path}", {"path": str(path), "image_path": str(image), "blocks": len(blocks)})


def parse_ocr_payload(payload: dict[str, Any]) -> list[DesktopTextBlock]:
    blocks: list[DesktopTextBlock] = []
    for index, raw in enumerate(payload.get("blocks", [])):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        bounds = _payload_bounds(raw.get("bounds"))
        confidence = raw.get("confidence")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        blocks.append(
            DesktopTextBlock(
                block_id=str(raw.get("block_id") or f"OCR{index + 1:04d}"),
                text=text,
                bounds=bounds,
                confidence=confidence_value,
            )
        )
    return blocks


def load_ocr_blocks(path: Path) -> list[DesktopTextBlock]:
    return parse_ocr_payload(json.loads(path.read_text(encoding="utf-8")))


def latest_ocr(project: Path) -> Path | None:
    directory = desktop_dir(project)
    if not directory.exists():
        return None
    snapshots = sorted(directory.glob("ocr_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def search_ocr_blocks(blocks: Iterable[DesktopTextBlock], query: str, *, limit: int = 10) -> list[DesktopSearchHit]:
    tokens = _tokens(query)
    normalized_query = _normalize(query)
    hits: list[DesktopSearchHit] = []
    for block in blocks:
        haystack = _normalize(block.text)
        score = _match_score(normalized_query, tokens, haystack)
        if score <= 0:
            continue
        target = block.to_target()
        if target:
            score += 15
        score += round(max(0.0, min(block.confidence, 1.0)) * 10)
        hits.append(DesktopSearchHit("ocr", score, block.text, target=target, payload=block.to_payload()))
    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:limit]


def search_ax_elements(elements: Iterable[DesktopElement], query: str, *, limit: int = 10) -> list[DesktopSearchHit]:
    tokens = _tokens(query)
    normalized_query = _normalize(query)
    hits: list[DesktopSearchHit] = []
    for element in elements:
        label = element.label
        if not label and not element.role:
            continue
        haystack = _normalize(" ".join([label, element.role]))
        score = _match_score(normalized_query, tokens, haystack)
        if score <= 0:
            continue
        target = element.to_target()
        if target:
            score += 20
        if element.focused.lower() == "true":
            score += 10
        hits.append(DesktopSearchHit("ax", score, label or element.role, target=target, element=element))
    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:limit]


def search_grid_payload(grid_payload: dict[str, Any], query: str, *, limit: int = 10) -> list[DesktopSearchHit]:
    tokens = _tokens(query)
    normalized_query = _normalize(query)
    hits: list[DesktopSearchHit] = []
    for cell in grid_payload.get("cells", []):
        if not isinstance(cell, dict):
            continue
        label = _grid_label(cell)
        cell_id = str(cell.get("id", "") or "").upper()
        haystack = _normalize(" ".join([cell_id, label]))
        score = _match_score(normalized_query, tokens, haystack)
        if score <= 0:
            continue
        target = GuiTarget("grid_cell", cell_id, label=label or f"grid {cell_id}", bounds=_cell_bounds(cell), confidence=0.65, source="grid")
        hits.append(DesktopSearchHit("grid", score, label or cell_id, target=target, payload=dict(cell)))
    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:limit]


def som_capture(
    project: Path,
    *,
    image_path: str | Path | None = None,
    include_ax: bool = True,
    include_ocr: bool = True,
    include_grid: bool = False,
    cols: int = 12,
    rows: int = 8,
    name: str | None = None,
) -> DesktopResult:
    if image_path is None:
        shot = screenshot(project, name=f"som_shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        if not shot.ok:
            return shot
        image = Path(str(shot.data["path"]))
    else:
        image = Path(image_path).expanduser()
        if not image.is_absolute():
            image = desktop_dir(project) / image
    if not image.exists():
        return DesktopResult("som", False, f"image not found: {image}")
    try:
        width, height = _image_size(image)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:687", exc)
        return DesktopResult("som", False, f"could not read image size: {exc}", {"image_path": str(image)})

    ax_elements: list[DesktopElement] = []
    ocr_blocks: list[DesktopTextBlock] = []
    errors: list[str] = []
    if include_ax:
        ax = ax_snapshot(project)
        if ax.ok:
            ax_elements = load_ax_elements(Path(str(ax.data["path"])))
        else:
            errors.append(ax.summary)
    if include_ocr:
        ocr = ocr_image(project, image)
        if ocr.ok:
            ocr_blocks = load_ocr_blocks(Path(str(ocr.data["path"])))
        else:
            errors.append(ocr.summary)

    grid_payload = build_grid_payload_for_image(image, width, height, cols=cols, rows=rows) if include_grid else None
    targets = build_som_targets(
        image_path=image,
        width=width,
        height=height,
        ax_elements=ax_elements,
        ocr_blocks=ocr_blocks,
        grid_payload=grid_payload,
        include_grid=include_grid,
    )
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    stem = name or f"som_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    json_path = directory / (stem if stem.endswith(".json") else f"{stem}.json")
    html_path = json_path.with_suffix(".html")
    payload = {
        "image_path": str(image),
        "width": width,
        "height": height,
        "targets": [target.to_payload() for target in targets],
        "errors": errors,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(_som_html(image, width, height, targets, errors), encoding="utf-8")
    return DesktopResult(
        "som",
        bool(targets),
        f"SoM: {html_path}",
        {"path": str(json_path), "html": str(html_path), "image_path": str(image), "targets": len(targets), "errors": errors},
    )


def build_grid_payload_for_image(image_path: Path, width: int, height: int, *, cols: int = 12, rows: int = 8) -> dict[str, Any]:
    cols = max(2, min(cols, 32))
    rows = max(2, min(rows, 32))
    cell_w = width / cols
    cell_h = height / rows
    cells: list[dict[str, Any]] = []
    for row in range(rows):
        for col in range(cols):
            x1 = round(col * cell_w)
            y1 = round(row * cell_h)
            x2 = round((col + 1) * cell_w)
            y2 = round((row + 1) * cell_h)
            cells.append(
                {
                    "id": _cell_name(row, col),
                    "row": row + 1,
                    "col": col + 1,
                    "x": round((x1 + x2) / 2),
                    "y": round((y1 + y2) / 2),
                    "bounds": [x1, y1, x2, y2],
                }
            )
    return {"image_path": str(image_path), "width": width, "height": height, "cols": cols, "rows": rows, "cells": cells}


def build_som_targets(
    *,
    image_path: Path,
    width: int,
    height: int,
    ax_elements: Iterable[DesktopElement] = (),
    ocr_blocks: Iterable[DesktopTextBlock] = (),
    grid_payload: dict[str, Any] | None = None,
    include_grid: bool = False,
    limit: int = 220,
) -> list[SomTarget]:
    raw: list[tuple[str, str, GuiTarget, int, dict[str, Any]]] = []
    for element in ax_elements:
        target = element.to_target()
        if not target or not _target_in_bounds(target, width, height):
            continue
        label = element.label or element.role or element.element_id
        raw.append(("ax", label, target, 90 - min(element.depth, 8), {"element_id": element.element_id, "role": element.role}))
    for block in ocr_blocks:
        target = block.to_target()
        if not target or not _target_in_bounds(target, width, height):
            continue
        raw.append(("ocr", block.text, target, 70 + round(block.confidence * 10), {"block_id": block.block_id, "confidence": block.confidence}))
    if include_grid and grid_payload:
        for cell in grid_payload.get("cells", []):
            if not isinstance(cell, dict):
                continue
            cell_id = str(cell.get("id") or "").upper()
            if not cell_id:
                continue
            target = GuiTarget("grid_cell", cell_id, label=f"grid {cell_id}", bounds=_cell_bounds(cell), confidence=0.45, source="grid")
            if not _target_in_bounds(target, width, height):
                continue
            raw.append(("grid", cell_id, target, 20, {"cell": cell}))

    deduped: list[tuple[str, str, GuiTarget, int, dict[str, Any]]] = []
    seen: set[tuple[int, int, str]] = set()
    for source, label, target, score_hint, payload in sorted(raw, key=lambda item: (-item[3], item[0], item[1])):
        center = target.center()
        if not center:
            continue
        key = (round(center[0] / 8), round(center[1] / 8), _normalize(label)[:30])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((source, label, target, score_hint, payload))
        if len(deduped) >= limit:
            break
    return [
        SomTarget(f"M{index + 1:03d}", source, label, target, score_hint, payload)
        for index, (source, label, target, score_hint, payload) in enumerate(deduped)
    ]


def latest_som(project: Path) -> Path | None:
    directory = desktop_dir(project)
    if not directory.exists():
        return None
    snapshots = sorted(directory.glob("som_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return snapshots[0] if snapshots else None


def load_som_targets(path: Path) -> list[SomTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets: list[SomTarget] = []
    for index, raw in enumerate(payload.get("targets", [])):
        if not isinstance(raw, dict):
            continue
        target_payload = raw.get("target")
        if not isinstance(target_payload, dict):
            continue
        target = _target_from_payload(target_payload)
        if target is None:
            continue
        targets.append(
            SomTarget(
                str(raw.get("mark_id") or f"M{index + 1:03d}"),
                str(raw.get("source") or "som"),
                str(raw.get("label") or ""),
                target,
                int(raw.get("score_hint") or 0),
                dict(raw.get("payload") or {}),
            )
        )
    return targets


def search_som_targets(targets: Iterable[SomTarget], query: str, *, limit: int = 10) -> list[DesktopSearchHit]:
    tokens = _tokens(query)
    normalized_query = _normalize(query)
    hits: list[DesktopSearchHit] = []
    for target in targets:
        haystack = _normalize(" ".join([target.mark_id, target.label, target.source]))
        score = _match_score(normalized_query, tokens, haystack)
        if score <= 0:
            continue
        score += target.score_hint
        hits.append(
            DesktopSearchHit(
                "som",
                score,
                f"{target.mark_id} {target.label}".strip(),
                target=target.target,
                payload=target.to_payload(),
            )
        )
    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:limit]


def desktop_find(
    project: Path,
    query: str,
    *,
    source: str = "all",
    limit: int = 10,
    ax_path: str | None = None,
    grid_path: str | None = None,
    ocr_path: str | None = None,
    som_path: str | None = None,
    refresh_ax: bool = False,
    refresh_som: bool = False,
) -> DesktopResult:
    hits: list[DesktopSearchHit] = []
    errors: list[str] = []
    selected = "all" if source == "both" else source

    if selected in {"ax", "all"}:
        path = Path(ax_path).expanduser() if ax_path else latest_ax(project)
        if refresh_ax or path is None:
            snap = ax_snapshot(project)
            if snap.ok:
                path = Path(str(snap.data["path"]))
            else:
                errors.append(snap.summary)
        if path and path.exists():
            try:
                hits.extend(search_ax_elements(load_ax_elements(path), query, limit=limit))
            except Exception as exc:
                errors.append(f"ax search failed: {type(exc).__name__}: {exc}")

    if selected in {"ocr", "all"}:
        path = Path(ocr_path).expanduser() if ocr_path else latest_ocr(project)
        if path and path.exists():
            try:
                hits.extend(search_ocr_blocks(load_ocr_blocks(path), query, limit=limit))
            except Exception as exc:
                errors.append(f"OCR search failed: {type(exc).__name__}: {exc}")

    if selected in {"som", "all"}:
        path = Path(som_path).expanduser() if som_path else latest_som(project)
        if refresh_som or path is None:
            som = som_capture(project, include_grid=False)
            if som.ok:
                path = Path(str(som.data["path"]))
            else:
                errors.append(som.summary)
        if path and path.exists():
            try:
                hits.extend(search_som_targets(load_som_targets(path), query, limit=limit))
            except Exception as exc:
                errors.append(f"SoM search failed: {type(exc).__name__}: {exc}")

    if selected in {"grid", "all"}:
        path = Path(grid_path).expanduser() if grid_path else latest_grid(project)
        if path and path.exists():
            try:
                hits.extend(search_grid_payload(json.loads(path.read_text(encoding="utf-8")), query, limit=limit))
            except Exception as exc:
                errors.append(f"grid search failed: {type(exc).__name__}: {exc}")

    ordered = sorted(hits, key=lambda hit: (-hit.score, hit.source, hit.label))[:limit]
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / f"find_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "query": query,
        "source": source,
        "hits": [hit.to_payload() for hit in ordered],
        "errors": errors,
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = bool(ordered)
    summary = f"{len(ordered)} desktop target(s) for {query!r}: {result_path}" if ok else f"no desktop target found for {query!r}"
    return DesktopResult("find", ok, summary, {"path": str(result_path), "hits": payload["hits"], "errors": errors})


def render_desktop_hits(result: DesktopResult) -> str:
    lines = ["# Desktop Search", "", f"Status: {'ok' if result.ok else 'no-match'}", result.summary]
    hits = result.data.get("hits", [])
    if isinstance(hits, list) and hits:
        lines.extend(["", "Hits:"])
        for item in hits[:10]:
            if not isinstance(item, dict):
                continue
            target = item.get("target") or {}
            coord = ""
            if isinstance(target, dict):
                center = target.get("value") if target.get("kind") == "coordinate" else None
                if isinstance(center, list) and len(center) == 2:
                    coord = f" at {center[0]},{center[1]}"
            lines.append(f"- {item.get('source')} score={item.get('score')}: {item.get('label')}{coord}")
    errors = result.data.get("errors", [])
    if isinstance(errors, list) and errors:
        lines.extend(["", "Notes:", *[f"- {err}" for err in errors[:5]]])
    return "\n".join(lines).rstrip() + "\n"


def plan_web_search(query: str, *, browser: str = "Safari", engine: str = "google") -> DesktopPlan:
    url = search_url(query, engine=engine)
    steps = (
        DesktopStep("activate", {"app": browser}, f"focus {browser}"),
        DesktopStep("hotkey", {"keys": ["cmd", "l"]}, "focus address/search bar"),
        DesktopStep("type", {"text": url}, "type search URL"),
        DesktopStep("hotkey", {"keys": ["return"]}, "submit search"),
        DesktopStep("wait", {"seconds": 1.0}, "wait for browser navigation", requires_review=False),
        DesktopStep("screenshot", {}, "capture search result page", requires_review=False),
    )
    return DesktopPlan(f"web search: {query}", steps)


def plan_find_and_click(project: Path, query: str, *, source: str = "all") -> DesktopPlan:
    find_result = desktop_find(project, query, source=source, refresh_ax=False)
    steps = [DesktopStep("find", {"query": query, "source": source}, "locate desktop target", requires_review=False)]
    hits = find_result.data.get("hits", [])
    first = hits[0] if isinstance(hits, list) and hits else None
    target = first.get("target") if isinstance(first, dict) else None
    if isinstance(target, dict):
        kind = target.get("kind")
        value = target.get("value")
        if kind == "grid_cell" and value:
            steps.append(DesktopStep("grid-click", {"cell": value}, f"click matched grid target {value}"))
        elif kind == "coordinate" and isinstance(value, list) and len(value) == 2:
            steps.append(DesktopStep("click", {"x": int(value[0]), "y": int(value[1])}, "click matched AX coordinate"))
    steps.append(DesktopStep("screenshot", {}, "capture after click", requires_review=False))
    return DesktopPlan(f"find and click: {query}", tuple(steps))


def execute_desktop_plan(
    project: Path,
    plan: DesktopPlan,
    *,
    execute: bool = False,
    reviewed: bool = False,
    verify_after: bool = False,
) -> DesktopRun:
    if not execute:
        return _write_run(project, DesktopRun(True, "preview", f"dry-run preview: {len(plan.steps)} step(s)", plan))

    results: list[DesktopResult] = []
    for index, step in enumerate(plan.steps, start=1):
        if step.side_effect and not reviewed:
            blocked = DesktopRun(
                False,
                "blocked",
                f"step {index} {step.action} requires --reviewed",
                plan,
                tuple(results),
            )
            return _write_run(project, blocked)
        result = _execute_step(project, step)
        results.append(result)
        if not result.ok:
            failed = DesktopRun(False, "failed", f"step {index} {step.action} failed: {result.summary}", plan, tuple(results))
            return _write_run(project, failed)
        if verify_after and step.side_effect:
            verify = _verify_after_step(project, step, index)
            results.extend(verify)
            failed_verify = next((item for item in verify if not item.ok), None)
            if failed_verify is not None:
                failed = DesktopRun(False, "verify_failed", failed_verify.summary, plan, tuple(results))
                return _write_run(project, failed)
    return _write_run(project, DesktopRun(True, "executed", f"executed {len(results)} desktop step(s)", plan, tuple(results)))


def render_desktop_plan(plan: DesktopPlan) -> str:
    lines = ["# Desktop Plan", "", f"Objective: {plan.objective}", f"Safety: {plan.safety_note}", "", "Steps:"]
    for index, step in enumerate(plan.steps, start=1):
        review = "reviewed" if step.side_effect or step.requires_review else "auto"
        args = json.dumps(step.args, ensure_ascii=False)
        reason = f" - {step.reason}" if step.reason else ""
        lines.append(f"{index}. {step.action} [{review}] {args}{reason}")
    return "\n".join(lines).rstrip() + "\n"


def render_desktop_run(run: DesktopRun) -> str:
    lines = ["# Desktop Run", "", f"Status: {run.status}", f"OK: {str(run.ok).lower()}", run.summary]
    if run.log_path:
        lines.append(f"Log: {run.log_path}")
    if run.results:
        lines.extend(["", "Results:"])
        for result in run.results:
            lines.append(f"- {result.action}: {'ok' if result.ok else 'fail'} - {result.summary}")
    return "\n".join(lines).rstrip() + "\n"


def load_desktop_plan(path: Path) -> DesktopPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    steps = []
    for raw in payload.get("steps", []):
        if not isinstance(raw, dict):
            continue
        steps.append(
            DesktopStep(
                str(raw.get("action") or ""),
                dict(raw.get("args") or {}),
                str(raw.get("reason") or ""),
                bool(raw.get("requires_review", True)),
            )
        )
    return DesktopPlan(
        objective=str(payload.get("objective") or path.name),
        steps=tuple(steps),
        safety_note=str(payload.get("safety_note") or "Dry-run by default. Use --execute --reviewed for side effects."),
        created_at=str(payload.get("created_at") or datetime.now().isoformat(timespec="seconds")),
    )


def search_url(query: str, *, engine: str = "google") -> str:
    encoded = quote_plus(query.strip())
    selected = engine.strip().lower()
    if selected in {"ddg", "duckduckgo"}:
        return f"https://duckduckgo.com/?q={encoded}"
    if selected == "bing":
        return f"https://www.bing.com/search?q={encoded}"
    return f"https://www.google.com/search?q={encoded}"


def _execute_step(project: Path, step: DesktopStep) -> DesktopResult:
    action = step.action
    args = step.args
    if action == "activate":
        return activate_app(str(args.get("app") or ""))
    if action == "open":
        return _execute_open_step(project, args)
    if action == "screenshot":
        if args.get("grid"):
            return screenshot_grid(project, cols=int(args.get("cols") or 12), rows=int(args.get("rows") or 8))
        return screenshot(project)
    if action == "ax":
        return ax_snapshot(project, max_depth=int(args.get("max_depth") or 4), limit=int(args.get("limit") or 500))
    if action == "ocr":
        return ocr_image(project, image_path=args.get("image"))
    if action == "som":
        return som_capture(
            project,
            image_path=args.get("image"),
            include_ax=bool(args.get("include_ax", True)),
            include_ocr=bool(args.get("include_ocr", True)),
            include_grid=bool(args.get("include_grid", False)),
            cols=int(args.get("cols") or 12),
            rows=int(args.get("rows") or 8),
        )
    if action == "find":
        return desktop_find(
            project,
            str(args.get("query") or ""),
            source=str(args.get("source") or "all"),
            refresh_ax=bool(args.get("refresh_ax")),
            refresh_som=bool(args.get("refresh_som")),
        )
    if action == "click":
        target = GuiTarget("coordinate", (int(args.get("x") or 0), int(args.get("y") or 0)))
        safety, reason = classify_gui_action("click", target=target)
        if safety == "deny":
            return DesktopResult("click", False, reason)
        return pointer(project, "click", int(args.get("x") or 0), int(args.get("y") or 0))
    if action == "move":
        return pointer(project, "move", int(args.get("x") or 0), int(args.get("y") or 0))
    if action == "grid-click":
        return click_grid_cell(project, str(args.get("cell") or ""), grid_path=args.get("grid"))
    if action == "som-click":
        return click_som_target(project, str(args.get("mark") or args.get("target") or ""), som_path=args.get("som"))
    if action == "type":
        safety, reason = classify_gui_action("type", text=str(args.get("text") or ""))
        if safety == "deny":
            return DesktopResult("type", False, reason)
        return type_text(str(args.get("text") or ""))
    if action == "hotkey":
        keys = args.get("keys")
        if isinstance(keys, str):
            keys = re.split(r"[+, ]+", keys)
        return hotkey([str(key) for key in (keys or [])])
    if action == "wait":
        seconds = max(0.0, min(float(args.get("seconds") or 1.0), 10.0))
        time.sleep(seconds)
        return DesktopResult("wait", True, f"waited {seconds:g}s", {"seconds": seconds})
    return DesktopResult(action or "desktop", False, f"unsupported desktop step: {action}")


def _approval_safe_step_args(step: DesktopStep) -> dict[str, Any]:
    if step.action != "type":
        return dict(step.args)
    text = str(step.args.get("text") or "")
    safe_args = dict(step.args)
    safe_args.pop("text", None)
    safe_args["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    safe_args["text_length"] = len(text)
    safe_args["text_preview"] = _redact_approval_text(text)
    return safe_args


def _redact_approval_text(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    if len(compact) <= 24:
        return compact
    return f"{compact[:12]}...{compact[-8:]}"


def click_som_target(project: Path, mark_id: str, *, som_path: str | None = None) -> DesktopResult:
    path = Path(som_path).expanduser() if som_path else latest_som(project)
    if not path:
        return DesktopResult("som-click", False, "no SoM file found; run `mako desktop som` first")
    if not path.is_absolute():
        path = desktop_dir(project) / path
    try:
        targets = load_som_targets(path)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:1160", exc)
        return DesktopResult("som-click", False, f"could not read SoM: {exc}", {"som_json": str(path)})
    wanted = mark_id.strip().upper()
    for target in targets:
        if target.mark_id.upper() != wanted:
            continue
        center = target.target.center()
        if center is None:
            return DesktopResult("som-click", False, f"SoM target has no coordinate: {mark_id}", {"som_json": str(path)})
        return pointer(project, "click", center[0], center[1])
    return DesktopResult("som-click", False, f"SoM target not found: {mark_id}", {"som_json": str(path)})


def _verify_after_step(project: Path, step: DesktopStep, index: int) -> list[DesktopResult]:
    results = [screenshot(project, name=f"verify_{index:02d}_{step.action}_{datetime.now().strftime('%H%M%S')}.png")]
    query = str(step.args.get("verify_query") or "")
    if query:
        results.append(desktop_find(project, query, source=str(step.args.get("verify_source") or "all"), refresh_som=True))
    return results


def _execute_open_step(project: Path, args: dict[str, Any]) -> DesktopResult:
    kind = str(args.get("kind") or "auto")
    command = args.get("command")
    if not isinstance(command, list) or not command:
        return DesktopResult("open", False, "open step has no command")
    proc = _run([str(item) for item in command], timeout=20)
    label = str(args.get("label") or kind)
    return DesktopResult(
        "open",
        proc.returncode == 0,
        f"opened {label}" if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip() or f"open failed: {label}"),
        {"kind": kind, "label": label, "command": command, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()},
    )


def _write_run(project: Path, run: DesktopRun) -> DesktopRun:
    directory = desktop_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = run.to_payload()
    payload["log_path"] = str(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return DesktopRun(run.ok, run.status, run.summary, run.plan, run.results, str(path))


def _som_html(image_path: Path, width: int, height: int, targets: Sequence[SomTarget], errors: Sequence[str]) -> str:
    marks: list[str] = []
    for item in targets:
        bounds = item.target.bounds
        center = item.target.center()
        if bounds:
            x1, y1, x2, y2 = bounds
            marks.append(
                f'<div class="box {escape(item.source)}" style="left:{x1}px;top:{y1}px;width:{max(1, x2 - x1)}px;height:{max(1, y2 - y1)}px;"></div>'
            )
        if center:
            x, y = center
            label = escape(item.mark_id)
            title = escape(f"{item.mark_id} {item.source}: {item.label}")
            marks.append(f'<div class="mark {escape(item.source)}" title="{title}" style="left:{x}px;top:{y}px;">{label}</div>')
    error_html = ""
    if errors:
        error_html = "<div class=\"notes\">" + "".join(f"<p>{escape(err)}</p>" for err in errors[:5]) + "</div>"
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{PRODUCT_NAME} SoM</title>
<style>
body {{ margin: 0; background: #151515; color: #eee; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }}
.bar {{ padding: 8px 10px; background: #202020; position: sticky; top: 0; z-index: 5; }}
.wrap {{ position: relative; width: {width}px; height: {height}px; }}
img {{ position: absolute; left: 0; top: 0; width: {width}px; height: {height}px; }}
.box {{ position: absolute; box-sizing: border-box; border: 1px solid rgba(0, 200, 255, .65); background: rgba(0, 200, 255, .05); }}
.box.ocr {{ border-color: rgba(255, 180, 30, .7); background: rgba(255, 180, 30, .06); }}
.box.grid {{ border-color: rgba(190, 190, 190, .35); background: transparent; }}
.mark {{ position: absolute; transform: translate(-50%, -50%); min-width: 26px; height: 18px; padding: 0 4px; border-radius: 4px; background: #006d9c; color: #fff; font: 12px/18px ui-monospace, SFMono-Regular, Menlo, monospace; text-align: center; box-shadow: 0 1px 5px rgba(0,0,0,.55); }}
.mark.ocr {{ background: #9c6200; }}
.mark.grid {{ background: #555; }}
.notes {{ padding: 8px 10px; background: #331f1f; color: #ffd8d8; }}
.notes p {{ margin: 0 0 4px; }}
</style>
</head>
<body>
<div class="bar">{PRODUCT_NAME} SoM targets: {len(targets)}. Use M ids from the JSON/HTML for reviewed clicks.</div>
{error_html}
<div class="wrap">
<img src="{escape(image_path.name)}" alt="screenshot">
{''.join(marks)}
</div>
</body>
</html>
"""


def _resolve_open_target(project: Path, target: str, *, kind: str = "auto", browser: str = "", cwd: str = "") -> tuple[str, dict[str, Any]]:
    selected = (kind or "auto").strip().lower()
    raw_target = str(target or "").strip()
    raw_cwd = str(cwd or "").strip()
    if selected == "terminal" or raw_target.lower() in {"terminal", "终端", "iterm", "iterm2"}:
        app = "iTerm" if raw_target.lower() in {"iterm", "iterm2"} else "Terminal"
        directory = _resolve_project_path(project, raw_cwd or ".")
        return "terminal", {"kind": "terminal", "label": f"{app} at {directory}", "command": ["open", "-a", app, str(directory)]}

    if selected == "search":
        url = search_url(raw_target, engine=browser or "google")
        return "url", {"kind": "url", "label": url, "command": _open_url_command(url, browser="")}

    if selected == "url" or _looks_like_url(raw_target):
        url = raw_target if _looks_like_url(raw_target) else "https://" + raw_target
        return "url", {"kind": "url", "label": url, "command": _open_url_command(url, browser=browser)}

    if selected == "app" or (selected == "auto" and raw_target and not _looks_like_path(raw_target)):
        app = _app_alias(raw_target)
        return "app", {"kind": "app", "label": app, "command": ["open", "-a", app]}

    path = _resolve_project_path(project, raw_target or raw_cwd or ".")
    return "path", {"kind": "path", "label": str(path), "command": ["open", str(path)]}


def _open_url_command(url: str, *, browser: str = "") -> list[str]:
    if browser:
        return ["open", "-a", _app_alias(browser), url]
    return ["open", url]


def _resolve_project_path(project: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project / path
    return path.resolve(strict=False)


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "file://")) or bool(re.match(r"^[\w.-]+\.[a-z]{2,}(?:/|$)", lowered))


def _looks_like_path(value: str) -> bool:
    return value.startswith(("/", "~", ".", "AI_")) or "/" in value or "\\" in value


def _app_alias(value: str) -> str:
    aliases = {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "谷歌浏览器": "Google Chrome",
        "edge": "Microsoft Edge",
        "microsoft edge": "Microsoft Edge",
        "edge浏览器": "Microsoft Edge",
        "微软浏览器": "Microsoft Edge",
        "safari": "Safari",
        "finder": "Finder",
        "terminal": "Terminal",
        "终端": "Terminal",
        "iterm": "iTerm",
        "iterm2": "iTerm",
        "cursor": "Cursor",
        "vscode": "Visual Studio Code",
        "code": "Visual Studio Code",
    }
    key = value.strip().lower()
    return aliases.get(key, value.strip() or "Finder")


def _bounds_from_fields(x: str, y: str, w: str, h: str) -> tuple[int, int, int, int] | None:
    values = [_safe_int(item, -1) for item in (x, y, w, h)]
    if values[0] < 0 or values[1] < 0 or values[2] <= 0 or values[3] <= 0:
        return None
    return values[0], values[1], values[2], values[3]


def _safe_int(value: str, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _payload_bounds(raw: Any) -> tuple[int, int, int, int] | None:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 4:
        try:
            x1, y1, x2, y2 = [int(item) for item in raw]
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return x1, y1, x2, y2
    return None


def _target_from_payload(payload: dict[str, Any]) -> GuiTarget | None:
    kind = str(payload.get("kind") or "")
    value = payload.get("value")
    bounds = _payload_bounds(payload.get("bounds"))
    if kind == "coordinate":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
            return None
        try:
            parsed_value: str | int | tuple[int, int] = (int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            return None
    elif kind == "som_element":
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            return None
    elif kind in {"grid_cell", "dom_selector", "text_query", "app_window"}:
        parsed_value = str(value or "")
        if not parsed_value:
            return None
    else:
        return None
    confidence = payload.get("confidence")
    try:
        confidence_value = None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        confidence_value = None
    return GuiTarget(
        kind=kind,  # type: ignore[arg-type]
        value=parsed_value,
        label=str(payload.get("label") or ""),
        bounds=bounds,
        confidence=confidence_value,
        source=str(payload.get("source") or ""),
    )


def _target_in_bounds(target: GuiTarget, width: int, height: int) -> bool:
    center = target.center()
    if center is None:
        return False
    x, y = center
    return 0 <= x <= width and 0 <= y <= height


def _cell_name(row: int, col: int) -> str:
    letters = ""
    value = col
    while True:
        letters = chr(ord("A") + (value % 26)) + letters
        value = value // 26 - 1
        if value < 0:
            break
    return f"{letters}{row + 1:02d}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _tokens(text: str) -> set[str]:
    return {item for item in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) if len(item) >= 2}


def _match_score(normalized_query: str, tokens: set[str], haystack: str) -> int:
    if not normalized_query:
        return 0
    if normalized_query and normalized_query in haystack:
        return 300 + min(len(normalized_query), 80)
    hits = [token for token in tokens if token in haystack]
    if not hits:
        return 0
    return 80 + len(hits) * 40 + sum(min(len(token), 20) for token in hits)


def _grid_label(cell: dict[str, Any]) -> str:
    parts = []
    for key in ("label", "text", "ocr_text", "caption", "name", "title"):
        value = cell.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)


def _cell_bounds(cell: dict[str, Any]) -> tuple[int, int, int, int] | None:
    bounds = cell.get("bounds")
    if isinstance(bounds, Sequence) and len(bounds) == 4:
        try:
            x1, y1, x2, y2 = [int(item) for item in bounds]
            return x1, y1, x2, y2
        except (TypeError, ValueError):
            return None
    if "x" in cell and "y" in cell:
        try:
            x = int(cell["x"])
            y = int(cell["y"])
            return x - 1, y - 1, x + 1, y + 1
        except (TypeError, ValueError):
            return None
    return None
