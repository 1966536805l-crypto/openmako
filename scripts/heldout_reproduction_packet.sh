#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_SUMMARY_JSON="${OPENMAKO_HELDOUT_REPRODUCTION_SOURCE_SUMMARY_JSON:-.quantagent/external_heldout_benchmark_gate/last_summary.json}"
PACKET_JSON="${OPENMAKO_HELDOUT_REPRODUCTION_PACKET_JSON:-.quantagent/heldout_reproduction_packet/packet.json}"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || printf unknown)"

python3 - "$SOURCE_SUMMARY_JSON" "$PACKET_JSON" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
source_arg = Path(sys.argv[1])
packet_arg = Path(sys.argv[2])
SOURCE_SUMMARY_JSON = source_arg if source_arg.is_absolute() else ROOT / source_arg
PACKET_JSON = packet_arg if packet_arg.is_absolute() else ROOT / packet_arg
GIT_COMMIT = sys.argv[3]
public_root_raw = os.environ.get("OPENMAKO_HELDOUT_REPRODUCTION_PUBLIC_ROOT", "")
PUBLIC_ROOT = Path(public_root_raw).resolve(strict=False) if public_root_raw else None
PUBLIC_PREFIX = os.environ.get("OPENMAKO_HELDOUT_REPRODUCTION_PUBLIC_PREFIX", "")


def fail(reason: str) -> None:
    raise SystemExit(f"heldout-reproduction-packet: {reason}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def raw_evidence_key(path: Path) -> str:
    if PUBLIC_ROOT is not None:
        try:
            relative = path.resolve(strict=False).relative_to(PUBLIC_ROOT)
            return str(Path(PUBLIC_PREFIX) / relative) if PUBLIC_PREFIX else str(relative)
        except ValueError:
            pass
    return display_path(path)


def require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field} is not an object")
    return value


if not SOURCE_SUMMARY_JSON.is_file():
    fail(f"missing source summary {display_path(SOURCE_SUMMARY_JSON)}")

summary = json.loads(SOURCE_SUMMARY_JSON.read_text(encoding="utf-8"))
if summary.get("schema_version") != "external-heldout-benchmark-gate/v0.1":
    fail("source summary schema_version mismatch")
if summary.get("status") != "passed":
    fail("source summary status is not passed")
invocation = require_dict(summary.get("invocation"), "source summary invocation")
if invocation.get("git_commit") != GIT_COMMIT:
    fail("source summary git_commit does not match HEAD")
if summary.get("source", {}).get("package") != "mcp-python-sdk":
    fail("source package mismatch")
if summary.get("external_source_heldout") is not True:
    fail("external_source_heldout is not true")
if summary.get("heldout_from_autonomous_gate") is not True:
    fail("heldout_from_autonomous_gate is not true")
if summary.get("independent_external_benchmark") is not False:
    fail("independent_external_benchmark boundary mismatch")
selected_tests = summary.get("selected_tests")
if not isinstance(selected_tests, list) or len(selected_tests) != 2:
    fail("selected_tests count mismatch")
task_proofs = summary.get("task_proofs")
if not isinstance(task_proofs, list) or len(task_proofs) != 2:
    fail("task_proofs count mismatch")

summary_dir = SOURCE_SUMMARY_JSON.parent
expected_raw_files = [
    SOURCE_SUMMARY_JSON,
    summary_dir / "pytest.log",
]
raw_evidence_files: dict[str, str] = {}

before_failure_count = 0
after_test_count = 0
diff_count = 0
labels: dict[str, str] = {}
final_claims: dict[str, str] = {}
task_proof_files: list[Path] = []
for proof in task_proofs:
    proof = require_dict(proof, "task proof")
    task_id = proof.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        fail("task proof task_id missing")
    proof_path_raw = proof.get("proof_path")
    proof_file = None
    if isinstance(proof_path_raw, str) and proof_path_raw:
        candidate = Path(proof_path_raw)
        proof_file = candidate if candidate.is_absolute() else ROOT / candidate
    fallback = summary_dir / "task_proofs" / f"{task_id}.json"
    if proof_file is None or not proof_file.is_file():
        proof_file = fallback
    task_proof_files.append(proof_file)
    before_failure = require_dict(proof.get("before_failure"), f"{task_id}.before_failure")
    after_test = require_dict(proof.get("after_test"), f"{task_id}.after_test")
    diff = require_dict(proof.get("diff"), f"{task_id}.diff")
    if before_failure.get("returncode") == 0:
        fail(f"{task_id}.before_failure is not a failure")
    if after_test.get("returncode") != 0:
        fail(f"{task_id}.after_test is not successful")
    if diff.get("contains_target_function") is not True:
        fail(f"{task_id}.diff does not contain target function")
    if not proof.get("agent_diagnosis", {}).get("observations"):
        fail(f"{task_id}.agent_diagnosis missing observations")
    if "vendored MCP held-out repair task" not in str(proof.get("final_claim", "")):
        fail(f"{task_id}.final_claim boundary mismatch")
    labels[task_id] = "supported_repair_claim"
    final_claims[task_id] = str(proof.get("final_claim", ""))
    before_failure_count += 1
    after_test_count += 1
    diff_count += 1

expected_raw_files.extend(task_proof_files)
for raw_file in expected_raw_files:
    if not raw_file.is_file():
        fail(f"missing raw evidence file {display_path(raw_file)}")
    raw_evidence_files[raw_evidence_key(raw_file)] = "sha256:" + sha256_file(raw_file)

not_proof = [
    "independent external benchmark standing",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "GitHub Actions artifact zip contents",
]
packet = {
    "schema_version": "heldout-reproduction-packet/v0.1",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": GIT_COMMIT,
        "proof_command": "bash scripts/heldout_reproduction_packet.sh",
        "source_summary_json": display_path(SOURCE_SUMMARY_JSON),
    },
    "source_summary": {
        "path": display_path(SOURCE_SUMMARY_JSON),
        "sha256": "sha256:" + sha256_file(SOURCE_SUMMARY_JSON),
        "schema_version": summary["schema_version"],
    },
    "raw_evidence_files": raw_evidence_files,
    "selected_tests": selected_tests,
    "task_proof_count": len(task_proofs),
    "before_failure_count": before_failure_count,
    "after_test_count": after_test_count,
    "target_diff_count": diff_count,
    "labels": labels,
    "final_claims": final_claims,
    "source": summary["source"],
    "task_source_manifest": summary["task_source_manifest"],
    "external_source_heldout": True,
    "heldout_from_autonomous_gate": True,
    "independent_external_benchmark": False,
    "not_proof": not_proof,
}

PACKET_JSON.parent.mkdir(parents=True, exist_ok=True)
PACKET_JSON.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(f"heldout-reproduction-packet: packet={display_path(PACKET_JSON)}")
print(f"heldout-reproduction-packet: source-summary={display_path(SOURCE_SUMMARY_JSON)}")
print(f"heldout-reproduction-packet: task-proof-count={len(task_proofs)}")
print("heldout-reproduction-packet: PASS")
print(
    "heldout-reproduction-packet: "
    "not-proof=independent external benchmark standing; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "GitHub Actions artifact zip contents"
)
PY
