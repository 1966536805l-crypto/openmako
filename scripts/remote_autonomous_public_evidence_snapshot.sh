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
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=False)
remote_sha = sys.argv[2]
repo = sys.argv[3]
branch = sys.argv[4]
summary_path = root / "autonomous" / remote_sha / "last_summary.json"
latest_path = root / "autonomous" / "latest.json"
mirror_path = root / "autonomous" / remote_sha / "public_mirror" / "manifest.json"


def fail(reason: str, detail: str = "") -> None:
    print(f"remote-autonomous-public-evidence-snapshot: repo={repo}")
    print(f"remote-autonomous-public-evidence-snapshot: branch={branch}")
    print(f"remote-autonomous-public-evidence-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-autonomous-public-evidence-snapshot: unavailable={reason}")
    if detail:
        print(f"remote-autonomous-public-evidence-snapshot: detail={detail}")
    print(
        "remote-autonomous-public-evidence-snapshot: "
        "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; external review; endorsement; "
        "stars; reposts; native live autonomy; broad unknown-repository repair; "
        "external benchmark standing; independent external held-out benchmark"
    )
    raise SystemExit(1)


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def verify_public_mirror() -> dict:
    if not mirror_path.is_file():
        fail("autonomous_public_mirror_manifest_missing", str(mirror_path.relative_to(root)))
    try:
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail("autonomous_public_mirror_manifest_invalid_json", str(exc))
    if mirror.get("schema_version") != "autonomous-public-evidence-artifact-mirror/v0.1":
        fail("autonomous_public_mirror_schema_mismatch")
    if mirror.get("status") != "passed":
        fail("autonomous_public_mirror_status_mismatch")
    if mirror.get("git_commit") != remote_sha:
        fail("autonomous_public_mirror_commit_mismatch")
    if mirror.get("mirror_scope") != "github-actions-upload-directory-content":
        fail("autonomous_public_mirror_scope_mismatch")
    files = mirror.get("files")
    if not isinstance(files, dict) or not files:
        fail("autonomous_public_mirror_files_malformed")
    for required in ("last_summary.json", "task_source_provenance_manifest.json"):
        if required not in files:
            fail("autonomous_public_mirror_required_file_missing", required)
    pytest_logs = [name for name in files if name.startswith("pytest_logs/") and name.endswith(".log")]
    if len(pytest_logs) < 3:
        fail("autonomous_public_mirror_pytest_logs_missing")
    if mirror.get("file_count") != len(files):
        fail("autonomous_public_mirror_file_count_mismatch")
    archive_relative = mirror.get("archive_path")
    if archive_relative != "public_mirror/autonomous-learning-gate-public-mirror.zip":
        fail("autonomous_public_mirror_archive_path_mismatch")
    archive_path = mirror_path.parent.parent / archive_relative
    if not archive_path.is_file():
        fail("autonomous_public_mirror_archive_missing", str(archive_relative))
    archive_sha256 = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if mirror.get("archive_sha256") != archive_sha256:
        fail("autonomous_public_mirror_archive_digest_mismatch")
    meta = mirror.get("github_actions_artifact")
    if not isinstance(meta, dict):
        fail("autonomous_public_mirror_artifact_metadata_malformed")
    if meta.get("name") != "autonomous-learning-gate-summary":
        fail("autonomous_public_mirror_artifact_name_mismatch")
    if not str(meta.get("run_id") or "").isdigit():
        fail("autonomous_public_mirror_artifact_run_id_malformed")
    if not str(meta.get("run_attempt") or "").isdigit():
        fail("autonomous_public_mirror_artifact_run_attempt_malformed")
    if not str(meta.get("artifact_id") or "").isdigit():
        fail("autonomous_public_mirror_artifact_id_malformed")
    if not is_sha256_digest(meta.get("artifact_digest")):
        fail("autonomous_public_mirror_artifact_digest_missing_or_malformed")
    artifact_url = meta.get("artifact_url")
    if not isinstance(artifact_url, str) or not artifact_url.startswith("https://"):
        fail("autonomous_public_mirror_artifact_url_malformed")
    not_proof = mirror.get("not_proof")
    if (
        not isinstance(not_proof, list)
        or "GitHub Actions API artifact zip endpoint byte-for-byte archive" not in not_proof
        or "independent external held-out benchmark" not in not_proof
    ):
        fail("autonomous_public_mirror_boundary_mismatch")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = sorted(name for name in archive.namelist() if not name.endswith("/"))
            if names != sorted(files):
                fail("autonomous_public_mirror_archive_file_list_mismatch")
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    fail("autonomous_public_mirror_archive_unsafe_path", name)
                digest = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
                if files.get(name) != digest:
                    fail("autonomous_public_mirror_archive_file_digest_mismatch", name)
    except zipfile.BadZipFile as exc:
        fail("autonomous_public_mirror_archive_bad_zip", str(exc))
    return mirror


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
mirror = verify_public_mirror()
mirror_meta = mirror["github_actions_artifact"]

print(f"remote-autonomous-public-evidence-snapshot: repo={repo}")
print(f"remote-autonomous-public-evidence-snapshot: branch={branch}")
print(f"remote-autonomous-public-evidence-snapshot: remote-main-sha={remote_sha}")
print(f"remote-autonomous-public-evidence-snapshot: summary=autonomous/{remote_sha}/last_summary.json")
print(f"remote-autonomous-public-evidence-snapshot: status={summary['status']}")
print("remote-autonomous-public-evidence-snapshot: public-mirror-zip=present")
print("remote-autonomous-public-evidence-snapshot: public-mirror-scope=github-actions-upload-directory-content")
print(f"remote-autonomous-public-evidence-snapshot: public-mirror-file-count={mirror['file_count']}")
print(f"remote-autonomous-public-evidence-snapshot: artifact-id={mirror_meta['artifact_id']}")
print(f"remote-autonomous-public-evidence-snapshot: artifact-digest={mirror_meta['artifact_digest']}")
print(f"remote-autonomous-public-evidence-snapshot: selected-test-count={len(all_selected)}")
print(f"remote-autonomous-public-evidence-snapshot: upstream-task-proof-count={len(upstream_proofs)}")
print(f"remote-autonomous-public-evidence-snapshot: cross-upstream-task-proof-count={len(cross_proofs)}")
print(f"remote-autonomous-public-evidence-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-autonomous-public-evidence-snapshot: "
    "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "external benchmark standing; independent external held-out benchmark"
)
print("remote-autonomous-public-evidence-snapshot: PASS")
PY
