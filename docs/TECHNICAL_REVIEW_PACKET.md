# OpenMako v0.1 Technical Review Packet

This packet is for reviewers who want to check whether OpenMako v0.1.0's
public claim matches the repository evidence. It is not an endorsement request,
promotion request, star request, or repost request.

## Review Target

The current public claim is narrow:

> OpenMako v0.1 demonstrates one learning-effect repair check inside an
> external-source benchmark gate, two held-out function-level source repair
> checks inside an external-heldout benchmark gate, a repo-defined independent
> external-heldout benchmark packet, public focused/autonomous evidence
> snapshots, and an Evidence Court CLI for auditing supplied records.

Do not treat older planning docs, local-only benchmark notes, archived quant
experiments, or agent-written summaries as public capability evidence.

A recent fully closed public-evidence target is:

- Main commit: `0c5741ed52447ca18876ec3e730ef361025650db`
- Public-evidence branch commit: `c68f7508b82b62f73a4034a552c6eb1eb84e554f`
- Focused CI run: https://github.com/1966536805l-crypto/openmako/actions/runs/27524605204
- Autonomous-learning CI run: https://github.com/1966536805l-crypto/openmako/actions/runs/27524605186
- Focused artifact ZIP proof:
  `sha256:875f84d65ee7d236b3db9aa03008fea3db187ed8bd9971489fe9fc19e3a70a5d`
- Autonomous artifact ZIP proof:
  `sha256:e9c47cd02b1171b60cf3c63edb6c95f9c38b0e465e04e6badceb64001a27a89b`
- Fresh-clone reproduction log:
  `sha256:5a05302adabfa85b274b17dd6d366e52540b97471047c461e46aee0d38b4d4d8`

Use the current `main` HEAD for a new review. The concrete values above are a
recent closed evidence example, not a promise that later commits have the same
run IDs or artifact hashes. These records are public reproducibility evidence
only. They are not external review, endorsement, stars, reposts, native live
autonomy, broad unknown-repository repair, or third-party benchmark standing.

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
- Public evidence branch:
  https://github.com/1966536805l-crypto/openmako/tree/public-evidence
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
git checkout 0c5741ed52447ca18876ec3e730ef361025650db
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . pytest
./scripts/public_review_gate.sh
```

That script runs the planner focused public test, the external-source benchmark
gate, the external-heldout benchmark gate, the repo-defined independent
external-heldout benchmark packet, metadata boundary checks, the supplied
Evidence Court bad-run audit, the artifact-provenance fixture, the SWTBench
patch-artifact fixture, the config-only repair fixture, runtime shadowing and
verifier/CI tamper fixtures, and the supplied transcript adapter matrix.

To run only the external-source benchmark gate:

For exact expected output and smaller checks, see `docs/REPRODUCE_V0_1.md`.

```bash
bash scripts/external_source_benchmark_gate.sh
```

Expected public snapshot signal:

```text
external-source-benchmark-gate: PASS
```

To reproduce the current public evidence branch and fresh-clone evidence:

```bash
OPENMAKO_REPRO_REF=0c5741ed52447ca18876ec3e730ef361025650db \
OPENMAKO_REPRO_LOG=/tmp/openmako-fresh-clone.log \
bash scripts/fresh_clone_reproduction.sh

OPENMAKO_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
bash scripts/remote_public_evidence_snapshot.sh

OPENMAKO_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
bash scripts/remote_autonomous_public_evidence_snapshot.sh

OPENMAKO_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
bash scripts/remote_artifact_zip_proof_snapshot.sh

OPENMAKO_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE=https://github.com/1966536805l-crypto/openmako.git \
bash scripts/remote_fresh_clone_reproduction_snapshot.sh
```

Expected high-level signal:

```text
fresh-clone-reproduction: PASS
remote-public-evidence-snapshot: PASS
remote-autonomous-public-evidence-snapshot: PASS
remote-artifact-zip-proof-snapshot: PASS
remote-fresh-clone-reproduction-snapshot: PASS
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

To inspect the SWTBench-style patch artifact boundary used by benchmark-thread
questions:

```bash
./bin/openmako --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/swtbench_patch_artifact.json
```

That fixture combines supplied patch-shape metadata with artifact identity
metadata. It does not validate a SWTBench score or ingest native benchmark
exports.

To inspect the config-only false-positive boundary:

```bash
./bin/openmako --no-trust-prompt evidence-court audit --ci --json \
  examples/evidence_court/config_only_repair.json
```

That fixture keeps a supplied config-only repair record in `PASS/config_only`
instead of treating it like a README-only repair claim. It does not prove broad
repair ability or native benchmark ingestion.

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
desktop-control-local-gate: misoperation_rate=0.0
desktop-control-local-gate: crash_rate=0.0
desktop-control-local-gate: not-proof=live desktop control, L4, L5, external endorsement, star or repost traction
desktop-control-local-gate: PASS
```

This is local implementation evidence for desktop intelligence and policy
guards. It is not evidence that OpenMako has live L4/L5 desktop autonomy.

## Please Challenge These Boundaries

- Does README claim more than the focused tests and CI prove?
- Are old or experimental code paths clearly separated from v0.1 public claims?
- Are `./scripts/public_review_gate.sh` and issue #1 enough public proof for
  the narrow claim?
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
