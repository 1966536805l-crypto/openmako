#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/wave1_thread_reply_ready.sh THREAD

Runs the public review gate, then prints one thread-specific technical-boundary
reply draft.

This does not send messages, create issues, ask for stars, ask for reposts, or
record outreach as evidence.

THREAD values:
  terminal-bench-1357
  openhands-benchmarks-708
  openhands-benchmarks-718
EOF
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

thread="$1"

case "$thread" in
  terminal-bench-1357|openhands-benchmarks-708|openhands-benchmarks-718)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "unknown thread: ${thread}" >&2
    usage >&2
    exit 2
    ;;
esac

echo "wave1-thread-reply-ready: checking public proof gate"
bash scripts/public_review_gate.sh

echo
echo "wave1-thread-reply-ready: thread=${thread}"
echo "queue: docs/WAVE1_PUBLIC_TARGET_QUEUE.md"
echo "decision: read the thread first; do not post if stale, closed, or off-topic"
echo "message:"
echo

case "$thread" in
  terminal-bench-1357)
    cat <<'EOF'
This is a related issue I keep hitting: once runs are expensive, a leaderboard row without cost/version/proof metadata is hard to trust.

I made a small harness for my own project that refuses to treat a run as proof unless patch scope, tests, and supplied-run metadata line up. If useful, I would rather get criticism on the boundary than repo promotion:
https://github.com/1966536805l-crypto/openmako/issues/2
EOF
    ;;
  openhands-benchmarks-708)
    cat <<'EOF'
This issue is a good example of why patch shape needs to be part of the evidence, not just the final score.

OpenMako v0.1 is much smaller than this benchmark work, but it treats "changed files outside the claimed scope" as a failing signal. If that framing is wrong or too weak, I would value the criticism here:
https://github.com/1966536805l-crypto/openmako/issues/2
EOF
    ;;
  openhands-benchmarks-718)
    cat <<'EOF'
This comparability problem is close to one thing I am trying to define: when evaluation rules change, old runs need audit metadata for rule version, runner version, and artifact provenance.

OpenMako is only a small supplied-record audit today; it does not ingest native OpenHands/SWTBench artifacts or solve historical re-scoring. The specific question for this thread is whether rule version, runner version, and artifact provenance are enough to keep old artifacts interpretable. Related notes, if useful:
https://github.com/1966536805l-crypto/openmako/issues/2
EOF
    ;;
esac
