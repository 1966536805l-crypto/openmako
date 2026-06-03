from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import re
from typing import Any


ALLOW = "allow"
DENY = "deny"

READ = "read"
CONTROL = "control"
WRITE = "write"
ADMIN = "admin"

COMMAND_SCOPES = (READ, CONTROL, WRITE, ADMIN)
_SCOPE_RANK = {READ: 0, CONTROL: 1, WRITE: 2, ADMIN: 3}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._:@/+~-]{0,191}$")

DEFAULT_COMMAND_SCOPE: dict[str, str] = {
    "/help": READ,
    "/status": READ,
    "/sessions": READ,
    "/messages": READ,
    "/summary": READ,
    "/list": READ,
    "/ls": READ,
    "/show": READ,
    "/cat": READ,
    "/grep": READ,
    "/search": READ,
    "/tail": READ,
    "/pause": CONTROL,
    "/resume": CONTROL,
    "/cancel": CONTROL,
    "/stop": CONTROL,
    "/start": CONTROL,
    "/restart": CONTROL,
    "/exec": WRITE,
    "/run": WRITE,
    "/write": WRITE,
    "/edit": WRITE,
    "/apply": WRITE,
    "/patch": WRITE,
    "/delete": WRITE,
    "/rm": WRITE,
    "/approve": ADMIN,
    "/admin": ADMIN,
    "/config": ADMIN,
    "/allow": ADMIN,
}


@dataclass(frozen=True)
class SenderIdentity:
    raw: str
    normalized: str
    valid: bool
    reason: str = ""


@dataclass(frozen=True)
class OperatorAuthDecision:
    action: str
    sender: str
    command: str
    scope: str
    reason: str
    matched_sender: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW


@dataclass(frozen=True)
class OperatorAuthPolicy:
    allowed_senders: tuple[str, ...] = ()
    sender_scopes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    command_scopes: Mapping[str, str] = field(default_factory=dict)
    default_scopes: tuple[str, ...] = (READ,)


def normalize_sender_identity(sender: Any) -> str:
    if isinstance(sender, Mapping):
        sender = sender.get("sender") or sender.get("from") or sender.get("id") or sender.get("user") or ""
    text = str(sender or "").strip().lower()
    text = _CONTROL_CHARS.sub("", text)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return _SPACE.sub("", text)


def validate_sender_identity(sender: Any) -> SenderIdentity:
    raw = "" if sender is None else str(sender)
    normalized = normalize_sender_identity(sender)
    if not normalized:
        return SenderIdentity(raw, normalized, False, "empty sender")
    if not _SAFE_ID.fullmatch(normalized):
        return SenderIdentity(raw, normalized, False, "sender contains unsupported characters")
    return SenderIdentity(raw, normalized, True, "sender identity is valid")


def sender_allowed(sender: Any, allowlist: Iterable[str]) -> tuple[bool, str]:
    identity = validate_sender_identity(sender)
    if not identity.valid:
        return False, identity.reason
    for raw_pattern in allowlist:
        pattern = normalize_sender_identity(raw_pattern)
        if not pattern:
            continue
        if pattern == "*" or pattern == identity.normalized:
            return True, pattern
        if "*" in pattern and fnmatchcase(identity.normalized, pattern):
            return True, pattern
    return False, "sender not in allowlist"


def command_scope(command: Any, command_scopes: Mapping[str, str] | None = None) -> str:
    text = str(command or "").strip()
    if not text:
        return READ
    command_name = text.split(maxsplit=1)[0].lower()
    scopes = dict(DEFAULT_COMMAND_SCOPE)
    scopes.update({str(key).strip().lower(): _normalize_scope(value) for key, value in (command_scopes or {}).items()})
    if command_name in scopes:
        return scopes[command_name]
    if not command_name.startswith("/"):
        return READ
    return WRITE


def authorize_operator_command(sender: Any, command: Any, policy: OperatorAuthPolicy | Mapping[str, Any]) -> OperatorAuthDecision:
    selected = _coerce_policy(policy)
    identity = validate_sender_identity(sender)
    cmd = str(command or "").strip()
    scope = command_scope(cmd, selected.command_scopes)
    if not identity.valid:
        return OperatorAuthDecision(DENY, identity.normalized, cmd, scope, identity.reason)

    allowed, matched = sender_allowed(identity.normalized, selected.allowed_senders)
    if not allowed:
        return OperatorAuthDecision(DENY, identity.normalized, cmd, scope, matched)

    granted = _scopes_for_sender(identity.normalized, selected, matched)
    if not _scope_allows(granted, scope):
        return OperatorAuthDecision(
            DENY,
            identity.normalized,
            cmd,
            scope,
            f"sender lacks {scope} scope",
            matched_sender=matched,
        )
    return OperatorAuthDecision(
        ALLOW,
        identity.normalized,
        cmd,
        scope,
        f"sender allowed for {scope}",
        matched_sender=matched,
    )


def _coerce_policy(policy: OperatorAuthPolicy | Mapping[str, Any]) -> OperatorAuthPolicy:
    if isinstance(policy, OperatorAuthPolicy):
        return policy
    raw_allowed = policy.get("allowed_senders") or policy.get("allowlist") or policy.get("allow_from") or ()
    raw_sender_scopes = policy.get("sender_scopes") or policy.get("scopes") or {}
    raw_command_scopes = policy.get("command_scopes") or {}
    raw_default_scopes = policy.get("default_scopes") or (READ,)
    return OperatorAuthPolicy(
        allowed_senders=tuple(str(item) for item in _as_sequence(raw_allowed)),
        sender_scopes={
            normalize_sender_identity(key): tuple(_normalize_scope(item) for item in _as_sequence(value))
            for key, value in raw_sender_scopes.items()
        },
        command_scopes={str(key): _normalize_scope(value) for key, value in raw_command_scopes.items()},
        default_scopes=tuple(_normalize_scope(item) for item in _as_sequence(raw_default_scopes)),
    )


def _scopes_for_sender(sender: str, policy: OperatorAuthPolicy, matched: str) -> tuple[str, ...]:
    for key in (sender, matched, "*"):
        scopes = policy.sender_scopes.get(key)
        if scopes:
            return tuple(_normalize_scope(scope) for scope in scopes)
    return tuple(_normalize_scope(scope) for scope in policy.default_scopes)


def _scope_allows(granted: Iterable[str], required: str) -> bool:
    required_rank = _SCOPE_RANK[_normalize_scope(required)]
    return any(_SCOPE_RANK[_normalize_scope(scope)] >= required_rank for scope in granted)


def _normalize_scope(scope: Any) -> str:
    selected = str(scope or "").strip().lower()
    return selected if selected in _SCOPE_RANK else READ


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)
