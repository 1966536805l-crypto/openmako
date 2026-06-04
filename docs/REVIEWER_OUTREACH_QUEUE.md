# Reviewer Outreach Queue

Snapshot date: 2026-06-05.

This is a routing queue for technical review, not a promotion list. Do not use
it to ask for stars, reposts, endorsements, or competitive comparisons.

## Send Gate

Do not contact reviewers until all of these are true:

- The selected review slice is committed on a clean branch.
- Remote CI is green for the branch or PR.
- The relevant artifact or log is downloadable or linked.
- `docs/PUBLIC_REVIEW_ENTRYPOINTS.md` points to the public branch or PR.
- `.github/ISSUE_TEMPLATE/technical-boundary-review.yml` is available in the
  pushed branch or default branch.

If any item is false, keep the work local.

## Copy Gate

Before posting a GitHub issue, release note, comment, DM, or X thread, run:

```bash
python3 scripts/outreach_copy_gate.py
```

The gate is a local five-reader pass:

- skeptic-reader: blocks star-bait, hype, and unsupported competitor claims.
- boundary-reader: requires a visible no-stars/no-endorsement boundary.
- evidence-reader: requires proof, command, artifact, CI, or evidence language.
- reviewer-reader: requires a review question, not a promotional ask.
- send-operator: requires send gates and stop conditions for reviewer outreach.

This does not replace actual external criticism or a five-agent copy review when
subagents are available. It only prevents obvious publish-before-evidence copy.

## Priority Order

### 1. Agent Reliability / Evaluation Maintainers

Why:

```text
They are most likely to care about claim-vs-evidence boundaries, failed verification, and benchmark overclaim.
```

Ask:

```text
Can you check whether the claim is narrower than the evidence, and whether the missing proof is obvious?
```

Do not ask:

```text
Can you endorse this agent?
Can you compare this favorably to your project?
```

Ready evidence:

- Evidence Court v0.1 smoke artifact or PR CI artifact
- autonomy stop-rule direct CLI/v3 proof
- `Technical boundary review` issue template

### 2. Coding-Agent Tool Maintainers

Why:

```text
They see real failure modes where agents claim success without enough evidence.
```

Ask:

```text
Does this catch a failure class you have seen, or is the boundary wrong?
```

Do not ask:

```text
Would you switch to OpenMako?
Can you promote OpenMako to your users?
```

Ready evidence:

- one 30-second command
- one failing demo
- one issue template for boundary feedback

### 3. Benchmark / SWE-Style Evaluation Readers

Why:

```text
They can critique whether narrow benchmark evidence is being overstated.
```

Ask:

```text
What claim would you allow from this evidence, and what claim would you reject?
```

Do not ask:

```text
Does this prove broad SWE-style repair?
```

Ready evidence:

- `docs/OPENMAKO_CAPABILITY_EVIDENCE.md`
- exact patch scope
- command output or artifact hash

### 4. CLI / Developer Tool Users

Why:

```text
They can test whether the first command and README explanation are understandable.
```

Ask:

```text
Can you run the first command, and where does the README confuse you?
```

Do not ask:

```text
Can you star it if it looks good?
```

Ready evidence:

- install command
- `mako evidence-court --demo bad-run`
- expected `Verdict: FAIL`

## Send Template

Only use this after the send gate passes:

```text
I am looking for technical boundary criticism, not stars or endorsement.

Could you check this OpenMako review slice?

Claim:
<one narrow claim>

Evidence:
<public PR / CI / artifact link>

Question:
Does the claim match the evidence, or is it too broad / missing proof / confusing?

Issue template for feedback:
<technical-boundary-review issue link>
```

## Stop Conditions

Stop outreach for this slice if:

- A reviewer finds a real overclaim.
- The public CI artifact cannot be opened.
- The first command fails on a clean checkout.
- The issue template or README asks for stars, endorsement, or promotion.
- The review question cannot be answered in under five minutes.

Fix the slice before contacting more people.
