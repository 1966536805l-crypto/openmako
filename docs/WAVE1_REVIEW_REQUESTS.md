# OpenMako Wave 1 Review Requests

Last refreshed: 2026-06-04.

These are copyable technical-review requests for the Wave 1 targets in
`docs/REVIEWER_TARGETS.md`. They are not endorsement requests, promotion
requests, star requests, repost requests, or public traction evidence. They are
also not proof that outreach has happened.

Use one message at a time. Send the short note first. Only send the proof card
or longer context if the reviewer asks. If a reviewer replies with a concrete
boundary issue, stop outreach and fix the repository before sending broader
messages.

## Common Proof Card

Run this before sending a request and paste the final proof-card block if the
reviewer asks for command output:

```bash
./scripts/public_proof_card.sh
```

Expected final block:

```text
openmako-public-proof-card: PASS
scope: focused learning-effect gate; public metadata boundary; supplied-record Evidence Court audit
not-proof: broad unknown-repository SWE repair; external endorsement; star or repost traction
review-request: https://github.com/1966536805l-crypto/openmako/issues/2
record-external-review: https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml
```

## SWE-Bench / SWE-Agent Review Request

```text
Could you poke holes in OpenMako v0.1's boundary?

It has one focused learning-effect gate, patch-scope checks, metadata checks,
and a supplied-record audit. It does not claim SWE-bench-scale repair.

The useful review is whether the README and proof command keep that boundary clear.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: ./scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Terminal-Bench / Agent-Eval Review Request

```text
Could you sanity-check OpenMako v0.1's evidence boundary?

It is a narrow evidence harness, not a broad terminal-agent benchmark. I am trying to find places where the wording goes beyond the public gate, README, or Evidence Court supplied-record audit.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: ./scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Aider Community Review Request

```text
Could you check whether OpenMako v0.1 is useful or too noisy from a coding-agent user's view?

It is not a replacement for Aider or any coding agent. The claim is narrower: run evidence, patch-scope discipline, test-proof checks, and an Evidence Court audit over supplied records.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: ./scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## OpenHands / Software-Agent Review Request

```text
Could you check OpenMako v0.1 for overclaim?

The current claim is not that OpenMako is a full software agent. It is an evidence harness for coding-agent repair runs, with one focused public learning-effect gate and Evidence Court audit for supplied records. The useful review is whether README, tests, and CI prove only that claim.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: ./scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Do Not Send

- Do not ask the reviewer to star, repost, endorse, or promote the repository.
- Do not send the boundary-clear follow-up before a named reviewer posts public
  feedback.
- Do not summarize private feedback as public evidence.
- Do not keep sending outreach if the first review finds a concrete overclaim;
  fix the repository first.
