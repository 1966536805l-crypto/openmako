from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_outreach_copy_gate_defaults_and_blocks_bad_copy(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    gate = root / "scripts" / "outreach_copy_gate.py"
    review_docs = [
        root / "docs" / "PUBLIC_REVIEW_ENTRYPOINTS.md",
        root / "docs" / "REVIEWER_OUTREACH_QUEUE.md",
        root / "docs" / "OPEN_SOURCE_TRACTION_GAP.md",
    ]

    default_run = subprocess.run(
        [sys.executable, str(gate)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert default_run.returncode == 0, default_run.stdout + default_run.stderr
    assert "outreach-copy-gate: PASS" in default_run.stdout
    assert "skeptic-reader" in default_run.stdout

    explicit_run = subprocess.run(
        [sys.executable, str(gate), *map(str, review_docs)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert explicit_run.returncode == 0, explicit_run.stdout + explicit_run.stderr

    for doc in review_docs[:2]:
        assert "python3 scripts/outreach_copy_gate.py" in doc.read_text(encoding="utf-8")

    bad_copy = tmp_path / "bad.md"
    bad_copy.write_text(
        "Please star my project. OpenMako is better than Hermes and solved autonomous coding.\n",
        encoding="utf-8",
    )
    blocked = subprocess.run(
        [sys.executable, str(gate), str(bad_copy)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode == 1
    assert "outreach-copy-gate: FAIL" in blocked.stdout
    assert "skeptic-reader" in blocked.stdout
    assert "boundary-reader" in blocked.stdout
