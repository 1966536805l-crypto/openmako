"""Per-agent iteration budget — thread-safe consume/refund counter.

Adapted from Hermes Agent
Copyright (c) 2025 Nous Research
Licensed under MIT License
https://github.com/NousResearch/hermes-agent

Original file: agent/iteration_budget.py
Modifications: Restored openmako API (exhausted, reason, EXHAUSTED_REASON)
"""

from __future__ import annotations

import threading


EXHAUSTED_REASON = "iteration budget exhausted"


class IterationBudget:
    """Thread-safe iteration counter for an agent.

    Each agent (parent or subagent) gets its own ``IterationBudget``.
    The parent's budget is capped at ``max_iterations`` (default 90).
    Each subagent gets an independent budget capped at
    ``delegation.max_iterations`` (default 50) — this means total
    iterations across parent + subagents can exceed the parent's cap.
    Users control the per-subagent limit via ``delegation.max_iterations``
    in config.yaml.

    ``execute_code`` (programmatic tool calling) iterations are refunded via
    :meth:`refund` so they don't eat into the budget.
    """

    def __init__(self, max_iterations: int | None = None, max_total: int | None = None):
        # Support both max_iterations (openmako) and max_total (Hermes) for compatibility
        if max_iterations is not None and max_total is not None:
            raise ValueError("Cannot specify both max_iterations and max_total")
        if max_iterations is None and max_total is None:
            raise ValueError("Must specify either max_iterations or max_total")

        if max_iterations is not None:
            # Reject bool before int check (bool is subclass of int in Python)
            if isinstance(max_iterations, bool):
                raise TypeError(f"max_iterations must be int, got {type(max_iterations).__name__}")
            if not isinstance(max_iterations, int):
                raise TypeError(f"max_iterations must be int, got {type(max_iterations).__name__}")
            if max_iterations <= 0:
                raise ValueError(f"max_iterations must be positive, got {max_iterations}")
            self.max_iterations = max_iterations
        else:
            if isinstance(max_total, bool):
                raise TypeError(f"max_total must be int, got {type(max_total).__name__}")
            if not isinstance(max_total, int):
                raise TypeError(f"max_total must be int, got {type(max_total).__name__}")
            if max_total <= 0:
                raise ValueError(f"max_total must be positive, got {max_total}")
            self.max_iterations = max_total

        self._used = 0
        self._reason = ""
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Try to consume one iteration.  Returns True if allowed."""
        with self._lock:
            if self._used >= self.max_iterations:
                if not self._reason:
                    self._reason = EXHAUSTED_REASON
                return False
            self._used += 1
            # Set reason when we reach exhaustion
            if self._used >= self.max_iterations:
                self._reason = EXHAUSTED_REASON
            return True

    def refund(self) -> None:
        """Give back one iteration (e.g. for execute_code turns)."""
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_iterations - self._used)

    @property
    def exhausted(self) -> bool:
        """Returns True if budget is exhausted."""
        with self._lock:
            return self._used >= self.max_iterations

    @property
    def reason(self) -> str:
        """Returns exhaustion reason if exhausted, empty string otherwise."""
        with self._lock:
            return self._reason

    def to_dict(self) -> dict:
        """Serialize budget state to dict."""
        with self._lock:
            return {
                "max_iterations": self.max_iterations,
                "remaining": max(0, self.max_iterations - self._used),
                "exhausted": self._used >= self.max_iterations,
                "reason": self._reason,
            }


__all__ = ["IterationBudget", "EXHAUSTED_REASON"]
