from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tool_registry import run_registered_tool


@dataclass
class ValidationResult:
    name: str
    ok: bool
    detail: str
    status: str = "ok"


def validate_project_scripts(project: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for script in sorted(project.glob("**/p*.py")):
        if script.name.startswith(("p4_", "p5_", "p5b_", "p6_")):
            result = run_registered_tool("py_compile", project, str(script))
            detail = result.stderr.strip() or result.stdout.strip() or "ok"
            results.append(
                ValidationResult(
                    script.name,
                    result.returncode == 0,
                    detail,
                    "ok" if result.returncode == 0 else "fail",
                )
            )

    if not next(project.glob("**/p4_real_execution_framework.py"), None):
        results.append(
            ValidationResult(
                "p4_real_execution_framework --help",
                True,
                "skip: p4_real_execution_framework.py not found in starter project",
                "skip",
            )
        )
        return results

    p4 = run_registered_tool("run_p4_help", project)
    results.append(
        ValidationResult(
            "p4_real_execution_framework --help",
            p4.returncode == 0,
            p4.stderr.strip() or p4.stdout[:300].strip() or "ok",
            "ok" if p4.returncode == 0 else "fail",
        )
    )
    return results
