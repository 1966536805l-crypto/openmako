# QuantAgent Project Memory

QuantAgent is a local quant-focused coding agent starter. The current goal is to converge toward a Claude Code-like local workflow while keeping the implementation clean, testable, and attribution-safe.

Core rules:

- Prefer project-local tools and deterministic checks before model conclusions.
- Treat PF, slippage, capacity, tick, broker, and P4 claims as evidence-gated.
- Use `python3 -m unittest discover -s tests` as the default regression command.
- Keep desktop actions plan-first: observe, locate, render a plan, then require explicit execution.
- Do not copy proprietary Claude Code source. MIT-licensed OpenClaw, Hermes Agent, and similar open source projects may be copied or adapted with attribution.

High-value local modules:

- `quantagent/agent_v2.py`: plan, execute, reflect, memory extract, trajectory record.
- `quantagent/patch_engine.py`: snapshot, contextual replace, diff preview, restore.
- `quantagent/trajectory.py`: deterministic JSONL event ledger.
- `quantagent/edit_loop.py`: edit, test, retry, restore.
- `quantagent/desktop_plan.py`: no-side-effect click planning from grid/label/OCR payloads.
- `quantagent/memory_extract.py`: deterministic long-term memory candidate extraction.

Current quality gate:

```bash
python3 -m py_compile quantagent/*.py
python3 -m unittest discover -s tests
```
