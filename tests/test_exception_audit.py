import ast
import json
from pathlib import Path

from quantagent.exception_audit import audit_suppressed_exception


def test_audit_suppressed_exception_writes_jsonl(tmp_path: Path) -> None:
    exc = RuntimeError("hidden failure")

    audit_suppressed_exception("unit.test", exc, project=tmp_path, data={"path": "x"})

    path = tmp_path / ".quantagent" / "exception_audit.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["location"] == "unit.test"
    assert records[-1]["exception_type"] == "RuntimeError"
    assert records[-1]["message"] == "hidden failure"
    assert records[-1]["context"] == {"path": "x"}


def test_no_silent_broad_exception_handlers_remain() -> None:
    offenders: list[str] = []
    for path in Path("quantagent").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            )
            if not broad or not node.body:
                continue
            if isinstance(node.body[0], (ast.Pass, ast.Continue, ast.Return)):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
