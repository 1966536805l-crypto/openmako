#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/external_review_record_check.sh REVIEW_RECORD_ISSUE_URL

Checks that a public OpenMako external-review record issue is structured,
current-commit bound, and tied to the current public evidence snapshots.

This does not create an external review, prove endorsement, ask for stars, or
turn a private message into public evidence.
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

review_record_url="$1"
if [[ ! "$review_record_url" =~ ^https://github\.com/1966536805l-crypto/openmako/issues/[0-9]+$ ]]; then
  echo "external-review-record-check: missing public external-review record issue URL" >&2
  echo "expected: https://github.com/1966536805l-crypto/openmako/issues/NUMBER" >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_REMOTE="${OPENMAKO_REMOTE:-openmako}"
expected_commit="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_COMMIT:-}"
if [ -z "$expected_commit" ]; then
  expected_commit="$(git ls-remote "$SOURCE_REMOTE" refs/heads/main | awk '{print $1}')"
fi
if [[ ! "$expected_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "external-review-record-check: could not resolve current openmako/main commit" >&2
  exit 2
fi

focused_run_id="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_FOCUSED_RUN_ID:-}"
fresh_clone_log_sha256="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_FRESH_CLONE_LOG_SHA256:-}"
focused_artifact_id="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_FOCUSED_ARTIFACT_ID:-}"
autonomous_artifact_id="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_AUTONOMOUS_ARTIFACT_ID:-}"
focused_zip_sha256="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_FOCUSED_ZIP_SHA256:-}"
autonomous_zip_sha256="${OPENMAKO_EXTERNAL_REVIEW_EXPECTED_AUTONOMOUS_ZIP_SHA256:-}"

if [ -z "$focused_run_id" ]; then
  focused_snapshot="$(OPENMAKO_REMOTE_MAIN_SHA="$expected_commit" bash scripts/remote_focused_ci_snapshot.sh)"
  focused_run_id="$(printf '%s\n' "$focused_snapshot" | awk -F= '/run-id=/{print $2; exit}')"
fi

if [ -z "$fresh_clone_log_sha256" ]; then
  fresh_snapshot="$(OPENMAKO_REMOTE_MAIN_SHA="$expected_commit" bash scripts/remote_fresh_clone_reproduction_snapshot.sh)"
  fresh_clone_log_sha256="$(printf '%s\n' "$fresh_snapshot" | awk -F= '/log-sha256=/{print $2; exit}')"
fi

if [ -z "$focused_artifact_id" ] || [ -z "$autonomous_artifact_id" ] || [ -z "$focused_zip_sha256" ] || [ -z "$autonomous_zip_sha256" ]; then
  artifact_snapshot="$(OPENMAKO_REMOTE_MAIN_SHA="$expected_commit" bash scripts/remote_artifact_zip_proof_snapshot.sh)"
  focused_artifact_id="${focused_artifact_id:-$(printf '%s\n' "$artifact_snapshot" | awk -F= '/focused-artifact-id=/{print $2; exit}')}"
  autonomous_artifact_id="${autonomous_artifact_id:-$(printf '%s\n' "$artifact_snapshot" | awk -F= '/autonomous-artifact-id=/{print $2; exit}')}"
  focused_zip_sha256="${focused_zip_sha256:-$(printf '%s\n' "$artifact_snapshot" | awk -F= '/focused-zip-sha256=/{print $2; exit}')}"
  autonomous_zip_sha256="${autonomous_zip_sha256:-$(printf '%s\n' "$artifact_snapshot" | awk -F= '/autonomous-zip-sha256=/{print $2; exit}')}"
fi

for value_name in \
  focused_run_id \
  fresh_clone_log_sha256 \
  focused_artifact_id \
  autonomous_artifact_id \
  focused_zip_sha256 \
  autonomous_zip_sha256
do
  value="${!value_name}"
  if [ -z "$value" ]; then
    echo "external-review-record-check: could not resolve ${value_name}" >&2
    exit 2
  fi
done

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

page_path="$tmp_dir/review-record.html"
if [ -n "${OPENMAKO_EXTERNAL_REVIEW_RECORD_HTML:-}" ]; then
  cp "$OPENMAKO_EXTERNAL_REVIEW_RECORD_HTML" "$page_path"
else
  curl_bin="${OPENMAKO_CURL_BIN:-curl}"
  "$curl_bin" -fsSL --max-time 20 -A openmako-external-review-record-check "$review_record_url" >"$page_path" || {
    echo "external-review-record-check: could not fetch external-review record issue: ${review_record_url}" >&2
    exit 2
  }
fi

python3 - \
  "$page_path" \
  "$review_record_url" \
  "$expected_commit" \
  "$focused_run_id" \
  "$fresh_clone_log_sha256" \
  "$focused_artifact_id" \
  "$autonomous_artifact_id" \
  "$focused_zip_sha256" \
  "$autonomous_zip_sha256" <<'PY'
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

(
    page_path,
    review_record_url,
    expected_commit,
    focused_run_id,
    fresh_clone_log_sha256,
    focused_artifact_id,
    autonomous_artifact_id,
    focused_zip_sha256,
    autonomous_zip_sha256,
) = sys.argv[1:10]

page = html.unescape(Path(page_path).read_text(encoding="utf-8", errors="replace"))

required_markers = {
    "record-title": "External review record:",
    "reviewer-field": "Reviewer",
    "public-review-link-field": "Public review link",
    "verdict-field": "Review verdict",
    "evidence-checked-field": "Evidence checked by reviewer",
    "boundary-confirmation-field": "Boundary confirmation",
    "public-review-boundary": "This records an already-public external technical review, not a private message or self-written summary.",
    "no-promotion-boundary": "This issue does not ask for endorsement, promotion, stars, reposts, or broader claims.",
    "current-commit": expected_commit,
    "focused-run-id": focused_run_id,
    "fresh-clone-log-sha256": fresh_clone_log_sha256,
    "focused-artifact-id": focused_artifact_id,
    "autonomous-artifact-id": autonomous_artifact_id,
    "focused-zip-sha256": focused_zip_sha256,
    "autonomous-zip-sha256": autonomous_zip_sha256,
}
verdict_markers = (
    "boundary clear",
    "overclaim found",
    "unclear boundary",
    "mixed / needs follow-up",
)
forbidden_markers = (
    "please star",
    "please repost",
    "10,000",
    "10000",
    "大咖",
)

missing = [name for name, marker in required_markers.items() if marker not in page]
if not any(marker in page for marker in verdict_markers):
    missing.append("selected-review-verdict")
if not re.search(r"https://(?!github\.com/1966536805l-crypto/openmako/issues/new\?template=external-review-record\.yml)[^\s\"<>]+", page):
    missing.append("public-review-url")
for marker in forbidden_markers:
    if marker.lower() in page.lower():
        missing.append(f"forbidden-marker:{marker}")

print(f"external-review-record-check: url={review_record_url}")
print(f"external-review-record-check: expected-commit={expected_commit}")
print(f"external-review-record-check: focused-run-id={focused_run_id}")
print(f"external-review-record-check: fresh-clone-log-sha256={fresh_clone_log_sha256}")
print(f"external-review-record-check: focused-artifact-id={focused_artifact_id}")
print(f"external-review-record-check: autonomous-artifact-id={autonomous_artifact_id}")
print(f"external-review-record-check: focused-zip-sha256={focused_zip_sha256}")
print(f"external-review-record-check: autonomous-zip-sha256={autonomous_zip_sha256}")
print(
    "external-review-record-check: "
    "not-proof=endorsement; stars; reposts; native live autonomy; "
    "broad unknown-repository repair; external benchmark standing; "
    "third-party benchmark standing"
)

if missing:
    print(
        "external-review-record-check: missing or invalid review record markers="
        + ",".join(missing),
        file=sys.stderr,
    )
    raise SystemExit(1)

print("external-review-record-check: PASS")
PY
