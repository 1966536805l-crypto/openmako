#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/public_share_ready.sh MODE

Modes:
  review-request
  boundary-clear

Runs the public review gate, then prints one boundary-preserving public share
message. It does not post, ask for stars, ask for reposts, or record outreach
as evidence.
EOF
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mode="$1"
case "$mode" in
  review-request|boundary-clear)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "unknown mode: ${mode}" >&2
    usage >&2
    exit 2
    ;;
esac

echo "public-share-ready: checking public proof gate"
bash scripts/public_review_gate.sh

echo
echo "public-share-ready: mode=${mode}"
echo "source: docs/PUBLIC_SHARE_PACKET.md"
if [ "$mode" = "boundary-clear" ]; then
  echo "requires-public-review: yes; use only after a named public technical boundary review exists"
fi
echo "message:"
echo

python3 - "$mode" <<'PY'
from pathlib import Path
import re
import sys

mode = sys.argv[1]
text = Path("docs/PUBLIC_SHARE_PACKET.md").read_text(encoding="utf-8")
heading = "Technical Review Request" if mode == "review-request" else "Boundary-Clear Follow-Up"
match = re.search(
    rf"### {re.escape(heading)}\n\n(?:Use this only after.*?\n\n)?```text\n(?P<message>.*?)\n```",
    text,
    flags=re.DOTALL,
)
if not match:
    raise SystemExit(f"share packet block not found: {heading}")
print(match.group("message").strip())
PY
