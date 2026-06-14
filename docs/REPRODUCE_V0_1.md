# OpenMako v0.1 Reproduction Guide

This guide is for technical reviewers who want to reproduce the narrow public
v0.1 claim before reading broader repository code. It is not an endorsement
request, promotion request, star request, or repost request.

## Claim Under Test

OpenMako v0.1 demonstrates one learning-effect repair check inside an
external-source benchmark gate, one held-out function-level source repair check
inside an external-heldout benchmark gate, plus an Evidence Court CLI for
auditing supplied records.

Do not treat older planning docs, archived quant experiments, desktop-control
experiments, or local-only benchmark notes as proof for this claim.

## Fresh Checkout

```bash
git clone https://github.com/1966536805l-crypto/openmako.git
cd openmako
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest
```

## One-Command Public Gate

```bash
./scripts/public_review_gate.sh
```

Expected high-level signal:

```text
public-review-gate: running planner focused public test
1 passed
public-review-gate: running external-source benchmark gate
external-source-benchmark-gate: running selected OpenClaw source and package-level regression tests
2 passed
external-source-benchmark-gate: PASS
public-review-gate: running external-heldout benchmark gate
external-heldout-benchmark-gate: running MCP Python SDK held-out repair regression
1 passed
external-heldout-benchmark-gate: PASS
public-review-gate: running public metadata boundary tests
<N> passed
public-review-gate: checking adversarial claim matrix generator
public-review-gate: running Evidence Court intensity matrix
316 passed
public-review-gate: recording Evidence Court bad-run fixture
public-review-gate: auditing supplied Evidence Court record
public-review-gate: auditing artifact provenance fixture
public-review-gate: auditing SWTBench patch artifact fixture
public-review-gate: auditing config-only repair fixture
public-review-gate: auditing runtime shadowing fixture
public-review-gate: auditing verifier tamper-risk fixture
public-review-gate: auditing verifier attack fixture
public-review-gate: auditing CI workflow tamper fixture
public-review-gate: running supplied transcript adapter matrix
adapter-matrix: PASS
public-review-gate: PASS
```

The script sets `PYTHONPATH` to the checkout root before running tests so a
stale installed package cannot silently satisfy the public gate.

The `<N>` metadata-test count is intentionally not fixed in this guide. It may
increase as public-boundary checks are added; the expected signal is that the
metadata section passes and the script reaches `public-review-gate: PASS`.

## What The Gate Covers

- The external-source benchmark gate verifies the vendored OpenClaw manifest,
  MIT license, selected source digest, one OpenClaw selected-source repair
  regression, and the package-level JavaScript learning-effect regression.
- The external-heldout benchmark gate verifies the vendored MCP Python SDK
  manifest, MIT license, selected source digest, upstream attribution boundary,
  one held-out function-level source repair regression, and that its selected
  test does not overlap the autonomous-learning gate's selected test manifest.
- The no-learning repair path fails the hidden task pack.
- The approved-learning repair path solves the hidden task pack.
- Repeat stability remains deterministic for the focused task.
- Changed files stay inside the expected source module.
- Test edits and failure-log tampering are classified as cheating.
- Public metadata keeps README, progress, review, and share packets inside the
  narrow v0.1 boundary.
- The local Evidence Court intensity matrix covers supplied test-output parser
  edge cases and 105 full supplied audit-record claim-boundary cases, including
  five multi-finding precedence cases.
- The adversarial claim matrix generator check prevents checked-in fixture
  metadata from drifting from the compact generator.
- The Evidence Court CLI audits a supplied bad-run record and fails closed on a
  scope violation.
- The artifact-provenance fixture preserves supplied benchmark artifact
  identity fields without claiming native benchmark ingestion.
- The config-only repair fixture keeps supplied project metadata/config repair
  evidence in `PASS/config_only` instead of treating it like a README-only
  repair claim.
- The runtime shadowing, verifier tamper-risk, verifier attack, and CI workflow
  tamper fixtures classify passing success claims that edit supplied Python
  startup-shadowing hooks, verifier, harness, benchmark, eval, or CI files as
  review-risk, not proof that the task implementation was fixed.
- Supplied transcript adapters preserve complete supplied proof fields and
  reject missing-test-proof, missing edited-file evidence, and missing
  diff-content evidence success claims.

## Smaller Checks

External-source benchmark gate only:

```bash
bash scripts/external_source_benchmark_gate.sh
```

This writes `.quantagent/external_source_benchmark_gate/last_summary.json` by
default. The summary records `external_source=true` and
`independent_external_heldout=false`. It is external-source regression evidence
only, not independent external held-out benchmark evidence, external benchmark
standing, external review, endorsement, stars, reposts, native live autonomy,
broad unknown-repository repair, or current remote CI proof.

External-heldout benchmark gate only:

```bash
bash scripts/external_heldout_benchmark_gate.sh
```

This writes `.quantagent/external_heldout_benchmark_gate/last_summary.json` by
default. The summary records `external_source_heldout=true`,
`heldout_from_autonomous_gate=true`, and
`independent_external_benchmark=false`. It is external-source held-out
regression evidence only, not external benchmark standing, external review,
endorsement, stars, reposts, native live autonomy, broad unknown-repository
repair, current remote CI proof, or owner license decision.

Slower local autonomous-learning stress gate:

```bash
bash scripts/autonomous_learning_gate.sh
```

Expected high-level signal:

```text
autonomous-learning-gate: running stage1 trajectory reuse matrix
autonomous-learning-gate: running upstream hidden-pack reuse stress test
autonomous-learning-gate: running cross-upstream no-seed reuse stress tests
autonomous-learning-gate: PASS
```

This optional gate runs repository tests for stage1 repair, trajectory
extraction, eval-gated learning approval, clean stage2 reuse, upstream
hidden-pack reuse, cross-upstream no-seed reuse, and cheating rejection. It is
local high-intensity learning evidence only, not native live autonomy, broad
unknown-repository repair proof, external benchmark standing, remote CI proof,
external review, endorsement, stars, or reposts.
It writes a machine-readable summary to
`.quantagent/autonomous_learning_gate/last_summary.json` by default. The summary
records the invoking commit, manifest-derived selected tests, per-segment elapsed
seconds, the per-segment pytest log paths and log tails, observed
pass/skip/warning counts, the expected stage1/upstream/cross-upstream
learning-effect contract counts, the tracked
`scripts/autonomous_task_source_provenance.json` path and sha256, an artifact
copy of that manifest, and the same not-proof boundary. Set
`OPENMAKO_AUTONOMOUS_LEARNING_GATE_SUMMARY_JSON` to write the summary
elsewhere.
The manifest-derived selected tests are constrained to the expected minimum
segment counts, pytest node-id shape, no pytest options, no whitespace, no
duplicates inside a segment, and no duplicates across segments, so a shortened or
injected manifest fails before pytest runs.
For commit-pinned public artifact capture, use the manual
`.github/workflows/autonomous-learning-gate.yml` workflow or push a change to
the workflow, the tracked task-source manifest, gate script, remote snapshot
script, core learning modules, selected gate-test paths, or supplied Evidence
Court/transcript proof surfaces. It uploads the summary JSON, manifest copy, and
pytest logs for that workflow run. This is path-filtered public CI artifact
evidence only, not broad default push or pull-request CI, external review,
endorsement, live autonomy, or broad unknown-repository repair proof.

After a remote autonomous-learning run exists, re-check the current artifact
boundary with:

```bash
bash scripts/remote_autonomous_learning_snapshot.sh
```

Expected high-level signal:

```text
remote-autonomous-learning-snapshot: run-sha=<current openmako/main SHA>
remote-autonomous-learning-snapshot: status=completed conclusion=success
remote-autonomous-learning-snapshot: artifact-name=autonomous-learning-gate-summary
remote-autonomous-learning-snapshot: artifact-digest=sha256:...
remote-autonomous-learning-snapshot: artifact-summary=last_summary.json
remote-autonomous-learning-snapshot: artifact-task-source-manifest=task_source_provenance_manifest.json
remote-autonomous-learning-snapshot: artifact-summary-upstream-hidden-task-count=10
remote-autonomous-learning-snapshot: artifact-summary-upstream-stability-solved=100
remote-autonomous-learning-snapshot: artifact-summary-upstream-cheat-caught=10
remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-hidden-stage2-tasks=8
remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-stability-solved=16
remote-autonomous-learning-snapshot: artifact-summary-cross-upstream-cheat-caught=8
remote-autonomous-learning-snapshot: artifact-summary-task-proof-files=5
remote-autonomous-learning-snapshot: artifact-summary-task-source-provenance=repo-authored-regression-pack
remote-autonomous-learning-snapshot: artifact-summary-task-source-manifest=scripts/autonomous_task_source_provenance.json
remote-autonomous-learning-snapshot: artifact-summary-task-source-manifest-sha256=...
remote-autonomous-learning-snapshot: artifact-summary-external-heldout=false
remote-autonomous-learning-snapshot: PASS
```

The command fails closed if the latest autonomous-learning workflow run is
stale, still running, failed, missing, rate limited, missing the named artifact,
expired, missing an artifact digest, unreadable as an artifact zip, blocked by
an artifact zip 401 that needs authenticated API access, or missing the expected
`last_summary.json` contract fields. It also fails closed if the artifact
manifest copy is missing, the manifest hash does not match the summary, the
summary provenance does not match the artifact manifest, or a segment's
manifest `selected_tests` no longer matches the summary's selected tests and
observed pass count. The remote artifact snapshot applies the same minimum
segment count, pytest node-id shape, no-option, no-whitespace, and no-duplicate
selected-test constraints to the artifact-contained manifest, so a self-consistent
but weakened artifact summary still fails closed. Set `OPENMAKO_GITHUB_TOKEN`,
`GITHUB_TOKEN`, or `GH_TOKEN` for live artifact zip reads, or set
`OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP` to verify the same contract against a saved
artifact fixture. Passing it is current public CI artifact evidence only, not
external review, endorsement, stars, reposts, live autonomy, broad
unknown-repository repair, external benchmark standing, or independent external
held-out benchmark evidence.

If the live GitHub API is rate-limited but the run metadata, artifact metadata,
and artifact zip were saved from the same workflow run, use the fixture-first
wrapper:

```bash
bash scripts/saved_autonomous_artifact_snapshot.sh runs.json artifacts.json autonomous-learning-gate-summary.zip <openmako-main-sha>
```

This delegates to `remote_autonomous_learning_snapshot.sh` with explicit
fixture paths. It checks the same artifact contract against saved inputs,
including the artifact metadata's `workflow_run` binding when present, but it
does not prove fixture provenance or current live GitHub API state. It is saved
public CI artifact evidence only, not a substitute for external review,
endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or
external benchmark standing, and not independent external held-out benchmark
evidence.

To re-check that the published public evidence comment still contains the
recorded remote-run markers and non-proof boundary:

```bash
bash scripts/public_evidence_comment_check.sh
```

Expected high-level signal:

```text
public-evidence-comment-check: marker=commit ok
public-evidence-comment-check: marker=run-id ok
public-evidence-comment-check: marker=artifact-id ok
public-evidence-comment-check: marker=artifact-digest ok
public-evidence-comment-check: PASS
```

Set `OPENMAKO_PUBLIC_EVIDENCE_HTML` to point the same checker at a saved HTML
fixture. This is public comment marker consistency only, not external review,
endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or
external benchmark standing.

Public boundary metadata only:

```bash
python -m pytest -p no:cacheprovider tests/test_public_metadata.py -q
```

Evidence Court supplied-record demo:

```bash
./bin/openmako --no-trust-prompt evidence-court record from-jsonl \
  --output run.json examples/evidence_court/simple_events.jsonl
./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json
```

Config-only false-positive boundary:

```bash
./bin/openmako --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/config_only_repair.json
```

Supplied transcript adapter matrix:

```bash
./scripts/supplied_transcript_adapter_matrix.sh
```

This script generates temporary repository-defined Codex, Claude, OpenHands,
and SWE-agent style transcripts, converts each one into an Evidence Court
record, audits each generated record, and checks that each adapter rejects a
success claim when command/test proof is missing, when validation command
exit-status evidence is missing, or when validation exists but edited-file or
supplied diff-content evidence is missing, only names test files, or covers
only a subset of edited source files, or when supplied ordered edit/command
evidence has passing validation before a later source edit for a claimed source
repair. It is still
a supplied-format smoke test, not native
product export parsing, proof that supplied patches were
applied outside the supplied record, or live agent control.

## What Passing Does Not Prove

- It does not prove broad unknown-repository SWE repair.
- It does not prove native Claude Code, Codex, Cursor, Devin, or SWE-bench
  transcript ingestion.
- It does not prove the full repository test suite is green.
- It does not prove external endorsement.

## Review Output

If the reproduction fails, the useful output is a concrete command, stderr
snippet, platform details, and the first mismatching file or expected signal.
If it passes, the useful output is still boundary criticism, not promotion.
