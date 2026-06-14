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
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape


repo, workflow, remote_sha = sys.argv[1:4]
fixture = os.environ.get("OPENMAKO_FOCUSED_RUNS_JSON")
run_html_fixture = os.environ.get("OPENMAKO_FOCUSED_RUN_HTML")
run_url_override = os.environ.get("OPENMAKO_FOCUSED_RUN_URL")
api_url = (
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
                print(
                    "remote-focused-ci-snapshot: "
                    "rerun-after-command="
                    f"sleep {seconds_until_reset} && bash scripts/remote_focused_ci_snapshot.sh"
                )
    print("remote-focused-ci-snapshot: not-proof=external review; endorsement; stars; reposts")


def read_html_fixture(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except Exception as exc:
        print_boundary_snapshot("run_html_fixture_unreadable")
        print(f"remote-focused-ci-snapshot: could not read HTML fixture {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def read_url(url: str, unavailable_reason: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "openmako-remote-focused-ci-html-fallback"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(f"remote-focused-ci-snapshot: could not read public HTML {url}: {exc}", file=sys.stderr)
        sys.exit(2)


def latest_run_url_from_workflow_page() -> str:
    workflow_page = unescape(read_url(manual_url, "workflow_html_unreadable"))
    match = re.search(rf"/{re.escape(repo)}/actions/runs/([0-9]+)", workflow_page)
    if not match:
        print_boundary_snapshot("workflow_html_missing_run_url")
        print("remote-focused-ci-snapshot: public workflow HTML did not expose a run URL", file=sys.stderr)
        sys.exit(2)
    return f"https://github.com/{repo}/actions/runs/{match.group(1)}"


def read_run_html() -> tuple[str, str]:
    if run_html_fixture:
        return unescape(read_html_fixture(run_html_fixture)), f"fixture:{run_html_fixture}"
    run_url = run_url_override or latest_run_url_from_workflow_page()
    return unescape(read_url(run_url, "run_html_unreadable")), run_url


def verify_public_html_fallback(reason: str, response_headers=None) -> None:
    page, source = read_run_html()
    run_id_match = re.search(r"/actions/runs/([0-9]+)", page)
    run_id = run_id_match.group(1) if run_id_match else "unknown"
    success = (
        'aria-label="completed successfully: "' in page
        or "completed successfully:" in page
        or "completed successfully" in page
    )
    if remote_sha not in page:
        print_boundary_snapshot("public_html_missing_remote_sha", response_headers)
        print("remote-focused-ci-snapshot: public HTML does not contain remote main SHA", file=sys.stderr)
        sys.exit(1)
    if not success:
        print_boundary_snapshot("public_html_not_completed_success", response_headers)
        print("remote-focused-ci-snapshot: public HTML does not show completed successfully", file=sys.stderr)
        sys.exit(1)

    print(f"remote-focused-ci-snapshot: repo={repo}")
    print(f"remote-focused-ci-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-focused-ci-snapshot: run-id={run_id}")
    print(f"remote-focused-ci-snapshot: run-sha={remote_sha}")
    print("remote-focused-ci-snapshot: status=completed conclusion=success")
    print("remote-focused-ci-snapshot: verified-by=public-html")
    print(f"remote-focused-ci-snapshot: public-html-source={source}")
    print(f"remote-focused-ci-snapshot: api-unavailable={reason}")
    print("remote-focused-ci-snapshot: not-proof=external review; endorsement; stars; reposts")
    print("remote-focused-ci-snapshot: PASS")


if os.environ.get("OPENMAKO_FORCE_PUBLIC_HTML_FALLBACK"):
    verify_public_html_fallback("forced_public_html_fallback")
    sys.exit(0)


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
        print(
            "remote-focused-ci-snapshot: GitHub API rate limit; re-check later "
            "or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN for authenticated API reads; "
            "trying public HTML fallback",
            file=sys.stderr,
        )
        verify_public_html_fallback("github_api_rate_limit", exc.headers)
        sys.exit(0)
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
