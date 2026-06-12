#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMMENT_URL="${OPENMAKO_PUBLIC_EVIDENCE_COMMENT_URL:-https://github.com/1966536805l-crypto/openmako/issues/1#issuecomment-4694860161}"
EXPECTED_COMMENT_ID="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMENT_ID:-4694860161}"
EXPECTED_COMMIT="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_COMMIT:-bc9dadd66d72dc5b392dab3f010fb5e336ca94c6}"
EXPECTED_RUN_ID="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_RUN_ID:-27439391469}"
EXPECTED_JOB_ID="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_JOB_ID:-81109429440}"
EXPECTED_ARTIFACT_NAME="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_NAME:-autonomous-learning-gate-summary}"
EXPECTED_ARTIFACT_ID="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_ID:-7601286143}"
EXPECTED_ARTIFACT_DIGEST="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_ARTIFACT_DIGEST:-sha256:950d41573c4d1b72c90b07318fd1dda231eb99c1971225ab3d587736245dc2ae}"
EXPECTED_BOUNDARY="${OPENMAKO_PUBLIC_EVIDENCE_EXPECTED_BOUNDARY:-not external review}"

python3 - \
  "$COMMENT_URL" \
  "$EXPECTED_COMMENT_ID" \
  "$EXPECTED_COMMIT" \
  "$EXPECTED_RUN_ID" \
  "$EXPECTED_JOB_ID" \
  "$EXPECTED_ARTIFACT_NAME" \
  "$EXPECTED_ARTIFACT_ID" \
  "$EXPECTED_ARTIFACT_DIGEST" \
  "$EXPECTED_BOUNDARY" <<'PY'
import html
import os
import sys
import urllib.error
import urllib.request


(
    comment_url,
    expected_comment_id,
    expected_commit,
    expected_run_id,
    expected_job_id,
    expected_artifact_name,
    expected_artifact_id,
    expected_artifact_digest,
    expected_boundary,
) = sys.argv[1:10]

fixture = os.environ.get("OPENMAKO_PUBLIC_EVIDENCE_HTML")
markers = {
    "comment-id": expected_comment_id,
    "commit": expected_commit,
    "run-id": expected_run_id,
    "job-id": expected_job_id,
    "artifact-name": expected_artifact_name,
    "artifact-id": expected_artifact_id,
    "artifact-digest": expected_artifact_digest,
    "boundary": expected_boundary,
}


def read_page() -> str:
    if fixture:
        try:
            with open(fixture, encoding="utf-8") as handle:
                return handle.read()
        except Exception as exc:
            print(
                f"public-evidence-comment-check: could not read fixture {fixture}: {exc}",
                file=sys.stderr,
            )
            sys.exit(2)

    request = urllib.request.Request(
        comment_url,
        headers={"User-Agent": "openmako-public-evidence-comment-check"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            f"public-evidence-comment-check: HTTP {exc.code} while reading {comment_url}: {body[:500]}",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:
        print(
            f"public-evidence-comment-check: could not read {comment_url}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


raw_page = read_page()
page = html.unescape(raw_page)

print(f"public-evidence-comment-check: url={comment_url}")
if fixture:
    print(f"public-evidence-comment-check: html-fixture={fixture}")

missing = []
for name, value in markers.items():
    if value and value in page:
        print(f"public-evidence-comment-check: marker={name} ok")
    else:
        missing.append(name)

print(
    "public-evidence-comment-check: "
    "not-proof=external review; endorsement; stars; reposts; live autonomy; "
    "broad unknown-repository repair; external benchmark standing"
)

if missing:
    print(
        "public-evidence-comment-check: missing public evidence markers="
        + ",".join(missing),
        file=sys.stderr,
    )
    sys.exit(1)

print("public-evidence-comment-check: PASS")
PY
