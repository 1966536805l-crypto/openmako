# Public Review Entrypoints

Use this page when asking for technical review. Do not use it to ask for stars,
endorsements, or promotion.

For the public traction gap and current comparable-project snapshot, see
`docs/OPEN_SOURCE_TRACTION_GAP.md`.

For who to ask after remote CI exists, see `docs/REVIEWER_OUTREACH_QUEUE.md`.

Before posting review copy publicly, run the outreach copy gate:

```bash
python3 scripts/outreach_copy_gate.py
```

When this branch is pushed, use the `Technical boundary review` issue template
for feedback. It asks reviewers to identify the exact claim, evidence checked,
boundary verdict, and smallest missing proof.

## What To Review First

### 1. Evidence Court v0.1

Review question:

```text
Does Evidence Court v0.1 actually catch unsupported success claims in supplied agent-run records, and does the README stay inside that boundary?
```

Start here:

- `README.md`
- `docs/EVIDENCE_COURT_V0_1_PR_BODY.md`
- `docs/CAPABILITY_GATES.md`
- `scripts/evidence_court_smoke.sh`
- `tests/test_evidence_court.py`
- `tests/test_evidence_court_smoke_script.py`

Local checks:

```bash
mako evidence-court --demo bad-run
bash scripts/evidence_court_smoke.sh
python -m pytest -p no:cacheprovider tests/test_evidence_court_smoke_script.py tests/test_evidence_court.py -q
```

Boundary:

- It audits supplied structured records.
- It does not prove tests actually ran outside the supplied record.
- It does not yet natively ingest Claude/Codex/Cursor/Devin/CI logs.

### 2. Autonomy Stop-Rule Candidate

Review question:

```text
Does the stop-rule block the second write before disk mutation when post-edit verification is missing or failed?
```

Start here:

- `docs/AUTONOMY_STOP_RULE_PR_PACKET.md`
- `quantagent/agent_loop_core.py`
- `quantagent/agent_loop_v3.py`
- `tests/test_agent_loop_core.py`
- `tests/test_agent_loop_v3_mode_router.py`
- `tests/test_agent_cli_build_path.py`

Clean candidate:

```text
/tmp/openmako-autonomy-stop-candidate-20260605b
```

Local evidence:

```text
direct CLI/v3 proof: 2 passed, 1 warning in 1.63s
related suite: 49 passed, 6 warnings in 17.36s
patch SHA-256: d09cd5c96548a706fe31e00c4b41e811d8a44da49a26aa687fff28a00d563cb3
```

Boundary:

- It is local clean-candidate evidence.
- It is not remote CI evidence yet.
- It does not prove broad unattended autonomy, Desktop L4/L5 autonomy, or
  OS/container sandbox isolation.

## Short Reviewer Message

```text
I am not asking for stars or endorsement.

Can you check whether these two OpenMako claims match the repo evidence?

1. Evidence Court v0.1 catches unsupported success claims inside supplied agent-run records.
2. The autonomy stop-rule candidate blocks a second write when verification is missing or failed.

I mainly want boundary criticism: overclaim, missing proof, confusing wording, or a better minimal gate.
```

## Do Not Send

Avoid messages like:

```text
Please star my project.
This is better than Hermes/OpenClaw.
OpenMako has solved autonomous coding.
```

Those claims are not supported by the current public evidence.
