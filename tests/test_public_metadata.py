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
FORBIDDEN_README_CLAIMS = (
    "Today, OpenMako proves",
    "## What It Proves Today",
    "| Green public CI |",
    "OpenMako does not copy Claude/closed-source code",
    "docs/COMPARISON.md",
    "docs/LAUNCH_PLAYBOOK.md",
    "docs/MARKET_TOOL_COPY_SCAN.md",
)
FORBIDDEN_PUBLIC_PROGRESS_CLAIMS = (
    "112/112",
    "60/60",
    "full pytest passed",
    "level=L5",
    "SWE-style repository reasoning",
    "broad unknown NPM repo repair",
)
FORBIDDEN_ROOT_AGENT_NOTES = (
    "QuantAgent Project Memory",
    "local quant-focused coding agent starter",
    "quant-focused coding agent starter",
    "Claude Code-like local workflow",
    "PF, slippage, capacity, tick, broker",
    "python3 -m unittest discover -s tests",
    "desktop actions",
    "Claude Code source",
    "OpenClaw, Hermes Agent",
    "desktop_plan.py",
)
ARCHIVED_ROOT_QUANT_FILES = (
    "TICK_CAPACITY_VALIDATOR_GUIDE.md",
    "capacity_validation_report.json",
    "tick_price_validation.json",
    "tick_price_validation.md",
)
EXAMPLE_ROOT_QUANT_FILES = (
    "demo_capacity_comprehensive.py",
    "demo_capacity_validation.py",
    "example_tick_price_validator.py",
    "realistic_t1_trades.csv",
)
LEGACY_ROOT_QUANT_TEST_FILES = (
    "test_tick_price_validator.py",
    "test_realistic_t1_trades.csv",
    "test_slippage_calculator.py",
    "test_tick_extraction_real.py",
    "test_tick_extraction.py",
    "tick_data_request_test.csv",
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


def test_readme_links_public_proof_issue() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Public proof card" in readme
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in readme


def test_readme_uses_reviewable_public_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "demonstrates one narrow public gate" in readme
    assert "## Implementation Boundary" in readme
    assert "## Beyond The Public Gate" in readme
    assert "OpenMako's project policy is clean-room implementation for closed-source tools" in readme
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden not in readme


def test_progress_file_is_public_boundary_not_internal_scoreboard() -> None:
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert "public status boundary" in progress
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in progress
    assert "stale internal notes" in progress
    for forbidden in FORBIDDEN_PUBLIC_PROGRESS_CLAIMS:
        assert forbidden not in progress


def test_root_agent_notes_match_public_evidence_boundary() -> None:
    notes = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert notes.startswith("# OpenMako Local Agent Notes")
    assert "OpenMako is a focused evidence harness for coding-agent repair runs." in notes
    assert "not a public capability claim" in notes
    assert "focused learning-effect gate" in notes
    assert "tests/test_public_metadata.py" in notes
    for forbidden in FORBIDDEN_ROOT_AGENT_NOTES:
        assert forbidden not in notes


def test_quant_reports_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant"

    for filename in ARCHIVED_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()


def test_quant_examples_are_moved_out_of_repository_root() -> None:
    expected_locations = {
        "demo_capacity_comprehensive.py": ROOT / "examples" / "quant" / "capacity",
        "demo_capacity_validation.py": ROOT / "examples" / "quant" / "capacity",
        "example_tick_price_validator.py": ROOT / "examples" / "quant" / "tick_price",
        "realistic_t1_trades.csv": ROOT / "examples" / "quant" / "data",
    }

    for filename in EXAMPLE_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (expected_locations[filename] / filename).exists()


def test_legacy_quant_test_artifacts_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant" / "legacy_tests"

    for filename in LEGACY_ROOT_QUANT_TEST_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()
