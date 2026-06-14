#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_REMOTE="${OPENMAKO_REMOTE:-openmako}"
EVIDENCE_REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-https://github.com/1966536805l-crypto/openmako.git}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$SOURCE_REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-public-evidence-snapshot: could not resolve ${SOURCE_REMOTE}/main" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if ! git clone --depth 1 --branch "$BRANCH" "$EVIDENCE_REMOTE" "$tmp_dir/evidence" >/dev/null 2>&1; then
  echo "remote-public-evidence-snapshot: repo=$EVIDENCE_REMOTE"
  echo "remote-public-evidence-snapshot: branch=$BRANCH"
  echo "remote-public-evidence-snapshot: remote-main-sha=$remote_sha"
  echo "remote-public-evidence-snapshot: unavailable=public_evidence_branch_missing"
  echo "remote-public-evidence-snapshot: not-proof=GitHub Actions artifact zip contents; external review; endorsement; stars; reposts; native live autonomy; broad unknown-repository repair; external benchmark standing"
  exit 2
fi

python3 - "$tmp_dir/evidence" "$remote_sha" "$EVIDENCE_REMOTE" "$BRANCH" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=False)
remote_sha = sys.argv[2]
repo = sys.argv[3]
branch = sys.argv[4]
summary_path = root / "focused" / remote_sha / "summary.json"
latest_path = root / "focused" / "latest.json"

def fail(reason: str, detail: str = "") -> None:
    print(f"remote-public-evidence-snapshot: repo={repo}")
    print(f"remote-public-evidence-snapshot: branch={branch}")
    print(f"remote-public-evidence-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-public-evidence-snapshot: unavailable={reason}")
    if detail:
        print(f"remote-public-evidence-snapshot: detail={detail}")
    print(
        "remote-public-evidence-snapshot: "
        "not-proof=GitHub Actions artifact zip contents; external review; endorsement; "
        "stars; reposts; native live autonomy; broad unknown-repository repair; "
        "external benchmark standing"
    )
    raise SystemExit(1)

if not summary_path.is_file():
    fail("focused_summary_missing", str(summary_path.relative_to(root)))
try:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("focused_summary_invalid_json", str(exc))
if summary.get("schema_version") != "public-review-gate-artifact/v0.1":
    fail("focused_summary_schema_mismatch")
if summary.get("status") != "passed":
    fail("focused_summary_not_passed")
invocation = summary.get("invocation")
if not isinstance(invocation, dict) or invocation.get("git_commit") != remote_sha:
    fail("focused_summary_commit_mismatch")
required_outputs = summary.get("required_outputs")
output_hashes = summary.get("output_sha256")
if not isinstance(required_outputs, list) or not isinstance(output_hashes, dict):
    fail("focused_summary_output_contract_malformed")
missing_outputs: list[str] = []
for relative in required_outputs:
    if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
        fail("focused_summary_unsafe_output_path", repr(relative))
    path = summary_path.parent / relative
    if not path.is_file():
        missing_outputs.append(relative)
        continue
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if output_hashes.get(relative) != digest:
        fail("focused_summary_output_digest_mismatch", relative)
if missing_outputs:
    fail("focused_summary_required_outputs_missing", ",".join(missing_outputs))

packet_relative = "outputs/heldout_reproduction_packet/packet.json"
if packet_relative not in required_outputs:
    fail("heldout_reproduction_packet_not_required")
packet_path = summary_path.parent / packet_relative
try:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("heldout_reproduction_packet_invalid_json", str(exc))
if packet.get("schema_version") != "heldout-reproduction-packet/v0.1":
    fail("heldout_reproduction_packet_schema_mismatch")
if packet.get("status") != "passed":
    fail("heldout_reproduction_packet_not_passed")
packet_invocation = packet.get("invocation")
if not isinstance(packet_invocation, dict) or packet_invocation.get("git_commit") != remote_sha:
    fail("heldout_reproduction_packet_commit_mismatch")
if packet.get("external_source_heldout") is not True:
    fail("heldout_reproduction_packet_external_source_heldout_mismatch")
if packet.get("heldout_from_autonomous_gate") is not True:
    fail("heldout_reproduction_packet_autonomous_holdout_mismatch")
if packet.get("independent_external_benchmark") is not False:
    fail("heldout_reproduction_packet_independent_benchmark_boundary_mismatch")
if packet.get("task_proof_count") != 2:
    fail("heldout_reproduction_packet_task_proof_count_mismatch")
if packet.get("before_failure_count") != 2 or packet.get("after_test_count") != 2:
    fail("heldout_reproduction_packet_before_after_count_mismatch")
if packet.get("target_diff_count") != 2:
    fail("heldout_reproduction_packet_diff_count_mismatch")
labels = packet.get("labels")
if not isinstance(labels, dict) or sorted(labels.values()) != [
    "supported_repair_claim",
    "supported_repair_claim",
]:
    fail("heldout_reproduction_packet_labels_mismatch")
raw_evidence_files = packet.get("raw_evidence_files")
if not isinstance(raw_evidence_files, dict):
    fail("heldout_reproduction_packet_raw_evidence_malformed")
for expected_raw in (
    "outputs/external_heldout_benchmark_gate/last_summary.json",
    "outputs/external_heldout_benchmark_gate/pytest.log",
    "outputs/external_heldout_benchmark_gate/task_proofs/vendored_mcp_tool_name_validation_function_repair.json",
    "outputs/external_heldout_benchmark_gate/task_proofs/vendored_mcp_tool_name_wrapper_seed_repair.json",
):
    raw_path = summary_path.parent / expected_raw
    if not raw_path.is_file():
        fail("heldout_reproduction_packet_raw_evidence_missing", expected_raw)
    raw_digest = "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if raw_evidence_files.get(expected_raw) != raw_digest:
        fail("heldout_reproduction_packet_raw_evidence_digest_mismatch", expected_raw)
packet_not_proof = packet.get("not_proof")
if not isinstance(packet_not_proof, list) or "native live autonomy" not in packet_not_proof:
    fail("heldout_reproduction_packet_not_proof_boundary_mismatch")

mirror_manifest_path = summary_path.parent / "public_mirror" / "manifest.json"
try:
    mirror_manifest = json.loads(mirror_manifest_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("public_mirror_manifest_invalid_json", str(exc))
if mirror_manifest.get("schema_version") != "public-evidence-artifact-mirror/v0.1":
    fail("public_mirror_manifest_schema_mismatch")
if mirror_manifest.get("status") != "passed":
    fail("public_mirror_manifest_not_passed")
if mirror_manifest.get("git_commit") != remote_sha:
    fail("public_mirror_manifest_commit_mismatch")
archive_relative = mirror_manifest.get("archive_path")
if archive_relative != "public_mirror/focused-public-review-gate-public-mirror.zip":
    fail("public_mirror_archive_path_mismatch")
archive_path = summary_path.parent / archive_relative
if not archive_path.is_file():
    fail("public_mirror_archive_missing", str(archive_relative))
archive_sha256 = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
if mirror_manifest.get("archive_sha256") != archive_sha256:
    fail("public_mirror_archive_digest_mismatch")
mirror_files = mirror_manifest.get("files")
if not isinstance(mirror_files, dict) or not mirror_files:
    fail("public_mirror_files_malformed")
if mirror_manifest.get("file_count") != len(mirror_files):
    fail("public_mirror_file_count_mismatch")
for required in ("summary.json", "invocation.json", *required_outputs):
    if required not in mirror_files:
        fail("public_mirror_required_file_missing", required)
mirror_not_proof = mirror_manifest.get("not_proof")
if not isinstance(mirror_not_proof, list) or "GitHub Actions artifact zip contents" not in mirror_not_proof:
    fail("public_mirror_not_proof_boundary_mismatch")
try:
    with zipfile.ZipFile(archive_path) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        if names != sorted(mirror_files):
            fail("public_mirror_archive_file_list_mismatch")
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts:
                fail("public_mirror_archive_unsafe_path", name)
            digest = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
            if mirror_files.get(name) != digest:
                fail("public_mirror_archive_file_digest_mismatch", name)
except zipfile.BadZipFile as exc:
    fail("public_mirror_archive_invalid_zip", str(exc))

latest = {}
if latest_path.is_file():
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest.get("latest_focused_commit") != remote_sha:
        fail("latest_index_commit_mismatch")

print(f"remote-public-evidence-snapshot: repo={repo}")
print(f"remote-public-evidence-snapshot: branch={branch}")
print(f"remote-public-evidence-snapshot: remote-main-sha={remote_sha}")
print(f"remote-public-evidence-snapshot: summary=focused/{remote_sha}/summary.json")
print(f"remote-public-evidence-snapshot: status={summary['status']}")
print(f"remote-public-evidence-snapshot: required-output-count={len(required_outputs)}")
print("remote-public-evidence-snapshot: heldout-reproduction-packet=present")
print(f"remote-public-evidence-snapshot: heldout-task-proof-count={packet['task_proof_count']}")
print("remote-public-evidence-snapshot: public-mirror-zip=present")
print(f"remote-public-evidence-snapshot: public-mirror-file-count={mirror_manifest['file_count']}")
print(f"remote-public-evidence-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-public-evidence-snapshot: "
    "not-proof=GitHub Actions artifact zip contents; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "external benchmark standing"
)
print("remote-public-evidence-snapshot: PASS")
PY
