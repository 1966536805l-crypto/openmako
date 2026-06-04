# OpenMako Reviewer Target Map

Last refreshed: 2026-06-04.

This is a public outreach planning map, not proof of endorsement, promotion,
stars, reposts, or external review. Verify each source again before contacting
anyone.

## Outreach Rule

The first ask is technical boundary criticism. Do not ask for stars, reposts,
promotion, or endorsement. A useful outcome is a public review that links the
exact file, command, workflow, issue, release, or missing proof checked.

Only after a named reviewer has posted public feedback should the review be
recorded with:

https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml

## Target Waves

| Wave | Target ecosystem | Public source signal | Why this fit exists | First ask |
| --- | --- | --- | --- | --- |
| 1 | SWE-bench / SWE-agent researchers and users | SWE-bench evaluates real GitHub issue repair; SWE-agent targets automatic GitHub issue fixing. Sources: `https://arxiv.org/abs/2310.06770`, `https://github.com/swe-agent/swe-agent` | They can judge whether OpenMako's narrow evidence claim is clearly separated from SWE-bench-scale claims. | Boundary criticism on issue #2 or the structured review form. |
| 1 | Terminal-Bench / Harbor evaluation community | Terminal-Bench is a benchmark for AI agents in real terminal environments. Source: `https://github.com/harbor-framework/terminal-bench` | OpenMako's public gate is also an agent-evidence harness, but narrower; this audience can spot benchmark overclaiming. | Reproduce `./scripts/public_review_gate.sh`; comment on missing evidence or unclear scope. |
| 1 | Aider maintainer/community | Aider is AI pair programming in the terminal. Source: `https://github.com/aider-ai/aider` | Aider users understand code-editing agents and can judge whether OpenMako's test-proof and patch-scope checks are useful. | Ask whether the public claim is useful and bounded, not whether Aider should endorse it. |
| 1 | OpenHands maintainer/community | OpenHands describes AI-driven development and a software-agent SDK. Source: `https://github.com/OpenHands/OpenHands` | OpenHands sits close to coding-agent execution; reviewers can judge evidence-harness positioning. | Ask for concrete boundary critique against README, tests, and CI. |
| 2 | AI engineering writers and conference/community curators | Swyx describes Latent.Space and AI Engineer community work. Source: `https://swyx.io/about` | They can amplify only after there is credible technical review, because their audience is broader. | Share a boundary-clear review record, not a raw star/repost request. |
| 2 | Software engineering trade writers | The Pragmatic Engineer has covered parallel AI agents and AI coding tools. Source: `https://blog.pragmaticengineer.com/` | This can reach engineering leaders, but only after the technical boundary has been externally checked. | Offer a concise evidence packet and the external review record. |

## Do Not Contact Yet

- General AI influencers who do not review code, tests, CI, or benchmark
  methodology.
- Product launch newsletters before one public external review exists.
- Any target with a message that asks for stars, reposts, or endorsement.
- Any private feedback channel that cannot later be linked as public evidence.

## Minimum Packet For Each Contact

- Repository: `https://github.com/1966536805l-crypto/openmako`
- Review issue: `https://github.com/1966536805l-crypto/openmako/issues/2`
- Public target queue: `docs/WAVE1_PUBLIC_TARGET_QUEUE.md`
- Wave 1 request copy: `docs/WAVE1_REVIEW_REQUESTS.md`
- Reproduction guide: `docs/REPRODUCE_V0_1.md`
- Technical review packet: `docs/TECHNICAL_REVIEW_PACKET.md`
- Public gate: `./scripts/public_review_gate.sh`
- External review record form:
  `https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml`

## Stop Conditions

Stop outreach and fix the repository first if a reviewer reports:

- README overclaims beyond the public gate.
- The public gate fails on a fresh checkout.
- A release, issue, or CI link is missing or misleading.
- The project wording implies endorsement, promotion, stars, reposts, or broad
  agent capability without evidence.
