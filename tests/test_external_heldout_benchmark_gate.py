from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTED_TEST = (
    "tests/test_upstream_function_file_bundle_regression.py::"
    "UpstreamFunctionFileBundleRegressionTest::"
    "test_vendored_mcp_function_level_repair_reuses_without_non_target_drift"
)


def _copy_file(source: Path, target_root: Path, rel_path: str) -> None:
    target = target_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / rel_path, target)


def _copy_minimal_gate_repo(tmp_path: Path) -> Path:
    target_root = tmp_path / "repo"
    target_root.mkdir()
    fixed_paths = [
        "scripts/external_heldout_benchmark_gate.sh",
        "scripts/autonomous_task_source_provenance.json",
        "docs/UPSTREAM_ATTRIBUTION.md",
        "third_party/mcp_python_sdk/MANIFEST.sha256",
    ]
    for rel_path in fixed_paths:
        _copy_file(ROOT, target_root, rel_path)

    manifest = ROOT / "third_party/mcp_python_sdk/MANIFEST.sha256"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _digest, rel_path = line.split(None, 1)
        _copy_file(ROOT, target_root, rel_path.strip())
    return target_root


def _run_gate(target_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENMAKO_EXTERNAL_HELDOUT_BENCHMARK_SUMMARY_JSON"] = str(target_root / "summary.json")
    return subprocess.run(
        ["bash", "scripts/external_heldout_benchmark_gate.sh"],
        cwd=target_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_fake_passing_selected_test(target_root: Path) -> None:
    test_path = target_root / "tests" / "test_upstream_function_file_bundle_regression.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(
        "import unittest\n\n"
        "class UpstreamFunctionFileBundleRegressionTest(unittest.TestCase):\n"
        "    def test_vendored_mcp_function_level_repair_reuses_without_non_target_drift(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refresh_manifest_digest(target_root: Path, rel_path: str) -> None:
    manifest = target_root / "third_party/mcp_python_sdk/MANIFEST.sha256"
    updated: list[str] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _old_digest, current_rel = line.split(None, 1)
        current_rel = current_rel.strip()
        digest = _sha256(target_root / current_rel) if current_rel == rel_path else _old_digest
        updated.append(f"{digest}  {current_rel}")
    manifest.write_text("\n".join(updated) + "\n", encoding="utf-8")


def test_external_heldout_gate_fails_closed_on_manifest_digest_mismatch(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    source = target_root / "third_party/mcp_python_sdk/src/mcp/shared/tool_name_validation.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "manifest digest mismatch" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_license_boundary_mismatch(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    license_path = target_root / "third_party/mcp_python_sdk/LICENSE"
    license_path.write_text("License text intentionally removed for fail-closed test.\n", encoding="utf-8")
    _refresh_manifest_digest(target_root, "third_party/mcp_python_sdk/LICENSE")

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "MCP Python SDK license boundary is not the expected MIT text" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_missing_attribution_boundary(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    attribution = target_root / "docs/UPSTREAM_ATTRIBUTION.md"
    attribution.write_text("## modelcontextprotocol/python-sdk\n\n- Repository: missing\n", encoding="utf-8")

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "upstream attribution boundary is missing MCP Python SDK evidence" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_autonomous_manifest_overlap(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    manifest = target_root / "scripts/autonomous_task_source_provenance.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    first_segment = next(iter(payload["segments"].values()))
    first_segment["selected_tests"].append(SELECTED_TEST)
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "selected tests overlap autonomous provenance" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_when_task_proof_is_missing(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_fake_passing_selected_test(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "task_proof_count=0" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout
