# OpenMako Wave 1 Review Requests

Last refreshed: 2026-06-05.

These are short notes for asking technical reviewers to check the v0.1 boundary
for the Wave 1 targets in `docs/REVIEWER_TARGETS.md`. They are not endorsement
requests, promotion requests, star requests, repost requests, or public traction
evidence. They are also not proof that outreach has happened.

Use one message at a time. Send the short note first. Only send the proof card
or longer context if the reviewer asks. If a reviewer replies with a concrete
boundary issue, stop outreach and fix the repository before sending broader
messages.

## Common Proof Card

Run this before sending a request and paste the final proof-card block if the
reviewer asks for command output:

```bash
bash scripts/public_proof_card.sh
```

Expected final block:

```text
openmako-public-proof-card: PASS
scope: focused learning-effect gate; public metadata boundary; supplied Evidence Court audit; artifact provenance; SWTBench patch artifact; config-only repair fixture; runtime-shadowing and verifier/CI tamper fixtures; supplied transcript adapter matrix
not-proof: broad unknown-repository SWE repair; external endorsement; star or repost traction
review-request: https://github.com/1966536805l-crypto/openmako/issues/2
record-external-review: https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml
```

## SWE-Bench / SWE-Agent Review Request

```text
Can you point out where OpenMako v0.1 overclaims its evidence boundary?

Current public proof covers one focused learning-effect gate, patch-scope
checks, metadata checks, supplied-record/provenance audits, a config-only
false-positive fixture, runtime-shadowing and verifier/CI tamper review-risk
fixtures, and a supplied transcript adapter matrix. It does not claim
SWE-bench-scale repair or native runtime/CI hardening.

I'm mainly looking for README lines or proof-command gaps that overclaim.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: bash scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Terminal-Bench / Agent-Eval Review Request

```text
Can you check OpenMako v0.1's evidence boundary?

It is a narrow evidence harness, not a broad terminal-agent benchmark. I'm looking for README lines or proof-command gaps that overclaim.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: bash scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Aider Community Review Request

```text
Could you check whether OpenMako v0.1 is useful or too noisy from a coding-agent user's view?

It is not a replacement for Aider or any coding agent. The claim is narrower: run evidence, patch-scope discipline, test-proof checks, and an Evidence Court audit over supplied records.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: bash scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## OpenHands / Software-Agent Review Request

```text
Could you check OpenMako v0.1 for overclaim?

The current claim is not that OpenMako is a full software agent. It is an evidence harness for coding-agent repair runs, with one focused public learning-effect gate and Evidence Court audit for supplied records. The useful review is whether README, tests, and CI prove only that claim.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: bash scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Agent Runtime / OpenClaw-Hermes Review Request

Use this only for reviewers already discussing agent runtime mechanics such as
skills, memory, ACP-style sessions, desktop control, or external harness
orchestration. Do not send it as a general launch note.

```text
Could you sanity-check whether OpenMako's runtime-adjacent docs overread the current proof?

It references skills, memory, ACP-style sessions, and desktop-control work as trends or future bets. The current public proof is narrower: evidence harness, patch-scope checks, test-proof checks, supplied-record/provenance audits, a config-only false-positive fixture, runtime-shadowing and verifier/CI tamper review-risk fixtures, and a supplied transcript adapter matrix.

I'm looking for any README/docs wording that makes it sound like those runtime features are already public v0.1 proof.

Repo: https://github.com/1966536805l-crypto/openmako
Proof command: bash scripts/public_proof_card.sh
Review issue: https://github.com/1966536805l-crypto/openmako/issues/2
```

## Do Not Send

- Do not ask the reviewer to star, repost, endorse, or promote the repository.
- Do not send the boundary-clear follow-up before a named reviewer posts public
  feedback.
- Do not summarize private feedback as public evidence.
- Do not keep sending outreach if the first review finds a concrete overclaim;
  fix the repository first.
