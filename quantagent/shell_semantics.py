from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


READ_VERBS = {
    "awk",
    "cat",
    "date",
    "df",
    "diff",
    "du",
    "echo",
    "false",
    "file",
    "find",
    "git",
    "grep",
    "head",
    "id",
    "ls",
    "printf",
    "pwd",
    "rg",
    "sed",
    "sort",
    "stat",
    "tail",
    "test",
    "true",
    "uname",
    "wc",
    "which",
}

WRITE_VERBS = {"cp", "install", "mkdir", "mv", "rsync", "tee", "touch"}
DESTRUCTIVE_VERBS = {"chmod", "chown", "dd", "diskutil", "kill", "mkfs", "rm", "rmdir", "shred", "sudo", "unlink"}
NETWORK_VERBS = {"curl", "gh", "git", "npm", "npx", "pip", "pip3", "pnpm", "uv", "wget", "yarn"}
PACKAGE_MANAGER_VERBS = {"brew", "cargo", "gem", "npm", "npx", "pip", "pip3", "pnpm", "uv", "yarn"}
CONNECTORS = {"&&", "||", ";", "|", "&"}
REDIRECTS = {">", ">>", "1>", "1>>", "2>", "2>>", "&>"}

GIT_READ_SUBCOMMANDS = {
    "branch",
    "blame",
    "diff",
    "grep",
    "log",
    "ls-files",
    "remote",
    "rev-parse",
    "show",
    "status",
}
GIT_WRITE_SUBCOMMANDS = {"add", "am", "apply", "checkout", "cherry-pick", "clean", "commit", "merge", "pull", "push", "rebase", "reset", "restore", "switch"}


@dataclass(frozen=True)
class ShellSegment:
    verb: str
    args: tuple[str, ...]
    categories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShellSemantics:
    command: str
    parse_ok: bool
    risk_level: str
    categories: tuple[str, ...]
    verbs: tuple[str, ...]
    segments: tuple[ShellSegment, ...]
    reasons: tuple[str, ...]
    subjects: tuple[str, ...]
    write_targets: tuple[str, ...]
    external_targets: tuple[str, ...]
    has_shell_expansion: bool

    @property
    def deny_hardline(self) -> bool:
        return self.risk_level.startswith("L5")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_shell_command(
    command: str,
    *,
    cwd: str | Path | None = None,
    project: str | Path | None = None,
) -> ShellSemantics:
    cwd_path = _real(Path(cwd or "."))
    project_path = _real(Path(project)) if project is not None else cwd_path
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return ShellSemantics(
            command=command,
            parse_ok=False,
            risk_level="L5_PARSE",
            categories=("parse_error",),
            verbs=(),
            segments=(),
            reasons=(f"cannot parse shell command: {exc}",),
            subjects=("risk:L5_PARSE", "category:parse_error"),
            write_targets=(),
            external_targets=(),
            has_shell_expansion=False,
        )

    if not tokens:
        return ShellSemantics(
            command=command,
            parse_ok=False,
            risk_level="L5_EMPTY",
            categories=("parse_error",),
            verbs=(),
            segments=(),
            reasons=("empty shell command",),
            subjects=("risk:L5_EMPTY", "category:parse_error"),
            write_targets=(),
            external_targets=(),
            has_shell_expansion=False,
        )

    segments = tuple(_classify_segment(segment) for segment in _split_segments(tokens) if segment)
    verbs = tuple(_unique(segment.verb for segment in segments if segment.verb))
    write_targets = tuple(_extract_write_targets(tokens, cwd_path))
    external_targets = tuple(path for path in write_targets if not _inside(Path(path), project_path))
    has_shell_expansion = _has_shell_expansion(command)
    hardline = _hardline_reasons(command, segments)
    reasons: list[str] = []
    categories = {category for segment in segments for category in segment.categories}

    if hardline:
        reasons.extend(hardline)
    if has_shell_expansion:
        categories.add("shell_expansion")
        reasons.append("shell expansion, pipeline, or command chaining needs review")
    if write_targets:
        categories.add("write")
        reasons.append("command has filesystem write target(s)")
    if external_targets:
        categories.add("external_write")
        reasons.append("command writes outside the project")
    if any(segment.verb in DESTRUCTIVE_VERBS for segment in segments):
        categories.add("destructive")
        reasons.append("command uses a destructive/high-impact verb")
    if any("network" in segment.categories for segment in segments):
        categories.add("network")
    if any("package_manager" in segment.categories for segment in segments):
        categories.add("package_manager")

    if hardline:
        risk_level = "L5_HARDLINE_DENY"
    elif "external_write" in categories:
        risk_level = "L4_EXTERNAL_WRITE"
    elif "destructive" in categories or "network" in categories or "package_manager" in categories:
        risk_level = "L3_REVIEW_REQUIRED"
    elif "write" in categories or any("write" in segment.categories for segment in segments):
        risk_level = "L2_PROJECT_WRITE"
    elif has_shell_expansion:
        risk_level = "L2_SHELL_REVIEW"
    elif _all_segments_read_only(segments):
        categories.add("read")
        risk_level = "L0_READ"
        reasons.append("all command segments look read-only")
    else:
        categories.add("unknown")
        risk_level = "L2_SHELL_REVIEW"
        reasons.append("command is not in the read-only allowlist")

    subjects = _subjects(risk_level, categories, verbs, write_targets, external_targets)
    return ShellSemantics(
        command=command,
        parse_ok=True,
        risk_level=risk_level,
        categories=tuple(sorted(categories)),
        verbs=verbs,
        segments=segments,
        reasons=tuple(_unique(reasons)),
        subjects=subjects,
        write_targets=write_targets,
        external_targets=external_targets,
        has_shell_expansion=has_shell_expansion,
    )


def render_shell_semantics(semantics: ShellSemantics) -> str:
    lines = [
        "# Shell Semantics",
        "",
        f"- command: {semantics.command}",
        f"- parse_ok: {str(semantics.parse_ok).lower()}",
        f"- risk: {semantics.risk_level}",
        f"- categories: {', '.join(semantics.categories) if semantics.categories else '-'}",
        f"- verbs: {', '.join(semantics.verbs) if semantics.verbs else '-'}",
    ]
    if semantics.write_targets:
        lines.append(f"- write_targets: {', '.join(semantics.write_targets)}")
    if semantics.external_targets:
        lines.append(f"- external_targets: {', '.join(semantics.external_targets)}")
    if semantics.reasons:
        lines.append("")
        lines.append("## Reasons")
        lines.extend(f"- {reason}" for reason in semantics.reasons)
    if semantics.subjects:
        lines.append("")
        lines.append("## Permission Subjects")
        lines.extend(f"- {subject}" for subject in semantics.subjects)
    return "\n".join(lines) + "\n"


def shell_permission_subjects(args: dict[str, Any] | None) -> list[str]:
    command = _first_arg_text(args, ("command", "cmd", "script", "input"))
    if not command:
        return []
    cwd = _first_arg_text(args, ("cwd", "working_dir", "workdir")) or None
    project = _first_arg_text(args, ("project", "project_path", "root")) or None
    return list(classify_shell_command(command, cwd=cwd, project=project).subjects)


def _classify_segment(tokens: list[str]) -> ShellSegment:
    verb = Path(tokens[0]).name if tokens else ""
    args = tuple(tokens[1:])
    categories: set[str] = set()
    if not verb:
        return ShellSegment("", args, ("unknown",))
    if verb in DESTRUCTIVE_VERBS:
        categories.add("destructive")
    if verb in NETWORK_VERBS and _network_intent(verb, args):
        categories.add("network")
    if verb in PACKAGE_MANAGER_VERBS:
        categories.add("package_manager")
    if verb in WRITE_VERBS:
        categories.add("write")
    if verb == "sed" and any(arg.startswith("-i") for arg in args):
        categories.add("write")
    if verb == "find" and "-delete" in args:
        categories.add("destructive")
    if verb == "git":
        subcommand = next((arg for arg in args if not arg.startswith("-")), "")
        if subcommand in GIT_WRITE_SUBCOMMANDS:
            categories.add("write")
        elif subcommand in GIT_READ_SUBCOMMANDS:
            categories.add("read")
        else:
            categories.add("unknown")
    elif verb in READ_VERBS and "write" not in categories and "destructive" not in categories:
        categories.add("read")
    if not categories:
        categories.add("unknown")
    return ShellSegment(verb, args, tuple(sorted(categories)))


def _split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in CONNECTORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _extract_write_targets(tokens: list[str], cwd: Path) -> list[str]:
    targets: list[str] = []
    for index, token in enumerate(tokens):
        if token in REDIRECTS and index + 1 < len(tokens):
            targets.append(str(_path_from_token(tokens[index + 1], cwd)))
            continue
        match = re.match(r"^(?:[12])?(?:>>?|&>)(?P<target>.+)$", token)
        if match:
            targets.append(str(_path_from_token(match.group("target"), cwd)))

    for segment in _split_segments(tokens):
        if not segment:
            continue
        verb = Path(segment[0]).name
        args = [arg for arg in segment[1:] if not arg.startswith("-")]
        if verb in {"tee", "touch", "mkdir"}:
            targets.extend(str(_path_from_token(arg, cwd)) for arg in args)
        elif verb in {"cp", "install", "mv", "rsync"} and args:
            targets.append(str(_path_from_token(args[-1], cwd)))
    return _unique(targets)


def _network_intent(verb: str, args: tuple[str, ...]) -> bool:
    if verb in {"curl", "wget"}:
        return True
    if verb == "git":
        subcommand = next((arg for arg in args if not arg.startswith("-")), "")
        return subcommand in {"clone", "fetch", "pull", "push", "remote"}
    if verb == "gh":
        return True
    if verb in PACKAGE_MANAGER_VERBS:
        return any(arg in {"add", "audit", "exec", "i", "install", "publish", "update", "upgrade"} for arg in args)
    return False


def _all_segments_read_only(segments: tuple[ShellSegment, ...]) -> bool:
    return bool(segments) and all(segment.categories == ("read",) for segment in segments)


def _hardline_reasons(command: str, segments: tuple[ShellSegment, ...]) -> list[str]:
    reasons: list[str] = []
    lowered = command.lower()
    if re.search(r"(^|[;&|\n])\s*(sudo\s+)?rm\s+(-[^\s]*[rf][^\s]*\s+)*(/|~|\$home)(\s|$|/)", lowered):
        reasons.append("broad recursive delete of root or home")
    if re.search(r"\bmkfs(\.[a-z0-9]+)?\b", lowered):
        reasons.append("filesystem format command")
    if re.search(r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)", lowered):
        reasons.append("raw block device overwrite")
    if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", command):
        reasons.append("fork bomb")
    if any(segment.verb in {"shutdown", "reboot", "halt", "poweroff"} for segment in segments):
        reasons.append("system shutdown or reboot")
    if re.search(r"\|\s*(sh|bash|zsh|python|python3|perl|ruby)\b", lowered) and ("curl " in lowered or "wget " in lowered):
        reasons.append("network download piped into an interpreter")
    return reasons


def _has_shell_expansion(command: str) -> bool:
    risky = ("$(", "`", "<(", "<<<", "${IFS}")
    return any(item in command for item in risky) or bool(re.search(r"(^|[^\\])(;|&&|\|\||\||&)", command))


def _subjects(
    risk_level: str,
    categories: set[str],
    verbs: tuple[str, ...],
    write_targets: tuple[str, ...],
    external_targets: tuple[str, ...],
) -> tuple[str, ...]:
    subjects: list[str] = [f"risk:{risk_level}"]
    subjects.extend(f"category:{category}" for category in sorted(categories))
    subjects.extend(f"verb:{verb}" for verb in verbs)
    if write_targets:
        subjects.append("writes:any")
    if external_targets:
        subjects.append("writes:external")
    elif write_targets:
        subjects.append("writes:project")
    return tuple(_unique(subjects))


def _first_arg_text(args: dict[str, Any] | None, keys: tuple[str, ...]) -> str:
    if not isinstance(args, dict):
        return ""
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _path_from_token(token: str, cwd: Path) -> Path:
    path = Path(token.strip("'\"")).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return _real(path)


def _real(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, parent: Path) -> bool:
    path_real = _real(path)
    parent_real = _real(parent)
    return path_real == parent_real or parent_real in path_real.parents


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        results.append(text)
    return results
