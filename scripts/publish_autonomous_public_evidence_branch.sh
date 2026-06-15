#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SUMMARY_DIR="${OPENMAKO_AUTONOMOUS_LEARNING_GATE_DIR:-$ROOT_DIR/.quantagent/autonomous_learning_gate}"
REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-origin}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"
GIT_COMMIT="$(git rev-parse HEAD)"

if [ ! -f "$SUMMARY_DIR/last_summary.json" ]; then
  echo "publish-autonomous-public-evidence-branch: missing $SUMMARY_DIR/last_summary.json" >&2
  exit 2
fi

python3 - "$SUMMARY_DIR" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

summary_dir = Path(sys.argv[1]).resolve(strict=False)
git_commit = sys.argv[2]
summary_path = summary_dir / "last_summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
if summary.get("schema_version") != "autonomous-learning-gate/v0.1":
    raise SystemExit("publish-autonomous-public-evidence-branch: summary schema_version mismatch")
if summary.get("status") != "passed":
    raise SystemExit("publish-autonomous-public-evidence-branch: summary status is not passed")
invocation = summary.get("invocation")
if not isinstance(invocation, dict) or invocation.get("git_commit") != git_commit:
    raise SystemExit("publish-autonomous-public-evidence-branch: summary git_commit does not match HEAD")
segments = summary.get("segments")
expected_segments = {
    "stage1_trajectory_reuse_matrix": "passed",
    "upstream_hidden_pack_reuse": "passed",
    "cross_upstream_no_seed_reuse": "passed",
}
if not isinstance(segments, dict) or any(segments.get(key) != value for key, value in expected_segments.items()):
    raise SystemExit("publish-autonomous-public-evidence-branch: summary segments are not all passed")
manifest = summary.get("task_source_manifest")
if not isinstance(manifest, dict):
    raise SystemExit("publish-autonomous-public-evidence-branch: task_source_manifest missing")
manifest_artifact = manifest.get("artifact_path")
manifest_digest = manifest.get("sha256")
if not isinstance(manifest_artifact, str) or not isinstance(manifest_digest, str):
    raise SystemExit("publish-autonomous-public-evidence-branch: task source manifest contract malformed")
manifest_path = summary_dir / Path(manifest_artifact).name
if not manifest_path.is_file():
    raise SystemExit("publish-autonomous-public-evidence-branch: task source manifest artifact missing")
actual_manifest_digest = hashlib.sha256(manifest_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
if actual_manifest_digest != manifest_digest:
    raise SystemExit("publish-autonomous-public-evidence-branch: task source manifest digest mismatch")
tests = summary.get("tests")
if not isinstance(tests, dict):
    raise SystemExit("publish-autonomous-public-evidence-branch: tests contract missing")
for segment in expected_segments:
    entry = tests.get(segment)
    if not isinstance(entry, dict):
        raise SystemExit(f"publish-autonomous-public-evidence-branch: missing test segment {segment}")
    observed = entry.get("observed_pytest")
    if not isinstance(observed, dict) or observed.get("exit_code") != 0:
        raise SystemExit(f"publish-autonomous-public-evidence-branch: test segment did not pass: {segment}")
    log_path = summary_dir / "pytest_logs" / f"{segment}.log"
    if not log_path.is_file():
        raise SystemExit(f"publish-autonomous-public-evidence-branch: pytest log missing: {segment}")
    log_tail = entry.get("log_tail")
    if not isinstance(log_tail, list) or not log_tail:
        raise SystemExit(f"publish-autonomous-public-evidence-branch: pytest log_tail missing: {segment}")
    log_lines = log_path.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
    if len(log_lines) < len(log_tail) or log_lines[-len(log_tail):] != log_tail:
        raise SystemExit(f"publish-autonomous-public-evidence-branch: pytest log_tail mismatch: {segment}")
task_proofs = summary.get("task_proofs")
if not isinstance(task_proofs, dict):
    raise SystemExit("publish-autonomous-public-evidence-branch: task_proofs missing")
if len(task_proofs.get("upstream_hidden_pack_reuse") or []) < 1:
    raise SystemExit("publish-autonomous-public-evidence-branch: upstream task proof missing")
if len(task_proofs.get("cross_upstream_no_seed_reuse") or []) < 4:
    raise SystemExit("publish-autonomous-public-evidence-branch: cross-upstream task proofs missing")
linked = summary.get("linked_external_heldout")
if not isinstance(linked, dict):
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout evidence missing")
if linked.get("schema_version") != "autonomous-linked-external-heldout/v0.1":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout schema mismatch")
if linked.get("status") != "passed":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout is not passed")
if linked.get("summary_path") != "linked_external_heldout/last_summary.json":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout summary path mismatch")
linked_summary_path = summary_dir / "linked_external_heldout" / "last_summary.json"
if not linked_summary_path.is_file():
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout summary missing")
linked_summary_text = linked_summary_path.read_text(encoding="utf-8")
if hashlib.sha256(linked_summary_text.encode("utf-8")).hexdigest() != linked.get("summary_sha256"):
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout summary digest mismatch")
linked_summary = json.loads(linked_summary_text)
if linked_summary.get("schema_version") != "external-heldout-benchmark-gate/v0.1":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout summary schema mismatch")
if linked_summary.get("status") != "passed":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout summary is not passed")
if linked_summary.get("external_source_heldout") is not True or linked.get("external_source_heldout") is not True:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout flag mismatch")
if linked_summary.get("heldout_from_autonomous_gate") is not True or linked.get("heldout_from_autonomous_gate") is not True:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout autonomy boundary mismatch")
if linked_summary.get("independent_external_benchmark") is not False or linked.get("independent_external_benchmark") is not False:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout benchmark boundary mismatch")
if linked.get("task_proof_count") != 2 or len(linked_summary.get("task_proofs") or []) != 2:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked external-heldout task proof count mismatch")
independent = summary.get("linked_independent_external_heldout")
if not isinstance(independent, dict):
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout evidence missing")
if independent.get("schema_version") != "autonomous-linked-independent-external-heldout/v0.1":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout schema mismatch")
if independent.get("status") != "passed":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout is not passed")
if independent.get("summary_path") != "linked_independent_external_heldout/last_summary.json":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout summary path mismatch")
independent_summary_path = summary_dir / "linked_independent_external_heldout" / "last_summary.json"
if not independent_summary_path.is_file():
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout summary missing")
independent_summary_text = independent_summary_path.read_text(encoding="utf-8")
if hashlib.sha256(independent_summary_text.encode("utf-8")).hexdigest() != independent.get("summary_sha256"):
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout summary digest mismatch")
independent_summary = json.loads(independent_summary_text)
if independent_summary.get("schema_version") != "independent-external-heldout-benchmark-gate/v0.1":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout summary schema mismatch")
if independent_summary.get("status") != "passed":
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout summary is not passed")
if independent_summary.get("independent_external_heldout_benchmark") is not True or independent.get("independent_external_heldout_benchmark") is not True:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout flag mismatch")
if independent_summary.get("third_party_benchmark_standing") is not False or independent.get("third_party_benchmark_standing") is not False:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout standing boundary mismatch")
if independent.get("task_proof_count") != 2 or len(independent_summary.get("case_results") or []) != 2:
    raise SystemExit("publish-autonomous-public-evidence-branch: linked independent external-heldout task proof count mismatch")
required_not_proof = {
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "third-party benchmark standing",
    "external review",
}
if not required_not_proof.issubset(set(summary.get("not_proof") or [])):
    raise SystemExit("publish-autonomous-public-evidence-branch: not_proof boundary missing")
PY

tmp_dir="$(mktemp -d)"
worktree_dir=""
temp_branch=""
fetch_ref=""
cleanup() {
  if [ -n "$worktree_dir" ]; then
    git -C "$ROOT_DIR" worktree remove --force "$worktree_dir" >/dev/null 2>&1 || true
  fi
  if [ -n "$temp_branch" ]; then
    git -C "$ROOT_DIR" branch -D "$temp_branch" >/dev/null 2>&1 || true
  fi
  if [ -n "$fetch_ref" ]; then
    git -C "$ROOT_DIR" update-ref -d "$fetch_ref" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

push_remote="origin"
if git remote get-url "$REMOTE" >/dev/null 2>&1; then
  push_remote="$REMOTE"
  worktree_dir="$tmp_dir/branch"
  fetch_ref="refs/tmp/openmako-public-evidence/$BRANCH"
  if git fetch --depth 1 "$REMOTE" "refs/heads/$BRANCH:$fetch_ref" >/dev/null 2>&1; then
    git worktree add --detach "$worktree_dir" "$fetch_ref" >/dev/null
  else
    git worktree add --detach "$worktree_dir" HEAD >/dev/null
    temp_branch="openmako-public-evidence-$GIT_COMMIT"
    git -C "$worktree_dir" checkout --orphan "$temp_branch" >/dev/null 2>&1
    git -C "$worktree_dir" rm -rf --ignore-unmatch . >/dev/null 2>&1 || true
  fi
  evidence_dir="$worktree_dir"
else
  remote_url="$REMOTE"
  mkdir -p "$tmp_dir/branch"
  evidence_dir="$tmp_dir/branch"
  git -C "$evidence_dir" init -q
  git -C "$evidence_dir" checkout --orphan "$BRANCH" >/dev/null 2>&1
  git -C "$evidence_dir" remote add origin "$remote_url"
fi

mkdir -p "$evidence_dir/autonomous/$GIT_COMMIT"
rm -rf "$evidence_dir/autonomous/$GIT_COMMIT"
mkdir -p "$evidence_dir/autonomous/$GIT_COMMIT"
cp -R "$SUMMARY_DIR"/. "$evidence_dir/autonomous/$GIT_COMMIT/"

python3 - "$evidence_dir" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
git_commit = sys.argv[2]
autonomous_dir = root / "autonomous" / git_commit
mirror_dir = autonomous_dir / "public_mirror"
mirror_dir.mkdir(parents=True, exist_ok=True)
archive_path = mirror_dir / "autonomous-learning-gate-public-mirror.zip"
manifest_path = mirror_dir / "manifest.json"

files: dict[str, str] = {}
for path in sorted(autonomous_dir.rglob("*")):
    if not path.is_file():
        continue
    rel = str(path.relative_to(autonomous_dir))
    if rel.startswith("public_mirror/"):
        continue
    files[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
for required in ("last_summary.json", "task_source_provenance_manifest.json"):
    if required not in files:
        raise SystemExit(f"publish-autonomous-public-evidence-branch: mirror missing required output {required}")
if "linked_external_heldout/last_summary.json" not in files:
    raise SystemExit("publish-autonomous-public-evidence-branch: mirror missing linked external-heldout summary")
if "linked_independent_external_heldout/last_summary.json" not in files:
    raise SystemExit("publish-autonomous-public-evidence-branch: mirror missing linked independent external-heldout summary")
pytest_logs = [name for name in files if name.startswith("pytest_logs/") and name.endswith(".log")]
if len(pytest_logs) < 3:
    raise SystemExit("publish-autonomous-public-evidence-branch: mirror missing pytest logs")

with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for rel in sorted(files):
        source = autonomous_dir / rel
        info = zipfile.ZipInfo(rel)
        info.date_time = (1980, 1, 1, 0, 0, 0)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, source.read_bytes())
archive_sha256 = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()

def required_env(name: str, label: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"publish-autonomous-public-evidence-branch: autonomous artifact {label} missing")
    return value

artifact_name = required_env("OPENMAKO_AUTONOMOUS_ARTIFACT_NAME", "name")
run_id = required_env("OPENMAKO_AUTONOMOUS_RUN_ID", "run id")
run_attempt = required_env("OPENMAKO_AUTONOMOUS_RUN_ATTEMPT", "run attempt")
artifact_id = required_env("OPENMAKO_AUTONOMOUS_ARTIFACT_ID", "id")
artifact_digest = required_env("OPENMAKO_AUTONOMOUS_ARTIFACT_DIGEST", "digest")
artifact_url = required_env("OPENMAKO_AUTONOMOUS_ARTIFACT_URL", "url")
if artifact_name != "autonomous-learning-gate-summary":
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact name mismatch")
if not run_id.isdigit():
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact run id malformed")
if not run_attempt.isdigit():
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact run attempt malformed")
if not artifact_id.isdigit():
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact id malformed")
artifact_digest = artifact_digest.lower()
if re.fullmatch(r"[0-9a-f]{64}", artifact_digest):
    artifact_digest = "sha256:" + artifact_digest
if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest):
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact digest missing/malformed")
if not artifact_url.startswith("https://"):
    raise SystemExit("publish-autonomous-public-evidence-branch: autonomous artifact url malformed")

manifest = {
    "schema_version": "autonomous-public-evidence-artifact-mirror/v0.1",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit,
    "mirror_scope": "github-actions-upload-directory-content",
    "source_summary": "last_summary.json",
    "archive_path": "public_mirror/autonomous-learning-gate-public-mirror.zip",
    "archive_sha256": archive_sha256,
    "file_count": len(files),
    "files": files,
    "github_actions_artifact": {
        "name": artifact_name,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifact_id": artifact_id,
        "artifact_digest": artifact_digest,
        "artifact_url": artifact_url,
    },
    "not_proof": [
        "GitHub Actions API artifact zip endpoint byte-for-byte archive",
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
        "third-party benchmark standing",
    ],
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

latest = {
    "schema_version": "openmako-public-evidence-index/v0.1",
    "latest_autonomous_commit": git_commit,
    "autonomous_summary": f"autonomous/{git_commit}/last_summary.json",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "not_proof": [
        "GitHub Actions API artifact zip endpoint byte-for-byte archive",
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
        "third-party benchmark standing",
    ],
}
(root / "autonomous").mkdir(parents=True, exist_ok=True)
(root / "autonomous" / "latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

git -C "$evidence_dir" config user.email "${OPENMAKO_PUBLIC_EVIDENCE_GIT_EMAIL:-openmako-evidence-bot@example.invalid}"
git -C "$evidence_dir" config user.name "${OPENMAKO_PUBLIC_EVIDENCE_GIT_NAME:-OpenMako Evidence Bot}"
git -C "$evidence_dir" add autonomous
if git -C "$evidence_dir" diff --cached --quiet; then
  echo "publish-autonomous-public-evidence-branch: no changes"
else
  git -C "$evidence_dir" commit -q -m "Publish autonomous public evidence for $GIT_COMMIT"
  git -C "$evidence_dir" push "$push_remote" "HEAD:$BRANCH" >/dev/null
  echo "publish-autonomous-public-evidence-branch: pushed branch=$BRANCH commit=$GIT_COMMIT"
fi

echo "publish-autonomous-public-evidence-branch: PASS"
