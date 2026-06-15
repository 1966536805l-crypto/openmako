# Reviewer Outreach Draft

Use this only for technical reviewers who might give boundary criticism. Do not
use it as a mass-promotion message.

## Short Message

Hi,

I'm looking for technical boundary criticism on OpenMako v0.1.0:

https://github.com/1966536805l-crypto/openmako/issues/2

The narrow claim is that OpenMako is an evidence harness for coding-agent repair
runs, with focused public evidence gates, two external-source held-out repair
checks, a repo-defined independent held-out packet, public artifact/fresh-clone
proof, and an Evidence Court CLI for auditing supplied records.

If you have time, the useful check is whether README, tests, release notes, and
GitHub Actions prove only that claim, or whether any wording still overclaims.
The review packet is here:

https://github.com/1966536805l-crypto/openmako/blob/main/docs/TECHNICAL_REVIEW_PACKET.md

The current exact-commit reproduction target is:

```text
main=0c5741ed52447ca18876ec3e730ef361025650db
focused CI=https://github.com/1966536805l-crypto/openmako/actions/runs/27524605204
autonomous CI=https://github.com/1966536805l-crypto/openmako/actions/runs/27524605186
fresh-clone log sha256=5a05302adabfa85b274b17dd6d366e52540b97471047c461e46aee0d38b4d4d8
```

If you decide to discuss it publicly after review, this share packet keeps the
claim narrow:

https://github.com/1966536805l-crypto/openmako/blob/main/docs/PUBLIC_SHARE_PACKET.md

I'm not asking for endorsement, stars, reposts, or promotion. A critical comment
pointing to a specific file, line, command, workflow, or missing artifact would
be more useful.

## Who To Send First

Send this first to people who can check the technical boundary, not to general
influencers.

1. Maintainers or reviewers of coding-agent eval, benchmark, or CI tooling.
2. Engineers who publicly write about agent reliability, test evidence, or
   benchmark methodology.
3. OSS maintainers who have criticized agent overclaiming or weak proof.

Do not send to general influencers before at least one public technical boundary
review exists.

For the public-source target map and contact order, see:

https://github.com/1966536805l-crypto/openmako/blob/main/docs/REVIEWER_TARGETS.md

## Follow-Up Rule

Only after a reviewer has independently said the boundary is clear, ask whether
their public criticism or summary may be linked as external review context.
Do not ask them to promote the project.

## Success Signal

The first useful outcome is a public technical critique on issue #2 or a linked
review that identifies a concrete overclaim, missing proof, confusing boundary,
or confirms no obvious boundary mismatch after inspection.
