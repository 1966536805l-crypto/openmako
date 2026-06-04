# OpenMako Wave 1 Public Target Queue

This queue is for finding public technical-boundary review surfaces.
It is not proof that outreach happened.
It is not evidence of endorsement, stars, reposts, or external review.

Use this only after `bash scripts/public_review_gate.sh` passes on the current
checkout. Send one short note at a time. Do not create a new issue in another
project unless the project norms allow meta/tooling review requests there.

## Verified Public Surfaces

These public pages were checked for reachability before adding them here.

| Order | Target | Public surface | Current surface state | Message helper | First move |
| --- | --- | --- | --- | --- | --- |
| 1 | SWE-agent | `https://github.com/SWE-agent/SWE-agent/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh swe-agent` | Look for an existing benchmark/evaluation/evidence thread. If there is no fit, do not open a new issue without a project-specific invitation. |
| 2 | Terminal-Bench / Harbor | `https://github.com/harbor-framework/terminal-bench/discussions` | Discussions page reachable; issues page also reachable. | `bash scripts/wave1_review_request.sh terminal-bench` | Prefer an existing discussion about benchmark methodology, verifier evidence, or terminal-agent evaluation. |
| 3 | Aider | `https://github.com/Aider-AI/aider/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh aider` | Look for a thread about coding-agent reliability or test evidence. If none exists, skip rather than creating unrelated noise. |
| 4 | OpenHands | `https://github.com/OpenHands/OpenHands/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh openhands` | Look for a thread about agent evaluation, logs, or evidence. Do not ask maintainers to endorse OpenMako. |

## Send Rule

Post only a boundary-check ask:

- What wording overclaims?
- What proof is missing?
- Does README make the project sound broader than the focused gate?
- Is the supplied-record Evidence Court boundary clear?

Do not ask for stars, reposts, promotion, endorsement, or maintainer approval.

## Stop Rule

Stop outreach and fix the repository first if any reviewer says:

- the public gate does not reproduce,
- README claims more than tests or CI prove,
- an issue/release/workflow link is confusing,
- the request looks like promotion rather than technical review.
