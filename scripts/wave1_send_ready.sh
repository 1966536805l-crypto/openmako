#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/wave1_send_ready.sh [--linkless] TARGET

Runs the public review gate, then prints one short Wave 1 technical-boundary
review request for TARGET.

This does not send messages, create issues, ask for stars, ask for reposts, or
record outreach as evidence.

Use --linkless for an existing public thread where a cold-start project link
would look promotional. The proof gate still runs first. The printed fragment
still requires replacing THREAD_HOOK with a concrete point from the thread
before posting.
EOF
}

linkless=0
if [ "$#" -ge 1 ] && [ "$1" = "--linkless" ]; then
  linkless=1
  shift
fi

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

target="$1"

case "$target" in
  swe-agent|terminal-bench|aider|openhands|agent-runtime)
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
if [ "$linkless" -eq 1 ]; then
  echo "wave1-send-ready: mode=linkless"
  echo "requires-thread-hook: yes; replace THREAD_HOOK before posting"
fi
echo "queue: docs/WAVE1_PUBLIC_TARGET_QUEUE.md"
echo "message:"
echo
review_args=()
if [ "$linkless" -eq 1 ]; then
  review_args+=(--linkless)
fi
review_args+=("$target")
bash scripts/wave1_review_request.sh "${review_args[@]}"
