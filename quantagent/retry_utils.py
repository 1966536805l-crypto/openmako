"""Retry utilities — jittered backoff for decorrelated retries.

Adapted from Hermes Agent
Copyright (c) 2025 Nous Research
Licensed under MIT License
https://github.com/NousResearch/hermes-agent

Original file: agent/retry_utils.py
Modifications: None (direct copy for openmako integration)
"""

import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

# Monotonic counter for jitter seed uniqueness within the same process.
# Protected by a lock to avoid race conditions in concurrent retry paths
# (e.g. multiple gateway sessions retrying simultaneously).
_jitter_counter = 0
_jitter_lock = threading.Lock()


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """Compute a jittered exponential backoff delay.

    Args:
        attempt: 1-based retry attempt number.
        base_delay: Base delay in seconds for attempt 1.
        max_delay: Maximum delay cap in seconds.
        jitter_ratio: Fraction of computed delay to use as random jitter
            range.  0.5 means jitter is uniform in [0, 0.5 * delay].

    Returns:
        Delay in seconds: min(base * 2^(attempt-1), max_delay) + jitter.

    The jitter decorrelates concurrent retries so multiple sessions
    hitting the same provider don't all retry at the same instant.
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    # Seed from time + counter for decorrelation even with coarse clocks.
    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return delay + jitter


def retry_after_seconds(value: object) -> Optional[float]:
    """Parse an HTTP Retry-After value into seconds."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        return seconds if seconds >= 0 else None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delay = (when - datetime.now(timezone.utc)).total_seconds()
    return delay if delay >= 0 else None


class RetryDecision:
    """Result of a retry fuse check."""

    def __init__(self, allowed: bool, attempt: int, reason: str = ""):
        self.allowed = allowed
        self.attempt = attempt
        self.attempts = attempt  # Alias for compatibility
        self.reason = reason


class RetryFuse:
    """Circuit breaker for retry attempts to prevent unbounded retries.

    Tracks retry attempts per key and blocks further retries after max_attempts.
    """

    def __init__(self, max_attempts: int = 3):
        """Initialize retry fuse.

        Args:
            max_attempts: Maximum number of retry attempts allowed per key.
        """
        self.max_attempts = max_attempts
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()

    def before_retry(self, key: str) -> RetryDecision:
        """Check if retry is allowed for the given key.

        Args:
            key: Unique identifier for the retry context (e.g., "provider:429").

        Returns:
            RetryDecision indicating if retry is allowed.
        """
        with self._lock:
            current = self._attempts.get(key, 0)
            self._attempts[key] = current + 1

            if current >= self.max_attempts:
                return RetryDecision(
                    allowed=False,
                    attempt=current + 1,
                    reason="retry fuse exhausted",
                )

            return RetryDecision(allowed=True, attempt=current + 1)

    def reset(self, key: str) -> None:
        """Reset retry counter for the given key.

        Args:
            key: Unique identifier for the retry context.
        """
        with self._lock:
            self._attempts.pop(key, None)

    def reset_all(self) -> None:
        """Reset all retry counters."""
        with self._lock:
            self._attempts.clear()
