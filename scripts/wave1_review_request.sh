#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: ./scripts/wave1_review_request.sh [--linkless] TARGET

Targets:
  swe-agent
  terminal-bench
  aider
  openhands
  agent-runtime

Prints one short technical-boundary review request. It does not send messages,
ask for stars, ask for reposts, or record outreach as evidence.

Use --linkless for an existing public thread where a cold-start project link
would look promotional. Linkless messages omit repo, proof-command, and issue
links, and include a required THREAD_HOOK placeholder. Do not post until the
placeholder is replaced with a concrete point from the target thread.
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

target="$1"
repo="https://github.com/1966536805l-crypto/openmako"
issue="https://github.com/1966536805l-crypto/openmako/issues/2"
proof="bash scripts/public_proof_card.sh"

print_footer() {
  if [ "$linkless" -eq 1 ]; then
    return 0
  fi
  cat <<EOF

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
}

case "$target" in
  swe-agent)
    if [ "$linkless" -eq 1 ]; then
      cat <<'EOF'
THREAD_HOOK: replace this with the specific eval-proof point from the thread.

Question: for a narrow repair run, would touched-file scope, exact test
command, and exit status be enough to keep the claim bounded, or would you also
require runner version and transcript?
EOF
    else
      cat <<EOF
Can you point out where OpenMako v0.1 overclaims its evidence boundary?

Current public proof covers one focused learning-effect gate, patch-scope
checks, metadata checks, and a supplied-record audit. It does not claim
SWE-bench-scale repair.

I'm mainly looking for README lines or proof-command gaps that overclaim.
EOF
    fi
    print_footer
    ;;
  terminal-bench)
    if [ "$linkless" -eq 1 ]; then
      cat <<'EOF'
THREAD_HOOK: replace this with the specific test-cost or eval-proof point from
the thread.

Question: if a terminal-agent result says it ran the intended tests, is command
transcript plus exit status enough proof, or should the row also carry output
hash and runner version?
EOF
    else
      cat <<EOF
Can you check OpenMako v0.1's evidence boundary?

It is a narrow evidence harness, not a broad terminal-agent benchmark. I'm
looking for README lines or proof-command gaps that overclaim.
EOF
    fi
    print_footer
    ;;
  aider)
    if [ "$linkless" -eq 1 ]; then
      cat <<'EOF'
THREAD_HOOK: replace this with the specific reliability or benchmark point from
the thread.

Question: for a small coding-agent repair run, which evidence would make you
trust it first: touched-file scope, exact test command, transcript, or
before/after diff?
EOF
    else
      cat <<EOF
Could you check whether OpenMako v0.1 is useful or too noisy from a coding-agent user's view?

It is not a replacement for Aider or any coding agent. The claim is narrower:
run evidence, patch-scope discipline, test-proof checks, and an Evidence Court
audit over supplied records.
EOF
    fi
    print_footer
    ;;
  openhands)
    if [ "$linkless" -eq 1 ]; then
      cat <<'EOF'
THREAD_HOOK: replace this with the specific log, patch-shape, or eval-artifact
point from the thread.

Question: is a plain JSON run record useful for auditing patch scope, command
proof, and missing-test failures, or is native log format required before that
check is credible?
EOF
    else
      cat <<EOF
Could you check OpenMako v0.1 for overclaim?

The current claim is not that OpenMako is a full software agent. It is an
evidence harness for coding-agent repair runs, with one focused public
learning-effect gate and Evidence Court audit for supplied records. The useful
review is whether README, tests, and CI prove only that claim.
EOF
    fi
    print_footer
    ;;
  agent-runtime)
    if [ "$linkless" -eq 1 ]; then
      cat <<'EOF'
THREAD_HOOK: replace this with the specific runtime-docs or session-control
point from the thread.

Question: for docs that mention planned runtime work, is "implemented and
tested" versus "exploring next" enough boundary wording, or would you expect a
separate proof table?
EOF
    else
      cat <<EOF
Could you sanity-check whether OpenMako's runtime-adjacent docs overread the current proof?

It references skills, memory, ACP-style sessions, and desktop-control work as trends or future bets. The current public proof is narrower: evidence harness, patch-scope checks, test-proof checks, and supplied-record audit.

I'm looking for any README/docs wording that makes it sound like those runtime features are already public v0.1 proof.
EOF
    fi
    print_footer
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "unknown target: $target" >&2
    usage >&2
    exit 2
    ;;
esac
