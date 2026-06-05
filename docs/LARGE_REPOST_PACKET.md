# OpenMako Post-Review Broader Share Packet

Use this only after a named external reviewer has posted public technical
feedback and that feedback has been recorded with the external review record
form. This packet is for broader technical writers, maintainers, and community
curators after the boundary has been checked.

It is not a launch claim, endorsement request, star request, or repost request.
It must not be used while OpenMako only has self-written proof.

Checked command:

```bash
bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review
```

`REVIEW_RECORD_ISSUE_URL` must be a reachable OpenMako issue created from the
external review record form:

```text
https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml
```

The command requires an explicit human confirmation flag, verifies that the
issue page is reachable, contains the structured external review record fields,
and includes a selected review verdict. It then runs the public proof gate
before printing text. It does not post messages, contact anyone, ask for stars,
ask for reposts, or record outreach as evidence.

This check cannot prove non-self authorship by itself. Before using this packet,
inspect the linked public review and confirm that a named external reviewer
actually wrote the feedback.

## Gate

Do not use this packet unless all are true:

- `./scripts/public_review_gate.sh` passes on the current `main`.
- A named external reviewer has posted public technical feedback.
- The feedback is recorded in a public OpenMako external review record issue.
- Any overclaim or unclear boundary from that review has been fixed or linked
  as follow-up.

## Broad Technical Summary

```text
OpenMako v0.1 is a small evidence harness for coding-agent repair runs. The useful part is not a leaderboard claim: it makes patch scope, test proof, learning-effect checks, and supplied-run audit evidence easy to inspect before anyone treats an agent result as real.
```

## Short Repost-Ready Note

```text
OpenMako v0.1 is a narrow evidence harness for coding-agent repair runs. It checks patch scope, test proof, learning-effect evidence, and supplied-run audit records before broader claims. Public proof: https://github.com/1966536805l-crypto/openmako
```

## Evidence Links

- Repository: https://github.com/1966536805l-crypto/openmako
- Public proof command: `./scripts/public_review_gate.sh`
- Technical boundary issue: https://github.com/1966536805l-crypto/openmako/issues/2
- External review record form:
  https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml
- Technical review packet: `docs/TECHNICAL_REVIEW_PACKET.md`

## Do Not Say

- Do not say OpenMako has broad SWE-bench-scale repair proof.
- Do not say OpenMako replaces Hermes, OpenClaw, OpenHands, SWE-agent, Aider,
  Claude Code, Codex, Cursor, or Devin.
- Do not say it has external endorsement unless the linked public review says
  that.
- Do not ask for stars, reposts, promotion, or endorsement.

## Failure Mode

If the external review record is missing, the right next action is not a broad
post. The next action is to ask for technical boundary criticism on issue #2 or
through the structured technical boundary issue form.
