#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

GIT_COMMIT="${OPENMAKO_ARTIFACT_ZIP_PROOF_REF:-$(git rev-parse HEAD)}"
REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-origin}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"
FOCUSED_ZIP="${OPENMAKO_FOCUSED_ARTIFACT_ZIP:?set OPENMAKO_FOCUSED_ARTIFACT_ZIP to the focused artifact zip}"
AUTONOMOUS_ZIP="${OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP:?set OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP to the autonomous artifact zip}"

python3 - "$GIT_COMMIT" "$FOCUSED_ZIP" "$AUTONOMOUS_ZIP" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import PurePosixPath

git_commit = sys.argv[1]
zip_inputs = [
    ("focused", sys.argv[2], "summary.json", "public-review-gate-artifact/v0.1"),
    ("autonomous", sys.argv[3], "last_summary.json", "autonomous-learning-gate/v0.1"),
]


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"publish-artifact-zip-proof-branch: missing env {name}")
    return value


def normalize_digest(value: str) -> str:
    value = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return "sha256:" + value
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    raise SystemExit(
        "publish-artifact-zip-proof-branch: unsupported artifact digest format"
    )


def validate_zip(kind: str, zip_path: str, summary_leaf: str, schema: str) -> dict[str, object]:
    path = os.path.abspath(zip_path)
    if not os.path.isfile(path):
        raise SystemExit(f"publish-artifact-zip-proof-branch: missing {kind} zip={zip_path}")
    payload = open(path, "rb").read()
    zip_sha256 = hashlib.sha256(payload).hexdigest()
    artifact_digest = normalize_digest(env_required(f"OPENMAKO_{kind.upper()}_ARTIFACT_DIGEST"))
    if artifact_digest != "sha256:" + zip_sha256:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} artifact zip sha256 "
            "does not match artifact digest"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            for name in files:
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts:
                    raise SystemExit(
                        f"publish-artifact-zip-proof-branch: unsafe {kind} zip member={name}"
                    )
            summary_candidates = [
                name for name in files if PurePosixPath(name).name == summary_leaf
            ]
            if len(summary_candidates) != 1:
                raise SystemExit(
                    f"publish-artifact-zip-proof-branch: {kind} artifact zip must "
                    f"contain exactly one {summary_leaf}"
                )
            summary_path = summary_candidates[0]
            summary = json.loads(archive.read(summary_path).decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} artifact is not a readable zip: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary is not valid JSON: {exc}"
        ) from exc
    if summary.get("schema_version") != schema:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary schema_version mismatch"
        )
    if summary.get("status") != "passed":
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary status mismatch"
        )
    invocation = summary.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("git_commit") != git_commit:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary git_commit mismatch"
        )
    return {
        "local_path": path,
        "zip_sha256": "sha256:" + zip_sha256,
        "zip_size_bytes": len(payload),
        "summary_path": summary_path,
        "artifact_digest": artifact_digest,
    }


for item in zip_inputs:
    validate_zip(*item)
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

record_dir="$evidence_dir/artifact_zip_proofs/$GIT_COMMIT"
mkdir -p "$record_dir/focused" "$record_dir/autonomous"
cp "$FOCUSED_ZIP" "$record_dir/focused/focused-public-review-gate.zip"
cp "$AUTONOMOUS_ZIP" "$record_dir/autonomous/autonomous-learning-gate-summary.zip"

python3 - "$evidence_dir" "$GIT_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1])
git_commit = sys.argv[2]
record_dir = root / "artifact_zip_proofs" / git_commit


def normalize_digest(value: str) -> str:
    value = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return "sha256:" + value
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    raise SystemExit(
        "publish-artifact-zip-proof-branch: unsupported artifact digest format"
    )


def read_zip_contract(
    *,
    kind: str,
    zip_relative: str,
    summary_leaf: str,
    schema: str,
    digest_env: str,
    id_env: str,
    run_env: str,
    name_env: str,
) -> dict[str, object]:
    zip_path = record_dir / zip_relative
    payload = zip_path.read_bytes()
    zip_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    artifact_digest = normalize_digest(os.environ[digest_env])
    if artifact_digest != zip_sha256:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} artifact digest mismatch"
        )
    with zipfile.ZipFile(zip_path) as archive:
        files = [name for name in archive.namelist() if not name.endswith("/")]
        for name in files:
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts:
                raise SystemExit(
                    f"publish-artifact-zip-proof-branch: unsafe {kind} zip member={name}"
                )
        summary_candidates = [
            name for name in files if PurePosixPath(name).name == summary_leaf
        ]
        if len(summary_candidates) != 1:
            raise SystemExit(
                f"publish-artifact-zip-proof-branch: {kind} summary count mismatch"
            )
        summary_path = summary_candidates[0]
        summary = json.loads(archive.read(summary_path).decode("utf-8"))
    if summary.get("schema_version") != schema:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary schema mismatch"
        )
    if summary.get("status") != "passed":
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary status mismatch"
        )
    invocation = summary.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("git_commit") != git_commit:
        raise SystemExit(
            f"publish-artifact-zip-proof-branch: {kind} summary commit mismatch"
        )
    return {
        "kind": kind,
        "name": os.environ.get(name_env, ""),
        "run_id": os.environ[run_env],
        "artifact_id": os.environ[id_env],
        "artifact_digest": artifact_digest,
        "zip_path": zip_relative,
        "zip_sha256": zip_sha256,
        "zip_size_bytes": len(payload),
        "summary_path": summary_path,
    }


artifacts = {
    "focused": read_zip_contract(
        kind="focused",
        zip_relative="focused/focused-public-review-gate.zip",
        summary_leaf="summary.json",
        schema="public-review-gate-artifact/v0.1",
        digest_env="OPENMAKO_FOCUSED_ARTIFACT_DIGEST",
        id_env="OPENMAKO_FOCUSED_ARTIFACT_ID",
        run_env="OPENMAKO_FOCUSED_RUN_ID",
        name_env="OPENMAKO_FOCUSED_ARTIFACT_NAME",
    ),
    "autonomous": read_zip_contract(
        kind="autonomous",
        zip_relative="autonomous/autonomous-learning-gate-summary.zip",
        summary_leaf="last_summary.json",
        schema="autonomous-learning-gate/v0.1",
        digest_env="OPENMAKO_AUTONOMOUS_ARTIFACT_DIGEST",
        id_env="OPENMAKO_AUTONOMOUS_ARTIFACT_ID",
        run_env="OPENMAKO_AUTONOMOUS_RUN_ID",
        name_env="OPENMAKO_AUTONOMOUS_ARTIFACT_NAME",
    ),
}
not_proof = [
    "unauthenticated GitHub Actions API artifact zip download",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "independent external held-out benchmark",
]
manifest = {
    "schema_version": "openmako-artifact-zip-proof/v0.1",
    "status": "passed",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": git_commit,
    "download_method": os.environ.get(
        "OPENMAKO_ARTIFACT_ZIP_DOWNLOAD_METHOD", "github-connector-download"
    ),
    "artifacts": artifacts,
    "not_proof": not_proof,
}
(record_dir / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
latest = {
    "schema_version": "openmako-artifact-zip-proof-index/v0.1",
    "latest_artifact_zip_proof_commit": git_commit,
    "manifest": f"artifact_zip_proofs/{git_commit}/manifest.json",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "not_proof": not_proof,
}
(root / "artifact_zip_proofs").mkdir(parents=True, exist_ok=True)
(root / "artifact_zip_proofs" / "latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

git -C "$evidence_dir" config user.email "${OPENMAKO_PUBLIC_EVIDENCE_GIT_EMAIL:-openmako-evidence-bot@example.invalid}"
git -C "$evidence_dir" config user.name "${OPENMAKO_PUBLIC_EVIDENCE_GIT_NAME:-OpenMako Evidence Bot}"
git -C "$evidence_dir" add artifact_zip_proofs
if git -C "$evidence_dir" diff --cached --quiet; then
  echo "publish-artifact-zip-proof-branch: no changes"
else
  git -C "$evidence_dir" commit -q -m "Publish artifact zip proof for $GIT_COMMIT"
  git -C "$evidence_dir" push "$push_remote" "HEAD:$BRANCH" >/dev/null
  echo "publish-artifact-zip-proof-branch: pushed branch=$BRANCH commit=$GIT_COMMIT"
fi

echo "publish-artifact-zip-proof-branch: PASS"
