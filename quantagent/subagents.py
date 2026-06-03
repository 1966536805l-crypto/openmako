from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_profiles import load_agent_profile_config, load_instructions
from .context_pack import build_context_pack
from .lifecycle_hooks import run_lifecycle_hook
from .runtime_store import record_task_run
from .sessions import append_message, create_session, latest_session
from .task_runtime import read_task_output, refresh_runtime_tasks, start_agent_task, stop_runtime_task
from .task_state import ABORTED, FAILED, LOST, NOTIFY_DONE_ONLY, PASSED, RUNNING, SCOPE_SESSION, add_task, load_tasks, task_dir, update_task
from .worktree_isolation import create_isolated_worktree, create_isolation_review, isolation_root, load_isolation_review


TERMINAL = {PASSED, FAILED, ABORTED, LOST}


@dataclass
class SubagentRecord:
    subagent_id: str
    parent_task_id: str
    child_task_id: str
    child_session_id: str
    task: str
    context_mode: str = "fork"
    agent_profile: str = "build"
    permission_mode: str = ""
    model: str = ""
    effort: str = ""
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    background: bool = True
    context_path: str = ""
    isolation_worktree_id: str = ""
    isolation_workspace_path: str = ""
    review_id: str = ""
    status: str = RUNNING
    progress_summary: str = ""
    terminal_outcome: str = ""
    artifacts: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubagentReviewBundle:
    bundle_id: str
    parent_task_id: str
    subagent_ids: list[str]
    review_ids: list[str]
    changed_paths: list[str]
    terminal_outcomes: dict[str, str]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def subagent_store_path(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "subagents.json"


def subagent_review_bundle_store_path(project: str | Path) -> Path:
    return task_dir(Path(project).expanduser().resolve(strict=False)) / "subagent_review_bundles.json"


def start_subagent(
    project: str | Path,
    task: str,
    *,
    parent_task_id: str | None = None,
    context_mode: str = "fork",
    title: str = "",
    include_validation: bool = True,
    agent_profile: str = "build",
    permission_mode: str = "",
    model: str = "",
    effort: str = "",
    tools: list[str] | tuple[str, ...] = (),
    disallowed_tools: list[str] | tuple[str, ...] = (),
    mcp_servers: list[str] | tuple[str, ...] = (),
    hooks: list[str] | tuple[str, ...] = (),
    skills: list[str] | tuple[str, ...] = (),
    background: bool = True,
    isolate_worktree: bool = False,
) -> SubagentRecord:
    project_path = Path(project).expanduser().resolve(strict=False)
    task_text = task.strip()
    if not task_text:
        raise ValueError("subagent task is empty")
    if context_mode not in {"fork", "isolated"}:
        raise ValueError("context_mode must be fork or isolated")

    subagent_id = "sub-" + uuid.uuid4().hex[:10]
    start_hook = run_lifecycle_hook(
        project_path,
        "subagent_start",
        {
            "subagent_id": subagent_id,
            "task": task_text,
            "parent_task_id": parent_task_id or "",
            "context_mode": context_mode,
            "agent_profile": agent_profile,
            "profile": agent_profile,
            "background": background,
            "isolate_worktree": isolate_worktree,
        },
        plugin_id=agent_profile or "subagent",
    )
    if start_hook.blocked:
        raise ValueError("; ".join(start_hook.summaries or start_hook.errors or ("subagent start blocked by hook",)))
    profile_spec = load_agent_profile_config(project_path).agents.get(agent_profile)
    if profile_spec and profile_spec.isolation.lower() in {"worktree", "isolated", "sandbox", "true", "1", "yes"}:
        isolate_worktree = True
    if not parent_task_id:
        parent = add_task(project_path, title or f"parent: {task_text[:80]}", detail="subagent parent task", status=RUNNING)
        parent_task_id = parent.id
    fork_session = latest_session(project_path) if context_mode == "fork" else None
    child_session = create_session(project_path, f"subagent: {title or task_text[:60]}")
    isolated = create_isolated_worktree(project_path, reason=f"subagent {subagent_id}: {task_text[:80]}") if isolate_worktree else None
    context_path = _write_context_artifact(
        project_path,
        subagent_id=subagent_id,
        task=task_text,
        parent_task_id=parent_task_id,
        child_session_id=child_session.session_id,
        context_mode=context_mode,
        agent_profile=agent_profile,
        permission_mode=permission_mode or (profile_spec.permission_mode if profile_spec else ""),
        model=model or (profile_spec.model if profile_spec else ""),
        effort=effort or (profile_spec.effort if profile_spec else ""),
        tools=list(tools or (profile_spec.tools if profile_spec else ())),
        disallowed_tools=list(disallowed_tools or (profile_spec.disallowed_tools if profile_spec else ())),
        mcp_servers=list(mcp_servers),
        hooks=list(hooks or (profile_spec.hooks if profile_spec else ())),
        skills=list(skills or (profile_spec.skills if profile_spec else ())),
        background=background,
        fork_session=fork_session,
        isolation_worktree_id=isolated.worktree_id if isolated else "",
        isolation_workspace_path=isolated.workspace_path if isolated else "",
    )
    context_text = context_path.read_text(encoding="utf-8", errors="replace")
    append_message(project_path, child_session.session_id, "system", context_text, meta={"context_mode": context_mode, "agent_profile": agent_profile, "context_path": str(context_path)})
    append_message(project_path, child_session.session_id, "user", task_text, meta={"parent_task_id": parent_task_id, "subagent_id": subagent_id})
    child = start_agent_task(
        project_path,
        task_text,
        title=title or task_text[:80],
        include_validation=include_validation,
        agent_profile=agent_profile,
        context_path=str(context_path),
        runtime_project=isolated.workspace_path if isolated else None,
        owner_key=agent_profile or "subagent",
        scope_kind=SCOPE_SESSION,
        child_session_key=child_session.session_id,
        parent_task_id=parent_task_id,
        notify_policy=NOTIFY_DONE_ONLY,
    )
    record_task_run(
        project_path,
        child,
        runtime="subagent",
        owner_key=agent_profile or "subagent",
        scope_kind=SCOPE_SESSION,
        parent_task_id=parent_task_id,
        child_session_key=child_session.session_id,
        agent_id=agent_profile or "subagent",
        label=title or task_text[:80],
        notify_policy=NOTIFY_DONE_ONLY,
        progress_summary=f"started {context_mode} subagent",
    )
    record = SubagentRecord(
        subagent_id=subagent_id,
        parent_task_id=parent_task_id,
        child_task_id=child.id,
        child_session_id=child_session.session_id,
        task=task_text,
        context_mode=context_mode,
        agent_profile=agent_profile,
        permission_mode=permission_mode or (profile_spec.permission_mode if profile_spec else ""),
        model=model or (profile_spec.model if profile_spec else ""),
        effort=effort or (profile_spec.effort if profile_spec else ""),
        tools=list(tools or (profile_spec.tools if profile_spec else ())),
        disallowed_tools=list(disallowed_tools or (profile_spec.disallowed_tools if profile_spec else ())),
        mcp_servers=list(mcp_servers),
        hooks=list(hooks or (profile_spec.hooks if profile_spec else ())),
        skills=list(skills or (profile_spec.skills if profile_spec else ())),
        background=background,
        context_path=str(context_path),
        isolation_worktree_id=isolated.worktree_id if isolated else "",
        isolation_workspace_path=isolated.workspace_path if isolated else "",
        progress_summary="started",
        artifacts=list(child.evidence),
    )
    records = load_subagents(project_path)
    records.append(record)
    save_subagents(project_path, records)
    return record


def refresh_subagents(project: str | Path) -> list[SubagentRecord]:
    project_path = Path(project).expanduser().resolve(strict=False)
    records = load_subagents(project_path)
    tasks = {task.id: task for task in refresh_runtime_tasks(project_path)}
    changed = False
    for record in records:
        child = tasks.get(record.child_task_id)
        if not child:
            continue
        try:
            output = read_task_output(project_path, child.id, tail_chars=1200)
        except KeyError:
            output = ""
        summary = _progress_summary(child.status, output)
        artifacts = list(dict.fromkeys([*record.artifacts, *child.evidence]))
        if record.status != child.status or record.progress_summary != summary or record.artifacts != artifacts:
            record.status = child.status
            record.progress_summary = summary
            record.artifacts = artifacts
            record.updated_at = datetime.now().isoformat(timespec="seconds")
            if child.status in TERMINAL:
                record.terminal_outcome = "ok" if child.status == PASSED else child.status
                if record.isolation_worktree_id and not record.review_id:
                    try:
                        review = create_isolation_review(project_path, record.isolation_worktree_id)
                        record.review_id = review.review_id
                        artifacts.append(str(isolation_root(project_path) / record.isolation_worktree_id / f"{review.review_id}.json"))
                        record.artifacts = list(dict.fromkeys(artifacts))
                    except Exception as exc:
                        audit_suppressed_exception(f"{__name__}:242", exc)
                        pass
                try:
                    update_task(
                        project_path,
                        record.parent_task_id,
                        status=PASSED if child.status == PASSED else child.status,
                        note=f"subagent {record.subagent_id} finished: {record.terminal_outcome}",
                    )
                except KeyError:
                    pass
                run_lifecycle_hook(
                    project_path,
                    "subagent_stop",
                    {
                        "subagent_id": record.subagent_id,
                        "parent_task_id": record.parent_task_id,
                        "child_task_id": record.child_task_id,
                        "child_session_id": record.child_session_id,
                        "agent_profile": record.agent_profile,
                        "profile": record.agent_profile,
                        "status": child.status,
                        "terminal_outcome": record.terminal_outcome,
                        "progress_summary": record.progress_summary,
                        "review_id": record.review_id,
                    },
                    session_id=record.child_session_id,
                    plugin_id=record.agent_profile or "subagent",
                )
            record_task_run(
                project_path,
                child,
                runtime="subagent",
                owner_key=record.agent_profile or "subagent",
                scope_kind=SCOPE_SESSION,
                parent_task_id=record.parent_task_id,
                child_session_key=record.child_session_id,
                agent_id=record.agent_profile or "subagent",
                notify_policy=NOTIFY_DONE_ONLY,
                progress_summary=record.progress_summary,
                terminal_outcome=record.terminal_outcome or None,
            )
            changed = True
    if changed:
        save_subagents(project_path, records)
    return records


def stop_subagent(project: str | Path, subagent_id: str) -> SubagentRecord:
    project_path = Path(project).expanduser().resolve(strict=False)
    records = load_subagents(project_path)
    for record in records:
        if record.subagent_id != subagent_id:
            continue
        stop_runtime_task(project_path, record.child_task_id)
        record.status = ABORTED
        record.terminal_outcome = ABORTED
        record.progress_summary = "stop requested"
        record.updated_at = datetime.now().isoformat(timespec="seconds")
        save_subagents(project_path, records)
        run_lifecycle_hook(
            project_path,
            "subagent_stop",
            {
                "subagent_id": record.subagent_id,
                "parent_task_id": record.parent_task_id,
                "child_task_id": record.child_task_id,
                "child_session_id": record.child_session_id,
                "agent_profile": record.agent_profile,
                "profile": record.agent_profile,
                "status": ABORTED,
                "terminal_outcome": ABORTED,
                "progress_summary": record.progress_summary,
            },
            session_id=record.child_session_id,
            plugin_id=record.agent_profile or "subagent",
        )
        return record
    raise KeyError(f"subagent not found: {subagent_id}")


def get_subagent(project: str | Path, subagent_id: str) -> SubagentRecord:
    for record in refresh_subagents(project):
        if record.subagent_id == subagent_id:
            return record
    raise KeyError(f"subagent not found: {subagent_id}")


def create_subagent_review_bundle(
    project: str | Path,
    *,
    parent_task_id: str | None = None,
    subagent_ids: list[str] | tuple[str, ...] | None = None,
) -> SubagentReviewBundle:
    project_path = Path(project).expanduser().resolve(strict=False)
    wanted_ids = set(subagent_ids or [])
    if not parent_task_id and not wanted_ids:
        raise ValueError("parent_task_id or subagent_ids is required")

    records = refresh_subagents(project_path)
    if wanted_ids:
        found_ids = {record.subagent_id for record in records}
        missing = sorted(wanted_ids - found_ids)
        if missing:
            raise KeyError(f"subagent not found: {', '.join(missing)}")
    selected = [
        record
        for record in records
        if (not parent_task_id or record.parent_task_id == parent_task_id)
        and (not wanted_ids or record.subagent_id in wanted_ids)
        and record.status in TERMINAL
        and record.isolation_worktree_id
        and record.review_id
    ]
    selected.sort(key=lambda record: record.created_at)
    if not selected:
        raise ValueError("no completed isolated subagents with reviews found")

    review_ids: list[str] = []
    changed_paths: list[str] = []
    artifacts: list[str] = []
    for record in selected:
        review = load_isolation_review(project_path, record.review_id)
        review_ids.append(review.review_id)
        changed_paths.extend(path for path in [*review.changed_paths, *review.new_paths, *review.deleted_paths] if _is_reviewable_path(path))
        artifacts.extend(_review_artifacts(project_path, record))

    parent_id = parent_task_id or _common_parent_task_id(selected)
    bundle = SubagentReviewBundle(
        bundle_id="bundle-" + uuid.uuid4().hex[:12],
        parent_task_id=parent_id,
        subagent_ids=[record.subagent_id for record in selected],
        review_ids=list(dict.fromkeys(review_ids)),
        changed_paths=sorted(dict.fromkeys(changed_paths)),
        terminal_outcomes={record.subagent_id: record.terminal_outcome or record.status for record in selected},
        summary=_review_bundle_summary(selected, changed_paths),
        artifacts=list(dict.fromkeys(artifacts)),
    )
    bundles = load_subagent_review_bundles(project_path)
    bundles.append(bundle)
    save_subagent_review_bundles(project_path, bundles)
    return bundle


def load_subagents(project: str | Path) -> list[SubagentRecord]:
    path = subagent_store_path(project)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = payload.get("subagents", []) if isinstance(payload, dict) else []
    records: list[SubagentRecord] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        records.append(
            SubagentRecord(
                subagent_id=str(raw.get("subagent_id") or ""),
                parent_task_id=str(raw.get("parent_task_id") or ""),
                child_task_id=str(raw.get("child_task_id") or ""),
                child_session_id=str(raw.get("child_session_id") or ""),
                task=str(raw.get("task") or ""),
                context_mode=str(raw.get("context_mode") or "fork"),
                agent_profile=str(raw.get("agent_profile") or "build"),
                permission_mode=str(raw.get("permission_mode") or ""),
                model=str(raw.get("model") or ""),
                effort=str(raw.get("effort") or ""),
                tools=[str(item) for item in raw.get("tools", [])],
                disallowed_tools=[str(item) for item in raw.get("disallowed_tools", [])],
                mcp_servers=[str(item) for item in raw.get("mcp_servers", [])],
                hooks=[str(item) for item in raw.get("hooks", [])],
                skills=[str(item) for item in raw.get("skills", [])],
                background=bool(raw.get("background", True)),
                context_path=str(raw.get("context_path") or ""),
                isolation_worktree_id=str(raw.get("isolation_worktree_id") or ""),
                isolation_workspace_path=str(raw.get("isolation_workspace_path") or ""),
                review_id=str(raw.get("review_id") or ""),
                status=str(raw.get("status") or RUNNING),
                progress_summary=str(raw.get("progress_summary") or ""),
                terminal_outcome=str(raw.get("terminal_outcome") or ""),
                artifacts=[str(item) for item in raw.get("artifacts", [])],
                created_at=str(raw.get("created_at") or datetime.now().isoformat(timespec="seconds")),
                updated_at=str(raw.get("updated_at") or datetime.now().isoformat(timespec="seconds")),
            )
        )
    return [record for record in records if record.subagent_id]


def load_subagent_review_bundles(project: str | Path) -> list[SubagentReviewBundle]:
    path = subagent_review_bundle_store_path(project)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_bundles = payload.get("review_bundles", []) if isinstance(payload, dict) else []
    bundles: list[SubagentReviewBundle] = []
    for raw in raw_bundles:
        if not isinstance(raw, dict):
            continue
        outcomes = raw.get("terminal_outcomes", {})
        bundles.append(
            SubagentReviewBundle(
                bundle_id=str(raw.get("bundle_id") or ""),
                parent_task_id=str(raw.get("parent_task_id") or ""),
                subagent_ids=[str(item) for item in raw.get("subagent_ids", [])],
                review_ids=[str(item) for item in raw.get("review_ids", [])],
                changed_paths=[str(item) for item in raw.get("changed_paths", [])],
                terminal_outcomes={str(key): str(value) for key, value in outcomes.items()} if isinstance(outcomes, dict) else {},
                created_at=str(raw.get("created_at") or datetime.now().isoformat(timespec="seconds")),
                summary=str(raw.get("summary") or ""),
                artifacts=[str(item) for item in raw.get("artifacts", [])],
            )
        )
    return [bundle for bundle in bundles if bundle.bundle_id]


def save_subagents(project: str | Path, records: list[SubagentRecord]) -> Path:
    path = subagent_store_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"subagents": [record.to_dict() for record in records]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_subagent_review_bundles(project: str | Path, bundles: list[SubagentReviewBundle]) -> Path:
    path = subagent_review_bundle_store_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"review_bundles": [bundle.to_dict() for bundle in bundles]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def render_subagents(records: list[SubagentRecord]) -> str:
    if not records:
        return "No subagents.\n"
    lines = ["# Mako Subagents", ""]
    for record in records:
        outcome = f" outcome={record.terminal_outcome}" if record.terminal_outcome else ""
        lines.append(
            f"- [{record.status}] {record.subagent_id}: child={record.child_task_id} parent={record.parent_task_id} "
            f"session={record.child_session_id} mode={record.context_mode} profile={record.agent_profile} permission={record.permission_mode or '-'}{outcome}"
        )
        extras = []
        if record.model:
            extras.append(f"model={record.model}")
        if record.effort:
            extras.append(f"effort={record.effort}")
        if record.tools:
            extras.append(f"tools={','.join(record.tools)}")
        if record.disallowed_tools:
            extras.append(f"disallowed={','.join(record.disallowed_tools)}")
        if extras:
            lines.append("  " + " ".join(extras))
        if record.context_path:
            lines.append(f"  context: {record.context_path}")
        if record.isolation_workspace_path:
            lines.append(f"  isolation: {record.isolation_worktree_id} {record.isolation_workspace_path}")
        if record.review_id:
            lines.append(f"  review: {record.review_id}")
        if record.progress_summary:
            lines.append(f"  progress: {record.progress_summary}")
    return "\n".join(lines) + "\n"


def render_subagent_review_bundle(bundle: SubagentReviewBundle) -> str:
    lines = [
        f"# Subagent Review Bundle {bundle.bundle_id}",
        "",
        f"- parent_task_id: {bundle.parent_task_id or '-'}",
        f"- subagents: {len(bundle.subagent_ids)}",
        f"- reviews: {len(bundle.review_ids)}",
        f"- changed_paths: {len(bundle.changed_paths)}",
        f"- created_at: {bundle.created_at}",
    ]
    if bundle.summary:
        lines.extend(["", "## Summary", "", bundle.summary])
    if bundle.subagent_ids:
        lines.extend(["", "## Subagents", ""])
        for subagent_id in bundle.subagent_ids:
            outcome = bundle.terminal_outcomes.get(subagent_id, "-")
            lines.append(f"- {subagent_id}: {outcome}")
    if bundle.review_ids:
        lines.extend(["", "## Reviews", ""])
        lines.extend(f"- {review_id}" for review_id in bundle.review_ids)
    if bundle.changed_paths:
        lines.extend(["", "## Changed Paths", ""])
        lines.extend(f"- {path}" for path in bundle.changed_paths)
    return "\n".join(lines).rstrip() + "\n"


def _write_context_artifact(
    project: Path,
    *,
    subagent_id: str,
    task: str,
    parent_task_id: str,
    child_session_id: str,
    context_mode: str,
    agent_profile: str,
    permission_mode: str = "",
    model: str = "",
    effort: str = "",
    tools: list[str] | tuple[str, ...] = (),
    disallowed_tools: list[str] | tuple[str, ...] = (),
    mcp_servers: list[str] | tuple[str, ...] = (),
    hooks: list[str] | tuple[str, ...] = (),
    skills: list[str] | tuple[str, ...] = (),
    background: bool = True,
    fork_session: Any = None,
    isolation_worktree_id: str = "",
    isolation_workspace_path: str = "",
) -> Path:
    root = task_dir(project) / "subagent_contexts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{subagent_id}.md"
    lines = [
        "# Mako Subagent Context",
        "",
        f"- subagent_id: {subagent_id}",
        f"- parent_task_id: {parent_task_id}",
        f"- child_session_id: {child_session_id}",
        f"- context_mode: {context_mode}",
        f"- agent_profile: {agent_profile}",
        f"- permission_mode: {permission_mode or '-'}",
        f"- model: {model or '-'}",
        f"- effort: {effort or '-'}",
        f"- background: {str(background).lower()}",
        f"- isolation_worktree_id: {isolation_worktree_id or '-'}",
        f"- isolation_workspace_path: {isolation_workspace_path or '-'}",
        "",
        "## Task",
        "",
        task,
        "",
    ]
    if context_mode == "fork":
        session = fork_session
        if session:
            lines.extend(["## Forked Session", "", f"- session_id: {session.session_id}", f"- title: {session.title}", f"- summary: {session.summary or '-'}", ""])
            for message in session.messages[-6:]:
                preview = " ".join(message.content.split())
                lines.append(f"- {message.role}: {preview[:500]}")
            lines.append("")
        pack = build_context_pack(project, task=task, max_message_chars=8000)
        lines.extend(["## Forked Project Context", "", pack.text[:12000]])
    else:
        lines.extend(["## Isolated Context", "", "Parent transcript and session messages are intentionally withheld. Project instructions only:", ""])
        for instruction in load_instructions(project):
            lines.extend([f"### {instruction.path}", "", instruction.text[:4000], ""])
    profile = load_agent_profile_config(project).agents.get(agent_profile)
    if profile:
        lines.extend(["", "## Agent Profile", ""])
        lines.append(f"- description: {profile.description or '-'}")
        lines.append(f"- permission_mode: {profile.permission_mode or '-'}")
        lines.append(f"- effort: {profile.effort or '-'}")
        lines.append(f"- isolation: {profile.isolation or '-'}")
        if profile.tools:
            lines.append(f"- tools: {', '.join(profile.tools)}")
        if profile.disallowed_tools:
            lines.append(f"- disallowed_tools: {', '.join(profile.disallowed_tools)}")
        if profile.skills:
            lines.append(f"- skills: {', '.join(profile.skills)}")
        if profile.prompt:
            lines.extend(["", "### Profile Prompt", "", profile.prompt[:8000]])
    lines.extend(["", "## Launch Permissions", ""])
    lines.append(f"- tools: {', '.join(tools) if tools else '-'}")
    lines.append(f"- disallowed_tools: {', '.join(disallowed_tools) if disallowed_tools else '-'}")
    lines.append(f"- mcp_servers: {', '.join(mcp_servers) if mcp_servers else '-'}")
    lines.append(f"- hooks: {', '.join(hooks) if hooks else '-'}")
    lines.append(f"- skills: {', '.join(skills) if skills else '-'}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _progress_summary(status: str, output: str) -> str:
    if not output:
        return f"status: {status}"
    compact = " ".join(output.split())
    if len(compact) > 220:
        compact = compact[:217] + "..."
    return compact


def _review_artifacts(project: Path, record: SubagentRecord) -> list[str]:
    review_path = str(isolation_root(project) / record.isolation_worktree_id / f"{record.review_id}.json")
    artifacts = [review_path]
    artifacts.extend(path for path in record.artifacts if record.review_id and record.review_id in path)
    return artifacts


def _common_parent_task_id(records: list[SubagentRecord]) -> str:
    parent_ids = {record.parent_task_id for record in records if record.parent_task_id}
    if len(parent_ids) == 1:
        return next(iter(parent_ids))
    return "mixed"


def _review_bundle_summary(records: list[SubagentRecord], changed_paths: list[str]) -> str:
    outcomes: dict[str, int] = {}
    for record in records:
        outcome = record.terminal_outcome or record.status
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    outcome_text = ", ".join(f"{name}={count}" for name, count in sorted(outcomes.items()))
    path_count = len(set(changed_paths))
    return f"{len(records)} isolated subagents produced {len(records)} reviews; {path_count} changed paths; outcomes: {outcome_text}."


def _is_reviewable_path(path: str) -> bool:
    blocked_prefixes = (
        ".quantagent/",
        "quantagent_tasks/",
        "quantagent_sessions/",
        "AI_协作交接/query_events.jsonl",
        "AI_协作交接/quantagent_isolated_worktrees/",
    )
    return not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in blocked_prefixes)
