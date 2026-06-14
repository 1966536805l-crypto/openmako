#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_DIR="${OPENMAKO_PUBLIC_REVIEW_GATE_ARTIFACT_DIR:-$ROOT_DIR/.quantagent/public_review_gate}"
REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-origin}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"
GIT_COMMIT="$(git rev-parse HEAD)"
if remote_url="$(git remote get-url "$REMOTE" 2>/dev/null)"; then
  REMOTE_URL="$remote_url"
else
  REMOTE_URL="$REMOTE"
fi

if [ ! -f "$ARTIFACT_DIR/summary.json" ]; then
  echo "publish-public-evidence-branch: missing $ARTIFACT_DIR/summary.json" >&2
  exit 2
fi

python3 - "$ARTIFACT_DIR" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

artifact_dir = Path(sys.argv[1]).resolve(strict=False)
git_commit = sys.argv[2]
summary_path = artifact_dir / "summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
if summary.get("schema_version") != "public-review-gate-artifact/v0.1":
    raise SystemExit("publish-public-evidence-branch: summary schema_version mismatch")
if summary.get("status") != "passed":
    raise SystemExit("publish-public-evidence-branch: summary status is not passed")
invocation = summary.get("invocation")
if not isinstance(invocation, dict) or invocation.get("git_commit") != git_commit:
    raise SystemExit("publish-public-evidence-branch: summary git_commit does not match HEAD")
required_outputs = summary.get("required_outputs")
output_hashes = summary.get("output_sha256")
if not isinstance(required_outputs, list) or not isinstance(output_hashes, dict):
    raise SystemExit("publish-public-evidence-branch: summary output contract is malformed")
for relative in required_outputs:
    if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
        raise SystemExit(f"publish-public-evidence-branch: unsafe output path {relative!r}")
    path = artifact_dir / relative
    if not path.is_file():
        raise SystemExit(f"publish-public-evidence-branch: required output missing: {relative}")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if output_hashes.get(relative) != digest:
        raise SystemExit(f"publish-public-evidence-branch: digest mismatch for {relative}")
PY

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if git clone --depth 1 --branch "$BRANCH" "$REMOTE_URL" "$tmp_dir/branch" >/dev/null 2>&1; then
  evidence_dir="$tmp_dir/branch"
else
  mkdir -p "$tmp_dir/branch"
  evidence_dir="$tmp_dir/branch"
  git -C "$evidence_dir" init -q
  git -C "$evidence_dir" checkout --orphan "$BRANCH" >/dev/null 2>&1
  git -C "$evidence_dir" remote add origin "$REMOTE_URL"
fi

mkdir -p "$evidence_dir/focused/$GIT_COMMIT"
rm -rf "$evidence_dir/focused/$GIT_COMMIT"
mkdir -p "$evidence_dir/focused/$GIT_COMMIT"
cp -R "$ARTIFACT_DIR"/. "$evidence_dir/focused/$GIT_COMMIT/"

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
    "latest_focused_commit": git_commit,
    "focused_summary": f"focused/{git_commit}/summary.json",
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
    ],
}
(root / "focused").mkdir(parents=True, exist_ok=True)
(root / "focused" / "latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

git -C "$evidence_dir" config user.email "${OPENMAKO_PUBLIC_EVIDENCE_GIT_EMAIL:-openmako-evidence-bot@example.invalid}"
git -C "$evidence_dir" config user.name "${OPENMAKO_PUBLIC_EVIDENCE_GIT_NAME:-OpenMako Evidence Bot}"
git -C "$evidence_dir" add focused
if git -C "$evidence_dir" diff --cached --quiet; then
  echo "publish-public-evidence-branch: no changes"
else
  git -C "$evidence_dir" commit -q -m "Publish focused public evidence for $GIT_COMMIT"
  git -C "$evidence_dir" push origin "HEAD:$BRANCH" >/dev/null
  echo "publish-public-evidence-branch: pushed branch=$BRANCH commit=$GIT_COMMIT"
fi

echo "publish-public-evidence-branch: PASS"
