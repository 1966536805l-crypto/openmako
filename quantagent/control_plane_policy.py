from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Mapping


READ_SCOPE = "read"
WRITE_SCOPE = "write"
ADMIN_SCOPE = "admin"
PAIRING_SCOPE = "pairing"

OPERATOR_SCOPES = frozenset({READ_SCOPE, WRITE_SCOPE, ADMIN_SCOPE, PAIRING_SCOPE})

DEFAULT_RATE_LIMIT_MAX_REQUESTS = 3
DEFAULT_RATE_LIMIT_WINDOW_MS = 60_000
DEFAULT_BUCKET_MAX_STALE_MS = 5 * 60_000
DEFAULT_BUCKET_MAX_ENTRIES = 10_000


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    method: str | None = None
    scope: str | None = None
    key: str | None = None
    retry_after_ms: int = 0
    remaining: int = 0
    missing_scope: str | None = None


@dataclass
class _Bucket:
    count: int
    window_start_ms: int


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class RateLimiter:
    """Fixed-window limiter for control-plane writes."""

    def __init__(
        self,
        *,
        window_ms: int = DEFAULT_RATE_LIMIT_WINDOW_MS,
        max_requests: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS,
        max_entries: int = DEFAULT_BUCKET_MAX_ENTRIES,
        max_stale_ms: int = DEFAULT_BUCKET_MAX_STALE_MS,
        clock: Callable[[], int] | None = None,
    ) -> None:
        if window_ms <= 0:
            raise ValueError("window_ms must be positive")
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if max_stale_ms < window_ms:
            raise ValueError("max_stale_ms must be greater than or equal to window_ms")
        self.window_ms = window_ms
        self.max_requests = max_requests
        self.max_entries = max_entries
        self.max_stale_ms = max_stale_ms
        self._clock = clock or _monotonic_ms
        self._buckets: dict[str, _Bucket] = {}

    def consume(self, key: str, *, now_ms: int | None = None) -> Decision:
        normalized_key = normalize_rate_limit_key(key)
        now = self._clock() if now_ms is None else now_ms
        bucket = self._buckets.get(normalized_key)

        if bucket is None or now - bucket.window_start_ms >= self.window_ms:
            self._insert_bucket(normalized_key, _Bucket(count=1, window_start_ms=now))
            return Decision(
                allowed=True,
                reason="allowed",
                key=normalized_key,
                remaining=self.max_requests - 1,
            )

        if bucket.count >= self.max_requests:
            retry_after_ms = max(0, bucket.window_start_ms + self.window_ms - now)
            return Decision(
                allowed=False,
                reason="rate_limited",
                key=normalized_key,
                retry_after_ms=retry_after_ms,
                remaining=0,
            )

        bucket.count += 1
        return Decision(
            allowed=True,
            reason="allowed",
            key=normalized_key,
            remaining=max(0, self.max_requests - bucket.count),
        )

    def prune_stale(self, *, now_ms: int | None = None) -> int:
        now = self._clock() if now_ms is None else now_ms
        stale_keys = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.window_start_ms > self.max_stale_ms
        ]
        for key in stale_keys:
            del self._buckets[key]
        return len(stale_keys)

    def reset(self) -> None:
        self._buckets.clear()

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)

    def _insert_bucket(self, key: str, bucket: _Bucket) -> None:
        if key not in self._buckets and len(self._buckets) >= self.max_entries:
            oldest_key = next(iter(self._buckets), None)
            if oldest_key is not None:
                del self._buckets[oldest_key]
        self._buckets[key] = bucket


def normalize_rate_limit_key(value: object, *, fallback: str = "unknown") -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


def resolve_control_plane_rate_limit_key(
    *,
    device_id: object = None,
    client_ip: object = None,
    conn_id: object = None,
) -> str:
    device = normalize_rate_limit_key(device_id, fallback="unknown-device")
    ip = normalize_rate_limit_key(client_ip, fallback="unknown-ip")
    conn = normalize_rate_limit_key(conn_id, fallback="")
    if device == "unknown-device" and ip == "unknown-ip" and conn:
        return f"{device}|{ip}|conn={conn}"
    return f"{device}|{ip}"


METHOD_SCOPES: Mapping[str, str] = {
    "connect": PAIRING_SCOPE,
    "pairing.approve": PAIRING_SCOPE,
    "pairing.reject": PAIRING_SCOPE,
    "pairing.status": PAIRING_SCOPE,
    "config.get": READ_SCOPE,
    "config.schema.lookup": READ_SCOPE,
    "talk.config": READ_SCOPE,
    "agents.files.list": READ_SCOPE,
    "agents.files.get": READ_SCOPE,
    "chat.history": READ_SCOPE,
    "chat.status": READ_SCOPE,
    "daemon.status": READ_SCOPE,
    "daemon.inspect": READ_SCOPE,
    "sessions.list": READ_SCOPE,
    "sessions.get": READ_SCOPE,
    "message.action": WRITE_SCOPE,
    "send": WRITE_SCOPE,
    "poll": WRITE_SCOPE,
    "agent": WRITE_SCOPE,
    "agent.wait": WRITE_SCOPE,
    "wake": WRITE_SCOPE,
    "talk.mode": WRITE_SCOPE,
    "talk.speak": WRITE_SCOPE,
    "chat.send": WRITE_SCOPE,
    "chat.abort": WRITE_SCOPE,
    "sessions.create": WRITE_SCOPE,
    "sessions.send": WRITE_SCOPE,
    "sessions.steer": WRITE_SCOPE,
    "sessions.abort": WRITE_SCOPE,
    "daemon.wake": WRITE_SCOPE,
    "daemon.stop": WRITE_SCOPE,
    "channels.start": ADMIN_SCOPE,
    "channels.logout": ADMIN_SCOPE,
    "agents.create": ADMIN_SCOPE,
    "agents.update": ADMIN_SCOPE,
    "agents.delete": ADMIN_SCOPE,
    "skills.install": ADMIN_SCOPE,
    "skills.update": ADMIN_SCOPE,
    "secrets.reload": ADMIN_SCOPE,
    "secrets.resolve": ADMIN_SCOPE,
    "cron.add": ADMIN_SCOPE,
    "cron.update": ADMIN_SCOPE,
    "cron.remove": ADMIN_SCOPE,
    "cron.run": ADMIN_SCOPE,
    "sessions.patch": ADMIN_SCOPE,
    "sessions.reset": ADMIN_SCOPE,
    "sessions.delete": ADMIN_SCOPE,
    "sessions.compact": ADMIN_SCOPE,
    "daemon.start": ADMIN_SCOPE,
    "daemon.restart": ADMIN_SCOPE,
    "daemon.configure": ADMIN_SCOPE,
}


def resolve_method_scope(method: str) -> str | None:
    return METHOD_SCOPES.get(method)


def least_privilege_scopes_for_method(method: str) -> tuple[str, ...]:
    scope = resolve_method_scope(method)
    return (scope,) if scope is not None else ()


def authorize_method(method: str, granted_scopes: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> Decision:
    required_scope = resolve_method_scope(method)
    if required_scope is None:
        return Decision(allowed=False, reason="unknown_method", method=method)

    scopes = frozenset(scope for scope in granted_scopes if scope in OPERATOR_SCOPES)
    if ADMIN_SCOPE in scopes:
        return Decision(allowed=True, reason="allowed", method=method, scope=required_scope)

    if required_scope == READ_SCOPE and WRITE_SCOPE in scopes:
        return Decision(allowed=True, reason="allowed", method=method, scope=required_scope)

    if required_scope in scopes:
        return Decision(allowed=True, reason="allowed", method=method, scope=required_scope)

    return Decision(
        allowed=False,
        reason="missing_scope",
        method=method,
        scope=required_scope,
        missing_scope=required_scope,
    )


def is_control_plane_write_method(method: str) -> bool:
    return resolve_method_scope(method) in {WRITE_SCOPE, ADMIN_SCOPE}

