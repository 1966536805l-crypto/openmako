from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime_store import (
    ApprovalRecord,
    decide_approval_request,
    get_approval_request,
    list_approval_requests,
    upsert_approval_request,
)


PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
ALLOW_ALWAYS = "allow_always"
EXPIRED = "expired"


@dataclass(frozen=True)
class ApprovalCheck:
    approval: ApprovalRecord | None
    allowed: bool
    blocked: bool
    summary: str

    @property
    def approval_id(self) -> str:
        return self.approval.approval_id if self.approval else ""

    @property
    def fingerprint(self) -> str:
        return self.approval.fingerprint if self.approval else ""


def approval_fingerprint(tool: str, args: dict[str, Any], policy: dict[str, Any]) -> str:
    payload = {
        "tool": tool,
        "args": _stable_json(args),
        "profile": policy.get("profile"),
        "policy_tool": policy.get("tool"),
        "action": policy.get("action"),
        "policy_reason": policy.get("policy_reason"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def ensure_approval_for_policy(
    project: str | Path,
    *,
    tool: str,
    args: dict[str, Any],
    policy: dict[str, Any],
    reason: str,
    approval_id: str | None = None,
    expires_at: int | None = None,
) -> ApprovalCheck:
    action = str(policy.get("action") or "")
    if action == "allow":
        return ApprovalCheck(None, True, False, "approval not required")

    if action == "deny":
        approval = _create_or_get(project, tool=tool, args=args, policy=policy, reason=reason, status=DENIED, expires_at=expires_at)
        return ApprovalCheck(approval, False, True, "deny policy cannot be overridden by approval")

    fingerprint = approval_fingerprint(tool, args, policy)
    if approval_id:
        approval = get_approval_request(project, approval_id)
        if not approval:
            approval = _create_or_get(project, tool=tool, args=args, policy=policy, reason=reason, status=PENDING, expires_at=expires_at)
            return ApprovalCheck(approval, False, True, f"approval id not found; created {approval.approval_id}")
        approval = _expire_if_needed(project, approval)
        if approval.status == EXPIRED:
            return ApprovalCheck(approval, False, True, f"approval {approval.approval_id} expired")
        if approval.status in {APPROVED, ALLOW_ALWAYS}:
            if approval.fingerprint == fingerprint:
                return ApprovalCheck(approval, True, False, f"approval {approval.approval_id} allows this invocation")
            return ApprovalCheck(approval, False, True, "approval fingerprint does not match this invocation")
        if approval.status == DENIED:
            return ApprovalCheck(approval, False, True, f"approval {approval.approval_id} is denied")
        return ApprovalCheck(approval, False, True, f"approval {approval.approval_id} is pending")

    approval = _create_or_get(project, tool=tool, args=args, policy=policy, reason=reason, status=PENDING, expires_at=expires_at)
    approval = _expire_if_needed(project, approval)
    if approval.status == EXPIRED:
        approval = _create_or_get(project, tool=tool, args=args, policy=policy, reason=reason, status=PENDING, expires_at=expires_at)
        approval = _expire_if_needed(project, approval)
    if approval.status == EXPIRED:
        return ApprovalCheck(approval, False, True, f"approval {approval.approval_id} expired")
    if approval.status in {APPROVED, ALLOW_ALWAYS}:
        return ApprovalCheck(approval, True, False, f"approval {approval.approval_id} already allows this invocation")
    if approval.status == DENIED:
        return ApprovalCheck(approval, False, True, f"approval {approval.approval_id} is denied")
    return ApprovalCheck(approval, False, True, f"approval required: {approval.approval_id}")


def approve(project: str | Path, approval_id: str, *, allow_always: bool = False, reason: str = "") -> ApprovalRecord:
    record = decide_approval_request(
        project,
        approval_id,
        decision=ALLOW_ALWAYS if allow_always else APPROVED,
        reason=reason,
    )
    if not record:
        raise KeyError(f"approval not found: {approval_id}")
    return record


def deny(project: str | Path, approval_id: str, *, reason: str = "") -> ApprovalRecord:
    record = decide_approval_request(project, approval_id, decision=DENIED, reason=reason)
    if not record:
        raise KeyError(f"approval not found: {approval_id}")
    return record


def get_approval(project: str | Path, approval_id: str) -> ApprovalRecord:
    record = get_approval_request(project, approval_id)
    if not record:
        raise KeyError(f"approval not found: {approval_id}")
    return record


def list_approvals(project: str | Path, *, status: str | None = None, limit: int = 50) -> list[ApprovalRecord]:
    return list_approval_requests(project, status=status, limit=limit)


def render_approvals(records: list[ApprovalRecord]) -> str:
    if not records:
        return "No approval requests.\n"
    lines = ["# Mako Approvals", ""]
    for record in records:
        expires = f" expires_at={record.expires_at}" if record.expires_at else ""
        lines.append(f"- [{record.status}] {record.approval_id}: {record.tool} action={record.action}{expires}")
        if record.reason:
            lines.append(f"  reason: {record.reason}")
    return "\n".join(lines) + "\n"


def render_approval(record: ApprovalRecord) -> str:
    lines = [
        f"# Approval {record.approval_id}",
        "",
        f"- status: {record.status}",
        f"- tool: {record.tool}",
        f"- action: {record.action}",
        f"- fingerprint: {record.fingerprint}",
        f"- created_at: {record.created_at}",
    ]
    if record.decided_at:
        lines.append(f"- decided_at: {record.decided_at}")
    if record.expires_at:
        lines.append(f"- expires_at: {record.expires_at}")
    if record.reason:
        lines.extend(["", "## Reason", "", record.reason])
    lines.extend(["", "## Args", "", _pretty_json(record.args_json), "", "## Policy", "", _pretty_json(record.policy_json)])
    return "\n".join(lines) + "\n"


def _create_or_get(
    project: str | Path,
    *,
    tool: str,
    args: dict[str, Any],
    policy: dict[str, Any],
    reason: str,
    status: str,
    expires_at: int | None,
) -> ApprovalRecord:
    fingerprint = approval_fingerprint(tool, args, policy)
    approval_id = "appr-" + uuid.uuid4().hex[:12]
    return upsert_approval_request(
        project,
        approval_id=approval_id,
        fingerprint=fingerprint,
        tool=tool,
        action=str(policy.get("action") or ""),
        status=status,
        reason=reason,
        policy=policy,
        args=args,
        expires_at=expires_at,
    )


def _expire_if_needed(project: str | Path, approval: ApprovalRecord) -> ApprovalRecord:
    if approval.expires_at and approval.expires_at <= _now_ms() and approval.status != EXPIRED:
        expired = decide_approval_request(project, approval.approval_id, decision=EXPIRED, reason="approval expired")
        return expired or approval
    return approval


def _now_ms() -> int:
    return int(time.time() * 1000)


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _pretty_json(value: str) -> str:
    try:
        return json.dumps(json.loads(value or "{}"), ensure_ascii=False, indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return value
