from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


RULE_LOCATIONS = (
    (".quantagent/rules", "*.md"),
    (".cursor/rules", "*.md"),
    ("", "AGENTS.md"),
    ("", "QUANTAGENT.md"),
)


@dataclass(frozen=True)
class ProjectRule:
    source: str
    body: str
    description: str | None = None
    globs: list[str] = field(default_factory=list)
    always_apply: bool = False


def load_project_rules(project: str | Path) -> list[ProjectRule]:
    project_path = Path(project).expanduser().resolve(strict=False)
    rules: list[ProjectRule] = []
    for directory, pattern in RULE_LOCATIONS:
        root = project_path / directory if directory else project_path
        if not root.exists():
            continue
        candidates = sorted(root.glob(pattern)) if directory else [root / pattern]
        for path in candidates:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = _relative_source(project_path, path)
            rules.append(parse_project_rule(text, rel))
    return rules


def parse_project_rule(text: str, source: str) -> ProjectRule:
    metadata, body = _split_frontmatter(text)
    description = _string_value(metadata.get("description"))
    globs = _glob_values(metadata.get("globs"))
    always_apply = _bool_value(metadata.get("alwaysApply")) or _bool_value(metadata.get("always_apply"))
    return ProjectRule(source=source, body=body.strip(), description=description, globs=globs, always_apply=always_apply)


def match_project_rules(project: str | Path, paths: Iterable[str | Path] | None = None) -> list[ProjectRule]:
    rules = load_project_rules(project)
    normalized_paths = [_normalize_path(path) for path in (paths or []) if _normalize_path(path)]
    return [rule for rule in rules if rule_matches_paths(rule, normalized_paths)]


def rules_for_paths(project: str | Path, paths: Iterable[str | Path] | None = None) -> list[ProjectRule]:
    return match_project_rules(project, paths)


def rule_matches_paths(rule: ProjectRule, paths: Iterable[str]) -> bool:
    if rule.always_apply:
        return True
    if not rule.globs:
        return True
    normalized_paths = [_normalize_path(path) for path in paths if _normalize_path(path)]
    if not normalized_paths:
        return False
    return any(_matches_any_glob(path, rule.globs) for path in normalized_paths)


def render_project_rules(rules: Iterable[ProjectRule], *, max_body_chars: int = 1200) -> str:
    rendered_rules = list(rules)
    if not rendered_rules:
        return "No project rules matched.\n"

    lines = ["## Project Rules", ""]
    for rule in rendered_rules:
        summary = _rule_summary(rule)
        lines.append(f"### {rule.source}")
        if summary:
            lines.append(summary)
        body = _trim_body(rule.body, max_body_chars)
        if body:
            lines.append("")
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text

    metadata = _parse_frontmatter_lines(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    if text.endswith("\n") and body:
        body += "\n"
    return metadata, body


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        if not raw.strip() or raw.lstrip().startswith("#"):
            index += 1
            continue
        if ":" not in raw:
            index += 1
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            index += 1
            continue
        if value:
            metadata[key] = _clean_scalar(value)
            index += 1
            continue

        items: list[str] = []
        next_index = index + 1
        while next_index < len(lines):
            candidate = lines[next_index]
            stripped = candidate.strip()
            if not stripped or stripped.startswith("#"):
                next_index += 1
                continue
            if not candidate[:1].isspace():
                break
            if stripped.startswith("-"):
                items.append(_clean_scalar(stripped[1:].strip()))
                next_index += 1
                continue
            break
        metadata[key] = items
        index = next_index
    return metadata


def _glob_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        text = str(value).strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        raw_items = re.split(r",|\s+", text) if "," not in text else text.split(",")
    return [item for item in (_clean_scalar(str(item)) for item in raw_items) if item]


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    text = _clean_scalar(str(value))
    return text or None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return _clean_scalar(str(value)).lower() in {"1", "true", "yes", "y", "on"}


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[:1] == value[-1:] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _matches_any_glob(path: str, globs: Iterable[str]) -> bool:
    return any(_matches_glob(path, glob) for glob in globs)


def _matches_glob(path: str, glob: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_glob = _normalize_path(glob)
    if not normalized_path or not normalized_glob:
        return False
    for candidate in _glob_candidates(normalized_glob):
        if fnmatch.fnmatchcase(normalized_path, candidate):
            return True
        if "/" not in candidate and fnmatch.fnmatchcase(Path(normalized_path).name, candidate):
            return True
    return False


def _glob_candidates(glob: str) -> list[str]:
    candidates = {glob}
    if "**/" in glob:
        candidates.add(glob.replace("**/", ""))
    if glob.startswith("**/"):
        candidates.add(glob[3:])
    return sorted(candidates)


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().strip("/")


def _relative_source(project: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(project.resolve(strict=False))).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _rule_summary(rule: ProjectRule) -> str:
    parts: list[str] = []
    if rule.description:
        parts.append(rule.description)
    if rule.always_apply:
        parts.append("alwaysApply")
    if rule.globs:
        parts.append("globs: " + ", ".join(rule.globs))
    return " | ".join(parts)


def _trim_body(body: str, max_chars: int) -> str:
    body = body.strip()
    if max_chars <= 0 or len(body) <= max_chars:
        return body
    return body[: max(0, max_chars - 14)].rstrip() + "\n[rule trimmed]"
