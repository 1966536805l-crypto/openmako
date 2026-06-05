# OpenMako Wave 1 Public Target Queue

This queue is for finding public technical-boundary review surfaces.
It is not proof that outreach happened.
It is not evidence of endorsement, stars, reposts, or external review.

Use this only after `bash scripts/public_review_gate.sh` passes on the current
checkout. To generate a checked message, run
`bash scripts/wave1_send_ready.sh TARGET`. Send one short note at a time. Do not
create a new issue in another project unless the project norms allow
meta/tooling review requests there.

For an existing public thread where a project link would look like promotion,
prefer `bash scripts/wave1_send_ready.sh --linkless TARGET`. It still runs the
public proof gate first, but prints a question without repo, proof-command, or
review-issue links. The output includes `THREAD_HOOK`; replace it with a
concrete point from the target thread before posting. If no concrete hook fits,
skip the thread.

For a thread-specific draft, run
`bash scripts/wave1_thread_reply_ready.sh THREAD`. This still does not send the
message or record outreach as evidence. The helper re-fetches the selected
thread and refuses to print a draft if the page no longer matches the expected
topic markers.

## Verified Public Surfaces

These public pages were checked for reachability before adding them here.

| Order | Target | Public surface | Current surface state | Message helper | First move |
| --- | --- | --- | --- | --- | --- |
| 1 | SWE-agent | `https://github.com/SWE-agent/SWE-agent/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh swe-agent` | Look for an existing benchmark/evaluation/evidence thread. If there is no fit, do not open a new issue without a project-specific invitation. |
| 2 | Terminal-Bench / Harbor | `https://github.com/harbor-framework/terminal-bench/discussions` | Discussions page reachable; issues page also reachable. | `bash scripts/wave1_review_request.sh terminal-bench` | Prefer an existing discussion about benchmark methodology, verifier evidence, or terminal-agent evaluation. |
| 3 | Aider | `https://github.com/Aider-AI/aider/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh aider` | Look for a thread about coding-agent reliability or test evidence. If none exists, skip rather than creating unrelated noise. |
| 4 | OpenHands | `https://github.com/OpenHands/OpenHands/issues` | Issues page reachable; discussions page not public. | `bash scripts/wave1_review_request.sh openhands` | Look for a thread about agent evaluation, logs, or evidence. Do not ask maintainers to endorse OpenMako. |

## Existing Threads To Inspect Before Posting

These are candidate reading targets, not approved posting targets. Read the
thread first and post only if the OpenMako boundary question directly matches
the existing discussion.

| Fit | Target | Thread | Why it is on the queue | Posting decision |
| --- | --- | --- | --- | --- |
| Best current fit | Terminal-Bench / Harbor | `https://github.com/harbor-framework/terminal-bench/discussions/1357` | Discussion asks about the cost of executing a test, which is close to verifier/evaluation evidence. | Inspect first; if still relevant, use `bash scripts/wave1_thread_reply_ready.sh terminal-bench-1357`. |
| Best current fit | OpenHands Benchmarks | `https://github.com/OpenHands/benchmarks/issues/708` | Current benchmark issue about non-test patch stripping and patch-shape evidence. | Inspect first; if still relevant, use `bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-708`. |
| Best current fit | OpenHands Benchmarks | `https://github.com/OpenHands/benchmarks/issues/718` | Current benchmark issue about whether rule changes affect comparability of historical runs. | Inspect first; if still relevant, use `bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-718`. |
| Skip unless directly relevant | OpenHands | `https://github.com/OpenHands/OpenHands/issues/10767` | Closed as not planned; originally about reproducing SWE-bench result claims. | Do not revive a closed main-repo issue for OpenMako outreach. |
| Read-only / weak fit | SWE-agent | `https://github.com/SWE-agent/SWE-agent/issues/21` | Logs from SWE-agent running on SWE-Bench. | Learn wording; do not post unless the thread asks for boundary-review tools. |
| Read-only / weak fit | SWE-agent | `https://github.com/SWE-agent/SWE-agent/issues/580` | all_preds.jsonl question around SWE-Bench Lite output. | Learn wording; likely too issue-specific for an OpenMako note. |
| Read-only / weak fit | SWE-agent | `https://github.com/SWE-agent/SWE-agent/issues/563` | Reusing previous built environments for faster evaluation. | Learn wording; likely too operational for a boundary request. |
| Read-only / weak fit | Aider | `https://github.com/Aider-AI/aider/issues/110` | Prompting-strategy discussion mentions benchmark and evidence terms. | Inspect only; do not turn a broad prompting thread into promotion. |
| Skip unless directly relevant | Aider | `https://github.com/Aider-AI/aider/issues/2588` | Solved benchmark issue. | Do not revive a solved issue for OpenMako outreach. |
| Skip unless directly relevant | OpenHands | `https://github.com/OpenHands/OpenHands/issues/12043` | SWE-bench evaluation issue about `chown` time. | Use only if commenting on that concrete bug; not for a generic review ask. |

## Send Rule

Post only a boundary-check ask:

- What wording overclaims?
- What proof is missing?
- Does README make the project sound broader than the focused gate?
- Is the supplied-record Evidence Court boundary clear?

Do not ask for stars, reposts, promotion, endorsement, or maintainer approval.
Do not post into a bug thread unless the comment addresses that thread's
existing question. If the fit is weak, skip the thread instead of making noise.
Do not post the same generic message to multiple threads.

## Stop Rule

Stop outreach and fix the repository first if any reviewer says:

- the public gate does not reproduce,
- README claims more than tests or CI prove,
- an issue/release/workflow link is confusing,
- the request looks like promotion rather than technical review.
