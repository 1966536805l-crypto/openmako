#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

ARTIFACT_DIR="${OPENMAKO_NATIVE_LIVE_REPAIR_GATE_DIR:-$ROOT_DIR/.quantagent/native_live_repair_gate}"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unknown)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

rm -rf "$ARTIFACT_DIR"
mkdir -p "$ARTIFACT_DIR"

"$PYTHON_BIN" - "$WORK_DIR" "$ARTIFACT_DIR" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from quantagent.agent_loop_core import run_agent_loop

workspace = Path(sys.argv[1])
artifact_dir = Path(sys.argv[2])
git_commit = sys.argv[3]
artifact_dir.mkdir(parents=True, exist_ok=True)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

subject_before = "def add_numbers(a, b):\n    return a - b\n"
test_source = (
    "import unittest\n"
    "from subject import add_numbers\n\n"
    "class SubjectTest(unittest.TestCase):\n"
    "    def test_int_sum(self):\n"
    "        self.assertEqual(add_numbers(2, 3), 5)\n\n"
    "    def test_float_sum(self):\n"
    "        self.assertEqual(add_numbers(1.5, 2.25), 3.75)\n"
)
(workspace / "subject.py").write_text(subject_before, encoding="utf-8")
(workspace / "test_subject.py").write_text(test_source, encoding="utf-8")

test_command = [sys.executable, "-m", "unittest", "-q", "test_subject"]

def run_test() -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        test_command,
        cwd=workspace,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

before = run_test()
if before.returncode == 0:
    raise SystemExit("native-live-repair-gate: before test unexpectedly passed")
shutil.rmtree(workspace / "__pycache__", ignore_errors=True)

result = run_agent_loop(
    workspace,
    "Fix add_numbers so it returns arithmetic sum for ints and floats.",
    explicit_mode="build",
    include_validation=True,
    input_provenance="native_live_repair_gate",
    learning_context="off",
)
after = run_test()

subject_after = (workspace / "subject.py").read_text(encoding="utf-8")
test_after = (workspace / "test_subject.py").read_text(encoding="utf-8")
if not result.ok:
    raise SystemExit("native-live-repair-gate: agent loop did not report ok")
if after.returncode != 0:
    raise SystemExit("native-live-repair-gate: after test did not pass")
if test_after != test_source:
    raise SystemExit("native-live-repair-gate: test file changed")
if "return a + b" not in subject_after:
    raise SystemExit("native-live-repair-gate: expected source repair is missing")
if not result.patch_artifact_path or not Path(result.patch_artifact_path).exists():
    raise SystemExit("native-live-repair-gate: patch artifact missing")
if not result.trajectory_path or not Path(result.trajectory_path).exists():
    raise SystemExit("native-live-repair-gate: trajectory artifact missing")

result_path = artifact_dir / "agent_result.json"
patch_path = artifact_dir / "agent_loop_patch.diff"
trajectory_path = artifact_dir / "agent_loop_trajectory.jsonl"
result_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
shutil.copyfile(result.patch_artifact_path, patch_path)
shutil.copyfile(result.trajectory_path, trajectory_path)

last_trajectory = json.loads(Path(result.trajectory_path).read_text(encoding="utf-8").splitlines()[-1])
event_source = Path(str(last_trajectory.get("event_trajectory_path") or ""))
event_path = artifact_dir / "agent_loop_events.jsonl"
if event_source.exists():
    shutil.copyfile(event_source, event_path)
else:
    raise SystemExit("native-live-repair-gate: event trajectory artifact missing")

patch_text = patch_path.read_text(encoding="utf-8")
if "--- a/subject.py" not in patch_text or "+++ b/subject.py" not in patch_text:
    raise SystemExit("native-live-repair-gate: patch artifact does not bind subject.py")
if "-    return a - b" not in patch_text or "+    return a + b" not in patch_text:
    raise SystemExit("native-live-repair-gate: patch artifact lacks expected repair diff")

observations = [item.to_dict() for item in result.observations]
observation_names = [item["name"] for item in observations]
for required_name in ("implement", "unit_tests"):
    if required_name not in observation_names:
        raise SystemExit(f"native-live-repair-gate: missing observation {required_name}")

summary = {
    "schema_version": "native-live-repair-gate/v0.1",
    "status": "passed",
    "git_commit": git_commit,
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "proof_command": "bash scripts/native_live_repair_gate.sh",
    "native_live_repair": True,
    "source_workspace": "temporary-local-project",
    "repair_task": "Fix add_numbers so it returns arithmetic sum for ints and floats.",
    "before_failure": {
        "command": test_command,
        "exit_code": before.returncode,
        "stdout_sha256": "sha256:" + hashlib.sha256(before.stdout.encode()).hexdigest(),
        "stderr_sha256": "sha256:" + hashlib.sha256(before.stderr.encode()).hexdigest(),
    },
    "agent_loop": {
        "ok": result.ok,
        "status": result.status,
        "failure_class": result.failure_class,
        "final_mode": result.final_mode,
        "input_provenance": "native_live_repair_gate",
        "learning_context": "off",
        "observations": observation_names,
        "trajectory_artifact": "agent_loop_trajectory.jsonl",
        "event_trajectory_artifact": "agent_loop_events.jsonl",
        "patch_artifact": "agent_loop_patch.diff",
        "result_artifact": "agent_result.json",
    },
    "after_test": {
        "command": test_command,
        "exit_code": after.returncode,
        "stdout_sha256": "sha256:" + hashlib.sha256(after.stdout.encode()).hexdigest(),
        "stderr_sha256": "sha256:" + hashlib.sha256(after.stderr.encode()).hexdigest(),
    },
    "diff": {
        "artifact": "agent_loop_patch.diff",
        "sha256": "sha256:" + hashlib.sha256(patch_path.read_bytes()).hexdigest(),
        "edited_files": ["subject.py"],
        "contains_expected_source_change": True,
        "test_file_preserved": True,
    },
    "not_proof": [
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "third-party benchmark standing",
        "broad unknown-repository repair",
        "native Claude Code, Codex, Cursor, or SWE-bench export ingestion",
        "live desktop or browser control",
    ],
}
(artifact_dir / "last_summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

echo "native-live-repair-gate: summary=$ARTIFACT_DIR/last_summary.json"
echo "native-live-repair-gate: not-proof=external review; endorsement; stars; reposts; third-party benchmark standing; broad unknown-repository repair; native export ingestion; live desktop or browser control"
echo "native-live-repair-gate: PASS"
