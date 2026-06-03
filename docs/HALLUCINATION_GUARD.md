# Hallucination Guard

QuantAgent treats model output as review text, not ground truth.

## Ground Truth Sources

1. Local data files with `sha256`.
2. Reproducible command lines.
3. Script files with `sha256`.
4. Registered JSON/Markdown results.
5. Validation logs.

## Hard Rules

- A model vote cannot create a fact.
- A PF, win rate, 2025 PF, capacity, or execution claim must cite a registered result or script output.
- If the input path, row count, dedup status, threshold, slippage, or execution assumption is unclear, the only valid vote is `NEEDS_WORK`.
- Any one `REJECT` or `NEEDS_WORK` among the three ChatGPT consistency review passes blocks material execution.
- Claude can comment, but it is not a gate voter.
- The three passes are not proof of real-world independence unless you configure separate providers/accounts/models.

## Experiment Evidence Lock

`qagent experiment` writes:

- `input_path`
- `input_sha256`
- `runner_path`
- `runner_sha256`
- `rows_before_filter`
- `rows_after_filter`
- threshold and return column parameters
- full/yearly/monthly metrics

Anything outside that evidence is opinion until reproduced.
