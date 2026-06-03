import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DESCRIPTION = (
    "Evidence harness for coding agents: learning-effect, patch-scope, and test-proof checks."
)
FORBIDDEN_DESCRIPTION_TERMS = (
    "agent runtime",
    "coding and data work",
    "general autonomy",
)


def _pyproject_description() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^description = "([^"]+)"$', text, flags=re.MULTILINE)
    assert match, "pyproject.toml must declare a project description"
    return match.group(1)


def _setup_description() -> str:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    raise AssertionError("setup.py must declare a setup(description=...)")


def test_package_metadata_uses_focused_public_positioning() -> None:
    descriptions = [_pyproject_description(), _setup_description()]

    assert descriptions == [PUBLIC_DESCRIPTION, PUBLIC_DESCRIPTION]
    for description in descriptions:
        lowered = description.lower()
        for forbidden in FORBIDDEN_DESCRIPTION_TERMS:
            assert forbidden not in lowered
