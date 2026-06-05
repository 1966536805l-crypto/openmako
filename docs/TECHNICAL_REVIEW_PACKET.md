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
- Structured technical boundary issue form:
  https://github.com/1966536805l-crypto/openmako/issues/new?template=technical-boundary-check.yml
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

To inspect the artifact-provenance boundary used for benchmark-style
comparability questions:

```bash
./bin/openmako --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/artifact_provenance.json
```

That fixture preserves supplied eval rule, runner, input hash, output hash, and
missing-provenance fields. It does not mean OpenMako ingests native benchmark
artifacts or validates benchmark scores.

## Optional Supplied-Transcript Adapter Checks

If you want to inspect the newly merged adapter surface, use the schema notes:
`docs/evidence_court_schema.md`.

The current adapters are repository-defined supplied transcript formats:

- `record from-codex-transcript`
- `record from-claude-transcript`
- `record from-openhands-transcript`
- `record from-swe-agent-transcript`

They preserve unsupported tool calls, events, or steps under
`adapter_report.unsupported`. They do not claim native Codex, Claude,
OpenHands, or SWE-agent export parsing, live agent control, benchmark
ingestion, or external endorsement.

## Optional Desktop-Control Dry-Run Check

The repository also contains desktop-control implementation work outside the
current v0.1 public claim. To inspect that path without treating it as launch
proof:

```bash
bash scripts/desktop_control_local_gate.sh
```

For a screenshot-friendly local summary of the same bounded gate:

```bash
bash scripts/desktop_control_proof_card.sh
```

Expected boundary signal:

```text
desktop-control-local-gate: status=dry_run
desktop-control-local-gate: scenarios=8
desktop-control-local-gate: level=L2
desktop-control-local-gate: not-proof=live desktop control, L4, L5, external endorsement, star or repost traction
desktop-control-local-gate: PASS
```

This is local implementation evidence for desktop intelligence and policy
guards. It is not evidence that OpenMako has live L4/L5 desktop autonomy.

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

If you prefer a structured GitHub issue form, use:
https://github.com/1966536805l-crypto/openmako/issues/new?template=technical-boundary-check.yml
