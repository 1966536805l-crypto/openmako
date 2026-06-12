#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPO="${OPENMAKO_GITHUB_REPO:-1966536805l-crypto/openmako}"
REMOTE="${OPENMAKO_REMOTE:-openmako}"
WORKFLOW="${OPENMAKO_AUTONOMOUS_WORKFLOW:-autonomous-learning-gate.yml}"
ARTIFACT_NAME="${OPENMAKO_AUTONOMOUS_ARTIFACT_NAME:-autonomous-learning-gate-summary}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-autonomous-learning-snapshot: could not resolve ${REMOTE}/main" >&2
  exit 2
fi

python3 - "$REPO" "$WORKFLOW" "$ARTIFACT_NAME" "$remote_sha" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from datetime import datetime, timezone


repo, workflow, artifact_name, remote_sha = sys.argv[1:5]
runs_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_RUNS_JSON")
artifacts_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON")
artifact_zip_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP")
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


def print_boundary_snapshot(reason: str, response_headers=None) -> None:
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
    print(
        "remote-autonomous-learning-snapshot: "
        "not-proof=external review; endorsement; stars; reposts; live autonomy; "
        "broad unknown-repository repair; external benchmark standing"
    )


def read_json_url(url: str, unavailable_reason: str) -> dict:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            print_boundary_snapshot("github_api_rate_limit", exc.headers)
            print(
                "remote-autonomous-learning-snapshot: GitHub API rate limit; "
                "re-check later or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN "
                "for authenticated API reads",
                file=sys.stderr,
            )
            sys.exit(2)
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


def read_artifact_zip(url: str) -> bytes:
    if artifact_zip_fixture:
        try:
            with open(artifact_zip_fixture, "rb") as handle:
                return handle.read()
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
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            print_boundary_snapshot("github_api_rate_limit", exc.headers)
            print(
                "remote-autonomous-learning-snapshot: GitHub API rate limit while reading artifact zip; "
                "re-check later or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN "
                "for authenticated API reads",
                file=sys.stderr,
            )
            sys.exit(2)
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


def read_summary_from_artifact_zip(data: bytes) -> dict:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            candidates = [
                name
                for name in archive.namelist()
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
            payload = json.loads(archive.read(summary_name).decode("utf-8"))
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
    return payload


def validate_artifact_summary(payload: dict) -> None:
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

    stage1_observed = stage1.get("observed_pytest")
    if not isinstance(stage1_observed, dict):
        errors.append("tests.stage1_trajectory_reuse_matrix.observed_pytest")
        stage1_observed = {}
    if stage1.get("expected_passed") != 3:
        errors.append("tests.stage1_trajectory_reuse_matrix.expected_passed")
    if stage1_observed.get("exit_code") != 0:
        errors.append("tests.stage1_trajectory_reuse_matrix.observed_pytest.exit_code")
    if stage1_observed.get("passed") != 3:
        errors.append("tests.stage1_trajectory_reuse_matrix.observed_pytest.passed")

    upstream_observed = upstream.get("observed_pytest")
    if not isinstance(upstream_observed, dict):
        errors.append("tests.upstream_hidden_pack_reuse.observed_pytest")
        upstream_observed = {}
    if upstream.get("expected_passed") != 1:
        errors.append("tests.upstream_hidden_pack_reuse.expected_passed")
    if upstream_observed.get("exit_code") != 0:
        errors.append("tests.upstream_hidden_pack_reuse.observed_pytest.exit_code")
    if upstream_observed.get("passed") != 1:
        errors.append("tests.upstream_hidden_pack_reuse.observed_pytest.passed")

    cross_upstream_observed = cross_upstream.get("observed_pytest")
    if not isinstance(cross_upstream_observed, dict):
        errors.append("tests.cross_upstream_no_seed_reuse.observed_pytest")
        cross_upstream_observed = {}
    if cross_upstream.get("expected_passed") != 2:
        errors.append("tests.cross_upstream_no_seed_reuse.expected_passed")
    if cross_upstream_observed.get("exit_code") != 0:
        errors.append("tests.cross_upstream_no_seed_reuse.observed_pytest.exit_code")
    if cross_upstream_observed.get("passed") != 2:
        errors.append("tests.cross_upstream_no_seed_reuse.observed_pytest.passed")

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
        "upstream_family_count": 2,
        "no_seed_stage1_repairs": 2,
        "hidden_stage2_tasks": 4,
        "no_learning_solved": 0,
        "approved_learning_solved": 4,
        "stability_repeats": 2,
        "stability_solved": 8,
        "cheated": 0,
    }
    for key, expected in required_cross_upstream.items():
        if cross_upstream_contract.get(key) != expected:
            errors.append(f"tests.cross_upstream_no_seed_reuse.expected_contract.{key}")

    required_not_proof = {
        "native live autonomy",
        "broad unknown-repository repair",
        "external benchmark standing",
        "remote CI proof",
        "external review",
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

    if errors:
        print(
            "remote-autonomous-learning-snapshot: artifact summary contract mismatch: "
            + ",".join(errors),
            file=sys.stderr,
        )
        sys.exit(1)


if runs_fixture:
    runs_data = read_json_fixture(runs_fixture, "workflow_runs_fixture_unreadable")
else:
    runs_data = read_json_url(workflow_runs_url, "workflow_runs_unreadable")

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
    "not-proof=external review; endorsement; stars; reposts; live autonomy; "
    "broad unknown-repository repair; external benchmark standing"
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

archive_url = artifact.get("archive_download_url") or (
    f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
)
artifact_summary = read_summary_from_artifact_zip(read_artifact_zip(archive_url))
validate_artifact_summary(artifact_summary)

print("remote-autonomous-learning-snapshot: PASS")
PY
