from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .exception_audit import audit_suppressed_exception


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED}


@dataclass
class RunRecord:
    run_id: str
    command: tuple[str, ...]
    scope: str = ""
    status: RunStatus = RunStatus.PENDING
    cwd: str = ""
    pid: int | None = None
    returncode: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    timeout_seconds: float | None = None
    no_output_timeout_seconds: float | None = None
    last_output_at: float | None = None
    stdout: list[str] = field(default_factory=list)
    error: str = ""
    cancel_reason: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "command": list(self.command),
            "scope": self.scope,
            "status": self.status.value,
            "terminal": self.terminal,
            "cwd": self.cwd,
            "pid": self.pid,
            "returncode": self.returncode,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "updated_at": self.updated_at,
            "timeout_seconds": self.timeout_seconds,
            "no_output_timeout_seconds": self.no_output_timeout_seconds,
            "last_output_at": self.last_output_at,
            "stdout": list(self.stdout),
            "output": "".join(self.stdout),
            "error": self.error,
            "cancel_reason": self.cancel_reason,
        }


@dataclass
class _Runtime:
    process: subprocess.Popen[str]
    output_queue: "queue.Queue[str]"
    reader: threading.Thread


class DaemonSupervisor:
    """Foreground subprocess supervisor with scoped cancellation and timeouts."""

    def __init__(self, *, terminate_grace_seconds: float = 0.5) -> None:
        self.terminate_grace_seconds = max(0.0, float(terminate_grace_seconds))
        self._records: dict[str, RunRecord] = {}
        self._runtime: dict[str, _Runtime] = {}

    def start(
        self,
        command: Sequence[str],
        *,
        scope: str = "",
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        no_output_timeout_seconds: float | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        if not command:
            raise ValueError("command must not be empty")
        rid = run_id or "run-" + uuid.uuid4().hex[:16]
        if rid in self._records:
            raise ValueError(f"duplicate run_id: {rid}")
        cwd_text = str(Path(cwd).expanduser().resolve(strict=False)) if cwd is not None else ""
        record = RunRecord(
            run_id=rid,
            command=tuple(str(part) for part in command),
            scope=scope,
            cwd=cwd_text,
            timeout_seconds=timeout_seconds,
            no_output_timeout_seconds=no_output_timeout_seconds,
        )
        self._records[rid] = record
        output_queue: "queue.Queue[str]" = queue.Queue()
        try:
            process = subprocess.Popen(
                list(record.command),
                cwd=cwd_text or None,
                env=dict(env) if env is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except Exception as exc:
            now = time.time()
            record.status = RunStatus.FAILED
            record.error = f"spawn failed: {exc}"
            record.started_at = now
            record.ended_at = now
            record.updated_at = now
            return record

        now = time.time()
        record.status = RunStatus.RUNNING
        record.pid = process.pid
        record.started_at = now
        record.updated_at = now
        record.last_output_at = now
        reader = threading.Thread(target=_read_output, args=(process, output_queue), name=f"daemon-supervisor-{rid}", daemon=True)
        reader.start()
        self._runtime[rid] = _Runtime(process=process, output_queue=output_queue, reader=reader)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        self.update(run_id)
        return self._records.get(run_id)

    def update(self, run_id: str | None = None) -> list[RunRecord]:
        selected = [run_id] if run_id is not None else list(self._records)
        updated: list[RunRecord] = []
        for rid in selected:
            record = self._records.get(rid)
            if record is None:
                continue
            self._update_one(record)
            updated.append(record)
        return updated

    def cancel_scope(self, scope: str, *, reason: str = "scope canceled") -> list[RunRecord]:
        canceled: list[RunRecord] = []
        for record in list(self._records.values()):
            self._update_one(record)
            if record.scope == scope and not record.terminal:
                record.cancel_reason = reason
                self._finish_by_stopping(record, RunStatus.CANCELED, reason)
                canceled.append(record)
        return canceled

    def cancel(self, run_id: str, *, reason: str = "canceled") -> RunRecord | None:
        record = self._records.get(run_id)
        if record is None:
            return None
        self._update_one(record)
        if not record.terminal:
            record.cancel_reason = reason
            self._finish_by_stopping(record, RunStatus.CANCELED, reason)
        return record

    def snapshot(self) -> dict[str, Any]:
        self.update()
        return {
            "runs": [record.to_dict() for record in sorted(self._records.values(), key=lambda item: item.created_at)],
            "counts": {
                status.value: sum(1 for record in self._records.values() if record.status == status)
                for status in RunStatus
            },
        }

    def _update_one(self, record: RunRecord) -> None:
        runtime = self._runtime.get(record.run_id)
        if runtime is None:
            return
        self._drain_output(record, runtime)
        if record.terminal:
            return

        now = time.time()
        if record.timeout_seconds is not None and record.started_at is not None:
            if now - record.started_at >= record.timeout_seconds:
                self._finish_by_stopping(record, RunStatus.FAILED, "timeout exceeded")
                return

        if record.no_output_timeout_seconds is not None and record.last_output_at is not None:
            if now - record.last_output_at >= record.no_output_timeout_seconds:
                self._finish_by_stopping(record, RunStatus.FAILED, "no-output timeout exceeded")
                return

        returncode = runtime.process.poll()
        if returncode is not None:
            runtime.reader.join(timeout=0.1)
            self._drain_output(record, runtime)
            record.returncode = returncode
            record.status = RunStatus.SUCCEEDED if returncode == 0 else RunStatus.FAILED
            if returncode != 0 and not record.error:
                record.error = f"process exited with code {returncode}"
            record.ended_at = now
            record.updated_at = now
            self._runtime.pop(record.run_id, None)
        else:
            record.updated_at = now

    def _finish_by_stopping(self, record: RunRecord, status: RunStatus, reason: str) -> None:
        runtime = self._runtime.get(record.run_id)
        if runtime is None:
            now = time.time()
            record.status = status
            record.error = reason if status == RunStatus.FAILED else record.error
            record.ended_at = now
            record.updated_at = now
            return

        self._stop_process(runtime.process)
        runtime.reader.join(timeout=0.1)
        self._drain_output(record, runtime)
        record.returncode = runtime.process.poll()
        record.status = status
        if status == RunStatus.FAILED:
            record.error = reason
        record.ended_at = time.time()
        record.updated_at = record.ended_at
        self._runtime.pop(record.run_id, None)

    def _stop_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        except Exception:
            process.terminate()
        try:
            process.wait(timeout=self.terminate_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            return
        except Exception:
            process.kill()
        try:
            process.wait(timeout=max(0.1, self.terminate_grace_seconds))
        except subprocess.TimeoutExpired:
            pass

    def _drain_output(self, record: RunRecord, runtime: _Runtime) -> None:
        saw_output = False
        while True:
            try:
                chunk = runtime.output_queue.get_nowait()
            except queue.Empty:
                break
            record.stdout.append(chunk)
            saw_output = True
        if saw_output:
            record.last_output_at = time.time()


def _read_output(process: subprocess.Popen[str], output_queue: "queue.Queue[str]") -> None:
    if process.stdout is None:
        return
    try:
        while True:
            chunk = process.stdout.read(1)
            if chunk == "":
                break
            output_queue.put(chunk)
    finally:
        try:
            process.stdout.close()
        except Exception as exc:
            audit_suppressed_exception(
                "daemon_supervisor._read_output.close_stdout",
                exc,
                data={"pid": process.pid},
            )
            pass
