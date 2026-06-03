# v0.1 Release Checklist

Use this checklist before tagging or announcing an OpenMako v0.1 release.
Do not treat this file as proof that a release already happened.

## Required Evidence

- Focused GitHub Actions workflow is green on the commit to tag:
  `.github/workflows/focused.yml`.
- Evidence Court demo workflow is green on the commit to tag:
  `.github/workflows/evidence-court-demo.yml`.
- Local focused gate has been run on the release commit:

```bash
python3 -m pytest -p no:cacheprovider \
  tests/test_agent_planner_contract.py::AgentPlannerContractTest::test_planner_no_seed_repairs_package_level_http_manifest_js_module \
  tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks \
  tests/test_public_metadata.py \
  tests/test_cli_wrappers.py \
  -q
```

- README capability claims are covered by `tests/test_public_metadata.py`.
- Evidence Court CLI behavior is covered by `tests/test_cli_wrappers.py`.
- The `CHANGELOG.md` v0.1 draft uses the allowed release-note claim and required
  caveat below.
- The GitHub Release body is drafted in `docs/v0.1_release_notes.md` and uses
  the same allowed claim and required caveat.
- The demo workflow report artifact exists for the release commit:
  `evidence-court-report.json`.

## Boundary Checks

- Do not claim native Claude Code, Codex, Cursor, or SWE-bench transcript
  ingestion unless a real adapter and tests exist.
- Do not claim broad unknown-repository SWE repair.
- Do not claim full pytest or hidden benchmark numbers unless those commands
  were run on the release commit.
- Do not describe the repository-local composite action as a published
  Marketplace action.
- Do not present internal planning docs as current public capability evidence.

## Tag Command

Only tag after the required local checks and GitHub Actions checks are green.

```bash
git tag -a v0.1.0 -m "OpenMako v0.1.0"
git push origin v0.1.0
```

## Release Note Boundary

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
