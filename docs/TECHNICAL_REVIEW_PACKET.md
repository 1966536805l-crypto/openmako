# OpenMako v0.1 Technical Review Packet

This packet is for reviewers who want to check whether OpenMako v0.1.0's
public claim matches the repository evidence. It is not an endorsement request,
promotion request, star request, or repost request.

## Review Target

The current public claim is narrow:

> OpenMako v0.1 demonstrates one focused learning-effect gate for coding-agent
> repair runs, plus an Evidence Court CLI for auditing supplied records.

Do not treat older planning docs, local-only benchmark notes, archived quant
experiments, or agent-written summaries as public capability evidence.

## Public Evidence To Inspect

- Public proof card: https://github.com/1966536805l-crypto/openmako/issues/1
- Technical boundary criticism request:
  https://github.com/1966536805l-crypto/openmako/issues/2
- v0.1.0 release:
  https://github.com/1966536805l-crypto/openmako/releases/tag/v0.1.0
- Focused CI:
  https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml
- Evidence Court demo CI:
  https://github.com/1966536805l-crypto/openmako/actions/workflows/evidence-court-demo.yml
- Reproduction guide:
  https://github.com/1966536805l-crypto/openmako/blob/main/docs/REPRODUCE_V0_1.md
- Reviewer outreach draft:
  https://github.com/1966536805l-crypto/openmako/blob/main/docs/REVIEWER_OUTREACH_DRAFT.md
- Boundary-preserving public share packet:
  https://github.com/1966536805l-crypto/openmako/blob/main/docs/PUBLIC_SHARE_PACKET.md

## Reproduce The Focused Gate

```bash
git clone https://github.com/1966536805l-crypto/openmako.git
cd openmako
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest
./scripts/public_review_gate.sh
```

That script runs the focused public gate, metadata boundary checks, and the
supplied Evidence Court bad-run audit. To run only the focused learning-effect
gate:

For exact expected output and smaller checks, see `docs/REPRODUCE_V0_1.md`.

```bash
python -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

Expected public snapshot signal:

```text
2 passed
```

## Reproduce The Evidence Court Demo

```bash
./bin/openmako --no-trust-prompt evidence-court record from-jsonl \
  --output run.json examples/evidence_court/simple_events.jsonl
./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json
```

The demo audits supplied JSON records. It does not claim native Claude Code,
Codex, Cursor, Devin, or SWE-bench transcript ingestion.

## Please Challenge These Boundaries

- Does README claim more than the focused tests and CI prove?
- Are old or experimental code paths clearly separated from v0.1 public claims?
- Is issue #1 enough public proof for the narrow claim?
- Does issue #2 ask for technical criticism rather than endorsement?
- Are there unsupported words such as broad, general, autonomous, L5, or
  unknown-repository repair that should be removed or qualified?

## What A Useful Review Looks Like

A useful review points to a specific file, line, command, workflow, or missing
artifact. The most useful outcome is boundary criticism that can be fixed in
README, tests, CI, or release notes.

## Minimal Review Comment Template

```text
Verdict: boundary clear / overclaim / unclear
Evidence checked:
- README section or line:
- Test command or workflow:
- Release or issue link:
Concrete mismatch or missing proof:
Suggested correction:
```

Do not include endorsement, promotion, star, or repost language in the review.
A useful comment is enough if it records the evidence checked.
