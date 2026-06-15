from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_live_repair_gate_records_failure_to_fix_loop(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "native_live_repair_gate"
    env = os.environ.copy()
    env["OPENMAKO_NATIVE_LIVE_REPAIR_GATE_DIR"] = str(artifact_dir)

    result = subprocess.run(
        ["bash", "scripts/native_live_repair_gate.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "native-live-repair-gate: PASS" in result.stdout
    summary_path = artifact_dir / "last_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "native-live-repair-gate/v0.1"
    assert payload["status"] == "passed"
    assert payload["native_live_repair"] is True
    assert payload["source_workspace"] == "temporary-local-project"
    assert payload["before_failure"]["exit_code"] != 0
    assert payload["after_test"]["exit_code"] == 0
    assert payload["agent_loop"]["ok"] is True
    assert payload["agent_loop"]["status"] == "done"
    assert payload["agent_loop"]["input_provenance"] == "native_live_repair_gate"
    assert payload["agent_loop"]["learning_context"] == "off"
    assert "implement" in payload["agent_loop"]["observations"]
    assert "unit_tests" in payload["agent_loop"]["observations"]
    assert payload["diff"]["edited_files"] == ["subject.py"]
    assert payload["diff"]["contains_expected_source_change"] is True
    assert payload["diff"]["test_file_preserved"] is True
    assert "external review" in payload["not_proof"]
    assert "third-party benchmark standing" in payload["not_proof"]
    assert "broad unknown-repository repair" in payload["not_proof"]

    patch_text = (artifact_dir / "agent_loop_patch.diff").read_text(encoding="utf-8")
    assert "--- a/subject.py" in patch_text
    assert "+++ b/subject.py" in patch_text
    assert "-    return a - b" in patch_text
    assert "+    return a + b" in patch_text
    assert (artifact_dir / "agent_result.json").exists()
    assert (artifact_dir / "agent_loop_trajectory.jsonl").exists()
    assert (artifact_dir / "agent_loop_events.jsonl").exists()
