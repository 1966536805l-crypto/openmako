from __future__ import annotations

import os
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path

from .openclaw_runtime_utils import sanitize_for_plain_text
from .project import is_chat_markdown, is_obsolete_handoff_markdown, read_text_preview, snapshot_project
from .result_registry import load_registry, render_registry_markdown
from .state import state_preview
from .lifecycle_hooks import run_lifecycle_hook


@dataclass
class ContextPack:
    project: Path
    text: str
    sources: list[Path]
    sections: list[str] = field(default_factory=list)
    char_budget: int = 0
    chars_used: int = 0
    token_budget: int = 0
    estimated_tokens: int = 0

    def source_summary(self, limit: int = 8) -> str:
        if not self.sources:
            return "sources: none"
        names = [path.name for path in self.sources[:limit]]
        extra = len(self.sources) - len(names)
        suffix = f", +{extra} more" if extra > 0 else ""
        return "sources: " + ", ".join(names) + suffix

    def budget_summary(self) -> str:
        pct = 0 if self.token_budget <= 0 else round((self.estimated_tokens / self.token_budget) * 100, 2)
        state = "ok"
        if pct >= 95:
            state = "blocking"
        elif pct >= 90:
            state = "compact-soon"
        elif pct >= 80:
            state = "watch"
        return (
            f"context: {self.estimated_tokens}/{self.token_budget} est tokens "
            f"({pct}%, {state}); chars={self.chars_used}/{self.char_budget}"
        )


@dataclass(frozen=True)
class ContextItem:
    title: str
    body: str
    source: Path | None
    priority: int
    section: str


TASK_KEYWORDS = {
    "p4": ["P4", "逐笔", "tick", "09:30", "真实成交", "成交", "PRE_TICK", "REAL_EXECUTION"],
    "decline": ["2025", "衰退", "退化", "P5", "(-9,-8]"],
    "experiment": ["实验", "回测", "PF", "threshold", "阈值", "复现"],
    "consensus": ["门禁", "共识", "ChatGPT", "APPROVE", "投票"],
    "risk": ["滑点", "容量", "风控", "仓位", "P6"],
}


def task_terms(task: str | None) -> set[str]:
    if not task:
        return set()
    lowered = task.lower()
    terms = {task}
    for values in TASK_KEYWORDS.values():
        for value in values:
            if value.lower() in lowered:
                terms.update(v.lower() for v in values)
    for token in task.replace("_", " ").replace("-", " ").split():
        if len(token) >= 2:
            terms.add(token.lower())
    return terms


def relevance_score(path: Path, text: str, terms: set[str]) -> int:
    if not terms:
        return 0
    haystack = f"{path.name}\n{text}".lower()
    return sum(1 for term in terms if term and term.lower() in haystack)


def obsolete_penalty(path: Path, text: str) -> int:
    lowered = f"{path.name}\n{text[:1000]}".lower()
    if is_chat_markdown(path):
        return 90
    if is_obsolete_handoff_markdown(path):
        return 70
    if "obsolete" in lowered or "废弃" in lowered or "已废弃" in lowered:
        return 40
    if "claude_action_required" in lowered:
        return 30
    return 0


def low_priority_markdown_name(name: str) -> bool:
    path = Path(name.strip("` :"))
    return is_chat_markdown(path) or is_obsolete_handoff_markdown(path)


def embedded_markdown_source_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("## Latest Communication: "):
        return stripped.removeprefix("## Latest Communication: ").strip()
    if stripped.startswith("### ") and ".md" in stripped:
        return stripped.removeprefix("### ").split()[0].strip()
    return None


def sanitize_context_preview(text: str) -> str:
    """Drop generated chat and superseded gate blocks from embedded context snapshots."""
    kept: list[str] = []
    skipping_low_priority_block = False
    for line in sanitize_for_plain_text(text).splitlines():
        source_name = embedded_markdown_source_name(line)
        if source_name:
            skipping_low_priority_block = low_priority_markdown_name(source_name)
            if skipping_low_priority_block:
                continue
        if skipping_low_priority_block:
            continue
        if "CHAT_REVIEW_STREAM.md" in line or "CHAT_REPORT_" in line or "40_CLAUDE" in line:
            continue
        kept.append(line)
    return "\n".join(kept).strip() + "\n"


def trim_to_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 80)] + "\n\n[trimmed by Context Engine]\n"


def estimate_tokens(text: str) -> int:
    """Rough mixed Chinese/English estimate, intentionally conservative."""
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return ceil(ascii_chars / 4 + non_ascii_chars / 1.7)


def add_item(lines: list[str], item: ContextItem, remaining: int) -> int:
    if remaining <= 0:
        return 0
    header = f"## {item.section}: {item.title}\n\n"
    body_limit = max(300, remaining - len(header) - 8)
    body = trim_to_chars(item.body, body_limit)
    chunk = header + body.rstrip() + "\n\n"
    lines.append(chunk)
    return remaining - len(chunk)


def default_token_budget() -> int:
    value = os.environ.get("QUANTAGENT_CONTEXT_BUDGET_TOKENS")
    if not value:
        return 80_000
    try:
        return max(8_000, int(value))
    except ValueError:
        return 80_000


def default_char_budget(token_budget: int) -> int:
    value = os.environ.get("QUANTAGENT_CONTEXT_BUDGET_CHARS")
    if value:
        try:
            return max(18_000, int(value))
        except ValueError:
            pass
    return token_budget * 3


def context_shape(char_budget: int) -> tuple[int, int, int, int]:
    """Return message preview, scan count, selected count, claude preview."""
    if char_budget >= 200_000:
        return 12_000, 80, 40, 20_000
    if char_budget >= 80_000:
        return 8_000, 40, 24, 12_000
    if char_budget >= 40_000:
        return 5_000, 24, 14, 8_000
    return 1_600, 14, 8, 3_200


def build_context_pack(
    project: Path,
    max_message_chars: int | None = None,
    task: str | None = None,
    char_budget: int | None = None,
    token_budget: int | None = None,
) -> ContextPack:
    """Build a layered, budgeted context for model calls or human review."""
    hook_payload = run_lifecycle_hook(
        project,
        "before_context_build",
        {
            "task": task or "",
            "max_message_chars": max_message_chars,
            "char_budget": char_budget,
            "token_budget": token_budget,
        },
    ).payload
    if hook_payload:
        task = str(hook_payload.get("task") or task or "")
        max_message_chars = hook_payload.get("max_message_chars", max_message_chars)
        char_budget = hook_payload.get("char_budget", char_budget)
        token_budget = hook_payload.get("token_budget", token_budget)
    token_budget = token_budget or default_token_budget()
    char_budget = char_budget or default_char_budget(token_budget)
    shape_message_chars, scan_limit, select_limit, claude_preview_chars = context_shape(char_budget)
    max_message_chars = max_message_chars or shape_message_chars
    snapshot = snapshot_project(project, "AI_协作交接")
    sources: list[Path] = []
    sections: list[str] = []
    terms = task_terms(task)
    lines = [
        "# Mako Context Pack",
        "",
        f"project: {project}",
        f"context_budget_chars: {char_budget}",
        f"context_budget_tokens: {token_budget}",
        f"task: {task or '(none)'}",
        "",
        "## Core Rules",
        "- Use deduplicated baselines only.",
        "- Original 1253-trade sample is polluted by duplicates and cannot support conclusions.",
        "- Treat PF improvement as suspicious until audited.",
        "- 09:25 is signal time; strategy entry is 09:30 continuous auction.",
        "- Real execution validation has priority over parameter optimization.",
        "- Material actions require three ChatGPT consistency APPROVE votes.",
        "- Model text is not ground truth; use data/script hashes and registry outputs.",
        "",
    ]
    remaining = char_budget - len("\n".join(lines))
    items: list[ContextItem] = []

    state_text = sanitize_context_preview(state_preview(project))
    items.append(ContextItem("PROJECT_STATE_COMPACT", state_text, project / "AI_协作交接" / "PROJECT_STATE_COMPACT.md", 100, "State"))

    if snapshot.claude_md:
        items.append(
            ContextItem(
                "CLAUDE.md Preview",
                sanitize_context_preview(read_text_preview(snapshot.claude_md, max_chars=claude_preview_chars)),
                snapshot.claude_md,
                95,
                "Rules",
            )
        )

    latest_candidates: list[ContextItem] = []
    for index, path in enumerate(snapshot.latest_messages[:scan_limit]):
        if is_chat_markdown(path) or is_obsolete_handoff_markdown(path):
            continue
        preview = sanitize_context_preview(read_text_preview(path, max_chars=max_message_chars))
        priority = 80 - min(index, 80) + relevance_score(path, preview, terms) * 12 - obsolete_penalty(path, preview)
        latest_candidates.append(ContextItem(path.name, preview, path, priority, "Latest Communication"))
    items.extend(sorted(latest_candidates, key=lambda item: item.priority, reverse=True)[:select_limit])

    registry = load_registry(project)
    if registry:
        registry_text = render_registry_markdown(registry, limit=40 if char_budget >= 200_000 else 12)
        items.append(
            ContextItem(
                "Result Registry",
                registry_text,
                project / "AI_协作交接" / "quantagent_results" / "registry.json",
                78,
                "Evidence",
            )
        )

    baseline_lines = ["Known clean/request files:"]
    for path in snapshot.baseline_files:
        baseline_lines.append(f"- {path.name}")
        sources.append(path)
    items.append(ContextItem("Baselines", "\n".join(baseline_lines), None, 76, "Evidence"))

    script_lines = ["Known scripts:"]
    for path in snapshot.scripts:
        script_lines.append(f"- {path.name}")
        sources.append(path)
    items.append(ContextItem("Scripts", "\n".join(script_lines), None, 74, "Tools"))

    for item in sorted(items, key=lambda value: value.priority, reverse=True):
        if remaining <= 500:
            break
        if item.source and item.source not in sources:
            sources.append(item.source)
        sections.append(item.section)
        remaining = add_item(lines, item, remaining)

    text = "\n".join(lines).rstrip() + "\n"
    estimated = estimate_tokens(text)
    pack = ContextPack(
        project=project,
        text=text,
        sources=sources,
        sections=sections,
        char_budget=char_budget,
        chars_used=len(text),
        token_budget=token_budget,
        estimated_tokens=estimated,
    )
    after = run_lifecycle_hook(
        project,
        "after_context_build",
        {
            "text": pack.text,
            "sources": [str(path) for path in pack.sources],
            "sections": pack.sections,
            "estimated_tokens": pack.estimated_tokens,
        },
    )
    if after.payload and isinstance(after.payload.get("text"), str):
        text = str(after.payload["text"])
        pack = ContextPack(
            project=pack.project,
            text=text,
            sources=pack.sources,
            sections=pack.sections,
            char_budget=pack.char_budget,
            chars_used=len(text),
            token_budget=pack.token_budget,
            estimated_tokens=estimate_tokens(text),
        )
    return pack
