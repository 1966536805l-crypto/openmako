#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review

Runs the public proof gate, then prints the broader technical share packet only
when a public OpenMako external-review record issue URL is supplied.

The confirmation flag means a human has inspected the linked public review and
confirmed that a named external reviewer actually wrote it.

This does not post, contact anyone, ask for stars, ask for reposts, or record
outreach as evidence.
EOF
}

case "${1:-}" in
  -h|--help|help)
    usage
    exit 0
    ;;
esac

if [ "$#" -ne 2 ]; then
  usage >&2
  exit 2
fi

review_record_url="$1"
confirmation="$2"
if [[ ! "$review_record_url" =~ ^https://github\.com/1966536805l-crypto/openmako/issues/[0-9]+$ ]]; then
  echo "large-repost-ready: missing public external-review record issue URL" >&2
  echo "expected: https://github.com/1966536805l-crypto/openmako/issues/NUMBER" >&2
  exit 2
fi
if [ "$confirmation" != "--confirm-external-review" ]; then
  echo "large-repost-ready: missing manual external-review authorship confirmation" >&2
  echo "expected second argument: --confirm-external-review" >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "large-repost-ready: verifying external review record issue"
bash scripts/external_review_record_check.sh "$review_record_url"

echo "large-repost-ready: checking public proof gate"
bash scripts/public_review_gate.sh

echo
echo "large-repost-ready: review-record=${review_record_url}"
echo "manual-confirmation=external-review-authorship"
echo "source: docs/LARGE_REPOST_PACKET.md"
echo "guard: use only after a named public external technical review is recorded"
echo "message:"
echo

python3 - <<'PY'
from pathlib import Path
import re

text = Path("docs/LARGE_REPOST_PACKET.md").read_text(encoding="utf-8")
for heading in ("Broad Technical Summary", "Short Repost-Ready Note"):
    match = re.search(
        rf"## {re.escape(heading)}\n\n```text\n(?P<message>.*?)\n```",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise SystemExit(f"large repost packet block not found: {heading}")
    print(f"## {heading}")
    print(match.group("message").strip())
    print()
PY
