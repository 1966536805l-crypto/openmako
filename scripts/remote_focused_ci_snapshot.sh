#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPO="${OPENMAKO_GITHUB_REPO:-1966536805l-crypto/openmako}"
REMOTE="${OPENMAKO_REMOTE:-openmako}"
WORKFLOW="${OPENMAKO_FOCUSED_WORKFLOW:-focused.yml}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-focused-ci-snapshot: could not resolve ${REMOTE}/main" >&2
  exit 2
fi

python3 - "$REPO" "$WORKFLOW" "$remote_sha" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


repo, workflow, remote_sha = sys.argv[1:4]
fixture = os.environ.get("OPENMAKO_FOCUSED_RUNS_JSON")
api_url = (
    f"https://api.github.com/repos/{repo}/actions/workflows/"
    f"{workflow}/runs?branch=main&per_page=1"
)
manual_url = f"https://github.com/{repo}/actions/workflows/{workflow}?query=branch%3Amain"
token = os.environ.get("OPENMAKO_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
headers = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "openmako-remote-focused-ci-snapshot",
}
if token:
    headers["Authorization"] = f"Bearer {token}"
    headers["X-GitHub-Api-Version"] = "2022-11-28"


def print_boundary_snapshot(reason: str, response_headers=None) -> None:
    checked_at = datetime.now(timezone.utc)
    print(f"remote-focused-ci-snapshot: repo={repo}")
    print(f"remote-focused-ci-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-focused-ci-snapshot: checked-at-utc={checked_at.isoformat()}")
    print(f"remote-focused-ci-snapshot: manual-url={manual_url}")
    print(f"remote-focused-ci-snapshot: unavailable={reason}")
    if response_headers:
        retry_after = response_headers.get("Retry-After")
        reset_at = response_headers.get("X-RateLimit-Reset")
        if retry_after:
            print(f"remote-focused-ci-snapshot: retry-after-seconds={retry_after}")
        if reset_at:
            print(f"remote-focused-ci-snapshot: rate-limit-reset-unix={reset_at}")
            try:
                reset_dt = datetime.fromtimestamp(int(reset_at), tz=timezone.utc)
                reset_utc = reset_dt.isoformat()
                seconds_until_reset = max(0, int((reset_dt - checked_at).total_seconds()))
            except (OSError, OverflowError, ValueError):
                reset_utc = ""
                seconds_until_reset = None
            if reset_utc:
                print(f"remote-focused-ci-snapshot: rate-limit-reset-utc={reset_utc}")
            if seconds_until_reset is not None:
                print(
                    "remote-focused-ci-snapshot: "
                    f"rate-limit-reset-seconds-until={seconds_until_reset}"
                )
    print("remote-focused-ci-snapshot: not-proof=external review; endorsement; stars; reposts")


try:
    if fixture:
        with open(fixture, encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        request = urllib.request.Request(
            api_url,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    if exc.code == 403 and "rate limit" in body.lower():
        print_boundary_snapshot("github_api_rate_limit", exc.headers)
        print(
            "remote-focused-ci-snapshot: GitHub API rate limit; re-check later "
            "or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN for authenticated API reads",
            file=sys.stderr,
        )
        sys.exit(2)
    print_boundary_snapshot(f"github_api_error_{exc.code}")
    print(f"remote-focused-ci-snapshot: GitHub API error {exc.code}: {body}", file=sys.stderr)
    sys.exit(2)
except Exception as exc:
    print_boundary_snapshot("workflow_runs_unreadable")
    print(f"remote-focused-ci-snapshot: could not read workflow runs: {exc}", file=sys.stderr)
    sys.exit(2)

runs = data.get("workflow_runs") or []
if not runs:
    print_boundary_snapshot("no_focused_workflow_runs")
    print("remote-focused-ci-snapshot: no focused workflow runs found", file=sys.stderr)
    sys.exit(1)

run = runs[0]
run_id = run.get("id")
head_sha = run.get("head_sha")
status = run.get("status")
conclusion = run.get("conclusion")
html_url = run.get("html_url", "")

print(f"remote-focused-ci-snapshot: repo={repo}")
print(f"remote-focused-ci-snapshot: remote-main-sha={remote_sha}")
print(f"remote-focused-ci-snapshot: run-id={run_id}")
print(f"remote-focused-ci-snapshot: run-sha={head_sha}")
print(f"remote-focused-ci-snapshot: status={status} conclusion={conclusion}")
if html_url:
    print(f"remote-focused-ci-snapshot: url={html_url}")
print("remote-focused-ci-snapshot: not-proof=external review; endorsement; stars; reposts")

if head_sha != remote_sha:
    print("remote-focused-ci-snapshot: latest focused run does not match remote main", file=sys.stderr)
    sys.exit(1)
if status != "completed" or conclusion != "success":
    print("remote-focused-ci-snapshot: focused workflow is not completed/success", file=sys.stderr)
    sys.exit(1)

print("remote-focused-ci-snapshot: PASS")
PY
