from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SafetyLevel = Literal["allow", "ask", "deny"]
TargetKind = Literal["coordinate", "grid_cell", "som_element", "dom_selector", "text_query", "app_window"]
PerceptionMode = Literal["dom", "ax", "som", "screenshot"]


@dataclass(frozen=True)
class GuiTarget:
    """A stable GUI target reference.

    Prefer references that survive layout changes (`dom_selector`,
    `som_element`, `grid_cell`) before falling back to raw coordinates.
    """

    kind: TargetKind
    value: str | int | tuple[int, int]
    label: str = ""
    bounds: tuple[int, int, int, int] | None = None
    confidence: float | None = None
    source: str = ""

    def center(self) -> tuple[int, int] | None:
        if self.kind == "coordinate" and isinstance(self.value, tuple):
            return self.value
        if self.bounds:
            x1, y1, x2, y2 = self.bounds
            return round((x1 + x2) / 2), round((y1 + y2) / 2)
        return None

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        if isinstance(self.value, tuple):
            data["value"] = list(self.value)
        if self.bounds:
            data["bounds"] = list(self.bounds)
        return data


@dataclass(frozen=True)
class GuiActionSpec:
    name: str
    description: str
    safety: SafetyLevel
    side_effect: bool
    target_required: bool = False
    text_required: bool = False
    preferred_targets: tuple[TargetKind, ...] = ()


@dataclass(frozen=True)
class GuiModeNote:
    mode: PerceptionMode
    best_for: str
    tradeoff: str
    default_safety: SafetyLevel


ACTION_SPECS: dict[str, GuiActionSpec] = {
    "capture": GuiActionSpec(
        "capture",
        "Read the current UI state without side effects.",
        "allow",
        False,
        preferred_targets=("app_window",),
    ),
    "dom_snapshot": GuiActionSpec(
        "dom_snapshot",
        "Read browser/page structure when an in-page or extension bridge is available.",
        "allow",
        False,
        preferred_targets=("app_window",),
    ),
    "click": GuiActionSpec(
        "click",
        "Click one UI target.",
        "ask",
        True,
        target_required=True,
        preferred_targets=("dom_selector", "som_element", "grid_cell", "coordinate"),
    ),
    "double_click": GuiActionSpec(
        "double_click",
        "Double-click one UI target.",
        "ask",
        True,
        target_required=True,
        preferred_targets=("som_element", "grid_cell", "coordinate"),
    ),
    "type": GuiActionSpec(
        "type",
        "Type text into the focused UI target or current focus.",
        "ask",
        True,
        text_required=True,
        preferred_targets=("dom_selector", "som_element", "grid_cell"),
    ),
    "hotkey": GuiActionSpec(
        "hotkey",
        "Send a keyboard shortcut.",
        "ask",
        True,
    ),
    "scroll": GuiActionSpec(
        "scroll",
        "Scroll a target area or the active window.",
        "ask",
        True,
        preferred_targets=("dom_selector", "som_element", "grid_cell", "coordinate"),
    ),
    "drag": GuiActionSpec(
        "drag",
        "Drag between two UI targets or coordinates.",
        "ask",
        True,
        target_required=True,
        preferred_targets=("som_element", "grid_cell", "coordinate"),
    ),
    "set_value": GuiActionSpec(
        "set_value",
        "Set a native DOM/AX value directly when supported.",
        "ask",
        True,
        target_required=True,
        text_required=True,
        preferred_targets=("dom_selector", "som_element"),
    ),
    "wait": GuiActionSpec(
        "wait",
        "Wait briefly for the UI to settle.",
        "allow",
        False,
    ),
}


MODE_NOTES: tuple[GuiModeNote, ...] = (
    GuiModeNote(
        "dom",
        "Web apps with an in-page script, browser extension, or CDP bridge.",
        "Most precise and cheap for forms/navigation, but only sees page DOM and inherits browser security boundaries.",
        "allow",
    ),
    GuiModeNote(
        "ax",
        "Native apps or browsers where accessibility trees are available.",
        "Text-rich and compact, but misses custom canvas, images, and poorly labeled controls.",
        "allow",
    ),
    GuiModeNote(
        "som",
        "Vision-capable models controlling native or browser UIs.",
        "More robust than raw pixels: click numbered elements or grid cells, but requires fresh capture state.",
        "allow",
    ),
    GuiModeNote(
        "screenshot",
        "Fallback for arbitrary screens, custom canvas, charts, and visual inspection.",
        "Universal but least structured; actions need coordinate/grid confirmation before side effects.",
        "allow",
    ),
)


BLOCKED_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-rf\s+/(?:\s|$)"),
    re.compile(r"\bcurl\b.+\|\s*(?:sh|bash)\b", re.IGNORECASE),
    re.compile(r"\bwget\b.+\|\s*(?:sh|bash)\b", re.IGNORECASE),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"\b(?:api[_-]?key|secret|password|passwd)\s*=", re.IGNORECASE),
)


def list_action_specs() -> list[GuiActionSpec]:
    return [ACTION_SPECS[name] for name in sorted(ACTION_SPECS)]


def render_mode_notes() -> str:
    lines = ["# GUI Perception Modes", ""]
    for note in MODE_NOTES:
        lines.extend(
            [
                f"## {note.mode}",
                f"- Best for: {note.best_for}",
                f"- Tradeoff: {note.tradeoff}",
                f"- Default safety: {note.default_safety}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def recommend_perception_mode(
    *,
    surface: str = "desktop",
    dom_available: bool = False,
    ax_available: bool = False,
    vision_model: bool = True,
) -> PerceptionMode:
    """Choose the cheapest useful perception mode for a GUI task."""

    normalized = surface.strip().lower()
    if dom_available or normalized in {"web", "browser", "page", "dom"}:
        return "dom"
    if ax_available and not vision_model:
        return "ax"
    if vision_model:
        return "som"
    if ax_available:
        return "ax"
    return "screenshot"


def gui_action_schema() -> dict[str, Any]:
    """OpenAI-compatible function schema for a future desktop/gui tool."""

    return {
        "name": "gui_action",
        "description": (
            "Inspect and control local GUI surfaces. Prefer DOM selectors when a browser bridge is available; "
            "otherwise capture SoM/grid targets before clicking or typing. Side-effect actions require approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(ACTION_SPECS),
                    "description": "The GUI action to perform.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["dom", "ax", "som", "screenshot"],
                    "description": "Perception mode for capture/dom_snapshot actions.",
                },
                "target": {
                    "type": "object",
                    "description": "Stable target reference. Prefer dom_selector > som_element > grid_cell > coordinate.",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["coordinate", "grid_cell", "som_element", "dom_selector", "text_query", "app_window"],
                        },
                        "value": {
                            "description": "Coordinate [x,y], grid id like A01, SoM index, CSS selector, text query, or app/window name."
                        },
                        "label": {"type": "string"},
                        "bounds": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        },
                        "confidence": {"type": "number"},
                        "source": {"type": "string"},
                    },
                    "required": ["kind", "value"],
                },
                "text": {"type": "string", "description": "Text for type/set_value actions."},
                "keys": {"type": "string", "description": "Shortcut such as cmd+l or return."},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer", "minimum": 1, "maximum": 20},
                "capture_after": {"type": "boolean", "description": "Capture the UI after side-effect actions for verification."},
                "reason": {"type": "string", "description": "Brief operator-facing reason for the action."},
            },
            "required": ["action"],
        },
    }


def normalize_target(payload: dict[str, Any]) -> GuiTarget:
    kind = str(payload.get("kind", "")).strip()
    if kind not in {"coordinate", "grid_cell", "som_element", "dom_selector", "text_query", "app_window"}:
        raise ValueError(f"unknown GUI target kind: {kind}")

    raw_value = payload.get("value")
    value: str | int | tuple[int, int]
    if kind == "coordinate":
        if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
            raise ValueError("coordinate target value must be [x, y]")
        value = (int(raw_value[0]), int(raw_value[1]))
    elif kind == "som_element":
        value = int(raw_value)
    else:
        value = str(raw_value)
        if not value.strip():
            raise ValueError(f"{kind} target value is empty")

    raw_bounds = payload.get("bounds")
    bounds = None
    if raw_bounds is not None:
        if not isinstance(raw_bounds, (list, tuple)) or len(raw_bounds) != 4:
            raise ValueError("bounds must be [x1, y1, x2, y2]")
        bounds = tuple(int(item) for item in raw_bounds)  # type: ignore[assignment]

    confidence = payload.get("confidence")
    return GuiTarget(
        kind=kind,  # type: ignore[arg-type]
        value=value,
        label=str(payload.get("label", "") or ""),
        bounds=bounds,
        confidence=None if confidence is None else float(confidence),
        source=str(payload.get("source", "") or ""),
    )


def targets_from_grid(grid_payload: dict[str, Any]) -> list[GuiTarget]:
    targets: list[GuiTarget] = []
    for cell in grid_payload.get("cells", []):
        if not isinstance(cell, dict):
            continue
        cell_id = str(cell.get("id", "")).upper()
        bounds = cell.get("bounds")
        if not cell_id or not isinstance(bounds, list) or len(bounds) != 4:
            continue
        targets.append(
            GuiTarget(
                kind="grid_cell",
                value=cell_id,
                label=f"grid {cell_id}",
                bounds=tuple(int(item) for item in bounds),  # type: ignore[arg-type]
                source=str(grid_payload.get("image_path", "") or "grid"),
            )
        )
    return targets


def target_to_coordinate(target: GuiTarget, *, grid_payload: dict[str, Any] | None = None) -> tuple[int, int] | None:
    direct = target.center()
    if direct:
        return direct
    if target.kind != "grid_cell" or grid_payload is None:
        return None
    wanted = str(target.value).upper()
    for item in targets_from_grid(grid_payload):
        if str(item.value).upper() == wanted:
            return item.center()
    return None


def classify_gui_action(action: str, *, target: GuiTarget | None = None, text: str = "") -> tuple[SafetyLevel, str]:
    normalized = action.strip().lower()
    spec = ACTION_SPECS.get(normalized)
    if spec is None:
        return "deny", f"unknown GUI action: {action}"
    if spec.target_required and target is None:
        return "deny", f"{normalized} requires a target"
    if spec.text_required and not text:
        return "deny", f"{normalized} requires text"
    if normalized == "type":
        blocked = blocked_type_pattern(text)
        if blocked:
            return "deny", f"type text matches blocked pattern: {blocked}"
    if target and target.kind == "coordinate" and normalized in {"click", "double_click", "drag"}:
        return "ask", f"{normalized} uses raw coordinates; prefer SoM/grid/DOM target when available"
    return spec.safety, f"{normalized} classified as {spec.safety}"


def blocked_type_pattern(text: str) -> str | None:
    for pattern in BLOCKED_TYPE_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def action_payload(action: str, *, target: GuiTarget | None = None, text: str = "", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"action": action}
    if target:
        payload["target"] = target.to_payload()
    if text:
        payload["text"] = text
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def action_payload_json(action: str, *, target: GuiTarget | None = None, text: str = "", **extra: Any) -> str:
    return json.dumps(action_payload(action, target=target, text=text, **extra), ensure_ascii=False, indent=2)
