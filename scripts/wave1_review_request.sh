#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
usage: ./scripts/wave1_review_request.sh TARGET

Targets:
  swe-agent
  terminal-bench
  aider
  openhands
  agent-runtime

Prints one short technical-boundary review request. It does not send messages,
ask for stars, ask for reposts, or record outreach as evidence.
EOF
}

if [ "$#" -ne 1 ]; then
  usage >&2
  exit 2
fi

repo="https://github.com/1966536805l-crypto/openmako"
issue="https://github.com/1966536805l-crypto/openmako/issues/2"
proof="bash scripts/public_proof_card.sh"

case "$1" in
  swe-agent)
    cat <<EOF
Can you point out where OpenMako v0.1 overclaims its evidence boundary?

Current public proof covers one focused learning-effect gate, patch-scope
checks, metadata checks, and a supplied-record audit. It does not claim
SWE-bench-scale repair.

I'm mainly looking for README lines or proof-command gaps that overclaim.

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
    ;;
  terminal-bench)
    cat <<EOF
Can you check OpenMako v0.1's evidence boundary?

It is a narrow evidence harness, not a broad terminal-agent benchmark. I'm
looking for README lines or proof-command gaps that overclaim.

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
    ;;
  aider)
    cat <<EOF
Could you check whether OpenMako v0.1 is useful or too noisy from a coding-agent user's view?

It is not a replacement for Aider or any coding agent. The claim is narrower:
run evidence, patch-scope discipline, test-proof checks, and an Evidence Court
audit over supplied records.

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
    ;;
  openhands)
    cat <<EOF
Could you check OpenMako v0.1 for overclaim?

The current claim is not that OpenMako is a full software agent. It is an
evidence harness for coding-agent repair runs, with one focused public
learning-effect gate and Evidence Court audit for supplied records. The useful
review is whether README, tests, and CI prove only that claim.

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
    ;;
  agent-runtime)
    cat <<EOF
Could you sanity-check whether OpenMako's runtime-adjacent docs overread the current proof?

It references skills, memory, ACP-style sessions, and desktop-control work as trends or future bets. The current public proof is narrower: evidence harness, patch-scope checks, test-proof checks, and supplied-record audit.

I'm looking for any README/docs wording that makes it sound like those runtime features are already public v0.1 proof.

Repo: ${repo}
Proof command: ${proof}
Review issue: ${issue}
EOF
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "unknown target: $1" >&2
    usage >&2
    exit 2
    ;;
esac
