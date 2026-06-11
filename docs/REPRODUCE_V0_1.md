# OpenMako v0.1 Reproduction Guide

This guide is for technical reviewers who want to reproduce the narrow public
v0.1 claim before reading broader repository code. It is not an endorsement
request, promotion request, star request, or repost request.

## Claim Under Test

OpenMako v0.1 demonstrates one focused learning-effect gate for coding-agent
repair runs, plus an Evidence Court CLI for auditing supplied records.

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
public-review-gate: running learning-effect focused public test
1 passed
public-review-gate: running public metadata boundary tests
<N> passed
public-review-gate: running Evidence Court intensity matrix
210 passed
public-review-gate: recording Evidence Court bad-run fixture
public-review-gate: auditing supplied Evidence Court record
public-review-gate: auditing artifact provenance fixture
public-review-gate: auditing SWTBench patch artifact fixture
public-review-gate: auditing config-only repair fixture
public-review-gate: auditing verifier tamper-risk fixture
public-review-gate: auditing verifier attack fixture
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

- The no-learning repair path fails the hidden task pack.
- The approved-learning repair path solves the hidden task pack.
- Repeat stability remains deterministic for the focused task.
- Changed files stay inside the expected source module.
- Test edits and failure-log tampering are classified as cheating.
- Public metadata keeps README, progress, review, and share packets inside the
  narrow v0.1 boundary.
- The local Evidence Court intensity matrix covers supplied test-output parser
  edge cases.
- The Evidence Court CLI audits a supplied bad-run record and fails closed on a
  scope violation.
- The artifact-provenance fixture preserves supplied benchmark artifact
  identity fields without claiming native benchmark ingestion.
- The config-only repair fixture keeps supplied project metadata/config repair
  evidence in `PASS/config_only` instead of treating it like a README-only
  repair claim.
- The verifier tamper-risk and verifier attack fixtures classify passing
  success claims that edit supplied verifier, harness, benchmark, or eval files
  as review-risk, not proof that the task implementation was fixed.
- Supplied transcript adapters preserve complete supplied proof fields and
  reject missing-test-proof, missing edited-file evidence, and missing
  diff-content evidence success claims.

## Smaller Checks

Focused learning-effect gate only:

```bash
python -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

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
success claim when command/test proof is missing or when validation exists but
edited-file or diff-content evidence is missing. It is still a supplied-format
smoke test, not native product export parsing, proof that supplied patches were
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
