from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


SIDE_EFFECT_ACTIONS = frozenset({"click", "type", "hotkey", "open", "activate", "move", "grid-click", "som-click"})
READ_ONLY_ACTIONS = frozenset({"screenshot", "observe", "noop", "stop", "wait"})
SUPPORTED_ACTIONS = READ_ONLY_ACTIONS | SIDE_EFFECT_ACTIONS
ACTION_TEXT_RISK_KEYS = frozenset(
    {
        "text",
        "target_text",
        "target",
        "label",
        "title",
        "name",
        "value",
        "placeholder",
        "button",
        "menu",
        "menu_item",
    }
)

RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "payment",
        re.compile(r"(转账|付款|支付|提现|充值|银行卡|\b(pay|payment|purchase|transfer|withdraw|deposit)\b)", re.IGNORECASE),
    ),
    (
        "trading",
        re.compile(r"(下单|买入|卖出|交易|实盘|\b(trade|trading|buy|sell|order|broker)\b)", re.IGNORECASE),
    ),
    (
        "credential",
        re.compile(
            r"(密码|验证码|身份证|私钥|助记词|"
            r"\b(password|passcode|otp|2fa|secret|api[\s_-]?key|private key|seed\s+phrase)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "destructive",
        re.compile(r"(删除|清空|格式化|抹掉|rm\s+-rf|\b(delete|destroy|format|wipe|erase)\b)", re.IGNORECASE),
    ),
    (
        "message_send",
        re.compile(r"(发消息|发送消息|发送邮件|群发|\b(send|send message|send email|post message|dm\b|publish)\b)", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class RiskFinding:
    blocked: bool
    category: str = ""
    matched: str = ""
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DaemonAction:
    action: str
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def side_effect(self) -> bool:
        return self.action in SIDE_EFFECT_ACTIONS

    def to_payload(self) -> dict[str, Any]:
        return {"action": self.action, "args": self.args, "side_effect": self.side_effect}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    status: str
    reason: str
    action: str = ""
    risk: RiskFinding = field(default_factory=lambda: RiskFinding(False))
    missing_gates: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "action": self.action,
            "risk": self.risk.to_payload(),
            "missing_gates": list(self.missing_gates),
        }


def classify_goal_risk(text: str) -> RiskFinding:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return RiskFinding(False)
    for category, pattern in RISK_PATTERNS:
        match = pattern.search(normalized)
        if match:
            matched = match.group(0)
            return RiskFinding(True, category, matched, f"high-risk {category} term: {matched}")
    return RiskFinding(False)


def normalize_daemon_action(value: str | Mapping[str, Any] | DaemonAction) -> DaemonAction:
    if isinstance(value, DaemonAction):
        if value.action not in SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported desktop daemon action: {value.action}")
        return value
    if isinstance(value, str):
        action = value.strip()
        args: dict[str, Any] = {}
    else:
        action = str(value.get("action") or value.get("name") or "").strip()
        raw_args = value.get("args") or {}
        args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
        for key, item in value.items():
            if key not in {"action", "name", "args"} and key not in args:
                args[str(key)] = item
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported desktop daemon action: {action or '<empty>'}")
    return DaemonAction(action, args)


def daemon_action_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action"],
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": sorted(SUPPORTED_ACTIONS)},
            "args": {"type": "object"},
            "reason": {"type": "string"},
        },
    }


def authorize_daemon_action(
    action: str | Mapping[str, Any] | DaemonAction,
    *,
    goal: str = "",
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
) -> PolicyDecision:
    risk = classify_goal_risk(goal)
    normalized = normalize_daemon_action(action)
    if risk.blocked:
        return PolicyDecision(False, "blocked", risk.reason, normalized.action, risk)

    text_risk = _action_text_risk(normalized)
    if text_risk.blocked:
        return PolicyDecision(False, "blocked", text_risk.reason, normalized.action, text_risk)

    missing: list[str] = []
    if normalized.side_effect:
        if not execute:
            missing.append("--execute")
        if not reviewed:
            missing.append("--reviewed")
        if not allow_actions:
            missing.append("--allow-actions")
    if missing:
        return PolicyDecision(
            False,
            "needs_review",
            f"side-effect action requires {', '.join(missing)}",
            normalized.action,
            risk,
            tuple(missing),
        )
    return PolicyDecision(True, "allowed", "action allowed", normalized.action, risk)


def is_side_effect_action(action: str | Mapping[str, Any] | DaemonAction) -> bool:
    return normalize_daemon_action(action).side_effect


def _action_text_risk(action: DaemonAction) -> RiskFinding:
    for key in ACTION_TEXT_RISK_KEYS:
        value = action.args.get(key)
        if value is None:
            continue
        finding = classify_goal_risk(str(value))
        if finding.blocked:
            return RiskFinding(True, finding.category, finding.matched, f"high-risk action {key} term: {finding.matched}")
    return RiskFinding(False)
