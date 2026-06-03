# Changelog

## v0.1.0 Draft

This is a release-note draft, not proof that `v0.1.0` has been tagged or
published.

### Added

- Evidence Court CLI commands for auditing supplied coding-agent run records:
  `audit`, `demo`, `record from-jsonl`, and `validate`.
- JSON audit output with the `evidence-court/v0.1` schema version.
- CI mode for failing on `FAIL` by default, or on `SUSPICIOUS` with
  `--fail-on suspicious`.
- A repository-local GitHub composite action for validating a supplied record,
  running an audit, writing an audit report, and checking the expected exit
  code.
- A GitHub Actions demo workflow that builds a known-bad run record and uploads
  `evidence-court-report.json`.

### Evidence

- README capability claims are guarded by `tests/test_public_metadata.py`.
- Evidence Court CLI behavior is guarded by `tests/test_cli_wrappers.py`.
- The focused learning-effect gate is run by `.github/workflows/focused.yml`.
- The Evidence Court demo is run by `.github/workflows/evidence-court-demo.yml`.

### Release Note Boundary

Allowed claim:

```text
OpenMako v0.1 audits supplied Evidence Court records for scope violations,
missing or failed validation evidence, and unsupported success claims.
```

Required caveat:

```text
v0.1 audits supplied records only. It does not yet ingest native Claude Code,
Codex, Cursor, or SWE-bench transcripts.
```

### Not Included In v0.1

- Native Claude Code, Codex, Cursor, or SWE-bench transcript ingestion.
- Broad unknown-repository SWE repair claims.
- A published Marketplace GitHub Action.
- Full-suite or hidden benchmark claims unless the exact command was run on the
  release commit.
