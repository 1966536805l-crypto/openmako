from __future__ import annotations

import fnmatch
import json
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .safety import DENY, SafetyPolicy, assess_command


CHECK_LOCATIONS = (
    (".quantagent/checks", "*.md"),
    (".continue/checks", "*.md"),
)
PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"


@dataclass(frozen=True)
class SourceCheckSpec:
    check_id: str
    source: str
    description: str
    body: str
    globs: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    required_patterns: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    severity: str = "error"
    always_apply: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["globs"] = list(self.globs)
        payload["commands"] = list(self.commands)
        payload["required_patterns"] = list(self.required_patterns)
        payload["forbidden_patterns"] = list(self.forbidden_patterns)
        return payload


@dataclass(frozen=True)
class SourceCheckResult:
    check_id: str
    status: str
    message: str
    source: str
    severity: str = "error"
    paths: tuple[str, ...] = ()
    command: str = ""
    output_preview: str = ""
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {PASS, SKIP}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paths"] = list(self.paths)
        return payload


def source_checks_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "checks"


def load_source_checks(project: str | Path) -> list[SourceCheckSpec]:
    project_path = Path(project).expanduser().resolve(strict=False)
    checks: list[SourceCheckSpec] = []
    for directory, pattern in CHECK_LOCATIONS:
        root = project_path / directory
        if not root.exists():
            continue
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            checks.append(parse_source_check(path.read_text(encoding="utf-8", errors="replace"), _rel(project_path, path)))
    return checks


def parse_source_check(text: str, source: str) -> SourceCheckSpec:
    metadata, body = _split_frontmatter(text)
    check_id = _string(metadata.get("id")) or Path(source).stem
    description = _string(metadata.get("description")) or _first_sentence(body) or check_id
    return SourceCheckSpec(
        check_id=check_id,
        source=source,
        description=description,
        body=body.strip(),
        globs=tuple(_list(metadata.get("globs") or metadata.get("paths"))),
        commands=tuple(_list(metadata.get("commands") or metadata.get("command"))),
        required_patterns=tuple(_list(metadata.get("required_patterns") or metadata.get("requiredPatterns") or metadata.get("require"))),
        forbidden_patterns=tuple(_list(metadata.get("forbidden_patterns") or metadata.get("forbiddenPatterns") or metadata.get("forbid"))),
        severity=_string(metadata.get("severity")) or "error",
        always_apply=_bool(metadata.get("always_apply") or metadata.get("alwaysApply")),
    )


def run_source_checks(
    project: str | Path,
    *,
    paths: Iterable[str | Path] = (),
    run_commands: bool = False,
    timeout: int = 120,
    checks_project: str | Path | None = None,
) -> list[SourceCheckResult]:
    project_path = Path(project).expanduser().resolve(strict=False)
    checks_project_path = Path(checks_project).expanduser().resolve(strict=False) if checks_project else project_path
    changed_paths = tuple(_normalize_path(path) for path in paths if _normalize_path(path))
    specs = load_source_checks(checks_project_path)
    if not specs:
        return []
    results: list[SourceCheckResult] = []
    for spec in specs:
        matched = _matched_paths(project_path, spec, changed_paths)
        if not spec.always_apply and not matched and changed_paths:
            results.append(SourceCheckResult(spec.check_id, SKIP, "check does not match changed paths", spec.source, spec.severity))
            continue
        target_paths = matched or _candidate_paths(project_path, spec)
        results.extend(_pattern_results(project_path, spec, target_paths))
        if run_commands:
            results.extend(_command_results(project_path, spec, timeout=timeout))
        elif spec.commands:
            results.append(SourceCheckResult(spec.check_id, SKIP, "commands not run; pass --run-commands to execute them", spec.source, spec.severity))
    return results


def render_source_checks(checks: Iterable[SourceCheckSpec]) -> str:
    items = list(checks)
    if not items:
        return "No source checks found.\n"
    lines = ["# Mako Source Checks", ""]
    for check in items:
        globs = f" globs={','.join(check.globs)}" if check.globs else ""
        commands = f" commands={len(check.commands)}" if check.commands else ""
        lines.append(f"- {check.check_id}{globs}{commands}: {check.description} ({check.source})")
    return "\n".join(lines) + "\n"


def render_source_check_results(results: Iterable[SourceCheckResult]) -> str:
    items = list(results)
    if not items:
        return "No source check results.\n"
    lines = ["# Source Check Results", ""]
    for result in items:
        paths = f" paths={','.join(result.paths[:5])}" if result.paths else ""
        command = f" command={result.command}" if result.command else ""
        lines.append(f"- [{result.status}] {result.check_id}{paths}{command}: {result.message}")
        if result.output_preview:
            lines.append(f"  {result.output_preview}")
    return "\n".join(lines) + "\n"


def source_check_summary(results: Iterable[SourceCheckResult]) -> dict[str, Any]:
    items = list(results)
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "total": len(items),
        "counts": counts,
        "ok": all(item.ok for item in items),
        "failures": [item.to_dict() for item in items if item.status == FAIL],
        "warnings": [item.to_dict() for item in items if item.status == WARN],
    }


def _pattern_results(project: Path, spec: SourceCheckSpec, paths: tuple[str, ...]) -> list[SourceCheckResult]:
    results: list[SourceCheckResult] = []
    combined = _combined_text(project, paths)
    for pattern in spec.required_patterns:
        try:
            matched = re.search(pattern, combined, re.MULTILINE) is not None
        except re.error as exc:
            results.append(SourceCheckResult(spec.check_id, FAIL, f"invalid required regex {pattern!r}: {exc}", spec.source, spec.severity))
            continue
        results.append(
            SourceCheckResult(
                spec.check_id,
                PASS if matched else FAIL,
                f"required pattern present: {pattern}" if matched else f"required pattern missing: {pattern}",
                spec.source,
                spec.severity,
                paths=paths,
            )
        )
    for pattern in spec.forbidden_patterns:
        try:
            matched = re.search(pattern, combined, re.MULTILINE) is not None
        except re.error as exc:
            results.append(SourceCheckResult(spec.check_id, FAIL, f"invalid forbidden regex {pattern!r}: {exc}", spec.source, spec.severity))
            continue
        results.append(
            SourceCheckResult(
                spec.check_id,
                FAIL if matched else PASS,
                f"forbidden pattern found: {pattern}" if matched else f"forbidden pattern absent: {pattern}",
                spec.source,
                spec.severity,
                paths=paths,
            )
        )
    if not spec.required_patterns and not spec.forbidden_patterns and not spec.commands:
        results.append(SourceCheckResult(spec.check_id, PASS, "check is advisory; no executable assertions configured", spec.source, spec.severity, paths=paths))
    return results


def _command_results(project: Path, spec: SourceCheckSpec, *, timeout: int) -> list[SourceCheckResult]:
    results: list[SourceCheckResult] = []
    for command in spec.commands:
        decision = assess_command(command, cwd=project, policy=SafetyPolicy(project=project))
        if decision.action == DENY:
            results.append(SourceCheckResult(spec.check_id, FAIL, f"command denied by safety policy: {decision.render()}", spec.source, spec.severity, command=command))
            continue
        started = time.time()
        try:
            proc = subprocess.run(
                shlex.split(command),
                cwd=project,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            duration_ms = int((time.time() - started) * 1000)
            output = (proc.stdout or "").strip()
            results.append(
                SourceCheckResult(
                    spec.check_id,
                    PASS if proc.returncode == 0 else FAIL,
                    f"command exited {proc.returncode}",
                    spec.source,
                    spec.severity,
                    command=command,
                    output_preview=_preview(output),
                    duration_ms=duration_ms,
                )
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            results.append(SourceCheckResult(spec.check_id, FAIL, f"command failed: {type(exc).__name__}: {exc}", spec.source, spec.severity, command=command))
    return results


def _matched_paths(project: Path, spec: SourceCheckSpec, changed_paths: tuple[str, ...]) -> tuple[str, ...]:
    if not changed_paths:
        return ()
    if spec.always_apply or not spec.globs:
        return changed_paths
    return tuple(path for path in changed_paths if _matches_any(path, spec.globs))


def _candidate_paths(project: Path, spec: SourceCheckSpec) -> tuple[str, ...]:
    if not spec.globs:
        return tuple()
    paths: list[str] = []
    for path in _iter_project_files(project):
        rel = _rel(project, path)
        if _matches_any(rel, spec.globs):
            paths.append(rel)
    return tuple(paths)


def _combined_text(project: Path, paths: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for rel in paths:
        path = project / rel
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[:120_000])
    return "\n".join(chunks)


def _iter_project_files(project: Path) -> list[Path]:
    skipped = {".git", ".quantagent", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    return [path for path in sorted(project.rglob("*")) if path.is_file() and not any(part in skipped for part in path.relative_to(project).parts)]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    return _parse_frontmatter(lines[1:end]), "\n".join(lines[end + 1 :])


def _parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            index += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = _clean_scalar(value)
            index += 1
            continue
        items: list[str] = []
        index += 1
        while index < len(lines) and lines[index][:1].isspace():
            stripped = lines[index].strip()
            if stripped.startswith("-"):
                items.append(_clean_scalar(stripped[1:].strip()))
            index += 1
        data[key] = items
    return data


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item for item in (_clean_scalar(part) for part in re.split(r",|\s+", text)) if item]


def _string(value: Any) -> str:
    return _clean_scalar(str(value)) if value is not None else ""


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _matches_any(path: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, glob) or fnmatch.fnmatchcase(Path(path).name, glob) for glob in globs)


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().strip("/")


def _rel(project: Path, path: Path) -> str:
    return str(path.relative_to(project)).replace("\\", "/")


def _first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    return compact.split(". ", 1)[0][:160]


def _preview(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."
