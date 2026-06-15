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
MCP_TOOL_NAME_SOURCE_SHA256 = "99312f833b0cb246b2ca294b68890fee521a0388def1c9e48fdc5821cea1b60a"


def _copy_file(source: Path, target_root: Path, rel_path: str) -> None:
    target = target_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / rel_path, target)


def _copy_minimal_gate_repo(tmp_path: Path) -> Path:
    target_root = tmp_path / "repo"
    target_root.mkdir()
    fixed_paths = [
        "scripts/external_heldout_benchmark_gate.sh",
        "scripts/heldout_reproduction_packet.sh",
        "scripts/independent_external_heldout_benchmark_gate.sh",
        "scripts/autonomous_task_source_provenance.json",
        "scripts/external_heldout_task_source_provenance.json",
        "benchmarks/independent_external_heldout/v0.1/cases.json",
        "docs/UPSTREAM_ATTRIBUTION.md",
        "tests/test_upstream_function_file_bundle_regression.py",
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


def _run_packet(target_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENMAKO_HELDOUT_REPRODUCTION_SOURCE_SUMMARY_JSON"] = str(target_root / "summary.json")
    env["OPENMAKO_HELDOUT_REPRODUCTION_PACKET_JSON"] = str(target_root / "packet.json")
    return subprocess.run(
        ["bash", "scripts/heldout_reproduction_packet.sh"],
        cwd=target_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_independent_benchmark_gate(target_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_SUMMARY_JSON"] = str(
        target_root / "independent_summary.json"
    )
    env["OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_SOURCE_SUMMARY_JSON"] = str(
        target_root / "summary.json"
    )
    env["OPENMAKO_INDEPENDENT_EXTERNAL_HELDOUT_PACKET_JSON"] = str(target_root / "packet.json")
    return subprocess.run(
        ["bash", "scripts/independent_external_heldout_benchmark_gate.sh"],
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
        "        self.assertTrue(True)\n"
        "    def test_vendored_mcp_wrapper_seed_repair_reuses_without_non_target_drift(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )


def _write_fake_passing_selected_test_with_task_proofs(
    target_root: Path,
    proofs: list[dict],
) -> None:
    test_path = target_root / "tests" / "test_upstream_function_file_bundle_regression.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    proofs_json = json.dumps(proofs, sort_keys=True)
    test_path.write_text(
        "import json\n"
        "import os\n"
        "import unittest\n"
        "from pathlib import Path\n\n"
        f"PROOFS_JSON = {proofs_json!r}\n\n"
        "class UpstreamFunctionFileBundleRegressionTest(unittest.TestCase):\n"
        "    def _write_proofs(self):\n"
        "        proof_dir = Path(os.environ['OPENMAKO_EXTERNAL_HELDOUT_TASK_PROOF_DIR'])\n"
        "        proof_dir.mkdir(parents=True, exist_ok=True)\n"
        "        for index, proof in enumerate(json.loads(PROOFS_JSON)):\n"
        "            (proof_dir / f'proof_{index}.json').write_text(\n"
        "                json.dumps(proof, indent=2, sort_keys=True) + '\\n',\n"
        "                encoding='utf-8',\n"
        "            )\n"
        "    def test_vendored_mcp_function_level_repair_reuses_without_non_target_drift(self):\n"
        "        self._write_proofs()\n"
        "        self.assertTrue(True)\n"
        "    def test_vendored_mcp_wrapper_seed_repair_reuses_without_non_target_drift(self):\n"
        "        self._write_proofs()\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )


def _write_semantic_lock_shaped_fake_passing_selected_test_with_task_proofs(
    target_root: Path,
    proofs: list[dict],
) -> None:
    test_path = target_root / "tests" / "test_upstream_function_file_bundle_regression.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    proofs_json = json.dumps(proofs, sort_keys=True)
    test_path.write_text(
        "import json\n"
        "import os\n"
        "import unittest\n"
        "from pathlib import Path\n\n"
        f"PROOFS_JSON = {proofs_json!r}\n\n"
        "class UpstreamFunctionFileBundleRegressionTest(unittest.TestCase):\n"
        "    def _write_proofs(self):\n"
        "        proof_dir = Path(os.environ['OPENMAKO_EXTERNAL_HELDOUT_TASK_PROOF_DIR'])\n"
        "        proof_dir.mkdir(parents=True, exist_ok=True)\n"
        "        for index, proof in enumerate(json.loads(PROOFS_JSON)):\n"
        "            (proof_dir / f'proof_{index}.json').write_text(\n"
        "                json.dumps(proof, indent=2, sort_keys=True) + '\\n',\n"
        "                encoding='utf-8',\n"
        "            )\n"
        "    def test_vendored_mcp_function_level_repair_reuses_without_non_target_drift(self):\n"
        "        if os.environ.get('OPENMAKO_UNREACHABLE_SEMANTIC_LOCK_CALLS') == '1':\n"
        "            run_agent_loop(learning_context=\"off\")\n"
        "            propose_file_bundle_repair_skill_from_trajectory()\n"
        "            run_skill_eval_command()\n"
        "            approve_skill_proposal()\n"
        "            run_learning_effect_coding_bench()\n"
        "            run_coding_bench_stability()\n"
        "            _assert_stability_preserves_function_repair()\n"
        "            _write_external_heldout_repair_proof()\n"
        "            'approved_learning_changed_files'\n"
        "            'approved_learning_out_of_scope_files'\n"
        "            'opaque-upstream-function-contract-1'\n"
        "            'validate_tool_name'\n"
        "        self._write_proofs()\n"
        "        self.assertTrue(True)\n"
        "    def test_vendored_mcp_wrapper_seed_repair_reuses_without_non_target_drift(self):\n"
        "        if os.environ.get('OPENMAKO_UNREACHABLE_SEMANTIC_LOCK_CALLS') == '1':\n"
        "            _install_seed_file_function_skill()\n"
        "            run_agent_loop(learning_context=\"on\")\n"
        "            propose_file_bundle_repair_skill_from_trajectory()\n"
        "            run_skill_eval_command()\n"
        "            approve_skill_proposal()\n"
        "            run_learning_effect_coding_bench()\n"
        "            run_coding_bench_stability()\n"
        "            _assert_stability_preserves_function_repair()\n"
        "            _write_external_heldout_repair_proof()\n"
        "            'approved_learning_changed_files'\n"
        "            'approved_learning_out_of_scope_files'\n"
        "            'seed-upstream-wrapper-function-1'\n"
        "            'validate_and_warn_tool_name'\n"
        "        self._write_proofs()\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )


def _valid_task_proof() -> dict:
    before_failure = {
        "command": ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
        "cwd": "/tmp/openmako-heldout-before",
        "returncode": 1,
        "stderr_tail": ["FAILED (failures=1)"],
        "stdout_tail": [],
    }
    after_test = {
        "command": ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
        "cwd": "/tmp/openmako-heldout-after",
        "returncode": 0,
        "stderr_tail": ["OK"],
        "stdout_tail": [],
    }
    unified_diff = [
        "--- a/mcp/shared/tool_name_validation.py",
        "+++ b/mcp/shared/tool_name_validation.py",
        "@@",
        "-def validate_tool_name(name):",
        "+def validate_tool_name(name):",
    ]
    return {
        "agent_diagnosis": {
            "observations": [
                {"data": {}, "name": "edit", "ok": True, "summary": "changed target function"}
            ],
            "ok": True,
        },
        "after_test": after_test,
        "before_failure": before_failure,
        "broken_source_sha256": "1" * 64,
        "command_log": [
            before_failure,
            {
                "command": ["run_agent_loop", "--mode", "repair", "--learning-context", "off"],
                "ok": True,
                "trajectory_path": "/tmp/openmako-heldout/trajectory.jsonl",
            },
            after_test,
        ],
        "diff": {
            "contains_target_function": True,
            "line_count": len(unified_diff),
            "unified_diff": unified_diff,
        },
        "evidence_boundary": {
            "not_proof": [
                "native benchmark ingestion",
                "live patch proof",
                "broad unknown-repository repair",
                "external benchmark standing",
                "current remote CI proof",
            ]
        },
        "external_source_heldout": True,
        "final_claim": (
            "For this vendored MCP held-out repair task, the agent loop changed "
            "only mcp/shared/tool_name_validation.py and the local package tests passed."
        ),
        "function_name": "validate_tool_name",
        "heldout_from_autonomous_gate": True,
        "independent_external_benchmark": False,
        "observed_counts": {
            "approved_learning_solved": 2,
            "hidden_stage2_tasks": 2,
            "no_learning_solved": 0,
            "stability_solved": 4,
        },
        "patch_scope": {
            "approved_learning_changed_files": [
                ["mcp/shared/tool_name_validation.py"],
                ["mcp/shared/tool_name_validation.py"],
            ],
            "approved_learning_out_of_scope_files": [[], []],
            "files_touched": ["mcp/shared/tool_name_validation.py"],
            "stage1_changed_files": ["mcp/shared/tool_name_validation.py"],
        },
        "repaired_source_sha256": "2" * 64,
        "schema_version": "external-heldout-repair-proof/v0.1",
        "source_package": "mcp-python-sdk",
        "source_repository": "https://github.com/modelcontextprotocol/python-sdk",
        "source_sha256": MCP_TOOL_NAME_SOURCE_SHA256,
        "target_path": "mcp/shared/tool_name_validation.py",
        "task_id": "vendored_mcp_tool_name_validation_function_repair",
    }


def _valid_wrapper_task_proof() -> dict:
    proof = _valid_task_proof()
    proof["task_id"] = "vendored_mcp_tool_name_wrapper_seed_repair"
    proof["function_name"] = "validate_and_warn_tool_name"
    proof["diff"]["unified_diff"] = [
        "--- a/mcp/shared/tool_name_validation.py",
        "+++ b/mcp/shared/tool_name_validation.py",
        "@@",
        "-def validate_and_warn_tool_name(name):",
        "+def validate_and_warn_tool_name(name):",
    ]
    proof["diff"]["line_count"] = len(proof["diff"]["unified_diff"])
    return proof


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


def _refresh_task_source_manifest_test_file_digest(target_root: Path) -> None:
    manifest = target_root / "scripts/external_heldout_task_source_provenance.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    test_path = target_root / payload["selected_test_file"]["path"]
    payload["selected_test_file"]["sha256"] = _sha256(test_path)
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_independent_benchmark_test_file_digest(target_root: Path) -> None:
    benchmark = target_root / "benchmarks/independent_external_heldout/v0.1/cases.json"
    payload = json.loads(benchmark.read_text(encoding="utf-8"))
    test_path = target_root / payload["selected_test_file"]["path"]
    payload["selected_test_file"]["sha256"] = _sha256(test_path)
    benchmark.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "task_proof_count=0" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_selected_test_file_replacement(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_fake_passing_selected_test(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "selected test file sha256 mismatch" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_duplicate_task_proofs(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    _write_fake_passing_selected_test_with_task_proofs(target_root, [proof, _valid_wrapper_task_proof(), proof])
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert "task_proof_count=3" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_forged_diff_target_flag(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    proof["diff"]["contains_target_function"] = True
    proof["diff"]["unified_diff"] = ["--- a/file.py", "+++ b/file.py", "-old", "+new"]
    proof["diff"]["line_count"] = len(proof["diff"]["unified_diff"])
    _write_fake_passing_selected_test_with_task_proofs(target_root, [proof, _valid_wrapper_task_proof()])
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert ".diff.unified_diff_target" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_successful_before_failure_claim(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    proof["before_failure"]["returncode"] = 0
    proof["command_log"][0] = proof["before_failure"]
    _write_fake_passing_selected_test_with_task_proofs(target_root, [proof, _valid_wrapper_task_proof()])
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert ".before_failure_returncode" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_nonzero_after_test_claim(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    proof["after_test"]["returncode"] = 1
    proof["command_log"][-1] = proof["after_test"]
    _write_fake_passing_selected_test_with_task_proofs(target_root, [proof, _valid_wrapper_task_proof()])
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert ".after_test_returncode" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_command_log_mismatch(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    proof["command_log"][0] = {
        "command": ["python", "-m", "unittest"],
        "cwd": "/tmp/other",
        "returncode": 1,
    }
    _write_fake_passing_selected_test_with_task_proofs(target_root, [proof, _valid_wrapper_task_proof()])
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert ".command_log.before_failure" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_external_heldout_gate_fails_closed_on_source_sha_manifest_mismatch(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    proof = _valid_task_proof()
    proof["source_sha256"] = "0" * 64
    _write_fake_passing_selected_test_with_task_proofs(
        target_root,
        [proof, _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)

    result = _run_gate(target_root)

    assert result.returncode != 0
    assert ".source_sha256_manifest" in result.stderr
    assert "external-heldout-benchmark-gate: PASS" not in result.stdout


def test_heldout_reproduction_packet_records_raw_evidence_hashes(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)

    gate = _run_gate(target_root)
    packet_result = _run_packet(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode == 0, packet_result.stderr
    assert "heldout-reproduction-packet: PASS" in packet_result.stdout
    packet = json.loads((target_root / "packet.json").read_text(encoding="utf-8"))
    assert packet["schema_version"] == "heldout-reproduction-packet/v0.1"
    assert packet["task_proof_count"] == 2
    assert packet["before_failure_count"] == 2
    assert packet["after_test_count"] == 2
    assert packet["target_diff_count"] == 2
    assert packet["labels"] == {
        "vendored_mcp_tool_name_validation_function_repair": "supported_repair_claim",
        "vendored_mcp_tool_name_wrapper_seed_repair": "supported_repair_claim",
    }
    assert packet["raw_evidence_files"]["summary.json"].startswith("sha256:")
    assert packet["raw_evidence_files"]["pytest.log"].startswith("sha256:")
    assert packet["raw_evidence_files"]["task_proofs/proof_0.json"].startswith("sha256:")
    assert packet["raw_evidence_files"]["task_proofs/proof_1.json"].startswith("sha256:")
    assert packet["independent_external_benchmark"] is False
    assert "native live autonomy" in packet["not_proof"]


def test_heldout_reproduction_packet_fails_closed_on_missing_raw_proof(tmp_path: Path) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)

    gate = _run_gate(target_root)
    proof = target_root / "task_proofs" / "proof_0.json"
    proof.unlink()
    packet_result = _run_packet(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode != 0
    assert "missing raw evidence file" in packet_result.stderr
    assert "heldout-reproduction-packet: PASS" not in packet_result.stdout


def test_independent_external_heldout_benchmark_gate_records_frozen_packet(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_semantic_lock_shaped_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)

    gate = _run_gate(target_root)
    packet_result = _run_packet(target_root)
    independent = _run_independent_benchmark_gate(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode == 0, packet_result.stderr
    assert independent.returncode == 0, independent.stderr
    assert "independent-external-heldout-benchmark-gate: PASS" in independent.stdout
    summary = json.loads((target_root / "independent_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "independent-external-heldout-benchmark-gate/v0.1"
    assert summary["status"] == "passed"
    assert summary["benchmark"]["case_count"] == 2
    assert summary["independent_external_heldout_benchmark"] is True
    assert summary["independent_from_autonomous_task_manifest"] is True
    assert summary["repo_defined_benchmark_packet"] is True
    assert summary["third_party_benchmark_standing"] is False
    assert summary["selected_test_semantic_lock"]["schema_version"] == (
        "openmako-selected-test-semantic-lock/v0.1"
    )
    assert [
        item["required_call_count"]
        for item in summary["selected_test_semantic_lock"]["checked_methods"]
    ] == [8, 9]
    assert summary["observed_pytest"] == {
        "exit_code": 0,
        "passed": 2,
        "skipped": 0,
        "warnings": 0,
    }
    assert set(summary["raw_evidence_files"]) >= {
        "summary.json",
        "pytest.log",
        "task_proofs/proof_0.json",
        "task_proofs/proof_1.json",
    }
    assert "third-party benchmark standing" in summary["not_proof"]


def test_independent_external_heldout_benchmark_gate_rebuilds_stale_local_inputs(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_semantic_lock_shaped_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)
    stale = {
        "schema_version": "stale/v0",
        "status": "passed",
        "invocation": {"git_commit": "0" * 40},
    }
    (target_root / "summary.json").write_text(
        json.dumps(stale, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (target_root / "packet.json").write_text(
        json.dumps(stale, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    independent = _run_independent_benchmark_gate(target_root)

    assert independent.returncode == 0, independent.stderr
    assert "running source held-out gate" in independent.stdout
    assert "building held-out reproduction packet" in independent.stdout
    assert "independent-external-heldout-benchmark-gate: PASS" in independent.stdout


def test_independent_external_heldout_benchmark_gate_fails_on_weakened_case_definition(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_semantic_lock_shaped_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)
    benchmark = target_root / "benchmarks/independent_external_heldout/v0.1/cases.json"
    payload = json.loads(benchmark.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_task_id"] = "weakened_task_id"
    benchmark.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    gate = _run_gate(target_root)
    packet_result = _run_packet(target_root)
    independent = _run_independent_benchmark_gate(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode == 0, packet_result.stderr
    assert independent.returncode != 0
    assert "task proof ids mismatch" in independent.stderr
    assert "independent-external-heldout-benchmark-gate: PASS" not in independent.stdout


def test_independent_external_heldout_benchmark_gate_fails_on_selected_test_replacement(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_semantic_lock_shaped_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)
    benchmark = target_root / "benchmarks/independent_external_heldout/v0.1/cases.json"
    payload = json.loads(benchmark.read_text(encoding="utf-8"))
    payload["cases"][1]["selected_test"] = payload["cases"][0]["selected_test"]
    payload["selected_tests_sha256"] = hashlib.sha256(
        ("\n".join(case["selected_test"] for case in payload["cases"]) + "\n").encode()
    ).hexdigest()
    benchmark.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    gate = _run_gate(target_root)
    packet_result = _run_packet(target_root)
    independent = _run_independent_benchmark_gate(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode == 0, packet_result.stderr
    assert independent.returncode != 0
    assert "selected_test_semantic_lock.expected_node_ids mismatch" in independent.stderr
    assert "independent-external-heldout-benchmark-gate: PASS" not in independent.stdout


def test_independent_external_heldout_benchmark_gate_fails_on_semantically_weakened_selected_test(
    tmp_path: Path,
) -> None:
    target_root = _copy_minimal_gate_repo(tmp_path)
    _write_fake_passing_selected_test_with_task_proofs(
        target_root,
        [_valid_task_proof(), _valid_wrapper_task_proof()],
    )
    _refresh_task_source_manifest_test_file_digest(target_root)
    _refresh_independent_benchmark_test_file_digest(target_root)

    gate = _run_gate(target_root)
    packet_result = _run_packet(target_root)
    independent = _run_independent_benchmark_gate(target_root)

    assert gate.returncode == 0, gate.stderr
    assert packet_result.returncode == 0, packet_result.stderr
    assert independent.returncode != 0
    assert "selected test semantic lock missing required calls" in independent.stderr
    assert "independent-external-heldout-benchmark-gate: PASS" not in independent.stdout
