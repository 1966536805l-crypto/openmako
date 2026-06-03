from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .edit_loop import AutoPatchSpec, run_auto_patch
from .tools import run_command_args


DEMO_TEST_COMMAND = ["python3", "-m", "unittest", "discover", "-s", "tests"]


@dataclass(frozen=True)
class FixDemoResult:
    ok: bool
    demo_id: str
    workspace: str
    initial_test_ok: bool
    final_test_ok: bool
    initial_summary: str
    final_summary: str
    fix_summary: str
    changed_files: tuple[str, ...]
    checkpoint_id: str
    model_calls: int
    result_json: str
    result_markdown: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_files"] = list(self.changed_files)
        return payload


def run_fix_demo(project: str | Path) -> FixDemoResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    demo_id = "fix-demo-" + uuid.uuid4().hex[:10]
    root = project_path / ".quantagent" / "demos" / demo_id
    workspace = root / "workspace"
    _write_demo_workspace(workspace)

    initial = run_command_args(DEMO_TEST_COMMAND, cwd=workspace, timeout=60, allow_risky=True)
    fix = run_auto_patch(
        workspace,
        AutoPatchSpec(
            task="fix failing demo test",
            path="calculator.py",
            old="return a - b",
            new="return a + b",
            test_command=(),
            reviewed=True,
            timeout=60,
        ),
        apply=True,
    )
    _clear_pycache(workspace)
    final = run_command_args(DEMO_TEST_COMMAND, cwd=workspace, timeout=60, allow_risky=True)
    changed_files = ("calculator.py",) if (workspace / "calculator.py").read_text(encoding="utf-8").strip().endswith("a + b") else ()
    ok = initial.returncode != 0 and fix.ok and final.returncode == 0 and not final.blocked
    result_json = root / "result.json"
    result_markdown = root / "result.md"
    result = FixDemoResult(
        ok=ok,
        demo_id=demo_id,
        workspace=str(workspace),
        initial_test_ok=initial.returncode == 0 and not initial.blocked,
        final_test_ok=final.returncode == 0 and not final.blocked,
        initial_summary=_command_summary(initial),
        final_summary=_command_summary(final),
        fix_summary=fix.summary,
        changed_files=changed_files,
        checkpoint_id=fix.checkpoint_id,
        model_calls=0,
        result_json=str(result_json),
        result_markdown=str(result_markdown),
    )
    root.mkdir(parents=True, exist_ok=True)
    result_json.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result_markdown.write_text(render_fix_demo(result), encoding="utf-8")
    return result


def render_fix_demo(result: FixDemoResult) -> str:
    lines = [
        "# Mako Fix Demo",
        "",
        f"- status: {'passed' if result.ok else 'failed'}",
        f"- demo_id: {result.demo_id}",
        f"- workspace: {result.workspace}",
        f"- model_calls: {result.model_calls}",
        f"- before: {'passed' if result.initial_test_ok else 'failed'} ({result.initial_summary})",
        f"- after: {'passed' if result.final_test_ok else 'failed'} ({result.final_summary})",
        f"- changed: {', '.join(result.changed_files) if result.changed_files else '-'}",
        f"- checkpoint: {result.checkpoint_id or '-'}",
        f"- result_json: {result.result_json}",
        "",
        "## Proof",
        "",
        f"- test command: `{' '.join(DEMO_TEST_COMMAND)}`",
        f"- fix: {result.fix_summary}",
    ]
    return "\n".join(lines) + "\n"


def _write_demo_workspace(workspace: Path) -> None:
    tests = workspace / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (workspace / "calculator.py").write_text(
        "\n".join(
            [
                "def add(a, b):",
                "    return a - b",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tests / "test_calculator.py").write_text(
        "\n".join(
            [
                "import unittest",
                "from pathlib import Path",
                "",
                "namespace = {}",
                "exec(compile(Path('calculator.py').read_text(encoding='utf-8'), 'calculator.py', 'exec'), namespace)",
                "add = namespace['add']",
                "",
                "",
                "class CalculatorTest(unittest.TestCase):",
                "    def test_adds_two_numbers(self):",
                "        self.assertEqual(add(2, 3), 5)",
                "",
                "",
                "if __name__ == '__main__':",
                "    unittest.main()",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _command_summary(result: Any) -> str:
    if getattr(result, "blocked", False):
        return getattr(result, "reason", "") or "blocked"
    return f"exit {getattr(result, 'returncode', 0)}"


def _clear_pycache(workspace: Path) -> None:
    for path in workspace.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
