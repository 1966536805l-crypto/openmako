#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_DIR="${OPENMAKO_PUBLIC_REVIEW_GATE_ARTIFACT_DIR:-$ROOT_DIR/.quantagent/public_review_gate}"
REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-origin}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"
GIT_COMMIT="$(git rev-parse HEAD)"

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

mkdir -p "$evidence_dir/focused/$GIT_COMMIT"
rm -rf "$evidence_dir/focused/$GIT_COMMIT"
mkdir -p "$evidence_dir/focused/$GIT_COMMIT"
cp -R "$ARTIFACT_DIR"/. "$evidence_dir/focused/$GIT_COMMIT/"

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
focused_dir = root / "focused" / git_commit
summary_path = focused_dir / "summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
required_outputs = summary.get("required_outputs")
if not isinstance(required_outputs, list):
    raise SystemExit("publish-public-evidence-branch: mirror required_outputs malformed")
mirror_dir = focused_dir / "public_mirror"
mirror_dir.mkdir(parents=True, exist_ok=True)
archive_path = mirror_dir / "focused-public-review-gate-public-mirror.zip"
manifest_path = mirror_dir / "manifest.json"
files: dict[str, str] = {}
for path in sorted(focused_dir.rglob("*")):
    if not path.is_file():
        continue
    rel = str(path.relative_to(focused_dir))
    if rel.startswith("public_mirror/"):
        continue
    files[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
for required in required_outputs:
    if required not in files:
        raise SystemExit(f"publish-public-evidence-branch: mirror missing required output {required}")
if "summary.json" not in files or "invocation.json" not in files:
    raise SystemExit("publish-public-evidence-branch: mirror missing summary or invocation")
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for rel in sorted(files):
        source = focused_dir / rel
        info = zipfile.ZipInfo(rel)
        info.date_time = (1980, 1, 1, 0, 0, 0)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, source.read_bytes())
archive_sha256 = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()

def required_env(name: str, label: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"publish-public-evidence-branch: focused artifact {label} missing")
    return value

artifact_name = required_env("OPENMAKO_FOCUSED_ARTIFACT_NAME", "name")
run_id = required_env("OPENMAKO_FOCUSED_RUN_ID", "run id")
run_attempt = required_env("OPENMAKO_FOCUSED_RUN_ATTEMPT", "run attempt")
artifact_id = required_env("OPENMAKO_FOCUSED_ARTIFACT_ID", "id")
artifact_digest = required_env("OPENMAKO_FOCUSED_ARTIFACT_DIGEST", "digest")
artifact_url = required_env("OPENMAKO_FOCUSED_ARTIFACT_URL", "url")
if artifact_name != "focused-public-review-gate":
    raise SystemExit("publish-public-evidence-branch: focused artifact name mismatch")
if not run_id.isdigit():
    raise SystemExit("publish-public-evidence-branch: focused artifact run id malformed")
if not run_attempt.isdigit():
    raise SystemExit("publish-public-evidence-branch: focused artifact run attempt malformed")
if not artifact_id.isdigit():
    raise SystemExit("publish-public-evidence-branch: focused artifact id malformed")
artifact_digest = artifact_digest.lower()
if re.fullmatch(r"[0-9a-f]{64}", artifact_digest):
    artifact_digest = "sha256:" + artifact_digest
if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest):
    raise SystemExit("publish-public-evidence-branch: focused artifact digest missing/malformed")
if not artifact_url.startswith("https://"):
    raise SystemExit("publish-public-evidence-branch: focused artifact url malformed")
github_actions_artifact = {
    "name": artifact_name,
    "run_id": run_id,
    "run_attempt": run_attempt,
    "artifact_id": artifact_id,
    "artifact_digest": artifact_digest,
    "artifact_url": artifact_url,
}
manifest = {
    "schema_version": "public-evidence-artifact-mirror/v0.2",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit,
    "mirror_scope": "github-actions-upload-directory-content",
    "source_summary": "summary.json",
    "archive_path": "public_mirror/focused-public-review-gate-public-mirror.zip",
    "archive_sha256": archive_sha256,
    "file_count": len(files),
    "files": files,
    "github_actions_artifact": github_actions_artifact,
    "required_outputs": required_outputs,
    "not_proof": [
        "GitHub Actions API artifact zip endpoint byte-for-byte archive",
        "external review",
        "endorsement",
        "stars",
        "reposts",
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
    ],
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

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
        "GitHub Actions API artifact zip endpoint byte-for-byte archive",
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
  git -C "$evidence_dir" push "$push_remote" "HEAD:$BRANCH" >/dev/null
  echo "publish-public-evidence-branch: pushed branch=$BRANCH commit=$GIT_COMMIT"
fi

echo "publish-public-evidence-branch: PASS"
