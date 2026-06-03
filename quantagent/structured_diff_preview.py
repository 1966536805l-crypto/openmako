from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .policy_gate import enforce_tool
from .project_rules import match_project_rules
from .shell_semantics import classify_shell_command
from .worktree_isolation import IsolationReview


@dataclass(frozen=True)
class StructuredDiffFile:
    path: str
    change_type: str
    additions: int = 0
    deletions: int = 0
    risk: str = "low"
    permission_action: str = "ask"
    permission_reason: str = ""
    matched_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructuredDiffPreview:
    preview_id: str
    project: str
    source: str
    task: str = ""
    files: list[StructuredDiffFile] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    test_command: list[str] = field(default_factory=list)
    test_permission: dict[str, Any] = field(default_factory=dict)
    unified_diff: str = ""
    diff_truncated: bool = False
    approval_required: bool = True
    created_at_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "project": self.project,
            "source": self.source,
            "task": self.task,
            "files": [item.to_dict() for item in self.files],
            "risks": self.risks,
            "test_command": self.test_command,
            "test_permission": self.test_permission,
            "unified_diff": self.unified_diff,
            "diff_truncated": self.diff_truncated,
            "approval_required": self.approval_required,
            "created_at_ms": self.created_at_ms,
        }


def diff_preview_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "diff_previews"


def create_structured_diff_preview(
    project: str | Path,
    unified_diff: str,
    *,
    task: str = "",
    source: str = "unified_diff",
    test_command: Sequence[str | Path] = (),
    profile: str = "build",
    max_diff_chars: int = 80_000,
) -> StructuredDiffPreview:
    project_path = Path(project).expanduser().resolve(strict=False)
    stats = _parse_diff_stats(unified_diff)
    files: list[StructuredDiffFile] = []
    risks: list[str] = []
    for path, stat in stats.items():
        risk, file_risks = _file_risk(path, stat["change_type"], stat["additions"], stat["deletions"])
        risks.extend(file_risks)
        decision = enforce_tool(profile, "edit", project=project_path, args={"path": path, "task": task})
        rules = [rule.source for rule in match_project_rules(project_path, [path])]
        files.append(
            StructuredDiffFile(
                path=path,
                change_type=stat["change_type"],
                additions=stat["additions"],
                deletions=stat["deletions"],
                risk=risk,
                permission_action=decision.action,
                permission_reason=decision.policy_reason,
                matched_rules=rules,
            )
        )
    test_permission: dict[str, Any] = {}
    test_args = [str(item) for item in test_command]
    if test_args:
        command = " ".join(test_args)
        decision = enforce_tool(profile, "shell", project=project_path, args={"command": command})
        shell = classify_shell_command(command, cwd=project_path, project=project_path)
        test_permission = decision.metadata() | {"shell_semantics": shell.to_dict()}
        if decision.action != "allow":
            risks.append(f"test command requires {decision.action}: {command}")

    trimmed_diff = unified_diff
    diff_truncated = False
    if len(trimmed_diff) > max_diff_chars:
        trimmed_diff = trimmed_diff[: max(0, max_diff_chars - 24)] + "\n[diff truncated]\n"
        diff_truncated = True
    approval_required = any(item.permission_action != "allow" for item in files) or bool(test_permission and test_permission.get("action") != "allow")
    return StructuredDiffPreview(
        preview_id="preview-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        source=source,
        task=task,
        files=files,
        risks=sorted(set(risks)),
        test_command=test_args,
        test_permission=test_permission,
        unified_diff=trimmed_diff,
        diff_truncated=diff_truncated,
        approval_required=approval_required,
        created_at_ms=int(time.time() * 1000),
    )


def create_preview_from_isolation_review(
    project: str | Path,
    review: IsolationReview,
    *,
    task: str = "",
    test_command: Sequence[str | Path] = (),
    profile: str = "build",
) -> StructuredDiffPreview:
    return create_structured_diff_preview(
        project,
        review.unified_diff,
        task=task,
        source=f"isolation_review:{review.review_id}",
        test_command=test_command,
        profile=profile,
    )


def save_structured_diff_preview(project: str | Path, preview: StructuredDiffPreview) -> Path:
    directory = diff_preview_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{preview.preview_id}.json"
    path.write_text(json.dumps(preview.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_structured_diff_preview(project: str | Path, preview_id: str) -> StructuredDiffPreview:
    path = diff_preview_dir(project) / f"{preview_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _preview_from_payload(payload)


def render_structured_diff_preview(preview: StructuredDiffPreview, *, include_diff: bool = False) -> str:
    lines = [
        f"# Structured Diff Preview {preview.preview_id}",
        "",
        f"- source: {preview.source}",
        f"- task: {preview.task or '-'}",
        f"- files: {len(preview.files)}",
        f"- approval_required: {str(preview.approval_required).lower()}",
    ]
    if preview.test_command:
        lines.append(f"- test_command: {' '.join(preview.test_command)}")
        if preview.test_permission:
            lines.append(f"- test_permission: {preview.test_permission.get('action', 'ask')}")
    if preview.risks:
        lines.extend(["", "## Risks"])
        lines.extend(f"- {risk}" for risk in preview.risks)
    lines.extend(["", "## Files"])
    if not preview.files:
        lines.append("- No files in diff.")
    for item in preview.files:
        rules = f" rules={len(item.matched_rules)}" if item.matched_rules else ""
        lines.append(
            f"- [{item.risk}] {item.change_type} {item.path} +{item.additions}/-{item.deletions} "
            f"permission={item.permission_action}{rules}"
        )
    if include_diff and preview.unified_diff:
        suffix = " (trimmed)" if preview.diff_truncated else ""
        lines.extend(["", "## Diff", "", f"```diff{suffix}", preview.unified_diff.rstrip(), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _parse_diff_stats(diff_text: str) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    current = ""
    old_path = ""
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            old_path = _diff_path(line[4:].strip())
            continue
        if line.startswith("+++ "):
            current = _diff_path(line[4:].strip())
            if current == "/dev/null":
                current = old_path
            change_type = "modified"
            if old_path == "/dev/null":
                change_type = "new"
            elif line[4:].strip() == "/dev/null":
                change_type = "deleted"
            stats.setdefault(current, {"additions": 0, "deletions": 0, "change_type": change_type})
            continue
        if not current or line.startswith("@@"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            stats[current]["additions"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            stats[current]["deletions"] += 1
    return {path: value for path, value in stats.items() if path and path != "/dev/null"}


def _diff_path(raw: str) -> str:
    if raw == "/dev/null":
        return raw
    clean = raw.split("\t", 1)[0]
    if clean.startswith("a/") or clean.startswith("b/"):
        clean = clean[2:]
    return clean


def _file_risk(path: str, change_type: str, additions: int, deletions: int) -> tuple[str, list[str]]:
    risks: list[str] = []
    suffix = Path(path).suffix.lower()
    total = additions + deletions
    level = "low"
    if change_type == "deleted":
        level = "high"
        risks.append(f"{path} deletes a file")
    if suffix in {".json", ".toml", ".yaml", ".yml"}:
        level = _max_risk(level, "medium")
        risks.append(f"{path} changes configuration/data")
    if re.search(r"(^|/)(auth|permission|policy|sandbox|mcp|plugin|security)", path, re.I):
        level = _max_risk(level, "high")
        risks.append(f"{path} touches security/runtime surface")
    if total > 400:
        level = _max_risk(level, "medium")
        risks.append(f"{path} has a large diff ({total} changed lines)")
    return level, risks


def _max_risk(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return left if order[left] >= order[right] else right


def _preview_from_payload(payload: dict[str, Any]) -> StructuredDiffPreview:
    return StructuredDiffPreview(
        preview_id=str(payload.get("preview_id") or ""),
        project=str(payload.get("project") or ""),
        source=str(payload.get("source") or ""),
        task=str(payload.get("task") or ""),
        files=[
            StructuredDiffFile(
                path=str(item.get("path") or ""),
                change_type=str(item.get("change_type") or "modified"),
                additions=int(item.get("additions") or 0),
                deletions=int(item.get("deletions") or 0),
                risk=str(item.get("risk") or "low"),
                permission_action=str(item.get("permission_action") or "ask"),
                permission_reason=str(item.get("permission_reason") or ""),
                matched_rules=[str(rule) for rule in item.get("matched_rules", [])],
            )
            for item in payload.get("files", [])
            if isinstance(item, dict)
        ],
        risks=[str(item) for item in payload.get("risks", [])],
        test_command=[str(item) for item in payload.get("test_command", [])],
        test_permission=dict(payload.get("test_permission") or {}),
        unified_diff=str(payload.get("unified_diff") or ""),
        diff_truncated=bool(payload.get("diff_truncated")),
        approval_required=bool(payload.get("approval_required", True)),
        created_at_ms=int(payload.get("created_at_ms") or 0),
    )
