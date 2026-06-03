from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


ALLOW = "allow"
ASK = "ask"
DENY = "deny"


@dataclass(frozen=True)
class SafetyDecision:
    action: str
    level: str
    reasons: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW

    def render(self) -> str:
        suffix = "" if not self.reasons else ": " + "; ".join(self.reasons)
        return f"{self.action.upper()} {self.level}{suffix}"


@dataclass(frozen=True)
class SafetyPolicy:
    project: Path
    communication_dir_name: str = "AI_协作交接"
    mode: str = "project_write"

    @property
    def communication_dir(self) -> Path:
        return self.project / self.communication_dir_name

    @property
    def writable_dirs(self) -> tuple[Path, ...]:
        return (
            self.communication_dir,
            self.communication_dir / "quantagent_results",
            self.project / ".quantagent",
        )


DESTRUCTIVE_TOKENS = {
    "rm",
    "rmdir",
    "unlink",
    "shred",
    "srm",
    "trash",
    "diskutil",
    "mkfs",
    "dd",
    "mount",
    "umount",
    "chmod",
    "chown",
    "sudo",
    "launchctl",
    "curl",
    "wget",
    "git",
}


FUND_OR_ACCOUNT_PATTERNS = [
    r"\border\b",
    r"\btrade\b",
    r"\bbuy\b",
    r"\bsell\b",
    r"\bwithdraw\b",
    r"\btransfer\b",
    r"\bapi[-_ ]?key\b",
    r"\bsecret\b",
    r"下单",
    r"买入",
    r"卖出",
    r"转账",
    r"提现",
    r"密钥",
]


RAW_DATA_MARKERS = [
    "逐笔",
    "tick",
    "raw",
    "origin",
    "原始",
    "行情",
    "level2",
    "l2",
]


WRITE_OPERATORS = [">", ">>", "tee", "mv", "cp", "rsync", "touch", "mkdir"]


# Adapted from Hermes Agent's MIT-licensed dangerous-command hardline guard.
# Keep this list intentionally small: only commands with host-level blast radius
# that should not pass through an agent policy prompt.
_CMDPOS = r"(?:^|[;&|\n`]|\$\()\s*(?:sudo\s+(?:-[^\s]+\s+)*)?"
HARDLINE_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE | re.DOTALL), reason)
    for pattern, reason in (
        (_CMDPOS + r"rm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)", "recursive delete of root filesystem"),
        (
            _CMDPOS
            + r"rm\s+(-[^\s]*\s+)*"
            r"(/home|/home/\*|/root|/root/\*|/etc|/etc/\*|/usr|/usr/\*|/var|/var/\*|/bin|/bin/\*|/sbin|/sbin/\*|/boot|/boot/\*)"
            r"(\s|$)",
            "recursive delete of system directory",
        ),
        (_CMDPOS + r"rm\s+(-[^\s]*\s+)*(~|\$HOME)(/?|/\*)?(\s|$)", "recursive delete of home directory"),
        (_CMDPOS + r"mkfs(\.[a-z0-9]+)?\b", "format filesystem"),
        (_CMDPOS + r"dd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*", "raw block device overwrite"),
        (r">\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b", "redirect to raw block device"),
        (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
        (_CMDPOS + r"kill\s+(-[^\s]+\s+)*-1\b", "kill all processes"),
        (_CMDPOS + r"(shutdown|reboot|halt|poweroff)\b", "system shutdown/reboot"),
        (_CMDPOS + r"systemctl\s+(poweroff|reboot|halt|kexec)\b", "systemctl shutdown/reboot"),
        (r"(?:^|[;&|\n`]|\$\()\s*sudo\s+-S\b", "explicit sudo password via stdin"),
    )
)

LOW_RISK_READ_COMMANDS = {
    "awk",
    "cat",
    "date",
    "df",
    "du",
    "echo",
    "false",
    "file",
    "find",
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

COMMAND_SEPARATORS = {"&&", "||", ";", "|"}
REDIRECT_OPERATORS = {">", ">>", "1>", "1>>", "2>", "2>>", "&>"}


def _real(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, parent: Path) -> bool:
    path_real = _real(path)
    parent_real = _real(parent)
    return path_real == parent_real or parent_real in path_real.parents


def _split(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _looks_like_raw_data(path_text: str) -> bool:
    lowered = path_text.lower()
    if any(marker in lowered for marker in ("逐笔", "原始", "行情")):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", lowered) if token]
    marker_words = {"tick", "raw", "origin", "level2", "l2"}
    return any(token in marker_words for token in tokens)


def _extract_paths(command: str, cwd: Path) -> list[Path]:
    paths: list[Path] = []
    for token in _split(command):
        if not token or token.startswith("-"):
            continue
        if "/" not in token and not token.startswith(".") and not token.startswith("~"):
            continue
        if re.match(r"^[a-zA-Z]+://", token):
            continue
        cleaned = token.strip("'\"")
        if cleaned in {">", ">>"}:
            continue
        path = Path(cleaned).expanduser()
        if not path.is_absolute():
            path = cwd / path
        paths.append(path)
    return paths


def _path_from_token(token: str, cwd: Path) -> Path:
    path = Path(token.strip("'\"")).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path


def _command_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _non_option_args(tokens: list[str]) -> list[str]:
    args: list[str] = []
    for index, token in enumerate(tokens):
        if token == "--":
            args.extend(tokens[index + 1 :])
            break
        if token.startswith("-"):
            continue
        args.append(token)
    return args


def _extract_redirection_targets(tokens: list[str], cwd: Path) -> list[Path]:
    targets: list[Path] = []
    for index, token in enumerate(tokens):
        if token in REDIRECT_OPERATORS and index + 1 < len(tokens):
            targets.append(_path_from_token(tokens[index + 1], cwd))
            continue
        match = re.match(r"^(?:[12])?(>>?|&>)(.+)$", token)
        if match and match.group(2):
            targets.append(_path_from_token(match.group(2), cwd))
    return targets


def _extract_command_write_targets(tokens: list[str], cwd: Path) -> list[Path]:
    targets = _extract_redirection_targets(tokens, cwd)
    for segment in _command_segments(tokens):
        if not segment:
            continue
        verb = Path(segment[0]).name
        args = _non_option_args(segment[1:])
        if verb in {"tee", "touch", "mkdir"}:
            targets.extend(_path_from_token(arg, cwd) for arg in args)
        elif verb in {"cp", "mv", "rsync"} and args:
            targets.append(_path_from_token(args[-1], cwd))
    return targets


def _extract_python_write_targets(tokens: list[str], cwd: Path) -> list[Path]:
    targets: list[Path] = []
    for segment in _command_segments(tokens):
        if len(segment) < 3 or Path(segment[0]).name not in {"python", "python3"}:
            continue
        if segment[1] != "-c":
            continue
        code = segment[2]
        for match in re.finditer(
            r"\bopen\(\s*(['\"])(?P<path>.+?)\1\s*,\s*(['\"])(?P<mode>[^'\"]*)\3",
            code,
        ):
            if any(flag in match.group("mode") for flag in ("w", "a", "x", "+")):
                targets.append(_path_from_token(match.group("path"), cwd))
        for match in re.finditer(
            r"\b(?:Path|pathlib\.Path)\(\s*(['\"])(?P<path>.+?)\1\s*\)\s*\."
            r"(?:write_text|write_bytes|touch|mkdir)\b",
            code,
        ):
            targets.append(_path_from_token(match.group("path"), cwd))
    return targets


def _is_py_compile_command(tokens: list[str], cwd: Path, policy: SafetyPolicy) -> bool:
    for segment in _command_segments(tokens):
        if len(segment) < 3 or Path(segment[0]).name not in {"python", "python3"}:
            return False
        if segment[1:3] != ["-m", "py_compile"]:
            return False
        targets = [_path_from_token(token, cwd) for token in segment[3:] if not token.startswith("-")]
        if not targets or any(not _inside(target, policy.project) for target in targets):
            return False
    return True


def _is_python_help_probe(tokens: list[str], cwd: Path, policy: SafetyPolicy) -> bool:
    for segment in _command_segments(tokens):
        if len(segment) < 2 or Path(segment[0]).name not in {"python", "python3"}:
            return False
        script = _path_from_token(segment[1], cwd)
        if script.suffix != ".py" or not _inside(script, policy.project):
            return False
        if any(arg not in {"-h", "--help"} for arg in segment[2:]):
            return False
    return True


def _is_low_risk_read_command(tokens: list[str], cwd: Path, policy: SafetyPolicy) -> bool:
    if _is_py_compile_command(tokens, cwd, policy) or _is_python_help_probe(tokens, cwd, policy):
        return True
    for segment in _command_segments(tokens):
        if not segment:
            continue
        verb = Path(segment[0]).name
        if verb not in LOW_RISK_READ_COMMANDS:
            return False
        if verb == "sed" and "-i" in segment[1:]:
            return False
        if verb == "find" and "-delete" in segment[1:]:
            return False
    return True


def _has_shell_injection_risk(command: str) -> bool:
    risky_parts = ["$(", "`", "<(", ">|", "<<<", "${IFS}", "/proc/environ"]
    if any(part in command for part in risky_parts):
        return True
    if re.search(r"(^|[^\\])(;|&&|\|\||&)", command):
        return True
    if re.search(r"(^|[^\\])\|", command):
        return True
    if re.search(r"(^|[^\\])\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]+\})", command):
        return True
    if re.search(r"(^|[^\\])<\s*\S+", command):
        return True
    return bool(re.search(r"[\u00a0\u2000-\u200b\u2028\u2029]", command))


def _has_pipe_to_shell(command: str) -> bool:
    lowered = command.lower()
    network_fetch = "curl " in lowered or "wget " in lowered
    shell_pipe = re.search(r"\|\s*(sh|bash|zsh|python|python3|perl|ruby)\b", lowered)
    return bool(network_fetch and shell_pipe)


def _command_verbs(tokens: list[str]) -> set[str]:
    verbs: set[str] = set()
    next_is_command = True
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            next_is_command = True
            continue
        if next_is_command:
            verbs.add(Path(token).name)
            next_is_command = False
    return verbs


def assess_command(command: str, cwd: Path, policy: SafetyPolicy | None = None) -> SafetyDecision:
    policy = policy or SafetyPolicy(project=cwd)
    tokens = _split(command)
    if not tokens:
        return SafetyDecision(DENY, "L0_PARSE", ("cannot parse shell command",))

    reasons: list[str] = []
    lowered = command.lower()
    verbs = _command_verbs(tokens)

    hardline_reasons = [reason for pattern, reason in HARDLINE_COMMAND_PATTERNS if pattern.search(command)]
    if hardline_reasons:
        return SafetyDecision(DENY, "L5_HARDLINE", tuple(sorted(set(hardline_reasons))))

    if _has_shell_injection_risk(command):
        reasons.append("shell expansion or injection-prone syntax")
    if _has_pipe_to_shell(command):
        reasons.append("network download piped to interpreter")
    if any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in FUND_OR_ACCOUNT_PATTERNS):
        reasons.append("fund/account/API-key related command")

    destructive = verbs & DESTRUCTIVE_TOKENS
    if destructive:
        reasons.append("high impact command: " + ", ".join(sorted(destructive)))

    if any(
        segment
        and (
            (Path(segment[0]).name == "rm" and any(flag in segment for flag in ("-rf", "-fr")) and any(arg in {"/", "~", "$HOME"} for arg in segment[1:]))
            or Path(segment[0]).name == "mkfs"
            or (Path(segment[0]).name == "diskutil" and "erase" in segment[1:])
        )
        for segment in _command_segments(tokens)
    ):
        return SafetyDecision(DENY, "L5_SYSTEM_DESTRUCTIVE", tuple(sorted(set(reasons + ["system destructive pattern"]))))

    if any(
        segment
        and Path(segment[0]).name == "rm"
        and any(flag in segment for flag in ("-rf", "-fr"))
        and any(arg in {"/", "~", "$HOME"} for arg in segment[1:])
        for segment in _command_segments(tokens)
    ):
        return SafetyDecision(DENY, "L5_SYSTEM_DESTRUCTIVE", tuple(sorted(set(reasons + ["broad recursive delete"]))))

    paths = _extract_paths(command, cwd)
    write_targets = _extract_command_write_targets(tokens, cwd) + _extract_python_write_targets(tokens, cwd)
    if any(_inside(path, policy.project) and _looks_like_raw_data(str(path)) for path in paths):
        if destructive or "mv" in tokens or re.search(r">>?\s*[^|&;]*(tick|raw|逐笔|原始|level2|l2)", lowered):
            return SafetyDecision(DENY, "L4_RAW_DATA_PROTECTED", tuple(sorted(set(reasons + ["raw/tick data mutation"]))))
        if "cp" in tokens or "rsync" in tokens:
            return SafetyDecision(ASK, "L4_RAW_DATA_COPY", tuple(sorted(set(reasons + ["copying raw/tick data needs explicit destination discipline"]))))

    if destructive and any(_inside(path, policy.project) for path in paths):
        return SafetyDecision(ASK, "L3_PROJECT_MUTATION", tuple(sorted(set(reasons + ["project mutation needs explicit intent"]))))

    if destructive:
        return SafetyDecision(ASK, "L4_HOST_MUTATION", tuple(sorted(set(reasons))))

    if write_targets:
        for path in write_targets:
            if not _inside(path, policy.project):
                return SafetyDecision(
                    ASK,
                    "L3_OUTSIDE_PROJECT_WRITE",
                    tuple(sorted(set(reasons + ["write outside configured quant project"]))),
                )
            if _looks_like_raw_data(str(path)):
                return SafetyDecision(
                    DENY,
                    "L4_RAW_DATA_PROTECTED",
                    tuple(sorted(set(reasons + ["raw/tick data path is read-only by default"]))),
                )
        if reasons:
            return SafetyDecision(ASK, "L3_REVIEW_REQUIRED", tuple(sorted(set(reasons))))
        for path in write_targets:
            if not any(_inside(path, directory) for directory in policy.writable_dirs):
                return SafetyDecision(ASK, "L2_PROJECT_WRITE", ("write outside Mako output dirs",))
        return SafetyDecision(ALLOW, "L1_GUARDED_WRITE", ("write appears contained",))

    if any(op in tokens for op in WRITE_OPERATORS):
        return SafetyDecision(ASK, "L2_WRITE_TARGET_UNKNOWN", ("write-like command without a clear target",))

    if reasons:
        return SafetyDecision(ASK, "L3_REVIEW_REQUIRED", tuple(sorted(set(reasons))))

    if _is_low_risk_read_command(tokens, cwd, policy):
        return SafetyDecision(ALLOW, "L0_READ_OR_SAFE", ("read-only or low-impact command",))

    return SafetyDecision(ASK, "L2_SHELL_REVIEW", ("command is not in the low-risk read allowlist",))


def assess_path_write(path: Path, policy: SafetyPolicy) -> SafetyDecision:
    if not _inside(path, policy.project):
        return SafetyDecision(ASK, "L3_OUTSIDE_PROJECT", ("write outside configured quant project",))
    if _looks_like_raw_data(str(path)):
        return SafetyDecision(DENY, "L4_RAW_DATA_PROTECTED", ("raw/tick data path is read-only by default",))
    if any(_inside(path, directory) for directory in policy.writable_dirs):
        return SafetyDecision(ALLOW, "L1_PROJECT_OUTPUT", ("Mako output path",))
    return SafetyDecision(ASK, "L2_PROJECT_WRITE", ("project source/data write needs explicit intent",))


def assess_quant_claim(text: str) -> SafetyDecision:
    lowered = text.lower()
    reasons: list[str] = []
    if "pf=" in lowered and "dedup" not in lowered and "去重" not in lowered:
        reasons.append("PF claim lacks dedup context")
    if "1253" in lowered and "污染" not in lowered and "重复" not in lowered:
        reasons.append("1253-trade polluted baseline referenced without warning")
    if "09:30" in text and "滑点" not in text and "slippage" not in lowered:
        reasons.append("09:30 execution claim lacks slippage assumption")
    if "(-9,-8]" in text and "诊断" not in text and "diagnostic" not in lowered:
        reasons.append("(-9,-8] band should be diagnostic only")
    if reasons:
        return SafetyDecision(ASK, "Q2_CLAIM_NEEDS_EVIDENCE", tuple(reasons))
    return SafetyDecision(ALLOW, "Q0_CLAIM_OK", ("no known quant claim hazards",))


def policy_summary(policy: SafetyPolicy) -> str:
    lines = [
        "# Mako Safety Policy",
        "",
        f"- project: {policy.project}",
        f"- mode: {policy.mode}",
        "- default stance: obey user instructions unless they damage the user's stated goal, data, funds, accounts, machine, or result credibility",
        "",
        "## Levels",
        "- L0: read-only or low-impact actions are allowed",
        "- L1: writes inside Mako output dirs are allowed",
        "- L2: project source/data writes require explicit intent",
        "- L3: destructive project mutation requires review",
        "- L4: raw/tick data, account/API-key, and host mutation are protected",
        "- L5: broad system destructive actions are denied",
        "",
        "## Writable Output Dirs",
    ]
    lines.extend(f"- {path}" for path in policy.writable_dirs)
    lines.extend(
        [
            "",
            "## Quant Evidence Gates",
            "- PF claims must state dedup baseline or evidence source",
            "- 1253-trade polluted baseline must not be used as clean evidence",
            "- 09:30 execution claims must include slippage/capacity assumptions",
            "- (-9,-8] is diagnostic unless fresh evidence says otherwise",
        ]
    )
    return "\n".join(lines) + "\n"


def mode_from_env(default: str = "project_write") -> str:
    return os.environ.get("QUANTAGENT_SAFETY_MODE", default)
