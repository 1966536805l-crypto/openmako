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
from datetime import datetime, timezone


repo, workflow, artifact_name, remote_sha = sys.argv[1:5]
runs_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_RUNS_JSON")
artifacts_fixture = os.environ.get("OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON")
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

print("remote-autonomous-learning-snapshot: PASS")
PY
