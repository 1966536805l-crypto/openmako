# OpenMako

[![focused](https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml/badge.svg)](https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml)

Evidence harness for coding agents.

OpenMako is for checking whether an AI coding agent actually improved across
runs, stayed inside the requested patch scope, and passed validation without
cheating by editing tests or hiding failures.

The v0.1 public claim is intentionally smaller than the repository: OpenMako
demonstrates one narrow public gate where approved learning must beat
no-learning on hidden repair tasks while staying inside exact patch scope.

## Why It Is Worth Checking

Coding-agent evals often collapse into a final pass/fail. OpenMako's narrower
job is to make the run evidence inspectable: did a repair skill actually
improve hidden variants, did it stay inside patch scope, and did the required
tests run as claimed?

The fastest useful criticism is a concrete mismatch between a public claim and
the command, workflow, issue, or artifact that should prove it.

## 60-Second Proof

Start with the public gate:

```bash
git clone https://github.com/1966536805l-crypto/openmako.git
cd openmako
python -m pip install -e . pytest
./scripts/public_review_gate.sh
```

For a screenshot-friendly summary after the same full gate passes:

```bash
bash scripts/public_proof_card.sh
```

Expected high-level signal:

```text
public-review-gate: running planner focused public test
public-review-gate: running learning-effect focused public test
public-review-gate: running public metadata boundary tests
public-review-gate: running Evidence Court intensity matrix
public-review-gate: recording Evidence Court bad-run fixture
public-review-gate: auditing supplied Evidence Court record
public-review-gate: auditing artifact provenance fixture
public-review-gate: auditing SWTBench patch artifact fixture
public-review-gate: auditing config-only repair fixture
public-review-gate: running supplied transcript adapter matrix
adapter-matrix: PASS
public-review-gate: PASS
```

What this checks is narrow: the focused learning-effect gate passes, public
metadata stays inside the v0.1 boundary, Evidence Court fails closed on a
supplied bad-run record, the local Evidence Court intensity matrix covers
supplied test-output parser edge cases, and supplied transcript adapters
preserve complete supplied proof fields while rejecting missing-test-proof
and missing edited-file or missing diff-content evidence success claims. It
also checks a supplied config-only repair fixture so that packaging/config
metadata fixes do not get confused with README-only repair claims. It does
not prove broad unknown-repository repair or external endorsement. This is a
local script result, not external reviewer approval.

## If You Came From A Benchmark Thread

The useful review is not "do you like this project?" It is narrower:

1. Run `./scripts/public_review_gate.sh`.
2. For artifact-identity questions, inspect the supplied-record fixture:
   `./bin/openmako --no-trust-prompt evidence-court audit --ci --json examples/evidence_court/artifact_provenance.json`.
3. For config-only false-positive questions, inspect:
   `./bin/openmako --no-trust-prompt evidence-court audit --ci --json examples/evidence_court/config_only_repair.json`.
4. Check whether the README claims more than those commands prove.
5. If a boundary is unclear, leave the concrete mismatch on
   [issue #2](https://github.com/1966536805l-crypto/openmako/issues/2).

If something is unclear, please point to the file, command, workflow, or
missing artifact.

## Technical Review Entry Points

For technical reviewers, start here before reading older implementation paths:

- Boundary criticism request: [issue #2](https://github.com/1966536805l-crypto/openmako/issues/2).
- Technical boundary issue form: [open a structured review issue](https://github.com/1966536805l-crypto/openmako/issues/new?template=technical-boundary-check.yml).
- External review record form: [record a public external review](https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml).
- Technical review packet: [`docs/TECHNICAL_REVIEW_PACKET.md`](docs/TECHNICAL_REVIEW_PACKET.md).
- Reproduction guide: [`docs/REPRODUCE_V0_1.md`](docs/REPRODUCE_V0_1.md).
- Contributor guide: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Attribution boundary: [`docs/UPSTREAM_ATTRIBUTION.md`](docs/UPSTREAM_ATTRIBUTION.md).
- Agent trend radar: [`docs/AGENT_TREND_RADAR.md`](docs/AGENT_TREND_RADAR.md).
- Reviewer target map: [`docs/REVIEWER_TARGETS.md`](docs/REVIEWER_TARGETS.md).
- Wave 1 review requests: [`docs/WAVE1_REVIEW_REQUESTS.md`](docs/WAVE1_REVIEW_REQUESTS.md).
- Wave 1 public target queue: [`docs/WAVE1_PUBLIC_TARGET_QUEUE.md`](docs/WAVE1_PUBLIC_TARGET_QUEUE.md).
- Wave 1 short-message helper: `bash scripts/wave1_review_request.sh swe-agent`.
- Wave 1 send-ready check: `bash scripts/wave1_send_ready.sh swe-agent`.
- Public share packet: [`docs/PUBLIC_SHARE_PACKET.md`](docs/PUBLIC_SHARE_PACKET.md).
- Public share-ready check: `bash scripts/public_share_ready.sh review-request`.
- Post-review broader share packet: [`docs/LARGE_REPOST_PACKET.md`](docs/LARGE_REPOST_PACKET.md).
- Post-review share check:
  `bash scripts/large_repost_ready.sh REVIEW_RECORD_ISSUE_URL --confirm-external-review`.
- Public proof card: [issue #1](https://github.com/1966536805l-crypto/openmako/issues/1).
- Focused public CI: [focused workflow](https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml).
- Local proof command: `./scripts/public_review_gate.sh`.

This path is for technical boundary review, not promotion.

## Public v0.1 Scope

The current release is a record-auditor and evidence-harness snapshot. It can
audit supplied Evidence Court records, run the focused learning-effect gate,
and fail closed when patch scope, test proof, or run evidence is missing.

The repository also contains older and experimental implementation paths. Those
paths are inspectable source, but they are not v0.1 launch claims until each has
a reproducible command, linked public evidence, and a matching CI workflow
result for that exact claim.

## CI Quickstart

This uses a simple JSONL event stream, not a native Claude Code, Codex, or Cursor transcript adapter.

```bash
./bin/openmako --no-trust-prompt evidence-court record from-jsonl --output run.json examples/evidence_court/simple_events.jsonl
./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json
```

For a minimal GitHub Actions workflow, see [`docs/github_actions_evidence_court.md`](docs/github_actions_evidence_court.md).

## 10-Second Bad-Run Demo

This fixture shows a coding agent run that edited code, ran validation, and
failed. OpenMako reports the failure from supplied trajectory, query-event, and
test-output evidence.

For supplied JSON records, see [`docs/evidence_court_schema.md`](docs/evidence_court_schema.md).

```bash
./bin/openmako --no-trust-prompt evidence-court demo bad-run
./bin/openmako --no-trust-prompt evidence-court demo missing-tests
./bin/openmako --no-trust-prompt evidence-court demo out-of-scope
./bin/openmako --no-trust-prompt evidence-court audit examples/evidence_court/out_of_scope.json
./bin/openmako --no-trust-prompt evidence-court audit examples/evidence_court/missing_tests.json
```

Expected signal:

```text
## Claim
## Evidence
## Scope Violations
## Test Verification
## Suspicious Behavior
## Verdict: FAIL
## Verdict: SUSPICIOUS
```

## What The Public Gate Checks

The focused public gate exercises a package-level JavaScript repair task:

- `no_learning` must fail the hidden task pack.
- `approved_learning` must solve the hidden task pack.
- repeat stability must stay at zero spread.
- changed files must stay on the exact target source module.
- protected-test and failure-log cheating must be classified as cheated.

Run the same gate locally:

```bash
python3 -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

Expected local result on the public snapshot:

```text
2 passed
```

## What It Does Not Claim

- It does not prove broad unknown-repository SWE repair.
- It does not replace Claude Code, Codex, Cursor, Devin, or other coding agents.
- It does not trust an agent's final message without command, diff, and test evidence.

## Why It Exists

Most coding-agent demos show the happy path. OpenMako focuses on the failure
boundary: did the agent run the required validation, touch only allowed files,
reuse an approved repair skill only after eval-gated approval, and fail closed
when the evidence is missing?

Use OpenMako when the useful question is not just "can the agent do it?", but
"can I inspect what it did, replay the path, and see where the risk is?"

## Install And Reproduce

```bash
git clone https://github.com/1966536805l-crypto/openmako.git
cd openmako
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest
./scripts/public_review_gate.sh
```

That script runs the focused public gate, metadata boundary checks, the
supplied Evidence Court bad-run audit, the artifact-provenance fixture, the
SWTBench patch-artifact fixture, and the supplied transcript adapter matrix.
To run only the focused learning-effect gate:

```bash
python -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

This is the same focused gate run by GitHub Actions. It is the current public
evidence for the v0.1 snapshot.

After installation, the CLI entrypoints are:

```bash
mako --help
openmako --help
qagent --help
```

## Public Evidence Links

| Evidence | Where |
| --- | --- |
| Public proof card | [issue #1](https://github.com/1966536805l-crypto/openmako/issues/1) |
| Technical boundary criticism request | [issue #2](https://github.com/1966536805l-crypto/openmako/issues/2), a review request rather than endorsement or promotion |
| Technical boundary issue form | [open a structured review issue](https://github.com/1966536805l-crypto/openmako/issues/new?template=technical-boundary-check.yml) |
| External review record form | [record a public external review](https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml), for already-public technical feedback only |
| Technical review packet | [`docs/TECHNICAL_REVIEW_PACKET.md`](docs/TECHNICAL_REVIEW_PACKET.md) |
| Reproduction guide | [`docs/REPRODUCE_V0_1.md`](docs/REPRODUCE_V0_1.md), exact local commands and expected public gate signals |
| Contributor guide | [`CONTRIBUTING.md`](CONTRIBUTING.md), public-boundary contribution rules |
| Attribution boundary | [`docs/UPSTREAM_ATTRIBUTION.md`](docs/UPSTREAM_ATTRIBUTION.md), upstream references and vendored-license boundaries |
| Agent trend radar | [`docs/AGENT_TREND_RADAR.md`](docs/AGENT_TREND_RADAR.md), source-linked trend map and non-claim development bets |
| Reviewer target map | [`docs/REVIEWER_TARGETS.md`](docs/REVIEWER_TARGETS.md), public-source outreach waves for technical review |
| Wave 1 review requests | [`docs/WAVE1_REVIEW_REQUESTS.md`](docs/WAVE1_REVIEW_REQUESTS.md), copyable non-promotional messages for technical reviewers |
| Public share packet | [`docs/PUBLIC_SHARE_PACKET.md`](docs/PUBLIC_SHARE_PACKET.md), boundary-preserving wording for reviewers who choose to discuss the project publicly |
| Public share-ready check | `bash scripts/public_share_ready.sh review-request`, runs the public gate before printing a non-promotional share message |
| v0.1 release | [release v0.1.0](https://github.com/1966536805l-crypto/openmako/releases/tag/v0.1.0) |
| Focused public CI | [focused workflow](https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml) |
| Remote focused CI snapshot | `bash scripts/remote_focused_ci_snapshot.sh`, a fail-closed check for the latest focused workflow on current `openmako/main`; supports `OPENMAKO_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`; if the GitHub API is unavailable it prints the remote SHA, local UTC check time, manual Actions URL, rate-limit reset countdown, and a copyable rerun command when available before exiting nonzero; not external review or endorsement |
| Screenshot-friendly proof card | [`scripts/public_proof_card.sh`](scripts/public_proof_card.sh), runs the public gate then prints scope and non-proof boundaries |
| Learning-effect gate | [`quantagent/learning_effect_coding_bench.py`](quantagent/learning_effect_coding_bench.py) |
| CodingBench execution | [`quantagent/coding_bench.py`](quantagent/coding_bench.py) |
| Agent repair loop used by the gate | [`quantagent/agent_loop.py`](quantagent/agent_loop.py) |
| Focused regression tests | [`tests/test_agent_planner_contract.py`](tests/test_agent_planner_contract.py), [`tests/test_external_benchmark_multimodule_regression.py`](tests/test_external_benchmark_multimodule_regression.py) |

## Category

OpenMako is best described as an evidence harness for coding agents. It is not
the coding agent itself, and it is not a general autonomy benchmark.

## Implementation Boundary

OpenMako's project policy is clean-room implementation for closed-source tools:
do not copy closed-source code, prompts, constants, endpoints, or proprietary
strings. Attribution and third-party review notes live in the docs below.

## Beyond The Public Gate

OpenMako contains implementation work beyond the current focused public gate.
Treat these as code paths to inspect and test, not as v0.1 launch claims:

- agent autopsy and trajectory reporting
- patch preview, checkpoint, and repair utilities
- desktop-control experiments with a bounded local dry-run gate
- quant/data-evidence gates
- MCP/runtime/profile plumbing

To inspect the current desktop-control path without treating it as public
proof, run:

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
desktop-control-local-gate: misoperation_rate=0.0
desktop-control-local-gate: crash_rate=0.0
desktop-control-local-gate: not-proof=live desktop control, L4, L5, external endorsement, star or repost traction
desktop-control-local-gate: PASS
```

That gate checks local desktop intelligence, policy guards, and the dry-run
`suite_l4` scenario plan. It is useful implementation evidence, not a claim
that OpenMako has live L4/L5 desktop autonomy.

Repository composition:

- `quantagent/` contains the active Python package and additional implementation
  paths.
- `tests/` contains regression coverage for both public and non-public paths.
- `.github/` contains the focused public CI and Evidence Court demo workflow.
- `docs/archive/` and older planning docs are historical context, not current
  public proof.
- `third_party/` contains external reference code and is not OpenMako-native
  capability evidence.

Useful entry points:

- [`quantagent/agent_autopsy.py`](quantagent/agent_autopsy.py)
- [`quantagent/edit_loop.py`](quantagent/edit_loop.py)
- [`quantagent/desktop_agent.py`](quantagent/desktop_agent.py)
- [`quantagent/quant_execution_gate.py`](quantagent/quant_execution_gate.py)
- [`quantagent/mcp_runtime.py`](quantagent/mcp_runtime.py)

## Attribution Boundary

OpenMako includes notes for learning from open-source agent and trading
projects. These notes are not v0.1 capability claims. The current public
evidence remains the focused learning-effect gate above.

For concrete upstream references, vendored files, and license boundaries, see
[`docs/UPSTREAM_ATTRIBUTION.md`](docs/UPSTREAM_ATTRIBUTION.md).

Relevant docs:

- [`docs/UPSTREAM_ATTRIBUTION.md`](docs/UPSTREAM_ATTRIBUTION.md)
- [`docs/SOURCE_COPY_BORROW_MATRIX.md`](docs/SOURCE_COPY_BORROW_MATRIX.md)

## Development

Run the public gate before claiming the snapshot is healthy:

```bash
python -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  -q
```

For broader local work, run the wider test suite only after your environment is
set up. Do not treat unrun local commands as public proof.
