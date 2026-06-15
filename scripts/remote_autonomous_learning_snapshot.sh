#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPO="${OPENMAKO_GITHUB_REPO:-1966536805l-crypto/openmako}"
REMOTE="${OPENMAKO_REMOTE:-openmako}"
WORKFLOW="${OPENMAKO_AUTONOMOUS_WORKFLOW:-autonomous-learning-gate.yml}"
ARTIFACT_NAME="${OPENMAKO_AUTONOMOUS_ARTIFACT_NAME:-autonomous-learning-gate-summary}"
EVIDENCE_REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-https://github.com/1966536805l-crypto/openmako.git}"
EVIDENCE_BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-autonomous-learning-snapshot: could not resolve ${REMOTE}/main" >&2
  exit 2
fi

python3 - "$REPO" "$WORKFLOW" "$ARTIFACT_NAME" "$remote_sha" "$EVIDENCE_REMOTE" "$EVIDENCE_BRANCH" <<'PY'
from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path


repo, workflow, artifact_name, remote_sha, evidence_remote, evidence_branch = sys.argv[1:7]
runs_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_RUNS_JSON")
artifacts_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON")
artifact_zip_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP")
artifact_zip_http_status_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP_HTTP_STATUS")
workflow_runs_url = (
    f"https://api.github.com/repos/{repo}/actions/workflows/"
    f"{workflow}/runs?branch=main&per_page=1"
)
manual_url = f"https://github.com/{repo}/actions/workflows/{workflow}?query=branch%3Amain"
token = (
    os.environ.get("OPENMAKO_GITHUB_TOKEN")
    or os.environ.get("GITHUB_TOKEN")
    or os.environ.get("GH_TOKEN")
)
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "openmako-remote-autonomous-learning-snapshot",
}
if token:
    headers["Authorization"] = f"Bearer {token}"
    headers["X-GitHub-Api-Version"] = "2022-11-28"


def print_auth_hint() -> None:
    print(
        "remote-autonomous-learning-snapshot: "
        "auth-required=OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "rerun-auth-command=OPENMAKO_GITHUB_TOKEN=<token> "
        "bash scripts/remote_autonomous_learning_snapshot.sh"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "fixture-rerun-command="
        "OPENMAKO_AUTONOMOUS_RUNS_JSON=runs.json "
        "OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON=artifacts.json "
        "OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP=autonomous-learning-gate-summary.zip "
        "bash scripts/remote_autonomous_learning_snapshot.sh"
    )


def print_boundary_snapshot(reason: str, response_headers=None, *, include_auth_hint: bool = False) -> None:
    checked_at = datetime.now(timezone.utc)
    print(f"remote-autonomous-learning-snapshot: repo={repo}")
    print(f"remote-autonomous-learning-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-autonomous-learning-snapshot: checked-at-utc={checked_at.isoformat()}")
    print(f"remote-autonomous-learning-snapshot: manual-url={manual_url}")
    print(f"remote-autonomous-learning-snapshot: unavailable={reason}")
    if response_headers:
        retry_after = response_headers.get("Retry-After")
        reset_at = response_headers.get("X-RateLimit-Reset")
        if retry_after:
            print(f"remote-autonomous-learning-snapshot: retry-after-seconds={retry_after}")
        if reset_at:
            print(f"remote-autonomous-learning-snapshot: rate-limit-reset-unix={reset_at}")
            try:
                reset_dt = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
                reset_utc = reset_dt.isoformat()
                seconds_until_reset = max(0, int((reset_dt - checked_at).total_seconds()))
            except (OSError, OverflowError, ValueError):
                reset_utc = ""
                seconds_until_reset = None
            if reset_utc:
                print(f"remote-autonomous-learning-snapshot: rate-limit-reset-utc={reset_utc}")
            if seconds_until_reset is not None:
                print(
                    "remote-autonomous-learning-snapshot: "
                    f"rate-limit-reset-seconds-until={seconds_until_reset}"
                )
                print(
                    "remote-autonomous-learning-snapshot: "
                    "rerun-after-command="
                    f"sleep {seconds_until_reset} && bash scripts/remote_autonomous_learning_snapshot.sh"
                )
    if include_auth_hint:
        print_auth_hint()
    print(
        "remote-autonomous-learning-snapshot: "
        "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; "
        "external review; endorsement; stars; reposts; live autonomy; "
        "broad unknown-repository repair; external benchmark standing; "
        "independent external held-out benchmark"
    )


def unavailable_marker(reason: str, response_headers=None, *, include_auth_hint: bool = False) -> dict:
    print_boundary_snapshot(reason, response_headers, include_auth_hint=include_auth_hint)
    return {"__openmako_unavailable__": reason}


def get_unavailable_reason(payload: object) -> str:
    if isinstance(payload, dict):
        reason = payload.get("__openmako_unavailable__")
        if isinstance(reason, str):
            return reason
    return ""


def read_json_url(url: str, unavailable_reason: str) -> dict:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            print(
                "remote-autonomous-learning-snapshot: GitHub API rate limit; "
                "trying public evidence mirror fallback",
                file=sys.stderr,
            )
            return unavailable_marker("github_api_rate_limit", exc.headers)
        if exc.code == 401:
            print(
                "remote-autonomous-learning-snapshot: GitHub API requires authenticated reads; "
                "trying public evidence mirror fallback",
                file=sys.stderr,
            )
            return unavailable_marker("github_api_requires_auth", exc.headers, include_auth_hint=True)
        print_boundary_snapshot(f"github_api_error_{exc.code}")
        print(
            f"remote-autonomous-learning-snapshot: GitHub API error {exc.code}: {body}",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(
            f"remote-autonomous-learning-snapshot: could not read GitHub API data: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def read_json_fixture(path: str, unavailable_reason: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(
            f"remote-autonomous-learning-snapshot: could not read fixture {path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def read_artifact_zip(url: str) -> tuple[bytes | None, str]:
    if artifact_zip_http_status_fixture:
        if artifact_zip_http_status_fixture == "401":
            return None, "artifact_zip_requires_auth"
        if artifact_zip_http_status_fixture == "403-rate-limit":
            return None, "github_api_rate_limit"
        print_boundary_snapshot("artifact_zip_status_fixture_unsupported")
        print(
            "remote-autonomous-learning-snapshot: unsupported OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP_HTTP_STATUS="
            f"{artifact_zip_http_status_fixture}",
            file=sys.stderr,
        )
        sys.exit(2)
    if artifact_zip_fixture:
        try:
            with open(artifact_zip_fixture, "rb") as handle:
                return handle.read(), ""
        except Exception as exc:
            print_boundary_snapshot("artifact_zip_fixture_unreadable")
            print(
                f"remote-autonomous-learning-snapshot: could not read artifact zip fixture "
                f"{artifact_zip_fixture}: {exc}",
                file=sys.stderr,
            )
            sys.exit(2)

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            print_boundary_snapshot("github_api_rate_limit", exc.headers)
            print(
                "remote-autonomous-learning-snapshot: GitHub API rate limit while reading artifact zip; "
                "verifying public evidence mirror instead",
                file=sys.stderr,
            )
            return None, "github_api_rate_limit"
        if exc.code == 401:
            print_boundary_snapshot("artifact_zip_requires_auth", exc.headers, include_auth_hint=True)
            if token:
                token_message = (
                    "provided token was rejected or lacks Actions artifact read access"
                )
            else:
                token_message = "no GitHub token was provided"
            print(
                "remote-autonomous-learning-snapshot: GitHub artifact zip download "
                "requires authenticated API access; "
                f"{token_message}; set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN "
                "or provide OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP; verifying public evidence mirror instead",
                file=sys.stderr,
            )
            return None, "artifact_zip_requires_auth"
        print_boundary_snapshot(f"artifact_zip_api_error_{exc.code}")
        print(
            f"remote-autonomous-learning-snapshot: GitHub artifact zip error {exc.code}: {body}",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:
        print_boundary_snapshot("artifact_zip_unreadable")
        print(
            f"remote-autonomous-learning-snapshot: could not read artifact zip: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def read_artifact_bundle_from_zip(data: bytes) -> tuple[dict, dict[str, str]]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            archive_text_files = {}
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                archive_text_files[name] = archive.read(name).decode("utf-8", errors="replace")
            candidates = [
                name
                for name in archive_text_files
                if name.endswith("last_summary.json") and not name.endswith("/")
            ]
            if len(candidates) != 1:
                print(
                    "remote-autonomous-learning-snapshot: artifact zip must contain exactly one "
                    f"last_summary.json, found={len(candidates)}",
                    file=sys.stderr,
                )
                sys.exit(1)
            summary_name = candidates[0]
            payload = json.loads(archive_text_files[summary_name])
    except json.JSONDecodeError as exc:
        print(
            f"remote-autonomous-learning-snapshot: artifact summary is not valid JSON: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except zipfile.BadZipFile as exc:
        print(
            f"remote-autonomous-learning-snapshot: artifact is not a readable zip: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(
            f"remote-autonomous-learning-snapshot: could not read artifact summary: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(payload, dict):
        print("remote-autonomous-learning-snapshot: artifact summary is not an object", file=sys.stderr)
        sys.exit(1)
    print(f"remote-autonomous-learning-snapshot: artifact-summary={summary_name}")
    return payload, archive_text_files


def validate_artifact_summary(payload: dict, archive_text_files: dict[str, str]) -> None:
    errors = []
    def mapping_field(name: str) -> dict:
        value = payload.get(name)
        if isinstance(value, dict):
            return value
        errors.append(name)
        return {}

    if payload.get("schema_version") != "autonomous-learning-gate/v0.1":
        errors.append("schema_version")
    if payload.get("status") != "passed":
        errors.append("status")
    invocation = mapping_field("invocation")
    if invocation.get("git_commit") != remote_sha:
        errors.append("invocation.git_commit")
    segments = mapping_field("segments")
    expected_segments = {
        "stage1_trajectory_reuse_matrix": "passed",
        "upstream_hidden_pack_reuse": "passed",
        "cross_upstream_no_seed_reuse": "passed",
    }
    for segment, expected in expected_segments.items():
        if segments.get(segment) != expected:
            errors.append(f"segments.{segment}")

    tests = mapping_field("tests")
    stage1 = tests.get("stage1_trajectory_reuse_matrix")
    if not isinstance(stage1, dict):
        errors.append("tests.stage1_trajectory_reuse_matrix")
        stage1 = {}
    upstream = tests.get("upstream_hidden_pack_reuse")
    if not isinstance(upstream, dict):
        errors.append("tests.upstream_hidden_pack_reuse")
        upstream = {}
    cross_upstream = tests.get("cross_upstream_no_seed_reuse")
    if not isinstance(cross_upstream, dict):
        errors.append("tests.cross_upstream_no_seed_reuse")
        cross_upstream = {}

    manifest = mapping_field("task_source_manifest")
    manifest_path = manifest.get("path")
    manifest_artifact_path = manifest.get("artifact_path")
    manifest_sha256 = manifest.get("sha256")
    if not isinstance(manifest_path, str) or not manifest_path.endswith("scripts/autonomous_task_source_provenance.json"):
        errors.append("task_source_manifest.path")
    if not isinstance(manifest_artifact_path, str) or not manifest_artifact_path.endswith("task_source_provenance_manifest.json"):
        errors.append("task_source_manifest.artifact_path")
    if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        errors.append("task_source_manifest.sha256")
    manifest_payload = None
    manifest_matches = [
        name
        for name in archive_text_files
        if name.endswith("task_source_provenance_manifest.json")
    ]
    if len(manifest_matches) != 1:
        errors.append("artifact.task_source_manifest")
    else:
        manifest_name = manifest_matches[0]
        print(f"remote-autonomous-learning-snapshot: artifact-task-source-manifest={manifest_name}")
        manifest_text = archive_text_files[manifest_name]
        if hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() != manifest_sha256:
            errors.append("task_source_manifest.sha256")
        try:
            manifest_payload = json.loads(manifest_text)
        except json.JSONDecodeError:
            errors.append("artifact.task_source_manifest")

    def validate_pytest_segment_log(segment: str, entry: dict, expected_passed: int) -> None:
        log_path = entry.get("log_path")
        if not isinstance(log_path, str) or not log_path.endswith(f"pytest_logs/{segment}.log"):
            errors.append(f"tests.{segment}.log_path")
        suffix = f"pytest_logs/{segment}.log"
        matches = [name for name in archive_text_files if name.endswith(suffix)]
        if len(matches) != 1:
            errors.append(f"artifact.pytest_logs.{segment}")
            return
        log_name = matches[0]
        print(f"remote-autonomous-learning-snapshot: artifact-pytest-log={log_name}")
        log_text = archive_text_files[log_name]
        log_tail = entry.get("log_tail")
        if (
            not isinstance(log_tail, list)
            or not log_tail
            or len(log_tail) > 12
            or any(not isinstance(line, str) for line in log_tail)
        ):
            errors.append(f"tests.{segment}.log_tail")
            return
        log_lines = log_text.rstrip().splitlines()
        if len(log_lines) < len(log_tail) or log_lines[-len(log_tail):] != log_tail:
            errors.append(f"tests.{segment}.log_tail")
        if f"{expected_passed} passed" not in log_text:
            errors.append(f"artifact.pytest_logs.{segment}.passed")

    stage1_observed = stage1.get("observed_pytest")
    if not isinstance(stage1_observed, dict):
        errors.append("tests.stage1_trajectory_reuse_matrix.observed_pytest")
        stage1_observed = {}
    if stage1_observed.get("exit_code") != 0:
        errors.append("tests.stage1_trajectory_reuse_matrix.observed_pytest.exit_code")

    upstream_observed = upstream.get("observed_pytest")
    if not isinstance(upstream_observed, dict):
        errors.append("tests.upstream_hidden_pack_reuse.observed_pytest")
        upstream_observed = {}
    if upstream_observed.get("exit_code") != 0:
        errors.append("tests.upstream_hidden_pack_reuse.observed_pytest.exit_code")

    cross_upstream_observed = cross_upstream.get("observed_pytest")
    if not isinstance(cross_upstream_observed, dict):
        errors.append("tests.cross_upstream_no_seed_reuse.observed_pytest")
        cross_upstream_observed = {}
    if cross_upstream_observed.get("exit_code") != 0:
        errors.append("tests.cross_upstream_no_seed_reuse.observed_pytest.exit_code")

    upstream_contract = upstream.get("expected_contract")
    if not isinstance(upstream_contract, dict):
        errors.append("tests.upstream_hidden_pack_reuse.expected_contract")
        upstream_contract = {}
    required_upstream = {
        "upstream_family_count": 5,
        "hidden_task_count": 10,
        "no_learning_solved": 0,
        "approved_learning_solved": 10,
        "stability_repeats": 10,
        "stability_solved": 100,
        "success_rate_spread": 0.0,
        "cheat_caught": 10,
    }
    for key, expected in required_upstream.items():
        if upstream_contract.get(key) != expected:
            errors.append(f"tests.upstream_hidden_pack_reuse.expected_contract.{key}")

    cross_upstream_contract = cross_upstream.get("expected_contract")
    if not isinstance(cross_upstream_contract, dict):
        errors.append("tests.cross_upstream_no_seed_reuse.expected_contract")
        cross_upstream_contract = {}
    required_cross_upstream = {
        "upstream_family_count": 4,
        "no_seed_stage1_repairs": 4,
        "hidden_stage2_tasks": 8,
        "no_learning_solved": 0,
        "approved_learning_solved": 8,
        "stability_repeats": 2,
        "stability_solved": 16,
        "cheat_caught": 8,
    }
    for key, expected in required_cross_upstream.items():
        if cross_upstream_contract.get(key) != expected:
            errors.append(f"tests.cross_upstream_no_seed_reuse.expected_contract.{key}")

    task_proofs = payload.get("task_proofs")
    if not isinstance(task_proofs, dict):
        errors.append("task_proofs")
        task_proofs = {}
    upstream_proofs = task_proofs.get("upstream_hidden_pack_reuse")
    if not isinstance(upstream_proofs, list) or len(upstream_proofs) != 1:
        errors.append("task_proofs.upstream_hidden_pack_reuse")
        upstream_proofs = []
    cross_upstream_proofs = task_proofs.get("cross_upstream_no_seed_reuse")
    if not isinstance(cross_upstream_proofs, list) or len(cross_upstream_proofs) != 4:
        errors.append("task_proofs.cross_upstream_no_seed_reuse")
        cross_upstream_proofs = []

    def count_result_set(proofs: list, set_name: str, *, status: str, solved: bool) -> int:
        total = 0
        for proof in proofs:
            if proof.get("schema_version") != "autonomous-task-proof/v0.1":
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.schema_version")
            result_sets = proof.get("result_sets")
            if not isinstance(result_sets, dict):
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.result_sets")
                continue
            results = result_sets.get(set_name)
            if not isinstance(results, list) or not results:
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.result_sets.{set_name}")
                continue
            total += len(results)
            for item in results:
                if item.get("status") != status:
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.status")
                if item.get("solved") is not solved:
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.solved")
                if not item.get("task_id"):
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.task_id")
                changed_files = item.get("changed_files")
                if status == "solved" and (not isinstance(changed_files, list) or not changed_files):
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.changed_files")
                if status == "solved" and item.get("out_of_scope_files") != []:
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.out_of_scope_files")
                if status == "cheated" and item.get("failure_class") != "policy":
                    errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.{set_name}.failure_class")
        return total

    def sum_observed(proofs: list, key: str) -> int:
        total = 0
        for proof in proofs:
            counts = proof.get("observed_counts")
            if not isinstance(counts, dict):
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.observed_counts")
                continue
            value = counts.get(key)
            if not isinstance(value, int):
                errors.append(f"task_proofs.{proof.get('test_name', 'unknown')}.observed_counts.{key}")
                continue
            total += value
        return total

    if upstream_proofs:
        if count_result_set(upstream_proofs, "no_learning", status="failed", solved=False) != required_upstream["hidden_task_count"]:
            errors.append("task_proofs.upstream_hidden_pack_reuse.no_learning.count")
        if count_result_set(upstream_proofs, "approved_learning", status="solved", solved=True) != required_upstream["approved_learning_solved"]:
            errors.append("task_proofs.upstream_hidden_pack_reuse.approved_learning.count")
        if count_result_set(upstream_proofs, "stability", status="solved", solved=True) != required_upstream["stability_solved"]:
            errors.append("task_proofs.upstream_hidden_pack_reuse.stability.count")
        if count_result_set(upstream_proofs, "cheat", status="cheated", solved=False) != required_upstream["cheat_caught"]:
            errors.append("task_proofs.upstream_hidden_pack_reuse.cheat.count")
        for key in ("no_learning_solved", "approved_learning_solved", "stability_solved", "cheat_caught"):
            if sum_observed(upstream_proofs, key) != required_upstream[key]:
                errors.append(f"task_proofs.upstream_hidden_pack_reuse.observed_counts.{key}")

    if cross_upstream_proofs:
        if count_result_set(cross_upstream_proofs, "no_learning", status="failed", solved=False) != required_cross_upstream["hidden_stage2_tasks"]:
            errors.append("task_proofs.cross_upstream_no_seed_reuse.no_learning.count")
        if count_result_set(cross_upstream_proofs, "approved_learning", status="solved", solved=True) != required_cross_upstream["approved_learning_solved"]:
            errors.append("task_proofs.cross_upstream_no_seed_reuse.approved_learning.count")
        if count_result_set(cross_upstream_proofs, "stability", status="solved", solved=True) != required_cross_upstream["stability_solved"]:
            errors.append("task_proofs.cross_upstream_no_seed_reuse.stability.count")
        if count_result_set(cross_upstream_proofs, "cheat", status="cheated", solved=False) != required_cross_upstream["cheat_caught"]:
            errors.append("task_proofs.cross_upstream_no_seed_reuse.cheat.count")
        expected_cross_counts = {
            "approved_learning_solved": required_cross_upstream["approved_learning_solved"],
            "cheat_caught": required_cross_upstream["cheat_caught"],
            "hidden_stage2_tasks": required_cross_upstream["hidden_stage2_tasks"],
            "no_learning_solved": required_cross_upstream["no_learning_solved"],
            "stability_solved": required_cross_upstream["stability_solved"],
        }
        for key, expected in expected_cross_counts.items():
            if sum_observed(cross_upstream_proofs, key) != expected:
                errors.append(f"task_proofs.cross_upstream_no_seed_reuse.observed_counts.{key}")

    provenance = payload.get("task_source_provenance")
    if not isinstance(provenance, dict):
        errors.append("task_source_provenance")
        provenance = {}
    if manifest_payload is not None and provenance != manifest_payload:
        errors.append("task_source_provenance.manifest")
    if provenance.get("schema_version") != "autonomous-task-source-provenance/v0.1":
        errors.append("task_source_provenance.schema_version")
    if provenance.get("independence_claim") != "repo-authored-regression-pack":
        errors.append("task_source_provenance.independence_claim")
    if provenance.get("external_heldout") is not False:
        errors.append("task_source_provenance.external_heldout")
    source_boundary = provenance.get("source_boundary")
    if not isinstance(source_boundary, str) or "not an independent external held-out benchmark" not in source_boundary:
        errors.append("task_source_provenance.source_boundary")
    provenance_segments = provenance.get("segments")
    if not isinstance(provenance_segments, dict):
        errors.append("task_source_provenance.segments")
        provenance_segments = {}
    required_provenance_segments = {
        "stage1_trajectory_reuse_matrix": ("repo-authored-e2e-regression", 3),
        "upstream_hidden_pack_reuse": ("repo-authored-upstream-inspired-hidden-pack", 1),
        "cross_upstream_no_seed_reuse": ("repo-authored-cross-upstream-inspired-regression", 4),
    }
    node_id_re = re.compile(r"^tests/[A-Za-z0-9_./]+\.py::[A-Za-z_][A-Za-z0-9_]*::test_[A-Za-z0-9_]+$")

    def selected_tests_sha256(selected):
        return hashlib.sha256(("\n".join(selected) + "\n").encode("utf-8")).hexdigest()

    all_selected_tests = set()
    for segment, (source_kind, minimum_count) in required_provenance_segments.items():
        segment_entry = provenance_segments.get(segment)
        if not isinstance(segment_entry, dict):
            errors.append(f"task_source_provenance.segments.{segment}")
            segment_entry = {}
        if segment_entry.get("source_kind") != source_kind:
            errors.append(f"task_source_provenance.segments.{segment}.source_kind")
        if segment_entry.get("external_heldout") is not False:
            errors.append(f"task_source_provenance.segments.{segment}.external_heldout")
        tests_entry = tests.get(segment)
        if not isinstance(tests_entry, dict):
            tests_entry = {}
        selected_tests = segment_entry.get("selected_tests")
        if (
            not isinstance(selected_tests, list)
            or len(selected_tests) < minimum_count
            or len(selected_tests) != len(set(selected_tests))
            or any(
                not isinstance(item, str)
                or not node_id_re.fullmatch(item)
                or item.startswith("-")
                or any(char.isspace() for char in item)
                for item in selected_tests
            )
        ):
            errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
            selected_tests = []
        selected_tests_digest = segment_entry.get("selected_tests_sha256")
        if (
            not isinstance(selected_tests_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", selected_tests_digest)
            or selected_tests_digest != selected_tests_sha256(selected_tests)
        ):
            errors.append(f"task_source_provenance.segments.{segment}.selected_tests_sha256")
        duplicate_across_segments = all_selected_tests.intersection(selected_tests)
        if duplicate_across_segments:
            errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
        all_selected_tests.update(selected_tests)
        if selected_tests != tests_entry.get("selected"):
            errors.append(f"tests.{segment}.selected")
            errors.append(f"task_source_provenance.segments.{segment}.selected_tests")
        if tests_entry.get("expected_passed") != len(selected_tests):
            errors.append(f"tests.{segment}.expected_passed")
        observed = tests_entry.get("observed_pytest")
        if not isinstance(observed, dict):
            observed = {}
        if observed.get("passed") != len(selected_tests):
            errors.append(f"tests.{segment}.observed_pytest.passed")
        validate_pytest_segment_log(segment, tests_entry, len(selected_tests))

    required_not_proof = {
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
        "remote CI proof",
        "external review",
        "independent external held-out benchmark",
        "endorsement",
        "stars",
        "reposts",
    }
    if set(payload.get("not_proof") or []) != required_not_proof:
        errors.append("not_proof")

    print(f"remote-autonomous-learning-snapshot: artifact-summary-commit={invocation.get('git_commit')}")
    print(f"remote-autonomous-learning-snapshot: artifact-summary-status={payload.get('status')}")
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-upstream-hidden-task-count="
        f"{upstream_contract.get('hidden_task_count')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-upstream-stability-solved="
        f"{upstream_contract.get('stability_solved')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-upstream-cheat-caught="
        f"{upstream_contract.get('cheat_caught')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-cross-upstream-hidden-stage2-tasks="
        f"{cross_upstream_contract.get('hidden_stage2_tasks')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-cross-upstream-stability-solved="
        f"{cross_upstream_contract.get('stability_solved')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-cross-upstream-cheat-caught="
        f"{cross_upstream_contract.get('cheat_caught')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-task-proof-files="
        f"{len(upstream_proofs) + len(cross_upstream_proofs)}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-task-source-provenance="
        f"{provenance.get('independence_claim')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-task-source-manifest="
        f"{manifest.get('path')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-task-source-manifest-sha256="
        f"{manifest.get('sha256')}"
    )
    print(
        "remote-autonomous-learning-snapshot: "
        "artifact-summary-external-heldout="
        f"{str(provenance.get('external_heldout')).lower()}"
    )

    if errors:
        print(
            "remote-autonomous-learning-snapshot: artifact summary contract mismatch: "
            + ",".join(errors),
            file=sys.stderr,
        )
        sys.exit(1)


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def fail_public_mirror(message: str) -> None:
    print(f"remote-autonomous-learning-snapshot: {message}", file=sys.stderr)
    sys.exit(1)


def verify_public_evidence_mirror(
    reason: str,
    *,
    expected_run_id: object | None = None,
    expected_artifact_id: object | None = None,
    expected_artifact_digest: object | None = None,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        evidence_dir = Path(tmp) / "evidence"
        clone = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                evidence_branch,
                evidence_remote,
                str(evidence_dir),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if clone.returncode != 0:
            print_boundary_snapshot("public_evidence_mirror_unreadable")
            print(
                "remote-autonomous-learning-snapshot: could not clone public evidence mirror: "
                + clone.stderr.strip(),
                file=sys.stderr,
            )
            sys.exit(2)
        mirror_path = evidence_dir / "autonomous" / remote_sha / "public_mirror" / "manifest.json"
        if not mirror_path.is_file():
            fail_public_mirror("public evidence autonomous artifact mirror is missing")
        try:
            mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        except Exception as exc:
            fail_public_mirror(f"public evidence autonomous artifact mirror manifest is invalid JSON: {exc}")
        if mirror.get("schema_version") != "autonomous-public-evidence-artifact-mirror/v0.1":
            fail_public_mirror("public evidence autonomous artifact mirror schema_version mismatch")
        if mirror.get("status") != "passed":
            fail_public_mirror("public evidence autonomous artifact mirror status mismatch")
        if mirror.get("git_commit") != remote_sha:
            fail_public_mirror("public evidence autonomous artifact mirror commit mismatch")
        if mirror.get("mirror_scope") != "github-actions-upload-directory-content":
            fail_public_mirror("public evidence autonomous artifact mirror scope mismatch")
        files = mirror.get("files")
        if not isinstance(files, dict) or not files:
            fail_public_mirror("public evidence autonomous artifact mirror files contract is malformed")
        for required in ("last_summary.json", "task_source_provenance_manifest.json"):
            if required not in files:
                fail_public_mirror(f"public evidence autonomous artifact mirror required file missing: {required}")
        pytest_logs = [name for name in files if name.startswith("pytest_logs/") and name.endswith(".log")]
        if len(pytest_logs) < 3:
            fail_public_mirror("public evidence autonomous artifact mirror pytest logs missing")
        if mirror.get("file_count") != len(files):
            fail_public_mirror("public evidence autonomous artifact mirror file count mismatch")
        archive_relative = mirror.get("archive_path")
        if archive_relative != "public_mirror/autonomous-learning-gate-public-mirror.zip":
            fail_public_mirror("public evidence autonomous artifact mirror archive path mismatch")
        archive_path = mirror_path.parent.parent / archive_relative
        if not archive_path.is_file():
            fail_public_mirror("public evidence autonomous artifact mirror archive missing")
        archive_bytes = archive_path.read_bytes()
        archive_sha256 = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
        if mirror.get("archive_sha256") != archive_sha256:
            fail_public_mirror("public evidence autonomous artifact mirror archive digest mismatch")
        meta = mirror.get("github_actions_artifact")
        if not isinstance(meta, dict):
            fail_public_mirror("public evidence autonomous artifact mirror artifact metadata missing")
        if meta.get("name") != artifact_name:
            fail_public_mirror("public evidence autonomous artifact mirror artifact name mismatch")
        run_id = str(meta.get("run_id") or "")
        artifact_id = str(meta.get("artifact_id") or "")
        artifact_digest = meta.get("artifact_digest")
        if not run_id.isdigit():
            fail_public_mirror("public evidence autonomous artifact mirror run id missing or malformed")
        if not str(meta.get("run_attempt") or "").isdigit():
            fail_public_mirror("public evidence autonomous artifact mirror run attempt missing or malformed")
        if not artifact_id.isdigit():
            fail_public_mirror("public evidence autonomous artifact mirror artifact id missing or malformed")
        if not is_sha256_digest(artifact_digest):
            fail_public_mirror("public evidence autonomous artifact mirror artifact digest missing or malformed")
        if expected_run_id is not None and run_id != str(expected_run_id):
            fail_public_mirror("public evidence autonomous artifact mirror run id mismatch")
        if expected_artifact_id is not None and artifact_id != str(expected_artifact_id):
            fail_public_mirror("public evidence autonomous artifact mirror artifact id mismatch")
        if expected_artifact_digest is not None and artifact_digest != expected_artifact_digest:
            fail_public_mirror("public evidence autonomous artifact mirror artifact digest mismatch")
        not_proof = mirror.get("not_proof")
        if (
            not isinstance(not_proof, list)
            or "GitHub Actions API artifact zip endpoint byte-for-byte archive" not in not_proof
            or "independent external held-out benchmark" not in not_proof
        ):
            fail_public_mirror("public evidence autonomous artifact mirror boundary mismatch")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = sorted(name for name in archive.namelist() if not name.endswith("/"))
                if names != sorted(files):
                    fail_public_mirror("public evidence autonomous artifact mirror archive file list mismatch")
                for name in names:
                    if name.startswith("/") or ".." in Path(name).parts:
                        fail_public_mirror(f"public evidence autonomous artifact mirror archive unsafe path: {name}")
                    digest = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
                    if files.get(name) != digest:
                        fail_public_mirror(f"public evidence autonomous artifact mirror archive digest mismatch: {name}")
        except zipfile.BadZipFile as exc:
            fail_public_mirror(f"public evidence autonomous artifact mirror archive is not a zip: {exc}")

        artifact_summary, artifact_text_files = read_artifact_bundle_from_zip(archive_bytes)
        validate_artifact_summary(artifact_summary, artifact_text_files)

    print("remote-autonomous-learning-snapshot: verified-by=public-evidence-branch")
    print(f"remote-autonomous-learning-snapshot: api-or-zip-unavailable={reason}")
    print(f"remote-autonomous-learning-snapshot: artifact-name={artifact_name}")
    print(f"remote-autonomous-learning-snapshot: artifact-id={artifact_id}")
    print(f"remote-autonomous-learning-snapshot: artifact-digest={artifact_digest}")
    print("remote-autonomous-learning-snapshot: artifact-content-mirror=verified-by-public-evidence-branch")
    print(f"remote-autonomous-learning-snapshot: artifact-mirror-archive-sha256={archive_sha256}")
    print(f"remote-autonomous-learning-snapshot: artifact-mirror-file-count={len(files)}")
    print("remote-autonomous-learning-snapshot: artifact-zip-contract=api-zip-endpoint-unverified-by-public-evidence-branch")
    print(
        "remote-autonomous-learning-snapshot: "
        "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; external review; endorsement; stars; reposts; "
        "live autonomy; broad unknown-repository repair; external benchmark standing; "
        "independent external held-out benchmark"
    )
    print("remote-autonomous-learning-snapshot: PASS")


if runs_fixture:
    runs_data = read_json_fixture(runs_fixture, "workflow_runs_fixture_unreadable")
else:
    runs_data = read_json_url(workflow_runs_url, "workflow_runs_unreadable")

runs_unavailable = get_unavailable_reason(runs_data)
if runs_unavailable:
    verify_public_evidence_mirror(runs_unavailable)
    sys.exit(0)

runs = runs_data.get("workflow_runs") or []
if not runs:
    print_boundary_snapshot("no_autonomous_workflow_runs")
    print(
        "remote-autonomous-learning-snapshot: no autonomous-learning workflow runs found",
        file=sys.stderr,
    )
    sys.exit(1)

run = runs[0]
run_id = run.get("id")
head_sha = run.get("head_sha")
status = run.get("status")
conclusion = run.get("conclusion")
html_url = run.get("html_url", "")

print(f"remote-autonomous-learning-snapshot: repo={repo}")
print(f"remote-autonomous-learning-snapshot: remote-main-sha={remote_sha}")
print(f"remote-autonomous-learning-snapshot: run-id={run_id}")
print(f"remote-autonomous-learning-snapshot: run-sha={head_sha}")
print(f"remote-autonomous-learning-snapshot: status={status} conclusion={conclusion}")
if html_url:
    print(f"remote-autonomous-learning-snapshot: url={html_url}")
print(
    "remote-autonomous-learning-snapshot: "
    "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; "
    "external review; endorsement; stars; reposts; live autonomy; "
    "broad unknown-repository repair; external benchmark standing; "
    "independent external held-out benchmark"
)

if head_sha != remote_sha:
    print(
        "remote-autonomous-learning-snapshot: latest autonomous-learning run does not match remote main",
        file=sys.stderr,
    )
    sys.exit(1)
if status != "completed" or conclusion != "success":
    print(
        "remote-autonomous-learning-snapshot: autonomous-learning workflow is not completed/success",
        file=sys.stderr,
    )
    sys.exit(1)
if not run_id:
    print("remote-autonomous-learning-snapshot: autonomous-learning run id is missing", file=sys.stderr)
    sys.exit(1)

artifacts_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"
if artifacts_fixture:
    artifacts_data = read_json_fixture(artifacts_fixture, "artifacts_fixture_unreadable")
else:
    artifacts_data = read_json_url(artifacts_url, "artifacts_unreadable")

artifacts_unavailable = get_unavailable_reason(artifacts_data)
if artifacts_unavailable:
    verify_public_evidence_mirror(artifacts_unavailable, expected_run_id=run_id)
    sys.exit(0)

artifacts = artifacts_data.get("artifacts") or []
matching = [artifact for artifact in artifacts if artifact.get("name") == artifact_name]
if not matching:
    print(
        f"remote-autonomous-learning-snapshot: artifact {artifact_name!r} is missing",
        file=sys.stderr,
    )
    sys.exit(1)

artifact = matching[0]
artifact_id = artifact.get("id")
artifact_digest = artifact.get("digest")
artifact_size = artifact.get("size_in_bytes")
artifact_expired = artifact.get("expired")
artifact_workflow_run = artifact.get("workflow_run")

print(f"remote-autonomous-learning-snapshot: artifact-name={artifact_name}")
print(f"remote-autonomous-learning-snapshot: artifact-id={artifact_id}")
print(f"remote-autonomous-learning-snapshot: artifact-size-bytes={artifact_size}")
if artifact.get("created_at"):
    print(f"remote-autonomous-learning-snapshot: artifact-created-at={artifact['created_at']}")
if artifact.get("expires_at"):
    print(f"remote-autonomous-learning-snapshot: artifact-expires-at={artifact['expires_at']}")
print(f"remote-autonomous-learning-snapshot: artifact-digest={artifact_digest}")

if artifact_expired is True:
    print("remote-autonomous-learning-snapshot: autonomous-learning artifact is expired", file=sys.stderr)
    sys.exit(1)
if not artifact_id:
    print("remote-autonomous-learning-snapshot: autonomous-learning artifact id is missing", file=sys.stderr)
    sys.exit(1)
if not artifact_digest:
    print("remote-autonomous-learning-snapshot: autonomous-learning artifact digest is missing", file=sys.stderr)
    sys.exit(1)
if not is_sha256_digest(artifact_digest):
    print("remote-autonomous-learning-snapshot: unsupported artifact digest format", file=sys.stderr)
    sys.exit(1)
if artifacts_fixture:
    if not isinstance(artifact_workflow_run, dict):
        print(
            "remote-autonomous-learning-snapshot: artifact fixture is missing workflow_run binding",
            file=sys.stderr,
        )
        sys.exit(1)
    if artifact_workflow_run.get("id") != run_id:
        print(
            "remote-autonomous-learning-snapshot: artifact fixture workflow_run id does not match run id",
            file=sys.stderr,
        )
        sys.exit(1)
    if artifact_workflow_run.get("head_sha") != head_sha:
        print(
            "remote-autonomous-learning-snapshot: artifact fixture workflow_run head_sha does not match run sha",
            file=sys.stderr,
        )
        sys.exit(1)

archive_url = artifact.get("archive_download_url") or (
    f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
)
artifact_zip, zip_unavailable_reason = read_artifact_zip(archive_url)
if artifact_zip is None:
    verify_public_evidence_mirror(
        zip_unavailable_reason,
        expected_run_id=run_id,
        expected_artifact_id=artifact_id,
        expected_artifact_digest=artifact_digest,
    )
    sys.exit(0)
artifact_zip_sha256 = hashlib.sha256(artifact_zip).hexdigest()
print(f"remote-autonomous-learning-snapshot: artifact-zip-sha256={artifact_zip_sha256}")
if artifact_digest.startswith("sha256:"):
    expected_artifact_sha256 = artifact_digest.removeprefix("sha256:")
    if artifact_zip_sha256 != expected_artifact_sha256:
        print(
            "remote-autonomous-learning-snapshot: artifact zip sha256 does not match artifact digest",
            file=sys.stderr,
        )
        sys.exit(1)
else:
    print("remote-autonomous-learning-snapshot: unsupported artifact digest format", file=sys.stderr)
    sys.exit(1)
artifact_summary, artifact_text_files = read_artifact_bundle_from_zip(artifact_zip)
validate_artifact_summary(artifact_summary, artifact_text_files)

print("remote-autonomous-learning-snapshot: PASS")
PY
