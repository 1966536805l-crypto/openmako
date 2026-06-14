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
import sys
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
required_not_proof = {
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "external review",
    "independent external held-out benchmark",
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

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
git_commit = sys.argv[2]
latest = {
    "schema_version": "openmako-public-evidence-index/v0.1",
    "latest_autonomous_commit": git_commit,
    "autonomous_summary": f"autonomous/{git_commit}/last_summary.json",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "not_proof": [
        "GitHub Actions artifact zip contents",
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
        "independent external held-out benchmark",
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
