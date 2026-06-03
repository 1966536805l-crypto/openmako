from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .gui_patterns import GuiTarget, target_to_coordinate


@dataclass(frozen=True)
class ClickCandidate:
    cell_id: str
    coordinate: tuple[int, int]
    reason: str
    score: int
    label: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coordinate"] = list(self.coordinate)
        return payload


@dataclass(frozen=True)
class ClickPlan:
    query: str
    target_cell: str
    coordinate: tuple[int, int] | None
    reason: str
    requires_confirmation: bool = True
    candidates: tuple[ClickCandidate, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.coordinate is not None and bool(self.target_cell)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coordinate"] = list(self.coordinate) if self.coordinate else None
        payload["candidates"] = [candidate.to_payload() for candidate in self.candidates]
        payload["ok"] = self.ok
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


CELL_ID_RE = re.compile(r"\b([A-Z]{1,3})\s*[-_ ]?\s*(\d{1,2})\b", re.IGNORECASE)
ROW_COL_RE = re.compile(
    r"\b(?:row|r)\s*[:#-]?\s*(\d{1,2})\b.*\b(?:column|col|c)\s*[:#-]?\s*([A-Z]{1,3}|\d{1,2})\b",
    re.IGNORECASE,
)
COL_ROW_RE = re.compile(
    r"\b(?:column|col|c)\s*[:#-]?\s*([A-Z]{1,3}|\d{1,2})\b.*\b(?:row|r)\s*[:#-]?\s*(\d{1,2})\b",
    re.IGNORECASE,
)


def plan_click(grid_payload: dict[str, Any], query: str) -> ClickPlan:
    """Plan a click from an existing screenshot grid without performing it."""

    cells = _normalized_cells(grid_payload)
    if not cells:
        return ClickPlan(query=query, target_cell="", coordinate=None, reason="grid payload has no usable cells")

    candidates = _cell_id_candidates(cells, grid_payload, query)
    if candidates:
        return _selected_plan(query, candidates, "cell id")

    candidates = _row_col_candidates(cells, grid_payload, query)
    if candidates:
        return _selected_plan(query, candidates, "row/column")

    candidates = _label_candidates(cells, grid_payload, query)
    if candidates:
        return _selected_plan(query, candidates, "text label")

    return ClickPlan(
        query=query,
        target_cell="",
        coordinate=None,
        reason=f"no grid target matched query: {query!r}",
        candidates=(),
    )


def render_click_plan(plan: ClickPlan) -> str:
    lines = ["# Desktop Click Plan", ""]
    if not plan.ok:
        lines.extend(["Status: no target selected", f"Reason: {plan.reason}"])
        return "\n".join(lines).rstrip() + "\n"

    x, y = plan.coordinate or (0, 0)
    lines.extend(
        [
            "Status: ready for confirmation",
            f"Target: {plan.target_cell}",
            f"Coordinate: {x},{y}",
            f"Requires confirmation: {str(plan.requires_confirmation).lower()}",
            f"Reason: {plan.reason}",
        ]
    )
    if plan.candidates:
        lines.extend(["", "Candidates:"])
        for candidate in plan.candidates[:5]:
            cx, cy = candidate.coordinate
            label = f" ({candidate.label})" if candidate.label else ""
            lines.append(f"- {candidate.cell_id} at {cx},{cy}{label}: {candidate.reason}")
    return "\n".join(lines).rstrip() + "\n"


def _selected_plan(query: str, candidates: list[ClickCandidate], source: str) -> ClickPlan:
    ordered = sorted(candidates, key=lambda item: (-item.score, item.cell_id))
    selected = ordered[0]
    return ClickPlan(
        query=query,
        target_cell=selected.cell_id,
        coordinate=selected.coordinate,
        reason=f"selected {selected.cell_id} by {source}: {selected.reason}",
        requires_confirmation=True,
        candidates=tuple(ordered),
    )


def _normalized_cells(grid_payload: dict[str, Any]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for index, raw in enumerate(grid_payload.get("cells", [])):
        if not isinstance(raw, dict):
            continue
        cell_id = str(raw.get("id", "")).strip().upper()
        if not cell_id:
            continue
        cell = dict(raw)
        cell["id"] = cell_id
        cell["_index"] = index
        cells.append(cell)
    return cells


def _cell_id_candidates(cells: list[dict[str, Any]], grid_payload: dict[str, Any], query: str) -> list[ClickCandidate]:
    wanted = {_normalize_cell_id(match.group(1), match.group(2)) for match in CELL_ID_RE.finditer(query)}
    if not wanted:
        return []
    return [
        _candidate(cell, grid_payload, "query contains exact grid cell id", 300)
        for cell in cells
        if str(cell["id"]).upper() in wanted and _cell_coordinate(cell, grid_payload)
    ]


def _row_col_candidates(cells: list[dict[str, Any]], grid_payload: dict[str, Any], query: str) -> list[ClickCandidate]:
    row_col = _parse_row_col(query)
    if not row_col:
        return []
    row, col = row_col
    candidates = []
    for cell in cells:
        if int(cell.get("row", -1)) != row:
            continue
        if _cell_col_index(cell) != col:
            continue
        if _cell_coordinate(cell, grid_payload):
            candidates.append(_candidate(cell, grid_payload, f"query asks for row {row}, column {col}", 250))
    return candidates


def _label_candidates(cells: list[dict[str, Any]], grid_payload: dict[str, Any], query: str) -> list[ClickCandidate]:
    tokens = _tokens(query)
    if not tokens:
        return []
    candidates: list[ClickCandidate] = []
    for cell in cells:
        label = _cell_label(cell)
        if not label:
            continue
        label_tokens = _tokens(label)
        if not label_tokens:
            continue
        hits = tokens & label_tokens
        normalized_query = _normalize_text(query)
        normalized_label = _normalize_text(label)
        contains = normalized_query in normalized_label or normalized_label in normalized_query
        if not hits and not contains:
            continue
        score = 100 + (len(hits) * 20) + (80 if contains else 0)
        if _cell_coordinate(cell, grid_payload):
            candidates.append(_candidate(cell, grid_payload, f"text label matches {sorted(hits) or [label]}", score, label=label))
    return candidates


def _candidate(
    cell: dict[str, Any],
    grid_payload: dict[str, Any],
    reason: str,
    score: int,
    *,
    label: str = "",
) -> ClickCandidate:
    coordinate = _cell_coordinate(cell, grid_payload)
    if coordinate is None:
        raise ValueError(f"cell has no coordinate: {cell.get('id')}")
    return ClickCandidate(
        cell_id=str(cell["id"]).upper(),
        coordinate=coordinate,
        reason=reason,
        score=score,
        label=label or _cell_label(cell),
    )


def _cell_coordinate(cell: dict[str, Any], grid_payload: dict[str, Any]) -> tuple[int, int] | None:
    if "x" in cell and "y" in cell:
        try:
            return int(cell["x"]), int(cell["y"])
        except (TypeError, ValueError):
            pass
    target = GuiTarget("grid_cell", str(cell["id"]).upper())
    return target_to_coordinate(target, grid_payload=grid_payload)


def _cell_label(cell: dict[str, Any]) -> str:
    parts = []
    for key in ("label", "text", "ocr_text", "caption", "name", "title"):
        value = cell.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)


def _parse_row_col(query: str) -> tuple[int, int] | None:
    match = ROW_COL_RE.search(query) or COL_ROW_RE.search(query)
    if not match:
        return None
    if ROW_COL_RE.search(query):
        row_text, col_text = match.group(1), match.group(2)
    else:
        col_text, row_text = match.group(1), match.group(2)
    row = int(row_text)
    col = _col_text_to_index(col_text)
    return (row, col) if row > 0 and col > 0 else None


def _cell_col_index(cell: dict[str, Any]) -> int:
    col = cell.get("col")
    if col is not None:
        try:
            return int(col)
        except (TypeError, ValueError):
            pass
    match = CELL_ID_RE.fullmatch(str(cell.get("id", "")).upper())
    return _letters_to_index(match.group(1)) if match else -1


def _normalize_cell_id(letters: str, digits: str) -> str:
    return f"{letters.upper()}{int(digits):02d}"


def _col_text_to_index(text: str) -> int:
    stripped = text.strip()
    if stripped.isdigit():
        return int(stripped)
    return _letters_to_index(stripped.upper())


def _letters_to_index(letters: str) -> int:
    value = 0
    for char in letters:
        if not ("A" <= char <= "Z"):
            return -1
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u4e00-\u9fff]+", _normalize_text(text)) if token}


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().strip().split())
