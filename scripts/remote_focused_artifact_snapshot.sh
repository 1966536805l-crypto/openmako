#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPO="${OPENMAKO_GITHUB_REPO:-1966536805l-crypto/openmako}"
REMOTE="${OPENMAKO_REMOTE:-openmako}"
WORKFLOW="${OPENMAKO_FOCUSED_WORKFLOW:-focused.yml}"
ARTIFACT_NAME="${OPENMAKO_FOCUSED_ARTIFACT_NAME:-focused-public-review-gate}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-focused-artifact-snapshot: could not resolve ${REMOTE}/main" >&2
  exit 2
fi

python3 - "$REPO" "$WORKFLOW" "$ARTIFACT_NAME" "$remote_sha" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO


repo, workflow, artifact_name, remote_sha = sys.argv[1:5]
runs_fixture = os.environ.get("OPENMAKO_FOCUSED_RUNS_JSON")
artifacts_fixture = os.environ.get("OPENMAKO_FOCUSED_ARTIFACTS_JSON")
artifact_zip_fixture = os.environ.get("OPENMAKO_FOCUSED_ARTIFACT_ZIP")
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
    "User-Agent": "openmako-remote-focused-artifact-snapshot",
}
if token:
    headers["Authorization"] = f"Bearer {token}"
    headers["X-GitHub-Api-Version"] = "2022-11-28"


def print_boundary_snapshot(reason: str, response_headers=None, *, include_auth_hint: bool = False) -> None:
    checked_at = datetime.now(timezone.utc)
    print(f"remote-focused-artifact-snapshot: repo={repo}")
    print(f"remote-focused-artifact-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-focused-artifact-snapshot: checked-at-utc={checked_at.isoformat()}")
    print(f"remote-focused-artifact-snapshot: manual-url={manual_url}")
    print(f"remote-focused-artifact-snapshot: unavailable={reason}")
    if response_headers:
        reset_at = response_headers.get("X-RateLimit-Reset")
        if reset_at:
            print(f"remote-focused-artifact-snapshot: rate-limit-reset-unix={reset_at}")
            try:
                reset_dt = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                reset_dt = None
            if reset_dt is not None:
                seconds_until_reset = max(0, int((reset_dt - checked_at).total_seconds()))
                print(f"remote-focused-artifact-snapshot: rate-limit-reset-utc={reset_dt.isoformat()}")
                print(
                    "remote-focused-artifact-snapshot: "
                    f"rerun-after-command=sleep {seconds_until_reset} && "
                    "bash scripts/remote_focused_artifact_snapshot.sh"
                )
    if include_auth_hint:
        print(
            "remote-focused-artifact-snapshot: "
            "auth-required=OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN"
        )
        print(
            "remote-focused-artifact-snapshot: "
            "fixture-rerun-command="
            "OPENMAKO_FOCUSED_RUNS_JSON=runs.json "
            "OPENMAKO_FOCUSED_ARTIFACTS_JSON=artifacts.json "
            "OPENMAKO_FOCUSED_ARTIFACT_ZIP=focused-public-review-gate.zip "
            "bash scripts/remote_focused_artifact_snapshot.sh"
        )
    print(
        "remote-focused-artifact-snapshot: "
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
                "remote-focused-artifact-snapshot: GitHub API rate limit; re-check later "
                "or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN",
                file=sys.stderr,
            )
            sys.exit(2)
        if exc.code == 401:
            print_boundary_snapshot("github_api_requires_auth", exc.headers, include_auth_hint=True)
            print(
                "remote-focused-artifact-snapshot: GitHub API requires authenticated reads",
                file=sys.stderr,
            )
            sys.exit(2)
        print_boundary_snapshot(f"github_api_error_{exc.code}")
        print(f"remote-focused-artifact-snapshot: GitHub API error {exc.code}: {body}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(f"remote-focused-artifact-snapshot: could not read GitHub API data: {exc}", file=sys.stderr)
        sys.exit(2)


def read_json_fixture(path: str, unavailable_reason: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(f"remote-focused-artifact-snapshot: could not read fixture {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def read_artifact_zip(url: str) -> bytes:
    if artifact_zip_fixture:
        try:
            with open(artifact_zip_fixture, "rb") as handle:
                return handle.read()
        except Exception as exc:
            print_boundary_snapshot("artifact_zip_fixture_unreadable")
            print(
                f"remote-focused-artifact-snapshot: could not read artifact zip fixture "
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
                "remote-focused-artifact-snapshot: GitHub API rate limit while reading artifact zip",
                file=sys.stderr,
            )
            sys.exit(2)
        if exc.code == 401:
            print_boundary_snapshot("artifact_zip_requires_auth", exc.headers, include_auth_hint=True)
            print(
                "remote-focused-artifact-snapshot: artifact zip download requires authenticated API access",
                file=sys.stderr,
            )
            sys.exit(2)
        print_boundary_snapshot(f"artifact_zip_api_error_{exc.code}")
        print(f"remote-focused-artifact-snapshot: artifact zip error {exc.code}: {body}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print_boundary_snapshot("artifact_zip_unreadable")
        print(f"remote-focused-artifact-snapshot: could not read artifact zip: {exc}", file=sys.stderr)
        sys.exit(2)


def fail(message: str) -> None:
    print(f"remote-focused-artifact-snapshot: {message}", file=sys.stderr)
    sys.exit(1)


runs_data = (
    read_json_fixture(runs_fixture, "workflow_runs_fixture_unreadable")
    if runs_fixture
    else read_json_url(workflow_runs_url, "workflow_runs_unreadable")
)
runs = runs_data.get("workflow_runs") or []
if not runs:
    print_boundary_snapshot("no_focused_workflow_runs")
    fail("no focused workflow runs found")

run = runs[0]
run_id = run.get("id")
head_sha = run.get("head_sha")
status = run.get("status")
conclusion = run.get("conclusion")
run_url = run.get("html_url", "")
print(f"remote-focused-artifact-snapshot: repo={repo}")
print(f"remote-focused-artifact-snapshot: remote-main-sha={remote_sha}")
print(f"remote-focused-artifact-snapshot: run-id={run_id}")
print(f"remote-focused-artifact-snapshot: run-sha={head_sha}")
print(f"remote-focused-artifact-snapshot: status={status} conclusion={conclusion}")
if run_url:
    print(f"remote-focused-artifact-snapshot: url={run_url}")
if head_sha != remote_sha:
    fail("latest focused run does not match remote main")
if status != "completed" or conclusion != "success":
    fail("focused workflow is not completed/success")

artifacts_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
artifacts_data = (
    read_json_fixture(artifacts_fixture, "artifacts_fixture_unreadable")
    if artifacts_fixture
    else read_json_url(artifacts_url, "artifacts_unreadable")
)
artifacts = artifacts_data.get("artifacts") or []
matches = [artifact for artifact in artifacts if artifact.get("name") == artifact_name]
if len(matches) != 1:
    fail(f"artifact '{artifact_name}' is missing or ambiguous")
artifact = matches[0]
if artifact.get("expired"):
    fail(f"artifact '{artifact_name}' is expired")
artifact_digest = artifact.get("digest")
if not isinstance(artifact_digest, str) or not artifact_digest.startswith("sha256:"):
    fail(f"artifact '{artifact_name}' digest is missing")
binding = artifact.get("workflow_run")
if isinstance(binding, dict):
    if binding.get("id") != run_id:
        fail("artifact workflow_run id does not match run id")
    if binding.get("head_sha") != head_sha:
        fail("artifact workflow_run head_sha does not match run sha")
artifact_url = artifact.get("archive_download_url")
if not isinstance(artifact_url, str) or not artifact_url:
    fail(f"artifact '{artifact_name}' archive_download_url is missing")

zip_data = read_artifact_zip(artifact_url)
zip_sha256 = hashlib.sha256(zip_data).hexdigest()
if artifact_digest != "sha256:" + zip_sha256:
    fail("artifact zip sha256 does not match artifact digest")

try:
    with zipfile.ZipFile(BytesIO(zip_data)) as archive:
        files = {
            name: archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        }
except zipfile.BadZipFile as exc:
    fail(f"artifact is not a readable zip: {exc}")

summary_candidates = [name for name in files if name.rsplit("/", 1)[-1] == "summary.json"]
if len(summary_candidates) != 1:
    fail(f"artifact zip must contain exactly one summary.json, found={len(summary_candidates)}")
summary_name = summary_candidates[0]
try:
    summary = json.loads(files[summary_name].decode("utf-8"))
except Exception as exc:
    fail(f"artifact summary is not valid JSON: {exc}")
if summary.get("schema_version") != "public-review-gate-artifact/v0.1":
    fail("artifact summary schema_version mismatch")
if summary.get("status") != "passed":
    fail("artifact summary status mismatch")
invocation = summary.get("invocation")
if not isinstance(invocation, dict) or invocation.get("git_commit") != remote_sha:
    fail("artifact summary git commit does not match remote main")
required_outputs = summary.get("required_outputs")
output_hashes = summary.get("output_sha256")
if not isinstance(required_outputs, list) or not isinstance(output_hashes, dict):
    fail("artifact summary output contract is malformed")
archive_hashes = {"sha256:" + hashlib.sha256(data).hexdigest() for data in files.values()}
for output in required_outputs:
    digest = output_hashes.get(output)
    if not isinstance(output, str) or not isinstance(digest, str):
        fail("artifact summary output digest is malformed")
    if digest not in archive_hashes:
        fail(f"artifact summary output digest is not present in artifact zip: {output}")

print(f"remote-focused-artifact-snapshot: artifact-name={artifact_name}")
print(f"remote-focused-artifact-snapshot: artifact-id={artifact.get('id')}")
print(f"remote-focused-artifact-snapshot: artifact-digest={artifact_digest}")
print(f"remote-focused-artifact-snapshot: artifact-zip-sha256={zip_sha256}")
print(f"remote-focused-artifact-snapshot: artifact-summary={summary_name}")
print(f"remote-focused-artifact-snapshot: artifact-summary-commit={invocation.get('git_commit')}")
print(f"remote-focused-artifact-snapshot: artifact-required-output-count={len(required_outputs)}")
print(
    "remote-focused-artifact-snapshot: "
    "not-proof=external review; endorsement; stars; reposts; live autonomy; "
    "broad unknown-repository repair; external benchmark standing"
)
print("remote-focused-artifact-snapshot: PASS")
PY
