from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
from pathlib import Path
from typing import Any, Mapping

from .shell_semantics import shell_permission_subjects


ALLOW = "allow"
ASK = "ask"
DENY = "deny"
MASK = "mask"

_SECRET_NAME_PATTERN = re.compile(
    r"(^|[_-])(api[_-]?key|token|secret|password|passwd|pwd|credential|credentials|auth|bearer|private[_-]?key)($|[_-])",
    re.IGNORECASE,
)
_BASE64_CREDENTIAL_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9+/=]{80,}$")
_MAX_ENV_VALUE_LENGTH = 32768
_DEFAULT_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_*",
    "PATH",
    "PWD",
    "SHELL",
    "TERM",
    "TMPDIR",
    "TZ",
    "USER",
    "USERNAME",
    "VIRTUAL_ENV",
)


@dataclass(frozen=True)
class SandboxProfile:
    name: str
    description: str
    allow: tuple[str, ...]
    ask: tuple[str, ...]
    deny: tuple[str, ...]


@dataclass(frozen=True)
class PermissionDslDecision:
    action: str
    pattern: str
    reason: str


@dataclass(frozen=True)
class EnvSanitizeResult:
    env: dict[str, str]
    removed: tuple[str, ...]
    masked: tuple[str, ...]
    warnings: tuple[str, ...] = ()


PERMISSION_TOOL_GROUPS = {
    "read",
    "edit",
    "glob",
    "grep",
    "list",
    "bash",
    "task",
    "external_directory",
    "todowrite",
    "webfetch",
    "websearch",
    "lsp",
    "skill",
    "question",
    "doom_loop",
    "mcp",
}

_GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "read": (
        "read",
        "file_read",
        "context",
        "status",
        "audit",
        "validate",
        "registry",
        "evidence_read",
        "memory.search",
        "checkpoint.show",
        "transcript",
    ),
    "edit": ("edit", "write", "file_write", "file_edit", "apply_patch", "multi_edit", "multiedit", "memory.add"),
    "glob": ("glob", "file_glob"),
    "grep": ("grep", "search", "file_grep", "file_search"),
    "list": ("list", "ls", "file_list", "directory_list", "checkpoint.list"),
    "bash": ("bash", "shell", "command"),
    "task": ("task",),
    "todowrite": ("todowrite", "todo_write", "todo.write"),
    "webfetch": ("webfetch", "web_fetch", "web.fetch"),
    "websearch": ("websearch", "web_search", "web.search"),
    "lsp": ("lsp", "language_server"),
    "skill": ("skill",),
    "question": ("question", "ask_user"),
    "doom_loop": ("doom_loop", "doom.loop"),
}

_PATH_ARG_KEYS = {
    "path",
    "paths",
    "file",
    "files",
    "filepath",
    "file_path",
    "filename",
    "directory",
    "directories",
    "dir",
    "target",
    "targets",
}


PROFILES: dict[str, SandboxProfile] = {
    "off": SandboxProfile(
        "off",
        "Trusted local operator mode. Policy checks still run; no isolation is promised.",
        allow=("status", "context", "audit", "validate", "registry", "file_read", "file_search", "memory.search", "desktop.live"),
        ask=("shell", "file_write", "file_edit", "desktop", "experiment", "run_p4", "memory.add"),
        deny=("raw_data_mutation", "account_funds", "secret_exfiltration"),
    ),
    "project": SandboxProfile(
        "project",
        "Default project-contained mode. Reads are allowed; writes and desktop actions ask.",
        allow=("status", "context", "audit", "validate", "registry", "file_read", "file_search", "memory.search"),
        ask=("file_write", "file_edit", "memory.add", "desktop.open", "desktop.shot", "desktop.grid", "desktop.ax", "desktop.ocr", "desktop.som", "desktop.tokenize", "desktop.decide", "desktop.daemon", "desktop.eval", "desktop.find", "shell"),
        deny=("desktop.click", "desktop.type", "experiment", "run_p4", "raw_data_mutation", "account_funds", "secret_exfiltration"),
    ),
    "strict": SandboxProfile(
        "strict",
        "Read-only evidence mode for untrusted tasks or remote/channel input.",
        allow=("status", "context", "audit", "validate", "registry", "file_read", "file_search", "memory.search", "desktop.live", "desktop.shot", "desktop.grid", "desktop.ax", "desktop.ocr", "desktop.som", "desktop.tokenize", "desktop.decide", "desktop.find"),
        ask=(),
        deny=("shell", "file_write", "file_edit", "desktop.open", "desktop.daemon", "desktop.eval", "desktop.click", "desktop.type", "desktop.hotkey", "experiment", "run_p4", "memory.add", "raw_data_mutation", "account_funds", "secret_exfiltration"),
    ),
}


def list_profiles() -> list[SandboxProfile]:
    return [PROFILES[name] for name in sorted(PROFILES)]


def sanitize_env(
    env: Mapping[str, Any] | None,
    *,
    allowlist: tuple[str, ...] | list[str] | set[str] = _DEFAULT_ENV_ALLOWLIST,
    mask: bool = False,
    mask_value: str = "[REDACTED]",
    include_report: bool = False,
) -> dict[str, str] | EnvSanitizeResult:
    sanitized: dict[str, str] = {}
    removed: list[str] = []
    masked: list[str] = []
    warnings: list[str] = []
    for key, value in (env or {}).items():
        name = str(key).strip()
        if not name or value is None:
            continue
        text = str(value)
        value_warning = _env_value_warning(text)
        if value_warning == "value contains null bytes":
            removed.append(name)
            continue
        if _env_name_allowed(name, allowlist):
            sanitized[name] = text
            if value_warning:
                warnings.append(f"{name}: {value_warning}")
            continue
        if _is_secret_env_name(name):
            if mask:
                sanitized[name] = mask_value
                masked.append(name)
            else:
                removed.append(name)
            continue
        sanitized[name] = text
        if value_warning:
            warnings.append(f"{name}: {value_warning}")
    result = EnvSanitizeResult(sanitized, tuple(sorted(removed)), tuple(sorted(masked)), tuple(sorted(warnings)))
    return result if include_report else result.env


def classify_tool(tool: str, profile: str = "project") -> tuple[str, str]:
    selected = PROFILES.get(profile)
    if not selected:
        raise KeyError(f"unknown sandbox profile: {profile}")
    normalized = tool.strip()
    if not normalized:
        return DENY, "empty tool name"
    if _matches(normalized, selected.deny):
        return DENY, f"{normalized} denied by {profile} profile"
    if _matches(normalized, selected.allow):
        return ALLOW, f"{normalized} allowed by {profile} profile"
    if _matches(normalized, selected.ask):
        return ASK, f"{normalized} requires explicit operator approval in {profile} profile"
    return ASK, f"{normalized} is not declared in {profile} profile"


def resolve_permission_dsl(permission: Any, tool: str, args: dict[str, Any] | None = None) -> PermissionDslDecision:
    normalized = tool.strip()
    if not normalized:
        return PermissionDslDecision(DENY, "<empty>", "empty tool name")
    if not isinstance(permission, dict):
        action = _normalize_permission_action(permission)
        return PermissionDslDecision(action, "<direct>", f"{normalized} {action} by direct permission")

    best: PermissionDslDecision | None = None
    best_score = -1
    for pattern, raw_action in permission.items():
        selected = str(pattern).strip()
        score = _permission_pattern_score(normalized, selected, args)
        if score < 0:
            continue
        if isinstance(raw_action, dict):
            candidate = _resolve_nested_permission(raw_action, normalized, selected, args)
            if candidate is None:
                continue
        else:
            action = _normalize_permission_action(raw_action)
            candidate = PermissionDslDecision(
                action,
                selected,
                f"{normalized} {action} by permission pattern {selected}",
            )
        if score > best_score or score == best_score:
            best = candidate
            best_score = score

    if best is not None:
        return best
    return PermissionDslDecision(ASK, "<default>", f"{normalized} ask by default permission")


def _matches(tool: str, patterns: tuple[str, ...]) -> bool:
    return any(matches_tool_pattern(tool, pattern) for pattern in patterns)


def _env_name_allowed(name: str, allowlist: tuple[str, ...] | list[str] | set[str]) -> bool:
    return any(matches_tool_pattern(name, str(pattern)) for pattern in allowlist)


def _is_secret_env_name(name: str) -> bool:
    normalized = name.strip()
    if not normalized:
        return False
    upper = normalized.upper()
    if upper.endswith(("APIKEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PRIVATEKEY")):
        return True
    return bool(_SECRET_NAME_PATTERN.search(normalized))


def _env_value_warning(value: str) -> str:
    # Python-native adaptation of OpenClaw's sandbox env value checks.
    if "\0" in value:
        return "value contains null bytes"
    if len(value) > _MAX_ENV_VALUE_LENGTH:
        return "value exceeds maximum length"
    if _BASE64_CREDENTIAL_VALUE_PATTERN.fullmatch(value):
        return "value looks like base64-encoded credential data"
    return ""


def matches_tool_pattern(tool: str, pattern: str) -> bool:
    normalized = tool.strip()
    selected = pattern.strip()
    if not normalized or not selected:
        return False
    if any(_matches_tool_pattern_variant(candidate, selected) for candidate in _tool_name_variants(normalized)):
        return True
    return _is_group_alias_pattern(selected) and bool(_tool_groups(normalized) & _tool_groups(selected))


def _matches_tool_pattern_variant(tool: str, pattern: str) -> bool:
    if any(char in pattern for char in "*?[]"):
        return fnmatchcase(tool, pattern)
    return tool == pattern or tool.startswith(pattern + ".") or pattern.startswith(tool + ".")


def _resolve_nested_permission(
    permission: dict[Any, Any],
    tool: str,
    outer_pattern: str,
    args: dict[str, Any] | None,
) -> PermissionDslDecision | None:
    matched: PermissionDslDecision | None = None
    for nested_pattern, raw_action in permission.items():
        selected = str(nested_pattern).strip()
        if not selected:
            continue
        if not _nested_pattern_matches(tool, outer_pattern, selected, args):
            continue
        action = _normalize_permission_action(raw_action)
        pattern = f"{outer_pattern}.{selected}"
        matched = PermissionDslDecision(
            action,
            pattern,
            f"{tool} {action} by nested permission pattern {pattern}",
        )
    return matched


def _nested_pattern_matches(tool: str, outer_pattern: str, pattern: str, args: dict[str, Any] | None) -> bool:
    subjects = _nested_subjects(tool, outer_pattern, args)
    if pattern == "*":
        return bool(subjects)
    return any(matches_tool_pattern(subject, pattern) for subject in subjects)


def _nested_subjects(tool: str, outer_pattern: str, args: dict[str, Any] | None) -> list[str]:
    subjects: list[str] = []
    groups = _tool_groups(tool, args)
    outer_groups = _tool_groups(outer_pattern)
    if "bash" in groups or "bash" in outer_groups:
        command = _first_arg_text(args, ("command", "cmd", "script", "input"))
        if command:
            subjects.append(command)
            subjects.extend(shell_permission_subjects(args))
    if "mcp" in groups or "mcp" in outer_groups:
        subjects.extend(_mcp_subjects(tool))
    if "external_directory" in groups or "external_directory" in outer_groups:
        subjects.extend(_path_subjects(args))
    subjects.extend(_tool_name_variants(tool))
    return _unique(subject for subject in subjects if subject)


def _permission_pattern_score(tool: str, pattern: str, args: dict[str, Any] | None) -> int:
    if not pattern:
        return -1
    if pattern == "*":
        return 1

    groups = _tool_groups(tool, args)
    pattern_groups = _tool_groups(pattern) if _is_group_alias_pattern(pattern) else set()
    if pattern == "external_directory":
        return 120 if "external_directory" in groups else -1

    best = -1
    for candidate in _tool_name_variants(tool):
        if candidate == pattern:
            best = max(best, 110)
        elif _matches_tool_pattern_variant(candidate, pattern):
            best = max(best, _pattern_specificity(pattern, wildcard_score=90, plain_score=80))

    if groups & pattern_groups:
        best = max(best, 70)
    return best


def _pattern_specificity(pattern: str, *, wildcard_score: int, plain_score: int) -> int:
    base = wildcard_score if any(char in pattern for char in "*?[]") else plain_score
    literal_chars = sum(1 for char in pattern if char not in "*?[]")
    return base + min(literal_chars, 30)


def _normalize_permission_action(raw: Any) -> str:
    if isinstance(raw, bool):
        return ALLOW if raw else DENY
    selected = str(raw).strip().lower()
    return selected if selected in {ALLOW, ASK, DENY} else ASK


def _tool_groups(tool: str, args: dict[str, Any] | None = None) -> set[str]:
    normalized = _normalize_tool_name(tool)
    groups: set[str] = set()
    if normalized in PERMISSION_TOOL_GROUPS:
        groups.add(normalized)
    if normalized.startswith(("mcp:", "mcp.", "mcp_", "mcp__")):
        groups.add("mcp")
    for group, aliases in _GROUP_ALIASES.items():
        if any(_tool_alias_matches(normalized, alias) for alias in aliases):
            groups.add(group)
    if _args_reference_external_directory(args):
        groups.add("external_directory")
    return groups


def _is_group_alias_pattern(pattern: str) -> bool:
    if any(char in pattern for char in "*?[]"):
        return False
    normalized = _normalize_tool_name(pattern)
    if normalized in PERMISSION_TOOL_GROUPS:
        return True
    return any(normalized == _normalize_tool_name(alias) for aliases in _GROUP_ALIASES.values() for alias in aliases)


def _tool_alias_matches(tool: str, alias: str) -> bool:
    normalized_alias = _normalize_tool_name(alias)
    return (
        tool == normalized_alias
        or tool.startswith(normalized_alias + ".")
        or tool.startswith(normalized_alias + ":")
        or tool.startswith(normalized_alias + "_")
    )


def _normalize_tool_name(tool: str) -> str:
    return tool.strip().lower().replace("-", "_")


def _tool_name_variants(tool: str) -> list[str]:
    normalized = tool.strip()
    variants = {
        normalized,
        normalized.replace(":", "."),
        normalized.replace(":", "_"),
        normalized.replace(":", "__"),
        normalized.replace("__", ":"),
    }
    if normalized.startswith("mcp."):
        variants.add(normalized.replace(".", ":"))
        variants.add(normalized.replace(".", "_"))
    if normalized.startswith("mcp__"):
        variants.add(normalized.replace("__", ":"))
        variants.add(normalized.replace("__", "."))
    return _unique(variant for variant in variants if variant)


def _mcp_subjects(tool: str) -> list[str]:
    normalized = tool.strip()
    for separator in (":", ".", "__", "_"):
        prefix = f"mcp{separator}"
        if not normalized.startswith(prefix):
            continue
        rest = normalized[len(prefix) :]
        if not rest:
            continue
        parts = rest.split("__", 1) if separator == "__" else rest.split(separator, 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue
        server, name = parts
        return _unique(
            [
                normalized,
                rest,
                f"{server}:{name}",
                f"{server}.{name}",
                f"{server}_{name}",
                name,
            ]
        )
    return [normalized]


def _first_arg_text(args: dict[str, Any] | None, keys: tuple[str, ...]) -> str:
    if not isinstance(args, dict):
        return ""
    for key in keys:
        value = args.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _path_subjects(args: dict[str, Any] | None) -> list[str]:
    return [str(item).strip() for item in _iter_arg_paths(args) if str(item).strip()]


def _args_reference_external_directory(args: dict[str, Any] | None) -> bool:
    if not isinstance(args, dict):
        return False
    for key in ("external_directory", "externalDirectory", "outside_project", "outsideProject", "external"):
        if bool(args.get(key)):
            return True

    project = args.get("project") or args.get("project_path") or args.get("projectPath") or args.get("workspace")
    if not project:
        return False
    project_path = Path(str(project)).expanduser().resolve(strict=False)
    for raw_path in _iter_arg_paths(args):
        text = str(raw_path).strip()
        if not text:
            continue
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = project_path / candidate
        try:
            candidate.resolve(strict=False).relative_to(project_path)
        except ValueError:
            return True
    return False


def _iter_arg_paths(value: Any, key: str = "") -> list[Any]:
    if isinstance(value, dict):
        paths: list[Any] = []
        for raw_key, raw_value in value.items():
            normalized_key = str(raw_key).strip().lower()
            if normalized_key in {"project", "project_path", "projectpath", "workspace"}:
                continue
            if normalized_key in _PATH_ARG_KEYS:
                paths.extend(_flatten_path_values(raw_value))
            elif isinstance(raw_value, (dict, list, tuple, set)):
                paths.extend(_iter_arg_paths(raw_value, normalized_key))
        return paths
    if key in _PATH_ARG_KEYS:
        return _flatten_path_values(value)
    return []


def _flatten_path_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        paths: list[Any] = []
        for item in value:
            paths.extend(_flatten_path_values(item))
        return paths
    return [value]


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


def render_profiles(profile: str | None = None) -> str:
    if profile:
        selected = PROFILES[profile]
        return "\n".join(
            [
                f"# Sandbox Profile {selected.name}",
                "",
                selected.description,
                "",
                "## Allow",
                *[f"- {item}" for item in selected.allow],
                "",
                "## Ask",
                *[f"- {item}" for item in selected.ask],
                "",
                "## Deny",
                *[f"- {item}" for item in selected.deny],
            ]
        ) + "\n"
    lines = ["# Mako Sandbox Profiles", ""]
    for item in list_profiles():
        lines.append(f"- {item.name}: {item.description}")
    return "\n".join(lines) + "\n"
