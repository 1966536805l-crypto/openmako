#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/wave1_send_ready.sh TARGET

Runs the public review gate, then prints one short Wave 1 technical-boundary
review request for TARGET.

This does not send messages, create issues, ask for stars, ask for reposts, or
record outreach as evidence.
EOF
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

target="$1"

case "$target" in
  swe-agent|terminal-bench|aider|openhands)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "unknown target: ${target}" >&2
    usage >&2
    exit 2
    ;;
esac

echo "wave1-send-ready: checking public proof gate"
bash scripts/public_review_gate.sh

echo
echo "wave1-send-ready: target=${target}"
echo "queue: docs/WAVE1_PUBLIC_TARGET_QUEUE.md"
echo "message:"
echo
bash scripts/wave1_review_request.sh "$target"
