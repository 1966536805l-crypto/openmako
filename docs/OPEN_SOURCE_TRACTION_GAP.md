# Open-Source Traction Gap

Snapshot date: 2026-06-05.

This page is not a marketing script. It is a gap list for making OpenMako
easier to evaluate from the outside.

## Current Public Gap

OpenMako has local technical evidence, but weak public entrypoints.

The current highest-leverage gap is not another broad claim. It is a public path
where a reviewer can answer:

```text
What exactly should I inspect first, what command proves it, and what is not claimed?
```

## Comparable Project Signals

These are current public-page observations from primary project pages. Star
counts and page text can drift; re-check before using numbers in public copy.

| Project | Public signal that makes people click | What OpenMako should copy | What OpenMako should not copy |
| --- | --- | --- | --- |
| OpenClaw | One-line "personal AI assistant" positioning, app screenshots, install instructions, docs, support channels, and a visible star/fork/contributor block | Clear first-screen use case and concrete reviewer path | Do not imply general assistant maturity or broad app ecosystem |
| Hermes Agent | Clear "personal AI agent that brings the power of the Web to you" claim, visible docs, examples, and install steps | Simple problem statement plus runnable start path | Do not claim web-scale general agency without matching adapters and evals |
| OpenCode | Short "AI coding agent" positioning, terminal-first install path, docs, Discord, and npm/build badges | Compact CLI install/run path and status badges | Do not use badges as a substitute for evidence |
| OpenHands | "AI-powered software development agents" positioning, docs, Slack, examples, SDK/CLI/GUI/cloud entrypoints, and tech-report links | Multiple evaluation entrypoints for different reviewers | Do not claim broad software-engineering autonomy from a narrow slice |
| Cline | IDE-native task framing, visible docs, Discord/Reddit/community links, screenshots, and marketplace install path | Show the fastest path for a developer to try the narrow claim | Do not pretend OpenMako has comparable IDE distribution yet |
| Aider | Tight "AI pair programming in your terminal" framing, install path, docs, GitHub stats, and strong social proof quotes | One sentence that says what the tool is and what command to run | Do not add social proof until it exists |

Primary pages checked:

- https://github.com/openclaw/openclaw
- https://github.com/NousResearch/hermes-agent
- https://github.com/sst/opencode
- https://github.com/All-Hands-AI/OpenHands
- https://github.com/cline/cline
- https://github.com/Aider-AI/aider

## OpenMako Action List

### 1. Public Reviewer Entrypoint

Status: local draft exists.

Current file:

```text
docs/PUBLIC_REVIEW_ENTRYPOINTS.md
```

Why it matters:

```text
It gives a reviewer two bounded doors: Evidence Court v0.1 and the autonomy stop-rule candidate.
```

Next gate:

```text
Commit and push a clean branch, then replace local-only evidence with remote CI/artifact links.
```

### 2. Reviewer Outreach Queue

Status: local draft exists.

Current file:

```text
docs/REVIEWER_OUTREACH_QUEUE.md
```

Why it matters:

```text
It separates technical-review targets from star/repost asks and defines stop conditions.
```

Next gate:

```text
Use it only after a clean branch, remote CI artifact, and issue template are public.
```

### 3. One Runnable Proof Before Any Outreach

Current best candidate:

```text
/tmp/openmako-autonomy-stop-candidate-20260605b
```

Local proof:

```text
direct CLI/v3 proof: 2 passed, 1 warning in 1.63s
related suite: 49 passed, 6 warnings in 17.36s
patch SHA-256: d09cd5c96548a706fe31e00c4b41e811d8a44da49a26aa687fff28a00d563cb3
```

Next gate:

```text
Push this as a named branch and verify remote CI.
```

### 4. Human-Sounding Outreach

Use a narrow review request:

```text
I am not asking for stars or endorsement.

Can you check whether these two OpenMako claims match the repo evidence?

1. Evidence Court v0.1 catches unsupported success claims inside supplied agent-run records.
2. The autonomy stop-rule candidate blocks a second write when verification is missing or failed.

I mainly want boundary criticism: overclaim, missing proof, confusing wording, or a better minimal gate.
```

Do not send:

```text
Please star my project.
This is better than Hermes/OpenClaw.
OpenMako has solved autonomous coding.
```

## Readiness Verdict

Current status:

```text
Not launch-ready for star growth.
Reviewer-ready only after clean branch + remote CI artifact.
```

Reason:

```text
The local evidence is useful, but public reviewers need a URL they can open and commands or artifacts they can verify.
```
