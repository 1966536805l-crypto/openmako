# OpenMako Local Agent Notes

This file is for local coding-agent behavior inside this repository. It is not a public capability claim.

Current public position:

- OpenMako is a focused evidence harness for coding-agent repair runs.
- The public v0.1 proof is the external-source public gate linked from
  `README.md` and issue #1. It is not independent external held-out benchmark
  evidence.
- Claims about broader agent-runtime, desktop-control, quant, or benchmark
  behavior require current tests and public evidence before they can be used in
  launch copy.

Core rules:

- Prefer deterministic commands and file evidence before model conclusions.
- Keep edits scoped to the requested files and explain any scope expansion.
- Do not claim tests passed unless the exact command ran in the current
  workspace.
- Do not copy closed-source code, prompts, endpoints, constants, or proprietary
  strings from commercial coding-agent tools.
- Treat open-source upstream references as attribution-bound sources, not as
  proof of OpenMako capability.

Current public quality gate:

```bash
bash scripts/public_review_gate.sh
```

The public wording lock lives in `tests/test_public_metadata.py`; update that
test when public-surface evidence boundaries change.
