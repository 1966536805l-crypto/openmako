#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPO="${OPENMAKO_GITHUB_REPO:-1966536805l-crypto/openmako}"
REMOTE="${OPENMAKO_REMOTE:-openmako}"
WORKFLOW="${OPENMAKO_FOCUSED_WORKFLOW:-focused.yml}"
ARTIFACT_NAME="${OPENMAKO_FOCUSED_ARTIFACT_NAME:-focused-public-review-gate}"
EVIDENCE_REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-https://github.com/1966536805l-crypto/openmako.git}"
EVIDENCE_BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-focused-artifact-snapshot: could not resolve ${REMOTE}/main" >&2
  exit 2
fi

python3 - "$REPO" "$WORKFLOW" "$ARTIFACT_NAME" "$remote_sha" "$EVIDENCE_REMOTE" "$EVIDENCE_BRANCH" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path


repo, workflow, artifact_name, remote_sha, evidence_remote, evidence_branch = sys.argv[1:7]
runs_fixture = os.environ.get("OPENMAKO_FOCUSED_RUNS_JSON")
artifacts_fixture = os.environ.get("OPENMAKO_FOCUSED_ARTIFACTS_JSON")
artifact_zip_fixture = os.environ.get("OPENMAKO_FOCUSED_ARTIFACT_ZIP")
artifact_zip_http_status_fixture = os.environ.get("OPENMAKO_FOCUSED_ARTIFACT_ZIP_HTTP_STATUS")
run_html_fixture = os.environ.get("OPENMAKO_FOCUSED_RUN_HTML")
run_url_override = os.environ.get("OPENMAKO_FOCUSED_RUN_URL")
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


def read_html_fixture(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except Exception as exc:
        print_boundary_snapshot("run_html_fixture_unreadable")
        print(
            f"remote-focused-artifact-snapshot: could not read HTML fixture {path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def read_text_url(url: str, unavailable_reason: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "openmako-remote-focused-artifact-html-fallback"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print_boundary_snapshot(unavailable_reason)
        print(
            f"remote-focused-artifact-snapshot: could not read public HTML {url}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def latest_run_url_from_workflow_page() -> str:
    workflow_page = unescape(read_text_url(manual_url, "workflow_html_unreadable"))
    match = re.search(rf"/{re.escape(repo)}/actions/runs/([0-9]+)", workflow_page)
    if not match:
        print_boundary_snapshot("workflow_html_missing_run_url")
        print(
            "remote-focused-artifact-snapshot: public workflow HTML did not expose a run URL",
            file=sys.stderr,
        )
        sys.exit(2)
    return f"https://github.com/{repo}/actions/runs/{match.group(1)}"


def read_run_html() -> tuple[str, str]:
    if run_html_fixture:
        return unescape(read_html_fixture(run_html_fixture)), f"fixture:{run_html_fixture}"
    run_url = run_url_override or latest_run_url_from_workflow_page()
    return unescape(read_text_url(run_url, "run_html_unreadable")), run_url


def fail(message: str) -> None:
    print(f"remote-focused-artifact-snapshot: {message}", file=sys.stderr)
    sys.exit(1)


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def verify_public_evidence_mirror(
    *,
    run_id: str,
    artifact_id: str,
    artifact_digest: str,
) -> dict:
    import subprocess
    import tempfile

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
                "remote-focused-artifact-snapshot: could not clone public evidence mirror: "
                + clone.stderr.strip(),
                file=sys.stderr,
            )
            sys.exit(2)
        mirror_path = evidence_dir / "focused" / remote_sha / "public_mirror" / "manifest.json"
        if not mirror_path.is_file():
            fail("public evidence artifact content mirror is missing")
        try:
            mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        except Exception as exc:
            fail(f"public evidence artifact mirror manifest is invalid JSON: {exc}")
        if mirror.get("schema_version") != "public-evidence-artifact-mirror/v0.2":
            fail("public evidence artifact mirror schema_version mismatch")
        if mirror.get("status") != "passed":
            fail("public evidence artifact mirror status mismatch")
        if mirror.get("git_commit") != remote_sha:
            fail("public evidence artifact mirror commit mismatch")
        if mirror.get("mirror_scope") != "github-actions-upload-directory-content":
            fail("public evidence artifact mirror scope mismatch")
        files = mirror.get("files")
        if not isinstance(files, dict) or not files:
            fail("public evidence artifact mirror files contract is malformed")
        required_outputs = mirror.get("required_outputs")
        if not isinstance(required_outputs, list) or not required_outputs:
            fail("public evidence artifact mirror required_outputs missing")
        for required in ("summary.json", "invocation.json", *required_outputs):
            if required not in files:
                fail(f"public evidence artifact mirror required file missing: {required}")
        archive_relative = mirror.get("archive_path")
        if archive_relative != "public_mirror/focused-public-review-gate-public-mirror.zip":
            fail("public evidence artifact mirror archive path mismatch")
        archive_path = mirror_path.parent.parent / archive_relative
        if not archive_path.is_file():
            fail("public evidence artifact mirror archive missing")
        archive_sha256 = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if mirror.get("archive_sha256") != archive_sha256:
            fail("public evidence artifact mirror archive digest mismatch")
        if mirror.get("file_count") != len(files):
            fail("public evidence artifact mirror file count mismatch")
        meta = mirror.get("github_actions_artifact")
        if not isinstance(meta, dict):
            fail("public evidence artifact mirror GitHub artifact metadata missing")
        if meta.get("name") != artifact_name:
            fail("public evidence artifact mirror artifact name mismatch")
        if not str(meta.get("run_id") or "").isdigit():
            fail("public evidence artifact mirror run id missing or malformed")
        if str(meta.get("run_id")) != str(run_id):
            fail("public evidence artifact mirror run id mismatch")
        if not str(meta.get("artifact_id") or "").isdigit():
            fail("public evidence artifact mirror artifact id missing or malformed")
        if str(meta.get("artifact_id")) != str(artifact_id):
            fail("public evidence artifact mirror artifact id mismatch")
        if not is_sha256_digest(meta.get("artifact_digest")):
            fail("public evidence artifact mirror artifact digest missing or malformed")
        if meta.get("artifact_digest") != artifact_digest:
            fail("public evidence artifact mirror artifact digest mismatch")
        not_proof = mirror.get("not_proof")
        if (
            not isinstance(not_proof, list)
            or "GitHub Actions API artifact zip endpoint byte-for-byte archive" not in not_proof
        ):
            fail("public evidence artifact mirror boundary mismatch")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = sorted(name for name in archive.namelist() if not name.endswith("/"))
                if names != sorted(files):
                    fail("public evidence artifact mirror archive file list mismatch")
                for name in names:
                    if name.startswith("/") or ".." in Path(name).parts:
                        fail(f"public evidence artifact mirror archive unsafe path: {name}")
                    digest = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
                    if files.get(name) != digest:
                        fail(f"public evidence artifact mirror archive digest mismatch: {name}")
        except zipfile.BadZipFile as exc:
            fail(f"public evidence artifact mirror archive is not a zip: {exc}")
        return mirror


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
        print(
            "remote-focused-artifact-snapshot: public HTML does not contain remote main SHA",
            file=sys.stderr,
        )
        sys.exit(1)
    if not success:
        print_boundary_snapshot("public_html_not_completed_success", response_headers)
        print(
            "remote-focused-artifact-snapshot: public HTML does not show completed successfully",
            file=sys.stderr,
        )
        sys.exit(1)
    if artifact_name not in page:
        print_boundary_snapshot("public_html_missing_artifact_name", response_headers)
        print(
            f"remote-focused-artifact-snapshot: public HTML does not contain artifact '{artifact_name}'",
            file=sys.stderr,
        )
        sys.exit(1)

    artifact_id = None
    artifact_digest = None
    for row_match in re.finditer(
        r'<tr[^>]*data-artifact-id="(?P<id>[0-9]+)"(?P<row>.*?)</tr>',
        page,
        flags=re.S,
    ):
        if artifact_name not in row_match.group("row"):
            continue
        artifact_id = row_match.group("id")
        digest_match = re.search(r"sha256:[0-9a-f]{64}", row_match.group("row"))
        if digest_match:
            artifact_digest = digest_match.group(0)
        break
    if artifact_id is None:
        id_match = re.search(r'data-artifact-id="([0-9]+)"', page)
        artifact_id = id_match.group(1) if id_match else None
    if artifact_digest is None:
        digest_match = re.search(r"sha256:[0-9a-f]{64}", page)
        artifact_digest = digest_match.group(0) if digest_match else None
    if not artifact_id or not artifact_digest:
        print_boundary_snapshot("public_html_missing_artifact_id_or_digest", response_headers)
        print(
            "remote-focused-artifact-snapshot: public HTML is missing artifact id or digest",
            file=sys.stderr,
        )
        sys.exit(1)
    mirror = verify_public_evidence_mirror(
        run_id=run_id,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )

    print(f"remote-focused-artifact-snapshot: repo={repo}")
    print(f"remote-focused-artifact-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-focused-artifact-snapshot: run-id={run_id}")
    print(f"remote-focused-artifact-snapshot: run-sha={remote_sha}")
    print("remote-focused-artifact-snapshot: status=completed conclusion=success")
    print("remote-focused-artifact-snapshot: verified-by=public-html")
    print(f"remote-focused-artifact-snapshot: public-html-source={source}")
    print(f"remote-focused-artifact-snapshot: api-unavailable={reason}")
    print(f"remote-focused-artifact-snapshot: artifact-name={artifact_name}")
    print(f"remote-focused-artifact-snapshot: artifact-id={artifact_id}")
    print(f"remote-focused-artifact-snapshot: artifact-digest={artifact_digest}")
    print("remote-focused-artifact-snapshot: artifact-content-mirror=verified-by-public-evidence-branch")
    print(f"remote-focused-artifact-snapshot: artifact-mirror-archive-sha256={mirror['archive_sha256']}")
    print(f"remote-focused-artifact-snapshot: artifact-mirror-file-count={mirror['file_count']}")
    print("remote-focused-artifact-snapshot: artifact-zip-contract=api-zip-endpoint-unverified-by-public-html")
    print(
        "remote-focused-artifact-snapshot: "
        "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; external review; endorsement; stars; reposts; "
        "live autonomy; broad unknown-repository repair; external benchmark standing"
    )
    print("remote-focused-artifact-snapshot: PASS")


if os.environ.get("OPENMAKO_FORCE_PUBLIC_HTML_FALLBACK"):
    verify_public_html_fallback("forced_public_html_fallback")
    sys.exit(0)


def read_json_url(url: str, unavailable_reason: str) -> dict:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and "rate limit" in body.lower():
            print(
                "remote-focused-artifact-snapshot: GitHub API rate limit; re-check later "
                "or set OPENMAKO_GITHUB_TOKEN/GITHUB_TOKEN/GH_TOKEN; "
                "trying public HTML fallback",
                file=sys.stderr,
            )
            verify_public_html_fallback("github_api_rate_limit", exc.headers)
            sys.exit(0)
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


def read_artifact_zip(url: str) -> tuple[bytes | None, str]:
    if artifact_zip_http_status_fixture:
        if artifact_zip_http_status_fixture == "401":
            return None, "artifact_zip_requires_auth"
        if artifact_zip_http_status_fixture == "403-rate-limit":
            return None, "github_api_rate_limit"
        print_boundary_snapshot("artifact_zip_status_fixture_unsupported")
        print(
            "remote-focused-artifact-snapshot: unsupported OPENMAKO_FOCUSED_ARTIFACT_ZIP_HTTP_STATUS="
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
                f"remote-focused-artifact-snapshot: could not read artifact zip fixture "
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
            print(
                "remote-focused-artifact-snapshot: GitHub API rate limit while reading artifact zip; "
                "verifying public evidence mirror instead",
                file=sys.stderr,
            )
            return None, "github_api_rate_limit"
        if exc.code == 401:
            print(
                "remote-focused-artifact-snapshot: artifact zip download requires authenticated API access; "
                "verifying public evidence mirror instead",
                file=sys.stderr,
            )
            return None, "artifact_zip_requires_auth"
        print_boundary_snapshot(f"artifact_zip_api_error_{exc.code}")
        print(f"remote-focused-artifact-snapshot: artifact zip error {exc.code}: {body}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print_boundary_snapshot("artifact_zip_unreadable")
        print(f"remote-focused-artifact-snapshot: could not read artifact zip: {exc}", file=sys.stderr)
        sys.exit(2)


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
if not is_sha256_digest(artifact_digest):
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

artifact_id = str(artifact.get("id") or "")
if not artifact_id.isdigit():
    fail(f"artifact '{artifact_name}' id is missing")

zip_data, zip_unavailable_reason = read_artifact_zip(artifact_url)
if zip_data is None:
    mirror = verify_public_evidence_mirror(
        run_id=str(run_id),
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )
    print(f"remote-focused-artifact-snapshot: artifact-name={artifact_name}")
    print(f"remote-focused-artifact-snapshot: artifact-id={artifact_id}")
    print(f"remote-focused-artifact-snapshot: artifact-digest={artifact_digest}")
    print(f"remote-focused-artifact-snapshot: verified-by=github-api-metadata+public-evidence-branch")
    print(f"remote-focused-artifact-snapshot: artifact-zip-unavailable={zip_unavailable_reason}")
    print("remote-focused-artifact-snapshot: artifact-content-mirror=verified-by-public-evidence-branch")
    print(f"remote-focused-artifact-snapshot: artifact-mirror-archive-sha256={mirror['archive_sha256']}")
    print(f"remote-focused-artifact-snapshot: artifact-mirror-file-count={mirror['file_count']}")
    print("remote-focused-artifact-snapshot: artifact-zip-contract=api-zip-endpoint-unverified-by-github-api")
    print(
        "remote-focused-artifact-snapshot: "
        "not-proof=GitHub Actions API artifact zip endpoint byte-for-byte archive; external review; endorsement; stars; reposts; "
        "live autonomy; broad unknown-repository repair; external benchmark standing"
    )
    print("remote-focused-artifact-snapshot: PASS")
    sys.exit(0)
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
