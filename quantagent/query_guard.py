from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock


IDLE = "idle"
DISPATCHING = "dispatching"
RUNNING = "running"

QUERY_GUARD_STATES = frozenset({IDLE, DISPATCHING, RUNNING})


@dataclass
class QueryGuard:
    _state: str = field(default=IDLE, init=False, repr=False)
    _generation: int = field(default=0, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def reserve(self) -> int | None:
        with self._lock:
            if self._state != IDLE:
                return None
            self._generation += 1
            self._state = DISPATCHING
            return self._generation

    def cancel_reservation(self) -> bool:
        with self._lock:
            if self._state != DISPATCHING:
                return False
            self._state = IDLE
            return True

    def start(self) -> int | None:
        with self._lock:
            if self._state == RUNNING:
                return None
            if self._state == IDLE:
                self._generation += 1
            self._state = RUNNING
            return self._generation

    def end(self, generation: int) -> bool:
        generation = _validate_generation(generation)
        with self._lock:
            if self._state != RUNNING or self._generation != generation:
                return False
            self._state = IDLE
            return True

    def force_end(self) -> int:
        with self._lock:
            if self._state != IDLE:
                self._generation += 1
                self._state = IDLE
            return self._generation


def _validate_generation(generation: int) -> int:
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise TypeError("generation must be an integer")
    return generation
