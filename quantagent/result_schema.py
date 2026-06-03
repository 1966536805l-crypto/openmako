from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ToolResult:
    name: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    task: str
    ok: bool
    stage: str
    summary: str
    tool_results: list[ToolResult] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def write_json(self, path: Path) -> Path:
        path.write_text(self.to_json() + "\n", encoding="utf-8")
        return path


def tool_result_from_command(name: str, returncode: int, stdout: str, stderr: str) -> ToolResult:
    ok = returncode == 0
    summary = "ok" if ok else (stderr.strip() or stdout.strip() or f"exit {returncode}")
    return ToolResult(
        name=name,
        ok=ok,
        summary=summary[:500],
        data={"returncode": returncode, "stdout_preview": stdout[:1000], "stderr_preview": stderr[:1000]},
    )

