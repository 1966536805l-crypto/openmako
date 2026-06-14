#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_PATH="${OPENMAKO_REPRO_LOG:?set OPENMAKO_REPRO_LOG to the fresh-clone reproduction log}"
GIT_COMMIT="${OPENMAKO_REPRO_REF:-$(git rev-parse HEAD)}"
REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-origin}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"

if [ ! -f "$LOG_PATH" ]; then
  echo "publish-fresh-clone-reproduction-branch: missing log=$LOG_PATH" >&2
  exit 2
fi

python3 - "$LOG_PATH" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

log_path = Path(sys.argv[1])
git_commit = sys.argv[2]
text = log_path.read_text(encoding="utf-8", errors="replace")
required = [
    f"fresh-clone-reproduction: requested-ref={git_commit}",
    f"fresh-clone-reproduction: checkout-sha={git_commit}",
    "fresh-clone-reproduction: install=PASS",
    "fresh-clone-reproduction: release-readiness=PASS",
    "fresh-clone-reproduction: public-review=PASS",
    "fresh-clone-reproduction: remote-public-evidence=PASS",
    "fresh-clone-reproduction: remote-autonomous-public-evidence=PASS",
    "fresh-clone-reproduction: PASS",
    "GitHub Actions artifact zip contents",
]
missing = [marker for marker in required if marker not in text]
if missing:
    raise SystemExit(
        "publish-fresh-clone-reproduction-branch: missing log markers="
        + ",".join(missing)
    )
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

mkdir -p "$evidence_dir/reproductions/$GIT_COMMIT"
cp "$LOG_PATH" "$evidence_dir/reproductions/$GIT_COMMIT/fresh_clone.log"

python3 - "$evidence_dir" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
git_commit = sys.argv[2]
record_dir = root / "reproductions" / git_commit
log_path = record_dir / "fresh_clone.log"
log_text = log_path.read_text(encoding="utf-8", errors="replace")
line_count = len(log_text.splitlines())
log_sha256 = "sha256:" + hashlib.sha256(log_path.read_bytes()).hexdigest()
markers = {
    "requested_ref": f"fresh-clone-reproduction: requested-ref={git_commit}",
    "checkout_sha": f"fresh-clone-reproduction: checkout-sha={git_commit}",
    "install": "fresh-clone-reproduction: install=PASS",
    "release_readiness": "fresh-clone-reproduction: release-readiness=PASS",
    "public_review": "fresh-clone-reproduction: public-review=PASS",
    "remote_public_evidence": "fresh-clone-reproduction: remote-public-evidence=PASS",
    "remote_autonomous_public_evidence": (
        "fresh-clone-reproduction: remote-autonomous-public-evidence=PASS"
    ),
    "fresh_clone": "fresh-clone-reproduction: PASS",
}
missing = [name for name, marker in markers.items() if marker not in log_text]
if missing:
    raise SystemExit(
        "publish-fresh-clone-reproduction-branch: missing record markers="
        + ",".join(missing)
    )
summary = {
    "schema_version": "fresh-clone-reproduction-public-evidence/v0.1",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit,
    "log_path": "fresh_clone.log",
    "log_sha256": log_sha256,
    "log_line_count": line_count,
    "markers": markers,
    "not_proof": [
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "independent external benchmark standing",
        "GitHub Actions artifact zip contents",
        "native live autonomy",
        "broad unknown-repository repair",
    ],
}
(record_dir / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
latest = {
    "schema_version": "openmako-fresh-clone-reproduction-index/v0.1",
    "latest_reproduction_commit": git_commit,
    "summary": f"reproductions/{git_commit}/summary.json",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "not_proof": summary["not_proof"],
}
(root / "reproductions").mkdir(parents=True, exist_ok=True)
(root / "reproductions" / "latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

git -C "$evidence_dir" config user.email "${OPENMAKO_PUBLIC_EVIDENCE_GIT_EMAIL:-openmako-evidence-bot@example.invalid}"
git -C "$evidence_dir" config user.name "${OPENMAKO_PUBLIC_EVIDENCE_GIT_NAME:-OpenMako Evidence Bot}"
git -C "$evidence_dir" add reproductions
if git -C "$evidence_dir" diff --cached --quiet; then
  echo "publish-fresh-clone-reproduction-branch: no changes"
else
  git -C "$evidence_dir" commit -q -m "Publish fresh clone reproduction for $GIT_COMMIT"
  git -C "$evidence_dir" push "$push_remote" "HEAD:$BRANCH" >/dev/null
  echo "publish-fresh-clone-reproduction-branch: pushed branch=$BRANCH commit=$GIT_COMMIT"
fi

echo "publish-fresh-clone-reproduction-branch: PASS"
