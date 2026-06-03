# GitHub Actions Evidence Court Check

This workflow assumes your job already writes an Evidence Court `run.json`.
It does not collect native Claude Code, Codex, Cursor, or SWE-bench logs.

```yaml
name: Evidence Court

on:
  pull_request:

jobs:
  evidence-court:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"
      - run: python -m pip install -e .
      - name: Ensure audit record exists
        run: test -f run.json
      - name: Validate audit record shape
        run: openmako evidence-court validate run.json
      - name: Audit supplied record
        run: openmako evidence-court audit --ci --json run.json > evidence-court-report.json
      - uses: actions/upload-artifact@v4
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
