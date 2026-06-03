# Project Memory Handoff

This handoff gives local agents a first project-level memory source.

- Latest push: agent-v2, patch_engine, trajectory, and model retry are now part of the local agent foundation.
- Keep borrowing from MIT sources with attribution: Hermes Agent for retry/trajectory/tool resilience, OpenClaw for tool planning/task flow/event ownership, PageAgent-style DOM/AX/OCR ideas for desktop locator planning.
- Next best engineering move: wire `patch_engine` into `edit_loop`, then add safe parallel execution for read-only tool batches.
- Desktop control should remain plan-first and confirmation-gated.
