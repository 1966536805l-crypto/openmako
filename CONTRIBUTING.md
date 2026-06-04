# Contributing To OpenMako

OpenMako is currently asking for technical boundary criticism before broader
promotion. Useful contributions should make the public v0.1 evidence clearer,
more reproducible, or more honest.

This is not an endorsement request, promotion request, star request, or repost
request.

## First Review Path

1. Reproduce the public gate:

   ```bash
   ./scripts/public_review_gate.sh
   ```

2. Compare the result with:

   - `docs/REPRODUCE_V0_1.md`
   - `docs/TECHNICAL_REVIEW_PACKET.md`
   - `README.md`

3. Open a structured technical boundary issue:

   https://github.com/1966536805l-crypto/openmako/issues/new?template=technical-boundary-check.yml

## Useful Contributions

- A reproduction failure with command output, platform, Python version, and the
  first mismatching expected signal.
- A README, docs, CI, or release-note correction that narrows an overclaim.
- A focused test that catches a public-boundary drift.
- A concrete Evidence Court supplied-record fixture that shows a missing or
  confusing failure boundary.

## Not Useful

- Asking people to star, repost, or promote the repository.
- Treating internal planning docs or archived experiments as v0.1 proof.
- Claiming broad unknown-repository SWE repair from the focused public gate.
- Claiming external endorsement without a named public reviewer saying it
  publicly.

## Patch Boundary

Small patches are preferred. If a change touches public claims, update
`tests/test_public_metadata.py` so the boundary remains testable.

Before claiming the public snapshot is healthy, run:

```bash
./scripts/public_review_gate.sh
```
