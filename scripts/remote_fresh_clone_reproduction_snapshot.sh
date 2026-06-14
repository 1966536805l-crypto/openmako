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
  echo "remote-fresh-clone-reproduction-snapshot: could not resolve ${SOURCE_REMOTE}/main" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if ! git clone --depth 1 --branch "$BRANCH" "$EVIDENCE_REMOTE" "$tmp_dir/evidence" >/dev/null 2>&1; then
  echo "remote-fresh-clone-reproduction-snapshot: repo=$EVIDENCE_REMOTE"
  echo "remote-fresh-clone-reproduction-snapshot: branch=$BRANCH"
  echo "remote-fresh-clone-reproduction-snapshot: remote-main-sha=$remote_sha"
  echo "remote-fresh-clone-reproduction-snapshot: unavailable=public_evidence_branch_missing"
  echo "remote-fresh-clone-reproduction-snapshot: not-proof=external review; endorsement; stars; reposts; independent external benchmark standing; GitHub Actions artifact zip contents; native live autonomy; broad unknown-repository repair"
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
summary_path = root / "reproductions" / remote_sha / "summary.json"
latest_path = root / "reproductions" / "latest.json"


def fail(reason: str, detail: str = "") -> None:
    print(f"remote-fresh-clone-reproduction-snapshot: repo={repo}")
    print(f"remote-fresh-clone-reproduction-snapshot: branch={branch}")
    print(f"remote-fresh-clone-reproduction-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-fresh-clone-reproduction-snapshot: unavailable={reason}")
    if detail:
        print(f"remote-fresh-clone-reproduction-snapshot: detail={detail}")
    print(
        "remote-fresh-clone-reproduction-snapshot: "
        "not-proof=external review; endorsement; stars; reposts; independent external "
        "benchmark standing; GitHub Actions artifact zip contents; native live autonomy; "
        "broad unknown-repository repair"
    )
    raise SystemExit(1)


if not summary_path.is_file():
    fail("fresh_clone_reproduction_summary_missing", str(summary_path.relative_to(root)))
try:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("fresh_clone_reproduction_summary_invalid_json", str(exc))
if summary.get("schema_version") != "fresh-clone-reproduction-public-evidence/v0.1":
    fail("fresh_clone_reproduction_summary_schema_mismatch")
if summary.get("status") != "passed":
    fail("fresh_clone_reproduction_summary_not_passed")
if summary.get("git_commit") != remote_sha:
    fail("fresh_clone_reproduction_summary_commit_mismatch")
log_relative = summary.get("log_path")
if log_relative != "fresh_clone.log":
    fail("fresh_clone_reproduction_log_path_mismatch")
log_path = summary_path.parent / log_relative
if not log_path.is_file():
    fail("fresh_clone_reproduction_log_missing", str(log_relative))
log_bytes = log_path.read_bytes()
log_text = log_bytes.decode("utf-8", errors="replace")
log_sha256 = "sha256:" + hashlib.sha256(log_bytes).hexdigest()
if summary.get("log_sha256") != log_sha256:
    fail("fresh_clone_reproduction_log_digest_mismatch")
if summary.get("log_line_count") != len(log_text.splitlines()):
    fail("fresh_clone_reproduction_log_line_count_mismatch")
markers = summary.get("markers")
if not isinstance(markers, dict):
    fail("fresh_clone_reproduction_markers_malformed")
expected_marker_keys = {
    "requested_ref",
    "checkout_sha",
    "install",
    "release_readiness",
    "public_review",
    "remote_public_evidence",
    "remote_autonomous_public_evidence",
    "fresh_clone",
}
if set(markers) != expected_marker_keys:
    fail("fresh_clone_reproduction_marker_keys_mismatch")
for key, marker in markers.items():
    if not isinstance(marker, str) or marker not in log_text:
        fail("fresh_clone_reproduction_marker_missing", key)
if f"fresh-clone-reproduction: requested-ref={remote_sha}" not in log_text:
    fail("fresh_clone_reproduction_requested_ref_missing")
if f"fresh-clone-reproduction: checkout-sha={remote_sha}" not in log_text:
    fail("fresh_clone_reproduction_checkout_sha_missing")
required_not_proof = {
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "independent external benchmark standing",
    "GitHub Actions artifact zip contents",
    "native live autonomy",
    "broad unknown-repository repair",
}
if not required_not_proof.issubset(set(summary.get("not_proof") or [])):
    fail("fresh_clone_reproduction_not_proof_boundary_mismatch")
latest = {}
if latest_path.is_file():
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest.get("latest_reproduction_commit") != remote_sha:
        fail("latest_index_commit_mismatch")

print(f"remote-fresh-clone-reproduction-snapshot: repo={repo}")
print(f"remote-fresh-clone-reproduction-snapshot: branch={branch}")
print(f"remote-fresh-clone-reproduction-snapshot: remote-main-sha={remote_sha}")
print(f"remote-fresh-clone-reproduction-snapshot: summary=reproductions/{remote_sha}/summary.json")
print(f"remote-fresh-clone-reproduction-snapshot: status={summary['status']}")
print(f"remote-fresh-clone-reproduction-snapshot: log-sha256={summary['log_sha256']}")
print(f"remote-fresh-clone-reproduction-snapshot: log-lines={summary['log_line_count']}")
print(f"remote-fresh-clone-reproduction-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-fresh-clone-reproduction-snapshot: "
    "not-proof=external review; endorsement; stars; reposts; independent external "
    "benchmark standing; GitHub Actions artifact zip contents; native live autonomy; "
    "broad unknown-repository repair"
)
print("remote-fresh-clone-reproduction-snapshot: PASS")
PY
