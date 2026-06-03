from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .event_log import RuntimeEvent, read_runtime_events
from .skills import load_skill_file, skill_root, write_skill_manifest
from .trajectory import TrajectoryEvent, read_events


@dataclass(frozen=True)
class SkillProposal:
    proposal_id: str
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    status: str = "proposed"
    source: str = "trajectory"
    evidence: tuple[str, ...] = ()
    created_at_ms: int = 0
    applicability: str = ""
    failure_conditions: str = ""
    evidence_strength: float = 0.0
    reproduction_count: int = 0
    risk: float = 0.0
    benefit: float = 0.0
    eval_status: str = ""
    eval_evidence: str = ""
    rejection_reason: str = ""
    rollback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["triggers"] = list(self.triggers)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True)
class SkillEvalResult:
    passed: bool
    command: str
    summary: str
    evidence: tuple[str, ...] = ()
    returncode: int | None = None
    stdout_summary: str = ""
    stderr_summary: str = ""
    require_learning_effect: bool = False
    learning_effect_report: Any = None
    executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True)
class CuratedProposal:
    proposal: SkillProposal
    score: float
    reproduction_score: float
    evidence_score: float
    risk_score: float
    benefit_score: float


def skill_proposal_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "skill_proposals"


def propose_skill_from_trajectory(
    project: str | Path,
    trajectory_path: str | Path,
    *,
    name: str = "",
    description: str = "",
    triggers: Iterable[str] = (),
) -> SkillProposal:
    path = Path(trajectory_path).expanduser().resolve(strict=False)
    events = read_events(path)
    if not events:
        raise ValueError(f"trajectory has no events: {path}")
    inferred_name = _clean_name(name or _infer_name(events))
    inferred_description = description or _infer_description(events)
    inferred_triggers = tuple(_clean_trigger(item) for item in (tuple(triggers) or _infer_triggers(events, inferred_name)))
    body = _skill_body_from_trajectory(events, source=str(path))
    proposal = _proposal(
        name=inferred_name,
        description=inferred_description,
        triggers=inferred_triggers,
        body=body,
        source="trajectory",
        evidence=(str(path),),
    )
    return save_skill_proposal(project, proposal)


def propose_skill_from_events(
    project: str | Path,
    *,
    name: str,
    description: str,
    triggers: Iterable[str] = (),
    limit: int = 80,
) -> SkillProposal:
    events = read_runtime_events(project, limit=limit)
    if not events:
        raise ValueError("runtime event log has no events")
    clean_name = _clean_name(name)
    body = _skill_body_from_runtime_events(events)
    proposal = _proposal(
        name=clean_name,
        description=description,
        triggers=tuple(_clean_trigger(item) for item in triggers) or (clean_name,),
        body=body,
        source="event_log",
        evidence=tuple(event.event_id for event in events[-10:]),
    )
    return save_skill_proposal(project, proposal)


def propose_subject_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    function_name: str,
    source: str,
    evidence: Iterable[str] = (),
    source_kind: str = "subject_repair",
) -> SkillProposal:
    from .agent_planner import _valid_subject_repair_source

    clean_name = _clean_name(name)
    clean_function = str(function_name or "").strip()
    if not clean_function:
        raise ValueError("function_name is required")
    if not _valid_subject_repair_source(source, clean_function):
        raise ValueError("source must define exactly the requested safe repair function")
    hint = {
        "target": "subject.py",
        "function": clean_function,
        "source": source if source.endswith("\n") else source + "\n",
    }
    body = (
        "Use this skill only for matching single-function subject.py repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned subject.py repair for {clean_function}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or (clean_name, clean_function, "subject.py"),
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_subject_bundle_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    function_names: Iterable[str],
    source: str,
    evidence: Iterable[str] = (),
    source_kind: str = "subject_repair_bundle",
) -> SkillProposal:
    from .agent_planner import _valid_subject_bundle_repair_source

    clean_name = _clean_name(name)
    clean_functions = tuple(sorted({str(item).strip() for item in function_names if str(item).strip()}))
    if len(clean_functions) < 2:
        raise ValueError("function_names must contain at least two functions")
    if not _valid_subject_bundle_repair_source(source, clean_functions):
        raise ValueError("source must define exactly the requested safe repair functions")
    hint = {
        "target": "subject.py",
        "functions": list(clean_functions),
        "source": source if source.endswith("\n") else source + "\n",
    }
    body = (
        "Use this skill only for matching multi-function subject.py repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    default_triggers = (clean_name, *clean_functions, "subject.py")
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned multi-function subject.py repair for {', '.join(clean_functions)}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or default_triggers,
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_multifile_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    function_names: Iterable[str],
    files: Mapping[str, str],
    evidence: Iterable[str] = (),
    source_kind: str = "multi_file_repair",
) -> SkillProposal:
    from .agent_planner import _valid_multifile_repair_sources

    clean_name = _clean_name(name)
    clean_functions = tuple(sorted({str(item).strip() for item in function_names if str(item).strip()}))
    clean_files = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    if not clean_functions:
        raise ValueError("function_names is required")
    if not _valid_multifile_repair_sources(clean_files, clean_functions):
        raise ValueError("files must define a safe subject.py multi-file repair bundle")
    hint = {
        "target": "multi_file",
        "functions": list(clean_functions),
        "files": {
            path: source if source.endswith("\n") else source + "\n"
            for path, source in sorted(clean_files.items())
        },
    }
    body = (
        "Use this skill only for matching multi-file Python repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    default_triggers = (clean_name, *clean_functions, *tuple(sorted(clean_files)))
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned multi-file repair for {', '.join(clean_functions)}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or default_triggers,
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_file_bundle_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    files: Mapping[str, str],
    mode: str = "write_files",
    reference_files: Mapping[str, str] | None = None,
    evidence: Iterable[str] = (),
    source_kind: str = "file_bundle_repair",
) -> SkillProposal:
    from .agent_planner import (
        _file_bundle_function_names,
        _valid_file_bundle_function_repair_sources,
        _valid_file_bundle_repair_sources,
    )

    clean_name = _clean_name(name)
    clean_files = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    clean_mode = str(mode or "write_files").strip()
    if clean_mode == "replace_functions":
        if not _valid_file_bundle_function_repair_sources(clean_files, reference_files=reference_files):
            raise ValueError("files must define a safe function-level file-bundle repair")
    elif clean_mode == "write_files":
        if not _valid_file_bundle_repair_sources(clean_files):
            raise ValueError("files must define a safe file-bundle repair")
    else:
        raise ValueError(f"unsupported file-bundle repair mode: {mode}")
    if not clean_files:
        raise ValueError("files must define a safe file-bundle repair")
    functions = _file_bundle_function_names(clean_files)
    hint = {
        "target": "file_bundle",
        "functions": list(functions),
        "files": {
            path: source if source.endswith("\n") else source + "\n"
            for path, source in sorted(clean_files.items())
        },
    }
    if clean_mode != "write_files":
        hint["mode"] = clean_mode
    language = "JavaScript" if clean_files and all(Path(path).suffix == ".js" for path in clean_files) else "Python"
    body = (
        f"Use this skill only for matching existing package-module {language} repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    default_triggers = (clean_name, *functions, *tuple(sorted(clean_files)))
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned file-bundle repair for {', '.join(sorted(clean_files))}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or default_triggers,
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_javascript_file_bundle_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    files: Mapping[str, str],
    evidence: Iterable[str] = (),
    source_kind: str = "js_file_bundle_repair",
) -> SkillProposal:
    from .agent_planner import _file_bundle_function_names, _valid_javascript_file_bundle_repair_sources

    clean_name = _clean_name(name)
    clean_files = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    if not _valid_javascript_file_bundle_repair_sources(clean_files):
        raise ValueError("files must define a safe JavaScript file-bundle repair")
    functions = _file_bundle_function_names(clean_files)
    hint = {
        "target": "js_file_bundle",
        "functions": list(functions),
        "files": {
            path: source if source.endswith("\n") else source + "\n"
            for path, source in sorted(clean_files.items())
        },
    }
    body = (
        "Use this skill only for matching existing OpenClaw JavaScript repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    default_triggers = (clean_name, *functions, *tuple(sorted(clean_files)))
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned JavaScript file-bundle repair for {', '.join(sorted(clean_files))}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or default_triggers,
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_file_function_bundle_repair_skill(
    project: str | Path,
    *,
    name: str,
    description: str = "",
    triggers: Iterable[str] = (),
    files: Mapping[str, Mapping[str, str]],
    evidence: Iterable[str] = (),
    source_kind: str = "file_function_bundle_repair",
) -> SkillProposal:
    from .agent_planner import _file_function_bundle_function_names, _valid_file_function_bundle_repair_sources

    clean_name = _clean_name(name)
    clean_files = {
        Path(str(path)).as_posix(): {
            str(function_name).strip(): source if str(source).endswith("\n") else str(source) + "\n"
            for function_name, source in replacements.items()
        }
        for path, replacements in files.items()
    }
    if not _valid_file_function_bundle_repair_sources(clean_files):
        raise ValueError("files must define safe top-level function repairs for existing package modules")
    functions = _file_function_bundle_function_names(clean_files)
    hint = {
        "target": "file_function_bundle",
        "functions": list(functions),
        "files": clean_files,
    }
    body = (
        "Use this skill only for matching existing package-module function repair tasks.\n\n"
        "```openmako-repair\n"
        f"{json.dumps(hint, sort_keys=True)}\n"
        "```"
    )
    default_triggers = (clean_name, *functions, *tuple(sorted(clean_files)))
    proposal = _proposal(
        name=clean_name,
        description=description or f"Learned function-level file-bundle repair for {', '.join(sorted(clean_files))}.",
        triggers=tuple(_clean_trigger(item) for item in triggers) or default_triggers,
        body=body,
        source=source_kind,
        evidence=tuple(str(item) for item in evidence if str(item).strip()),
    )
    return save_skill_proposal(project, proposal)


def propose_file_bundle_repair_skill_from_trajectory(
    project: str | Path,
    trajectory_path: str | Path,
    *,
    workspace: str | Path | None = None,
    name: str = "",
    description: str = "",
    triggers: Iterable[str] = (),
) -> SkillProposal:
    project_path = Path(project).expanduser().resolve(strict=False)
    trajectory = Path(trajectory_path).expanduser().resolve(strict=False)
    workspace_path = Path(workspace).expanduser().resolve(strict=False) if workspace else project_path
    evidence = _successful_file_bundle_repair_trajectory_evidence(trajectory)
    touched_files = tuple(evidence.get("files_touched") or ())
    workspace_sources = _workspace_repair_files(workspace_path, touched_files)
    javascript_files = _workspace_javascript_repair_files(workspace_path, touched_files)
    proposal_name = name or _file_bundle_repair_name(touched_files)
    clean_triggers = tuple(_clean_trigger(item) for item in triggers)
    task = str(evidence.get("task") or "")
    if javascript_files:
        return propose_javascript_file_bundle_repair_skill(
            project_path,
            name=proposal_name,
            description=description or "Learned OpenClaw JavaScript repair from successful agent trajectory.",
            triggers=clean_triggers or _file_bundle_repair_trajectory_triggers(tuple(sorted(javascript_files)), task, proposal_name),
            files=javascript_files,
            evidence=(
                str(trajectory),
                *(str(workspace_path / path) for path in sorted(javascript_files)),
                f"trajectory_status={evidence.get('status', '')}",
            ),
            source_kind="file_bundle_repair_trajectory",
        )
    repair_files = workspace_sources
    mode = "write_files"
    if not _workspace_file_bundle_sources_are_full_file_safe(repair_files):
        function_files = _workspace_function_repair_files(workspace_path, touched_files)
        if function_files:
            repair_files = function_files
            mode = "replace_functions"
    return propose_file_bundle_repair_skill(
        project_path,
        name=proposal_name,
        description=description or "Learned package-module file-bundle repair from successful agent trajectory.",
        triggers=clean_triggers or _file_bundle_repair_trajectory_triggers(tuple(sorted(repair_files)), task, proposal_name),
        files=repair_files,
        mode=mode,
        reference_files=workspace_sources if mode == "replace_functions" else None,
        evidence=(
            str(trajectory),
            *(str(workspace_path / path) for path in sorted(repair_files)),
            f"trajectory_status={evidence.get('status', '')}",
        ),
        source_kind="file_bundle_repair_trajectory",
    )


def propose_subject_repair_skill_from_trajectory(
    project: str | Path,
    trajectory_path: str | Path,
    *,
    workspace: str | Path | None = None,
    name: str = "",
    description: str = "",
    triggers: Iterable[str] = (),
) -> SkillProposal:
    from .agent_planner import _find_subject_test, _subject_imports, _top_level_functions

    project_path = Path(project).expanduser().resolve(strict=False)
    trajectory = Path(trajectory_path).expanduser().resolve(strict=False)
    workspace_path = Path(workspace).expanduser().resolve(strict=False) if workspace else project_path
    evidence = _successful_subject_repair_trajectory_evidence(trajectory)
    subject_path = workspace_path / "subject.py"
    test_path = _find_subject_test(workspace_path)
    if not subject_path.exists():
        raise ValueError(f"subject.py not found in workspace: {workspace_path}")
    if test_path is None:
        raise ValueError(f"test_subject.py not found in workspace: {workspace_path}")
    subject_source = subject_path.read_text(encoding="utf-8")
    test_source = test_path.read_text(encoding="utf-8")
    function_names = tuple(sorted(_top_level_functions(subject_source)))
    imported_functions = tuple(sorted(_subject_imports(test_source)))
    if not function_names or function_names != imported_functions:
        raise ValueError("workspace subject.py functions must match test_subject.py imports")
    proposal_name = name or "-".join(function_names) + "-repair"
    task = str(evidence.get("task") or "")
    clean_triggers = tuple(_clean_trigger(item) for item in triggers)
    if len(function_names) == 1:
        touched_files = tuple(evidence.get("files_touched") or ("subject.py",))
        if touched_files != ("subject.py",):
            repair_files = _workspace_repair_files(workspace_path, touched_files)
            return propose_multifile_repair_skill(
                project_path,
                name=name or "-".join(function_names) + "-multifile-repair",
                description=description or f"Learned multi-file repair for {function_names[0]} from successful agent trajectory.",
                triggers=clean_triggers or _multifile_repair_trajectory_triggers(function_names, tuple(sorted(repair_files)), task, proposal_name),
                function_names=function_names,
                files=repair_files,
                evidence=(
                    str(trajectory),
                    *(str(workspace_path / path) for path in sorted(repair_files)),
                    str(test_path),
                    f"trajectory_status={evidence.get('status', '')}",
                ),
                source_kind="multi_file_repair_trajectory",
            )
        function_name = function_names[0]
        if not clean_triggers:
            clean_triggers = _subject_repair_trajectory_triggers(function_name, task, proposal_name)
        return propose_subject_repair_skill(
            project_path,
            name=proposal_name,
            description=description or f"Learned subject.py repair for {function_name} from successful agent trajectory.",
            triggers=clean_triggers,
            function_name=function_name,
            source=subject_source,
            evidence=(
                str(trajectory),
                str(subject_path),
                str(test_path),
                f"trajectory_status={evidence.get('status', '')}",
            ),
            source_kind="subject_repair_trajectory",
        )
    touched_files = tuple(evidence.get("files_touched") or ("subject.py",))
    if touched_files != ("subject.py",):
        repair_files = _workspace_repair_files(workspace_path, touched_files)
        return propose_multifile_repair_skill(
            project_path,
            name=name or "-".join(function_names) + "-multifile-repair",
            description=description or f"Learned multi-file repair for {', '.join(function_names)} from successful agent trajectory.",
            triggers=clean_triggers or _multifile_repair_trajectory_triggers(function_names, tuple(sorted(repair_files)), task, proposal_name),
            function_names=function_names,
            files=repair_files,
            evidence=(
                str(trajectory),
                *(str(workspace_path / path) for path in sorted(repair_files)),
                str(test_path),
                f"trajectory_status={evidence.get('status', '')}",
            ),
            source_kind="multi_file_repair_trajectory",
        )
    if not clean_triggers:
        clean_triggers = _subject_bundle_repair_trajectory_triggers(function_names, task, proposal_name)
    return propose_subject_bundle_repair_skill(
        project_path,
        name=proposal_name,
        description=description or f"Learned subject.py repair for {', '.join(function_names)} from successful agent trajectory.",
        triggers=clean_triggers,
        function_names=function_names,
        source=subject_source,
        evidence=(
            str(trajectory),
            str(subject_path),
            str(test_path),
            f"trajectory_status={evidence.get('status', '')}",
        ),
        source_kind="subject_repair_bundle_trajectory",
    )


def save_skill_proposal(project: str | Path, proposal: SkillProposal) -> SkillProposal:
    root = skill_proposal_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{proposal.proposal_id}.json"
    path.write_text(json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proposal


def list_skill_proposals(project: str | Path) -> list[SkillProposal]:
    root = skill_proposal_dir(project)
    if not root.exists():
        return []
    proposals: list[SkillProposal] = []
    for path in sorted(root.glob("*.json")):
        try:
            proposals.append(_proposal_from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:105", exc)
            continue
    return proposals


def load_skill_proposal(project: str | Path, proposal_id: str) -> SkillProposal:
    path = skill_proposal_dir(project) / f"{proposal_id}.json"
    if not path.exists():
        raise KeyError(f"skill proposal not found: {proposal_id}")
    return _proposal_from_dict(json.loads(path.read_text(encoding="utf-8")))


def approve_skill_proposal(
    project: str | Path,
    proposal_id: str,
    *,
    force: bool = False,
    eval_result: SkillEvalResult | None = None,
    require_learning_effect: bool = False,
) -> Path:
    proposal = load_skill_proposal(project, proposal_id)

    # Check if rejected
    if proposal.status == "rejected":
        raise PermissionError(f"cannot approve rejected proposal: {proposal_id}")

    # Require eval result
    if eval_result is None:
        raise PermissionError(f"skill approval requires eval_result")

    # Check eval result type
    if not isinstance(eval_result, SkillEvalResult):
        raise PermissionError(f"eval_result must be SkillEvalResult instance")

    if not eval_result.command.strip():
        raise PermissionError(f"skill approval requires eval command")

    if eval_result.returncode != 0:
        raise PermissionError(f"skill approval requires executed eval command returncode 0")

    if not eval_result.executed:
        raise PermissionError("skill approval requires eval command executed by run_skill_eval_command")

    # Check eval passed
    if not eval_result.passed:
        raise PermissionError(f"skill approval requires passing eval")

    _validate_learning_effect_report(eval_result.learning_effect_report, proposal=proposal)

    target_dir = skill_root(project) / proposal.name
    target = target_dir / "SKILL.md"
    if target.exists() and not force:
        raise FileExistsError(f"skill already exists: {proposal.name}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(render_skill_markdown(proposal), encoding="utf-8")
    # Validate the generated artifact before marking approved.
    skill = load_skill_file(target, source="project")
    eval_evidence = _render_eval_evidence(eval_result)
    write_skill_manifest(
        project,
        skill,
        approved=True,
        source_path=f"skill_proposal:{proposal.proposal_id}",
        proposal_id=proposal.proposal_id,
        proposal_body_hash=skill_proposal_body_hash(proposal),
        eval_evidence_hash=_sha256_text(eval_evidence),
        eval_command_hash=_sha256_text(eval_result.command),
    )
    approved = SkillProposal(
        proposal_id=proposal.proposal_id,
        name=proposal.name,
        description=proposal.description,
        triggers=proposal.triggers,
        body=proposal.body,
        status="approved",
        source=proposal.source,
        evidence=proposal.evidence,
        created_at_ms=proposal.created_at_ms,
        applicability=proposal.applicability,
        failure_conditions=proposal.failure_conditions,
        evidence_strength=proposal.evidence_strength,
        reproduction_count=proposal.reproduction_count,
        risk=proposal.risk,
        benefit=proposal.benefit,
        eval_status="passed",
        eval_evidence=eval_evidence,
        rejection_reason=proposal.rejection_reason,
        rollback_reason=proposal.rollback_reason,
    )
    save_skill_proposal(project, approved)
    return target


def run_skill_eval_command(
    project: str | Path,
    command: str,
    *,
    summary: str = "",
    evidence: Iterable[str] = (),
    timeout_seconds: int = 300,
) -> SkillEvalResult:
    clean_command = str(command).strip()
    if not clean_command:
        raise ValueError("eval command is required")
    completed = subprocess.run(
        clean_command,
        cwd=Path(project).expanduser().resolve(strict=False),
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    stdout_summary = _preview(completed.stdout, 800)
    stderr_summary = _preview(completed.stderr, 800)
    evidence_items = tuple(str(item) for item in evidence if str(item).strip())
    return SkillEvalResult(
        passed=completed.returncode == 0,
        command=clean_command,
        summary=summary or f"eval command exited {completed.returncode}",
        evidence=evidence_items,
        returncode=completed.returncode,
        stdout_summary=stdout_summary,
        stderr_summary=stderr_summary,
        executed=True,
    )


def reject_skill_proposal(project: str | Path, proposal_id: str, *, reason: str = "") -> SkillProposal:
    """Reject a skill proposal and record the reason."""
    proposal = load_skill_proposal(project, proposal_id)
    rejected = SkillProposal(
        proposal_id=proposal.proposal_id,
        name=proposal.name,
        description=proposal.description,
        triggers=proposal.triggers,
        body=proposal.body,
        status="rejected",
        source=proposal.source,
        evidence=proposal.evidence,
        created_at_ms=proposal.created_at_ms,
        applicability=proposal.applicability,
        failure_conditions=proposal.failure_conditions,
        evidence_strength=proposal.evidence_strength,
        reproduction_count=proposal.reproduction_count,
        risk=proposal.risk,
        benefit=proposal.benefit,
        eval_status=proposal.eval_status,
        eval_evidence=proposal.eval_evidence,
        rejection_reason=reason,
        rollback_reason=proposal.rollback_reason,
    )
    save_skill_proposal(project, rejected)
    return rejected


def rollback_skill_proposal_install(project: str | Path, proposal_id: str, *, reason: str = "") -> SkillProposal:
    """Rollback an installed skill proposal."""
    proposal = load_skill_proposal(project, proposal_id)

    # Remove installed skill
    target_dir = skill_root(project) / proposal.name
    target = target_dir / "SKILL.md"
    if target.exists():
        target.unlink()
    if target_dir.exists() and not any(target_dir.iterdir()):
        target_dir.rmdir()

    rolled_back = SkillProposal(
        proposal_id=proposal.proposal_id,
        name=proposal.name,
        description=proposal.description,
        triggers=proposal.triggers,
        body=proposal.body,
        status="rolled_back",
        source=proposal.source,
        evidence=proposal.evidence,
        created_at_ms=proposal.created_at_ms,
        applicability=proposal.applicability,
        failure_conditions=proposal.failure_conditions,
        evidence_strength=proposal.evidence_strength,
        reproduction_count=proposal.reproduction_count,
        risk=proposal.risk,
        benefit=proposal.benefit,
        eval_status=proposal.eval_status,
        eval_evidence=proposal.eval_evidence,
        rejection_reason=proposal.rejection_reason,
        rollback_reason=reason,
    )
    save_skill_proposal(project, rolled_back)
    return rolled_back


def curate_skill_proposals(proposals: Iterable[SkillProposal]) -> list[CuratedProposal]:
    """Rank skill proposals by evidence, reproduction, risk, and benefit."""
    curated: list[CuratedProposal] = []

    for proposal in proposals:
        # Calculate component scores
        evidence_score = proposal.evidence_strength
        reproduction_score = min(1.0, proposal.reproduction_count / 3.0)
        risk_score = 1.0 - proposal.risk
        benefit_score = proposal.benefit

        # Overall score: weighted combination
        score = (
            evidence_score * 0.3 +
            reproduction_score * 0.3 +
            risk_score * 0.2 +
            benefit_score * 0.2
        )

        curated.append(CuratedProposal(
            proposal=proposal,
            score=score,
            reproduction_score=reproduction_score,
            evidence_score=evidence_score,
            risk_score=risk_score,
            benefit_score=benefit_score,
        ))

    # Sort by score descending
    return sorted(curated, key=lambda c: c.score, reverse=True)



def render_skill_proposals(proposals: Iterable[SkillProposal]) -> str:
    items = list(proposals)
    if not items:
        return "No skill proposals.\n"
    lines = ["# Mako Skill Proposals", ""]
    for proposal in items:
        triggers = ", ".join(proposal.triggers)
        lines.append(f"- [{proposal.status}] {proposal.proposal_id}: {proposal.name} ({triggers})")
        lines.append(f"  {proposal.description}")
    return "\n".join(lines) + "\n"


def render_skill_markdown(proposal: SkillProposal) -> str:
    triggers = ", ".join(proposal.triggers)
    return (
        "---\n"
        f"name: {proposal.name}\n"
        f"description: {proposal.description}\n"
        f"triggers: {triggers}\n"
        "---\n\n"
        f"# {proposal.name}\n\n"
        f"{proposal.body.strip()}\n"
    )


def render_skill_proposal(proposal: SkillProposal) -> str:
    return json.dumps(proposal.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _proposal(
    *,
    name: str,
    description: str,
    triggers: tuple[str, ...],
    body: str,
    source: str,
    evidence: tuple[str, ...],
) -> SkillProposal:
    import time

    payload = {
        "name": name,
        "description": description,
        "triggers": list(triggers),
        "body": body,
        "source": source,
        "evidence": list(evidence),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return SkillProposal(
        proposal_id=f"skill-{digest}",
        name=name,
        description=description,
        triggers=triggers,
        body=body,
        source=source,
        evidence=evidence,
        created_at_ms=int(time.time() * 1000),
        applicability="Use when a future task has the same failure signals and evidence shape.",
        failure_conditions="Do not use if the reproduced failure or verification evidence differs.",
        evidence_strength=min(1.0, 0.25 + 0.15 * len(evidence)),
        reproduction_count=max(1, len(evidence)),
        risk=0.3,
        benefit=0.6,
    )


def _proposal_from_dict(data: dict[str, Any]) -> SkillProposal:
    return SkillProposal(
        proposal_id=str(data["proposal_id"]),
        name=str(data["name"]),
        description=str(data.get("description") or ""),
        triggers=tuple(str(item) for item in data.get("triggers") or ()),
        body=str(data.get("body") or ""),
        status=str(data.get("status") or "proposed"),
        source=str(data.get("source") or "trajectory"),
        evidence=tuple(str(item) for item in data.get("evidence") or ()),
        created_at_ms=int(data.get("created_at_ms") or 0),
        applicability=str(data.get("applicability") or ""),
        failure_conditions=str(data.get("failure_conditions") or ""),
        evidence_strength=float(data.get("evidence_strength") or 0.0),
        reproduction_count=int(data.get("reproduction_count") or 0),
        risk=float(data.get("risk") or 0.0),
        benefit=float(data.get("benefit") or 0.0),
        eval_status=str(data.get("eval_status") or ""),
        eval_evidence=str(data.get("eval_evidence") or ""),
        rejection_reason=str(data.get("rejection_reason") or ""),
        rollback_reason=str(data.get("rollback_reason") or ""),
    )


def _skill_body_from_trajectory(events: list[TrajectoryEvent], *, source: str) -> str:
    failures = [event for event in events if event.ok is False]
    successes = [event for event in events if event.ok is True]
    lines = [
        "Use this skill when a task resembles the trajectory that produced this proposal.",
        "",
        "Procedure:",
        "1. Reproduce the exact failure or uncertainty before editing.",
        "2. Inspect the files, commands, diagnostics, and artifacts that explain the outcome.",
        "3. Apply the smallest change that addresses the observed cause.",
        "4. Run the narrow verification first, then the broader suite.",
        "",
        "Observed signals:",
    ]
    for event in events[-12:]:
        state = "ok" if event.ok is True else ("failed" if event.ok is False else "observed")
        lines.append(f"- {event.kind}/{state}: {_preview(event.content)}")
    if failures:
        lines.extend(["", "Failure patterns:"])
        for event in failures[-5:]:
            lines.append(f"- {_preview(event.content, 180)}")
    if successes:
        lines.extend(["", "Successful checks:"])
        for event in successes[-5:]:
            lines.append(f"- {_preview(event.content, 180)}")
    lines.extend(["", f"Source trajectory: {source}"])
    return "\n".join(lines)


def _skill_body_from_runtime_events(events: list[RuntimeEvent]) -> str:
    lines = [
        "Use this skill when runtime events show a similar tool/task/diagnostic pattern.",
        "",
        "Checklist:",
        "1. Read the correlated event/task history before acting.",
        "2. Check approval, diff, diagnostic, and test events for the first failing cause.",
        "3. Prefer replayable commands and artifact-backed conclusions.",
        "",
        "Recent event pattern:",
    ]
    for event in events[-15:]:
        lines.append(f"- {event.kind}/{event.status}: {_preview(event.summary)}")
    return "\n".join(lines)


def _infer_name(events: list[TrajectoryEvent]) -> str:
    failed = next((event for event in events if event.ok is False), None)
    seed = failed.content if failed else events[-1].content
    words = re.findall(r"[A-Za-z0-9_]+", seed.lower())[:4]
    return "-".join(words) if words else "learned-repair"


def _infer_description(events: list[TrajectoryEvent]) -> str:
    failed = [event for event in events if event.ok is False]
    if failed:
        return "Learned repair procedure from a failed trajectory."
    return "Learned procedure from a successful trajectory."


def _infer_triggers(events: list[TrajectoryEvent], name: str) -> tuple[str, ...]:
    triggers = [name]
    for event in events:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", event.content.lower()):
            if word not in triggers:
                triggers.append(word)
            if len(triggers) >= 5:
                return tuple(triggers)
    return tuple(triggers)


def _clean_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "learned-skill"


def _clean_trigger(value: str) -> str:
    return " ".join(str(value).split()).strip() or "learned"


def _successful_subject_repair_trajectory_evidence(path: Path) -> dict[str, Any]:
    entries = _read_agent_loop_trajectory_entries(path)
    if not entries:
        raise ValueError(f"agent-loop trajectory has no entries: {path}")
    successful = [entry for entry in entries if entry.get("ok") is True]
    if not successful:
        raise ValueError("agent-loop trajectory has no successful entry")
    entry = successful[-1]
    observations = entry.get("observations")
    if not isinstance(observations, list):
        raise ValueError("agent-loop trajectory entry has no observations")
    implement = next(
        (
            observation
            for observation in observations
            if isinstance(observation, dict)
            and observation.get("name") == "implement"
            and observation.get("ok") is True
            and _valid_repair_trajectory_touch_set(_observation_files_touched(observation))
        ),
        None,
    )
    if implement is None:
        raise ValueError("successful trajectory must record a subject.py repair implement step")
    if not any(
        isinstance(observation, dict)
        and observation.get("ok") is True
        and str(observation.get("name") or "") in {"validate", "unit_tests", "checks", "final_review"}
        for observation in observations
    ):
        raise ValueError("successful trajectory must include a passing verification observation")
    return {
        "task": str(entry.get("task") or ""),
        "status": str(entry.get("status") or ""),
        "files_touched": _observation_files_touched(implement),
    }


def _successful_file_bundle_repair_trajectory_evidence(path: Path) -> dict[str, Any]:
    entries = _read_agent_loop_trajectory_entries(path)
    if not entries:
        raise ValueError(f"agent-loop trajectory has no entries: {path}")
    successful = [entry for entry in entries if entry.get("ok") is True]
    if not successful:
        raise ValueError("agent-loop trajectory has no successful entry")
    entry = successful[-1]
    observations = entry.get("observations")
    if not isinstance(observations, list):
        raise ValueError("agent-loop trajectory entry has no observations")
    implement = next(
        (
            observation
            for observation in observations
            if isinstance(observation, dict)
            and observation.get("name") == "implement"
            and observation.get("ok") is True
            and _valid_file_bundle_trajectory_touch_set(_observation_files_touched(observation))
        ),
        None,
    )
    if implement is None:
        raise ValueError("successful trajectory must record a safe file-bundle repair implement step")
    if not any(
        isinstance(observation, dict)
        and observation.get("ok") is True
        and str(observation.get("name") or "") in {"validate", "unit_tests", "checks", "final_review"}
        for observation in observations
    ):
        raise ValueError("successful trajectory must include a passing verification observation")
    return {
        "task": str(entry.get("task") or ""),
        "status": str(entry.get("status") or ""),
        "files_touched": _observation_files_touched(implement),
    }


def _read_agent_loop_trajectory_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"trajectory not found: {path}")
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid agent-loop trajectory JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"invalid agent-loop trajectory JSONL at line {line_number}: expected object")
            if "observations" in payload and "ok" in payload:
                entries.append(payload)
    return entries


def _observation_files_touched(observation: dict[str, Any]) -> tuple[str, ...]:
    data = observation.get("data")
    if not isinstance(data, dict):
        return ()
    files = data.get("files_touched") or data.get("changed_files") or ()
    if isinstance(files, str):
        files = (files,)
    if not isinstance(files, (list, tuple)):
        return ()
    return tuple(sorted(str(item) for item in files if str(item).strip()))


def _valid_repair_trajectory_touch_set(files: tuple[str, ...]) -> bool:
    if "subject.py" not in files:
        return False
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            return False
        if len(path.parts) != 1 or path.suffix != ".py":
            return False
        if path.name.startswith("test_") or path.name == "conftest.py":
            return False
    return True


def _valid_file_bundle_trajectory_touch_set(files: tuple[str, ...]) -> bool:
    if not files:
        return False
    if "subject.py" in files:
        return False
    try:
        from .agent_planner import _safe_file_bundle_repair_path, _safe_javascript_repair_path
    except ImportError:
        return False
    return all(_safe_file_bundle_repair_path(name) or _safe_javascript_repair_path(name) for name in files)


def _workspace_repair_files(workspace: Path, files_touched: tuple[str, ...]) -> dict[str, str]:
    repair_files: dict[str, str] = {}
    for name in files_touched:
        path = workspace / name
        if not path.exists():
            raise ValueError(f"trajectory touched missing repair file: {name}")
        repair_files[name] = path.read_text(encoding="utf-8")
    return repair_files


def _workspace_javascript_repair_files(workspace: Path, files_touched: tuple[str, ...]) -> dict[str, str]:
    try:
        from .agent_planner import _safe_javascript_repair_path, _valid_javascript_file_bundle_repair_sources
    except ImportError:
        return {}
    touched = tuple(Path(name).as_posix() for name in files_touched)
    if not touched or not all(_safe_javascript_repair_path(name) for name in touched):
        return {}
    repair_files: dict[str, str] = {}
    for name in touched:
        path = workspace / name
        if not path.exists():
            return {}
        try:
            repair_files[name] = path.read_text(encoding="utf-8")
        except OSError:
            return {}
    if not _valid_javascript_file_bundle_repair_sources(repair_files):
        return {}
    return repair_files


def _workspace_file_bundle_sources_are_full_file_safe(files: Mapping[str, str]) -> bool:
    try:
        from .agent_planner import _valid_file_bundle_repair_sources
    except ImportError:
        return False
    return _valid_file_bundle_repair_sources(files)


def _workspace_function_repair_files(workspace: Path, files_touched: tuple[str, ...]) -> dict[str, str]:
    try:
        from .agent_planner import (
            _file_bundle_function_repair_snippet,
            _file_bundle_test_text,
            _package_function_imports,
            _safe_file_bundle_repair_path,
            _valid_file_bundle_function_repair_sources,
        )
    except ImportError:
        return {}
    test_text = "\n".join(_file_bundle_test_text(workspace).values())
    if not test_text:
        return {}
    functions_by_path: dict[str, list[str]] = {}
    touched = {Path(name).as_posix() for name in files_touched}
    for module, function_name in _package_function_imports(test_text):
        path = Path(*module.split(".")).with_suffix(".py").as_posix()
        if path in touched and _safe_file_bundle_repair_path(path):
            functions_by_path.setdefault(path, []).append(function_name)
    repair_files: dict[str, str] = {}
    reference_sources: dict[str, str] = {}
    for name in sorted(touched):
        function_names = tuple(dict.fromkeys(functions_by_path.get(name, ())))
        if not function_names:
            return {}
        source_path = workspace / name
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        snippet = _file_bundle_function_repair_snippet(source, function_names)
        if snippet is None:
            return {}
        repair_files[name] = snippet
        reference_sources[name] = source
    if not repair_files or not _valid_file_bundle_function_repair_sources(repair_files, reference_files=reference_sources):
        return {}
    return repair_files


def _subject_repair_trajectory_triggers(function_name: str, task: str, proposal_name: str) -> tuple[str, ...]:
    triggers = [proposal_name, function_name, function_name.replace("_", " "), "subject.py"]
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", task.lower()):
        if word not in triggers:
            triggers.append(word)
        if len(triggers) >= 6:
            break
    return tuple(triggers)


def _subject_bundle_repair_trajectory_triggers(function_names: tuple[str, ...], task: str, proposal_name: str) -> tuple[str, ...]:
    triggers = [proposal_name, "subject.py"]
    for function_name in function_names:
        for trigger in (function_name, function_name.replace("_", " ")):
            if trigger not in triggers:
                triggers.append(trigger)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", task.lower()):
        if word not in triggers:
            triggers.append(word)
        if len(triggers) >= 8:
            break
    return tuple(triggers)


def _multifile_repair_trajectory_triggers(
    function_names: tuple[str, ...],
    files: tuple[str, ...],
    task: str,
    proposal_name: str,
) -> tuple[str, ...]:
    triggers = [proposal_name, "multi file repair"]
    for function_name in function_names:
        for trigger in (function_name, function_name.replace("_", " ")):
            if trigger not in triggers:
                triggers.append(trigger)
    for path in files:
        if path not in triggers:
            triggers.append(path)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", task.lower()):
        if word not in triggers:
            triggers.append(word)
        if len(triggers) >= 10:
            break
    return tuple(triggers)


def _file_bundle_repair_trajectory_triggers(files: tuple[str, ...], task: str, proposal_name: str) -> tuple[str, ...]:
    triggers = [proposal_name, "file bundle repair", "package module repair"]
    for path in files:
        if path not in triggers:
            triggers.append(path)
        module = ".".join(Path(path).with_suffix("").parts)
        if module and module not in triggers:
            triggers.append(module)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", task.lower()):
        if word not in triggers:
            triggers.append(word)
        if len(triggers) >= 10:
            break
    return tuple(triggers)


def _file_bundle_repair_name(files: tuple[str, ...]) -> str:
    if not files:
        return "file-bundle-repair"
    stems = [Path(path).with_suffix("").as_posix().replace("/", "-") for path in files]
    return "-".join(stems) + "-repair"


def _preview(text: str, max_chars: int = 140) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "..."


def _render_eval_evidence(eval_result: SkillEvalResult) -> str:
    payload = {
        "command": eval_result.command,
        "returncode": eval_result.returncode,
        "summary": eval_result.summary,
        "stdout_summary": eval_result.stdout_summary,
        "stderr_summary": eval_result.stderr_summary,
        "executed": eval_result.executed,
        "evidence": list(eval_result.evidence),
    }
    learning_effect = _learning_effect_evidence(eval_result.learning_effect_report)
    if learning_effect is not None:
        payload["learning_effect"] = learning_effect
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def skill_proposal_body_hash(proposal: SkillProposal) -> str:
    return hashlib.sha256(proposal.body.encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bind_learning_effect_report_to_proposal(report: Any, proposal: SkillProposal) -> dict[str, Any]:
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
    elif isinstance(report, dict):
        payload = dict(report)
    else:
        raise PermissionError("learning-effect report must be structured")
    payload["proposal_id"] = proposal.proposal_id
    payload["proposal_name"] = proposal.name
    payload["proposal_body_hash"] = skill_proposal_body_hash(proposal)
    return payload


def _validate_learning_effect_report(report: Any, *, proposal: SkillProposal) -> None:
    evidence = learning_effect_report_evidence(report)
    if evidence["status"] != "pass":
        raise PermissionError("skill approval requires learning-effect status pass")
    if evidence["score_delta"] <= 0:
        raise PermissionError("skill approval requires positive learning-effect score_delta")
    if evidence["proposal_id"] != proposal.proposal_id:
        raise PermissionError("learning-effect report proposal_id does not match approved proposal")
    if evidence["proposal_body_hash"] != skill_proposal_body_hash(proposal):
        raise PermissionError("learning-effect report proposal_body_hash does not match approved proposal")


def learning_effect_report_evidence(report: Any) -> dict[str, Any]:
    evidence = _learning_effect_evidence(report)
    if evidence is None:
        raise PermissionError("skill approval requires learning-effect report")
    return evidence


def _learning_effect_evidence(report: Any) -> dict[str, Any] | None:
    if report is None:
        return None
    if hasattr(report, "to_dict"):
        payload = report.to_dict()
    elif isinstance(report, dict):
        payload = dict(report)
    else:
        raise PermissionError("learning-effect report must be structured")

    status = str(payload.get("status") or "").strip().lower()
    try:
        score_delta = float(payload.get("score_delta"))
    except (TypeError, ValueError) as exc:
        raise PermissionError("learning-effect report requires numeric score_delta") from exc
    if not math.isfinite(score_delta):
        raise PermissionError("learning-effect report requires finite score_delta")
    gap = str(payload.get("gap") or "")
    summary = str(payload.get("summary") or gap or f"learning_effect {status} delta {score_delta:g}")
    comparisons = _validated_learning_effect_comparisons(payload)
    return {
        "status": status,
        "score_delta": score_delta,
        "gap": gap,
        "summary": summary,
        "total": int(payload.get("total") or 0),
        "solved": payload.get("solved"),
        "comparison_count": len(comparisons),
        "proposal_id": str(payload.get("proposal_id") or ""),
        "proposal_name": str(payload.get("proposal_name") or ""),
        "proposal_body_hash": str(payload.get("proposal_body_hash") or ""),
    }


def _validated_learning_effect_comparisons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons = payload.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        raise PermissionError("learning-effect report requires per-task comparisons")
    try:
        total = int(payload.get("total") or 0)
    except (TypeError, ValueError) as exc:
        raise PermissionError("learning-effect report requires positive total") from exc
    if total <= 0:
        raise PermissionError("learning-effect report requires positive total")
    if len(comparisons) != total:
        raise PermissionError("learning-effect comparison count must match total")
    solved = payload.get("solved")
    if not isinstance(solved, dict):
        raise PermissionError("learning-effect report requires solved summary")
    try:
        approved_solved = int(solved.get("approved_learning") or 0)
        no_learning_solved = int(solved.get("no_learning") or 0)
    except (TypeError, ValueError) as exc:
        raise PermissionError("learning-effect report requires numeric solved summary") from exc
    if approved_solved <= no_learning_solved:
        raise PermissionError("learning-effect report requires approved-learning solved improvement")
    positive_task_delta = False
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            raise PermissionError("learning-effect comparisons must be objects")
        task_id = str(comparison.get("task_id") or "").strip()
        if not task_id:
            raise PermissionError("learning-effect comparison requires task_id")
        try:
            task_delta = float(comparison.get("score_delta"))
        except (TypeError, ValueError) as exc:
            raise PermissionError("learning-effect comparison requires numeric score_delta") from exc
        if not math.isfinite(task_delta):
            raise PermissionError("learning-effect comparison requires finite score_delta")
        positive_task_delta = positive_task_delta or task_delta > 0
        _validate_learning_result_evidence(comparison.get("no_learning"), "no_learning", task_id)
        _validate_learning_result_evidence(comparison.get("approved_learning"), "approved_learning", task_id)
    if not positive_task_delta:
        raise PermissionError("learning-effect report requires positive per-task score_delta")
    return comparisons


def _validate_learning_result_evidence(result: Any, field: str, task_id: str) -> None:
    if not isinstance(result, dict):
        raise PermissionError(f"learning-effect comparison requires {field} result")
    if str(result.get("task_id") or "").strip() != task_id:
        raise PermissionError(f"learning-effect {field} result task_id must match comparison")
    evidence = result.get("evidence")
    if isinstance(evidence, str):
        has_evidence = bool(evidence.strip())
    elif isinstance(evidence, list):
        has_evidence = any(str(item).strip() for item in evidence)
    else:
        has_evidence = False
    if not has_evidence:
        raise PermissionError(f"learning-effect {field} result requires evidence")
    if str(result.get("invalid_reason") or "").strip():
        raise PermissionError(f"learning-effect {field} result is invalid")
