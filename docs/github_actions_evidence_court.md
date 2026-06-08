# GitHub Actions Evidence Court Check

This workflow assumes your job already writes an Evidence Court `run.json`.
It does not collect native Claude Code, Codex, Cursor, or SWE-bench logs.

This repository also includes
[`../.github/workflows/evidence-court-demo.yml`](../.github/workflows/evidence-court-demo.yml),
which builds a known bad sample from `examples/evidence_court/simple_events.jsonl`
and asserts that `audit --ci --json` exits with `1`.

Inside this repository, the demo workflow uses the local composite action at
[`../.github/actions/evidence-court/action.yml`](../.github/actions/evidence-court/action.yml).
That is a repository-local action, not a published Marketplace action.

```yaml
name: Evidence Court

on:
  pull_request:

jobs:
  evidence-court:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.x"
      - run: python -m pip install -e .
      - name: Ensure audit record exists
        run: test -f run.json
      - name: Run Evidence Court
        uses: ./.github/actions/evidence-court
        with:
          record: run.json
          report: evidence-court-report.json
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: evidence-court-report
          path: evidence-court-report.json
```

To build `run.json` from the simple JSONL event format before the audit step:

```bash
openmako evidence-court record from-jsonl --output run.json path/to/events.jsonl
```

To fail CI on both `FAIL` and `SUSPICIOUS` verdicts:

```bash
openmako evidence-court audit --ci --fail-on suspicious --json run.json
```

Boundary: this check audits only the supplied `run.json`. It does not prove that
commands actually ran outside the record.
