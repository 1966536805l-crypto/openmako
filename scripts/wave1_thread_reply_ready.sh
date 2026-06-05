#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: bash scripts/wave1_thread_reply_ready.sh THREAD

Checks that the target thread still looks on-topic, runs the public review
gate, then prints one thread-specific technical-boundary reply draft.

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

case "$thread" in
  terminal-bench-1357)
    target_url="https://github.com/harbor-framework/terminal-bench/discussions/1357"
    ;;
  openhands-benchmarks-708)
    target_url="https://github.com/OpenHands/benchmarks/issues/708"
    ;;
  openhands-benchmarks-718)
    target_url="https://github.com/OpenHands/benchmarks/issues/718"
    ;;
esac

case "$thread" in
  terminal-bench-1357)
    expected_title="How costly is it to execute a test?"
    required_markers="terminal-bench|cost|test|discussion"
    ;;
  openhands-benchmarks-708)
    expected_title="swtbench: qwen3-coder-next score is artificially low"
    required_markers='"state":"OPEN"|332|424|model_patch|non-test|patch'
    ;;
  openhands-benchmarks-718)
    expected_title="Assess impact of swtbench non-test patch stripping on historical runs"
    required_markers='"state":"OPEN"|output.jsonl|output.swtbench.jsonl|historical|patch'
    ;;
esac

echo "wave1-thread-reply-ready: checking target thread page"
thread_page_path="$(mktemp)"
trap 'rm -f "$thread_page_path"' EXIT
if [ -n "${OPENMAKO_THREAD_PAGE_FIXTURE:-}" ]; then
  cat "$OPENMAKO_THREAD_PAGE_FIXTURE" >"$thread_page_path"
else
  curl_bin="${OPENMAKO_CURL_BIN:-curl}"
  "$curl_bin" -fsSL --max-time 20 -A openmako-wave1-thread-check "$target_url" >"$thread_page_path" || {
    echo "wave1-thread-reply-ready: could not fetch target thread: ${target_url}" >&2
    exit 2
  }
fi

python3 - "$thread" "$target_url" "$expected_title" "$required_markers" "$thread_page_path" <<'PY'
from pathlib import Path
import sys

thread, target_url, expected_title, markers_raw, page_path = sys.argv[1:]
page = Path(page_path).read_text(encoding="utf-8", errors="replace")
page_lower = page.lower()
missing = []
if expected_title.lower() not in page_lower:
    missing.append(f"title contains {expected_title!r}")
for marker in markers_raw.split("|"):
    if marker.lower() not in page_lower:
        missing.append(marker)
if missing:
    print(
        f"wave1-thread-reply-ready: target thread does not match expected topic: {thread}",
        file=sys.stderr,
    )
    print(f"target-url: {target_url}", file=sys.stderr)
    print("missing markers: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(2)
PY

echo "wave1-thread-reply-ready: checking public proof gate"
bash scripts/public_review_gate.sh

echo
echo "wave1-thread-reply-ready: thread=${thread}"
echo "target-url: ${target_url}"
echo "preflight: target thread page matched expected topic markers"
echo "queue: docs/WAVE1_PUBLIC_TARGET_QUEUE.md"
echo "decision: read the thread first; do not post if stale, closed, or off-topic"
echo "requires-confirmation: yes; do not submit a public comment without final user confirmation"
echo "message:"
echo

case "$thread" in
  terminal-bench-1357)
    cat <<'EOF'
This is a related issue I keep hitting: once runs are expensive, a leaderboard row without cost/version/proof metadata is hard to trust.

The useful unit might be something like: command/test count, wall time, runner or environment version, validation command, and whether failures were observed directly or inferred after the fact.

Boundary question: what is the minimum metadata a benchmark row should expose so another project can compare execution cost without rerunning the task?
EOF
    ;;
  openhands-benchmarks-708)
    cat <<'EOF'
The 332 / 424 mixed bucket feels like the key metadata, not just an implementation detail.

If a run writes both the test and a source-code fix, I would want the published row to expose the patch-shape bucket separately from the final SWT-bench score. Otherwise it is hard to tell whether a low score means weak test generation or just the expected F2P failure mode from source edits under model_patch.

Boundary question: should "mixed test+source patch" be a first-class verdict/metadata field rather than a post-hoc explanation?
EOF
    ;;
  openhands-benchmarks-718)
    cat <<'EOF'
I think this comes down to artifact identity, not just the score delta.

If the same `output.jsonl` can produce a different `output.swtbench.jsonl` after eval-time patch stripping changes, I would expect the published artifact to carry enough provenance to make comparisons stable: eval rule version, runner version or commit, input/output hashes, and possibly a patch-shape bucket.

Boundary question: are rule version, runner commit, and input/output hashes enough to compare artifacts, or should patch shape be first-class metadata too?
EOF
    ;;
esac
