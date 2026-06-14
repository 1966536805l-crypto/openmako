#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

SUMMARY_JSON="${OPENMAKO_EXTERNAL_SOURCE_BENCHMARK_SUMMARY_JSON:-.quantagent/external_source_benchmark_gate/last_summary.json}"
SUMMARY_DIR="$(dirname -- "$SUMMARY_JSON")"
PYTEST_LOG="$SUMMARY_DIR/pytest.log"
mkdir -p "$SUMMARY_DIR"

SELECTED_TESTS=(
  "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_openclaw_selected_js_no_seed_repair_changes_only_target_file"
  "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest::test_package_level_http_manifest_js_trajectory_skill_reuses_on_hidden_tasks"
)

GIT_COMMIT="unknown"
if git rev-parse HEAD >/dev/null 2>&1; then
  GIT_COMMIT="$(git rev-parse HEAD)"
fi

write_summary() {
  local status="$1"
  local pytest_exit="$2"
  "$PYTHON_BIN" - "$SUMMARY_JSON" "$PYTEST_LOG" "$GIT_COMMIT" "$status" "$pytest_exit" "${SELECTED_TESTS[@]}" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
SUMMARY_JSON = ROOT / sys.argv[1]
PYTEST_LOG = ROOT / sys.argv[2]
GIT_COMMIT = sys.argv[3]
STATUS = sys.argv[4]
PYTEST_EXIT = int(sys.argv[5])
SELECTED_TESTS = sys.argv[6:]

MANIFEST = ROOT / "third_party" / "openclaw" / "MANIFEST.sha256"
LICENSE = ROOT / "third_party" / "openclaw" / "LICENSE"
README = ROOT / "third_party" / "openclaw" / "README.md"
REQUIRED_SOURCE_PATHS = [
    "third_party/openclaw/LICENSE",
    "third_party/openclaw/README.md",
    "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js",
]
NOT_PROOF = [
    "independent external held-out benchmark",
    "external benchmark standing",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "current remote CI proof",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        raise SystemExit(f"external-source-benchmark-gate: missing manifest {MANIFEST}")
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise SystemExit(f"external-source-benchmark-gate: invalid manifest line {line_number}: {raw_line!r}")
        expected, rel_path = parts
        rel_path = rel_path.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise SystemExit(f"external-source-benchmark-gate: invalid sha256 on manifest line {line_number}")
        abs_path = ROOT / rel_path
        if not abs_path.exists():
            raise SystemExit(f"external-source-benchmark-gate: manifest path missing: {rel_path}")
        actual = sha256_file(abs_path)
        if actual != expected:
            raise SystemExit(
                f"external-source-benchmark-gate: manifest digest mismatch for {rel_path}: "
                f"expected {expected}, got {actual}"
            )
        entries[rel_path] = expected
    return entries


def parse_pytest_log() -> dict[str, Any]:
    if not PYTEST_LOG.exists():
        return {"exit_code": PYTEST_EXIT, "passed": 0, "skipped": 0, "warnings": 0}
    text = PYTEST_LOG.read_text(encoding="utf-8", errors="replace")
    passed = 0
    skipped = 0
    warnings = 0
    for match in re.finditer(r"(\d+)\s+passed", text):
        passed = int(match.group(1))
    for match in re.finditer(r"(\d+)\s+skipped", text):
        skipped = int(match.group(1))
    for match in re.finditer(r"(\d+)\s+warnings?", text):
        warnings = int(match.group(1))
    return {
        "exit_code": PYTEST_EXIT,
        "passed": passed,
        "skipped": skipped,
        "warnings": warnings,
    }


def log_tail() -> list[str]:
    if not PYTEST_LOG.exists():
        return []
    lines = PYTEST_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-20:]


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


manifest_entries = read_manifest()
license_text = LICENSE.read_text(encoding="utf-8") if LICENSE.exists() else ""
readme_text = README.read_text(encoding="utf-8") if README.exists() else ""
missing_required = [path for path in REQUIRED_SOURCE_PATHS if path not in manifest_entries]
if missing_required:
    raise SystemExit(f"external-source-benchmark-gate: required manifest paths missing: {missing_required}")
if "MIT License" not in license_text:
    raise SystemExit("external-source-benchmark-gate: OpenClaw license does not contain MIT License")
if "https://github.com/openclaw/openclaw" not in readme_text or "Upstream version: `2026.5.20`" not in readme_text:
    raise SystemExit("external-source-benchmark-gate: OpenClaw README is missing upstream repository/version boundary")

observed = parse_pytest_log()
selected_source_files = {
    rel_path: {
        "sha256": manifest_entries[rel_path],
        "bytes": (ROOT / rel_path).stat().st_size,
    }
    for rel_path in REQUIRED_SOURCE_PATHS
}
summary = {
    "schema_version": "external-source-benchmark-gate/v0.1",
    "status": STATUS,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "invocation": {
        "git_commit": GIT_COMMIT,
        "summary_json": display_path(SUMMARY_JSON),
    },
    "source": {
        "package": "openclaw",
        "repository": "https://github.com/openclaw/openclaw",
        "version": "2026.5.20",
        "license": "MIT",
        "license_path": "third_party/openclaw/LICENSE",
        "license_sha256": manifest_entries["third_party/openclaw/LICENSE"],
        "readme_path": "third_party/openclaw/README.md",
        "readme_sha256": manifest_entries["third_party/openclaw/README.md"],
        "manifest_path": "third_party/openclaw/MANIFEST.sha256",
        "manifest_sha256": sha256_file(MANIFEST),
        "manifest_entry_count": len(manifest_entries),
        "selected_source_files": selected_source_files,
    },
    "selected_tests": SELECTED_TESTS,
    "expected_passed": len(SELECTED_TESTS),
    "observed_pytest": observed,
    "log_path": display_path(PYTEST_LOG),
    "log_tail": log_tail(),
    "external_source": True,
    "independent_external_heldout": False,
    "not_proof": NOT_PROOF,
}

invalid: list[str] = []
if len(SELECTED_TESTS) != 2:
    invalid.append("selected_tests_count")
if not all(test.startswith("tests/test_external_benchmark_multimodule_regression.py::") for test in SELECTED_TESTS):
    invalid.append("selected_test_node_shape")
if STATUS == "passed" and observed != {"exit_code": 0, "passed": 2, "skipped": 0, "warnings": 0}:
    invalid.append(f"observed_pytest={observed!r}")
if summary["independent_external_heldout"] is not False:
    invalid.append("independent_external_heldout_boundary")
if "independent external held-out benchmark" not in summary["not_proof"]:
    invalid.append("not_proof_boundary")

SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if invalid:
    print(f"external-source-benchmark-gate: invalid summary fields={'; '.join(invalid)}", file=sys.stderr)
    print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)

if STATUS != "running":
    print(f"external-source-benchmark-gate: source-package={summary['source']['package']}")
    print(f"external-source-benchmark-gate: source-license={summary['source']['license']}")
    print(f"external-source-benchmark-gate: source-manifest-sha256={summary['source']['manifest_sha256']}")
    print(f"external-source-benchmark-gate: selected-tests={len(SELECTED_TESTS)}")
    print(f"external-source-benchmark-gate: observed-passed={observed['passed']}")
    print(f"external-source-benchmark-gate: summary={summary['invocation']['summary_json']}")
PY
}

write_summary "running" 0

echo "external-source-benchmark-gate: running selected OpenClaw source and package-level regression tests"
set +e
"$PYTHON_BIN" -m pytest -p no:cacheprovider "${SELECTED_TESTS[@]}" -q > "$PYTEST_LOG" 2>&1
pytest_exit=$?
set -e
cat "$PYTEST_LOG"

if [ "$pytest_exit" -ne 0 ]; then
  write_summary "failed" "$pytest_exit"
  echo "external-source-benchmark-gate: FAIL pytest-exit=$pytest_exit" >&2
  exit "$pytest_exit"
fi

write_summary "passed" "$pytest_exit"
echo "external-source-benchmark-gate: PASS"
echo "external-source-benchmark-gate: not-proof=independent external held-out benchmark; external benchmark standing; external review; endorsement; stars; reposts; native live autonomy; broad unknown-repository repair; current remote CI proof"
