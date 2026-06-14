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
print(f"remote-public-evidence-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-public-evidence-snapshot: "
    "not-proof=GitHub Actions artifact zip contents; external review; endorsement; "
    "stars; reposts; native live autonomy; broad unknown-repository repair; "
    "external benchmark standing"
)
print("remote-public-evidence-snapshot: PASS")
PY
