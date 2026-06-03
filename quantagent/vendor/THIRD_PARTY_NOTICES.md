# Third-Party Software Notices

## Hermes Agent

**License**: MIT License  
**Copyright**: (c) 2025 Nous Research  
**Source**: https://github.com/NousResearch/hermes-agent  
**Version / evidence**: copied from inspected local and reference material on
2026-05-28; skill files declare `license: MIT` in frontmatter and the local
license copy is included at `hermes/LICENSE`.

### Files Included

1. `hermes/iteration_budget.py` (adapted from `agent/iteration_budget.py`)
   - Thread-safe iteration budget counter
   - 63 lines, no external dependencies

2. `hermes/retry_utils.py` (adapted from `agent/retry_utils.py`)
   - Jittered exponential backoff for retries
   - 58 lines, no external dependencies

3. `hermes/error_classifier.py` (adapted from `agent/error_classifier.py`)
   - Structured API error classification
   - 1134 lines, no external dependencies

4. `../tool_result_classification.py` (adapted from `agent/tool_result_classification.py`)
   - Tool-result mutation landing classifier
   - Python-native adaptation used by the evidence ledger

5. `hermes/skills/**`
   - Packaged copy of selected Hermes skill documents.
   - Source reference copy is also kept under `third_party/hermes/skills/**`.
   - The copied skill set currently includes:
     - `skills/data-science/jupyter-live-kernel/SKILL.md`
     - `skills/finance/a-stock-market-analysis/SKILL.md`
     - `skills/finance/news-sentiment-analysis/SKILL.md`
     - `skills/finance/quant-backtesting/SKILL.md`
     - `skills/finance/risk-position-sizing/SKILL.md`
     - `skills/finance/stock-screening-sector-rotation/SKILL.md`
     - `skills/finance/stock-screening-sector-rotation/references/a-share-realtime-screening-notes.md`
     - `skills/finance/technical-trading-analysis/SKILL.md`
     - `skills/finance/trade-plan-review/SKILL.md`
     - `skills/github/codebase-inspection/SKILL.md`
     - `skills/mcp/native-mcp/SKILL.md`
     - `skills/software-development/requesting-code-review/SKILL.md`
     - `skills/software-development/spike/SKILL.md`
     - `skills/software-development/subagent-driven-development/SKILL.md`
     - `skills/software-development/subagent-driven-development/references/context-budget-discipline.md`
     - `skills/software-development/subagent-driven-development/references/gates-taxonomy.md`
     - `skills/software-development/systematic-debugging/SKILL.md`
     - `skills/software-development/test-driven-development/SKILL.md`
     - `skills/software-development/writing-plans/SKILL.md`

### MIT License

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Modifications / Boundary

These files are not treated as proof of zero legal or operational risk. The
project keeps the original project name, source URL, license type, and usage
mode here so downstream redistribution can audit the boundary.

- `hermes/skills/**` is a direct packaged copy of selected skill documents.
- `hermes/iteration_budget.py`, `hermes/retry_utils.py`, and
  `hermes/error_classifier.py` retain upstream-derived behavior with local
  attribution headers. Some OpenMako-facing modules add project-specific
  integration behavior outside these vendor paths.
- `../tool_result_classification.py` is an adapted implementation, not a
  whole-file direct copy.

### Upstream Snapshot Decision

The Hermes skill documents under `hermes/skills/**` are direct packaged copies
and can be byte-compared against `third_party/hermes/skills/**`. The repository
currently stores only Hermes license and selected skill source snapshots under
`upstream_refs/hermes-agent/` and `third_party/hermes/`; it does not store
byte-comparable upstream copies of `agent/iteration_budget.py`,
`agent/retry_utils.py`, or `agent/error_classifier.py`. The vendored Python
files above are therefore treated as attributed adapted/vendor code, not as
verified byte-identical upstream snapshots.

Local vendor hashes recorded during the 2026-05-30 audit:

- `hermes/error_classifier.py`: `14058a80f6db2911cefe0047ce9a61c812e8055c2ef5de55252d67994efcb332`
- `hermes/iteration_budget.py`: `51ae7f980456d0f6f7588a65889e5f194b28196665668b8ff0170dad9808d4c3`
- `hermes/retry_utils.py`: `5ca02cb8233ea0fed83e907a18f37f619fa1fbb043ae0bd5075402c1d5681281`

### Integration

These sources are vendored under `quantagent/vendor/hermes/`. Runtime code
should prefer OpenMako adapter or rewrite modules outside `quantagent/vendor/`
unless a direct vendored module is deliberately being exercised.
