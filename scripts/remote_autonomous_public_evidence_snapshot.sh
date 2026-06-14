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
  echo "remote-autonomous-public-evidence-snapshot: could not resolve ${SOURCE_REMOTE}/main" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if ! git clone --depth 1 --branch "$BRANCH" "$EVIDENCE_REMOTE" "$tmp_dir/evidence" >/dev/null 2>&1; then
  echo "remote-autonomous-public-evidence-snapshot: repo=$EVIDENCE_REMOTE"
  echo "remote-autonomous-public-evidence-snapshot: branch=$BRANCH"
  echo "remote-autonomous-public-evidence-snapshot: remote-main-sha=$remote_sha"
  echo "remote-autonomous-public-evidence-snapshot: unavailable=public_evidence_branch_missing"
  echo "remote-autonomous-public-evidence-snapshot: not-proof=GitHub Actions artifact zip contents; external review; endorsement; stars; reposts; native live autonomy; broad unknown-repository repair; external benchmark standing; independent external held-out benchmark"
  exit 2
fi

python3 - "$tmp_dir/evidence" "$remote_sha" "$EVIDENCE_REMOTE" "$BRANCH" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=False)
remote_sha = sys.argv[2]
repo = sys.argv[3]
branch = sys.argv[4]
summary_path = root / "autonomous" / remote_sha / "last_summary.json"
latest_path = root / "autonomous" / "latest.json"


def fail(reason: str, detail: str = "") -> None:
    print(f"remote-autonomous-public-evidence-snapshot: repo={repo}")
    print(f"remote-autonomous-public-evidence-snapshot: branch={branch}")
    print(f"remote-autonomous-public-evidence-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-autonomous-public-evidence-snapshot: unavailable={reason}")
    if detail:
        print(f"remote-autonomous-public-evidence-snapshot: detail={detail}")
    print(
        "remote-autonomous-public-evidence-snapshot: "
        "not-proof=GitHub Actions artifact zip contents; external review; endorsement; "
        "stars; reposts; native live autonomy; broad unknown-repository repair; "
        "external benchmark standing; independent external held-out benchmark"
    )
    raise SystemExit(1)


if not summary_path.is_file():
    fail("autonomous_summary_missing", str(summary_path.relative_to(root)))
try:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("autonomous_summary_invalid_json", str(exc))
if summary.get("schema_version") != "autonomous-learning-gate/v0.1":
    fail("autonomous_summary_schema_mismatch")
if summary.get("status") != "passed":
    fail("autonomous_summary_not_passed")
invocation = summary.get("invocation")
if not isinstance(invocation, dict) or invocation.get("git_commit") != remote_sha:
    fail("autonomous_summary_commit_mismatch")
segments = summary.get("segments")
expected_segments = {
    "stage1_trajectory_reuse_matrix": "passed",
    "upstream_hidden_pack_reuse": "passed",
    "cross_upstream_no_seed_reuse": "passed",
}
if not isinstance(segments, dict):
    fail("autonomous_summary_segments_malformed")
for segment, expected in expected_segments.items():
    if segments.get(segment) != expected:
        fail("autonomous_summary_segment_not_passed", segment)
tests = summary.get("tests")
if not isinstance(tests, dict):
    fail("autonomous_summary_tests_malformed")
manifest = summary.get("task_source_manifest")
if not isinstance(manifest, dict):
    fail("autonomous_summary_manifest_malformed")
manifest_artifact = manifest.get("artifact_path")
manifest_digest = manifest.get("sha256")
if not isinstance(manifest_artifact, str) or not isinstance(manifest_digest, str):
    fail("autonomous_summary_manifest_contract_malformed")
manifest_matches = [
    path
    for path in summary_path.parent.rglob("task_source_provenance_manifest.json")
    if path.is_file()
]
if len(manifest_matches) != 1:
    fail("autonomous_task_source_manifest_missing_or_ambiguous", str(len(manifest_matches)))
manifest_text = manifest_matches[0].read_text(encoding="utf-8")
if hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() != manifest_digest:
    fail("autonomous_task_source_manifest_digest_mismatch")
try:
    manifest_payload = json.loads(manifest_text)
except Exception as exc:
    fail("autonomous_task_source_manifest_invalid_json", str(exc))
if summary.get("task_source_provenance") != manifest_payload:
    fail("autonomous_task_source_manifest_payload_mismatch")
provenance = summary.get("task_source_provenance")
if not isinstance(provenance, dict):
    fail("autonomous_summary_provenance_malformed")
if provenance.get("independence_claim") != "repo-authored-regression-pack":
    fail("autonomous_summary_independence_claim_mismatch")
if provenance.get("external_heldout") is not False:
    fail("autonomous_summary_external_heldout_mismatch")
node_id_re = re.compile(r"^tests/[A-Za-z0-9_./]+\.py::[A-Za-z_][A-Za-z0-9_]*::test_[A-Za-z0-9_]+$")
all_selected: set[str] = set()
for segment in expected_segments:
    entry = tests.get(segment)
    if not isinstance(entry, dict):
        fail("autonomous_summary_test_segment_missing", segment)
    selected = entry.get("selected")
    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) != len(set(selected))
        or any(not isinstance(item, str) or not node_id_re.fullmatch(item) for item in selected)
    ):
        fail("autonomous_summary_selected_tests_invalid", segment)
    overlap = all_selected.intersection(selected)
    if overlap:
        fail("autonomous_summary_selected_tests_overlap", ",".join(sorted(overlap)))
    all_selected.update(selected)
    observed = entry.get("observed_pytest")
    if not isinstance(observed, dict) or observed.get("exit_code") != 0 or observed.get("passed") != len(selected):
        fail("autonomous_summary_observed_pytest_mismatch", segment)
    log_tail = entry.get("log_tail")
    if not isinstance(log_tail, list) or not log_tail:
        fail("autonomous_summary_log_tail_missing", segment)
    log_path = summary_path.parent / "pytest_logs" / f"{segment}.log"
    if not log_path.is_file():
        fail("autonomous_pytest_log_missing", segment)
    log_lines = log_path.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
    if len(log_lines) < len(log_tail) or log_lines[-len(log_tail):] != log_tail:
        fail("autonomous_pytest_log_tail_mismatch", segment)
task_proofs = summary.get("task_proofs")
if not isinstance(task_proofs, dict):
    fail("autonomous_task_proofs_malformed")
upstream_proofs = task_proofs.get("upstream_hidden_pack_reuse")
cross_proofs = task_proofs.get("cross_upstream_no_seed_reuse")
if not isinstance(upstream_proofs, list) or len(upstream_proofs) < 1:
    fail("autonomous_upstream_task_proof_missing")
if not isinstance(cross_proofs, list) or len(cross_proofs) < 4:
    fail("autonomous_cross_upstream_task_proofs_missing")
required_not_proof = {
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "remote CI proof",
    "external review",
    "independent external held-out benchmark",
    "endorsement",
    "stars",
    "reposts",
}
if not required_not_proof.issubset(set(summary.get("not_proof") or [])):
    fail("autonomous_not_proof_boundary_missing")
latest = {}
if latest_path.is_file():
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest.get("latest_autonomous_commit") != remote_sha:
        fail("latest_index_commit_mismatch")

print(f"remote-autonomous-public-evidence-snapshot: repo={repo}")
print(f"remote-autonomous-public-evidence-snapshot: branch={branch}")
print(f"remote-autonomous-public-evidence-snapshot: remote-main-sha={remote_sha}")
print(f"remote-autonomous-public-evidence-snapshot: summary=autonomous/{remote_sha}/last_summary.json")
print(f"remote-autonomous-public-evidence-snapshot: status={summary['status']}")
print(f"remote-autonomous-public-evidence-snapshot: selected-test-count={len(all_selected)}")
print(f"remote-autonomous-public-evidence-snapshot: upstream-task-proof-count={len(upstream_proofs)}")
print(f"remote-autonomous-public-evidence-snapshot: cross-upstream-task-proof-count={len(cross_proofs)}")
print(f"remote-autonomous-public-evidence-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-autonomous-public-evidence-snapshot: "
    "not-proof=GitHub Actions artifact zip contents; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "external benchmark standing; independent external held-out benchmark"
)
print("remote-autonomous-public-evidence-snapshot: PASS")
PY
