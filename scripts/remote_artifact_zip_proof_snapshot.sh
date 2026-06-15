#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_REMOTE="${OPENMAKO_REMOTE:-openmako}"
EVIDENCE_REMOTE="${OPENMAKO_PUBLIC_EVIDENCE_REMOTE:-https://github.com/1966536805l-crypto/openmako.git}"
BRANCH="${OPENMAKO_PUBLIC_EVIDENCE_BRANCH:-public-evidence}"

if [ -n "${OPENMAKO_REMOTE_MAIN_SHA:-}" ]; then
  remote_sha="$OPENMAKO_REMOTE_MAIN_SHA"
else
  remote_sha="$(git ls-remote "$SOURCE_REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "remote-artifact-zip-proof-snapshot: could not resolve ${SOURCE_REMOTE}/main" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if ! git clone --depth 1 --branch "$BRANCH" "$EVIDENCE_REMOTE" "$tmp_dir/evidence" >/dev/null 2>&1; then
  echo "remote-artifact-zip-proof-snapshot: repo=$EVIDENCE_REMOTE"
  echo "remote-artifact-zip-proof-snapshot: branch=$BRANCH"
  echo "remote-artifact-zip-proof-snapshot: remote-main-sha=$remote_sha"
  echo "remote-artifact-zip-proof-snapshot: unavailable=public_evidence_branch_missing"
  echo "remote-artifact-zip-proof-snapshot: not-proof=unauthenticated GitHub Actions API artifact zip download; external review; endorsement; stars; reposts; native live autonomy; broad unknown-repository repair; external benchmark standing; independent external held-out benchmark"
  exit 2
fi

python3 - "$tmp_dir/evidence" "$remote_sha" "$EVIDENCE_REMOTE" "$BRANCH" <<'PY'
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve(strict=False)
remote_sha = sys.argv[2]
repo = sys.argv[3]
branch = sys.argv[4]
record_dir = root / "artifact_zip_proofs" / remote_sha
manifest_path = record_dir / "manifest.json"
latest_path = root / "artifact_zip_proofs" / "latest.json"


def fail(reason: str, detail: str = "") -> None:
    print(f"remote-artifact-zip-proof-snapshot: repo={repo}")
    print(f"remote-artifact-zip-proof-snapshot: branch={branch}")
    print(f"remote-artifact-zip-proof-snapshot: remote-main-sha={remote_sha}")
    print(f"remote-artifact-zip-proof-snapshot: unavailable={reason}")
    if detail:
        print(f"remote-artifact-zip-proof-snapshot: detail={detail}")
    print(
        "remote-artifact-zip-proof-snapshot: "
        "not-proof=unauthenticated GitHub Actions API artifact zip download; "
        "external review; endorsement; stars; reposts; native live autonomy; "
        "broad unknown-repository repair; external benchmark standing; "
        "independent external held-out benchmark"
    )
    raise SystemExit(1)


def is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", value))


def verify_artifact(kind: str, contract: object) -> dict[str, object]:
    if not isinstance(contract, dict):
        fail("artifact_zip_proof_artifact_contract_malformed", kind)
    for key in (
        "run_id",
        "artifact_id",
        "artifact_digest",
        "zip_path",
        "zip_sha256",
        "zip_size_bytes",
        "summary_path",
    ):
        if key not in contract:
            fail("artifact_zip_proof_artifact_contract_missing_key", f"{kind}:{key}")
    if not str(contract["run_id"]).isdigit():
        fail("artifact_zip_proof_run_id_malformed", kind)
    if not str(contract["artifact_id"]).isdigit():
        fail("artifact_zip_proof_artifact_id_malformed", kind)
    if not is_sha256_digest(contract["artifact_digest"]):
        fail("artifact_zip_proof_artifact_digest_malformed", kind)
    if contract["artifact_digest"] != contract["zip_sha256"]:
        fail("artifact_zip_proof_artifact_digest_zip_mismatch", kind)
    zip_relative = str(contract["zip_path"])
    zip_parts = PurePosixPath(zip_relative).parts
    if zip_relative.startswith("/") or ".." in zip_parts:
        fail("artifact_zip_proof_zip_path_unsafe", kind)
    zip_path = record_dir / zip_relative
    if not zip_path.is_file():
        fail("artifact_zip_proof_zip_missing", kind)
    payload = zip_path.read_bytes()
    zip_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
    if contract["zip_sha256"] != zip_sha256:
        fail("artifact_zip_proof_zip_digest_mismatch", kind)
    if contract["zip_size_bytes"] != len(payload):
        fail("artifact_zip_proof_zip_size_mismatch", kind)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            for name in files:
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts:
                    fail("artifact_zip_proof_zip_member_unsafe", f"{kind}:{name}")
            summary_path = str(contract["summary_path"])
            if summary_path not in files:
                fail("artifact_zip_proof_summary_missing", kind)
            summary = json.loads(archive.read(summary_path).decode("utf-8"))
    except zipfile.BadZipFile as exc:
        fail("artifact_zip_proof_zip_unreadable", f"{kind}:{exc}")
    except json.JSONDecodeError as exc:
        fail("artifact_zip_proof_summary_invalid_json", f"{kind}:{exc}")
    expected_schema = {
        "focused": "public-review-gate-artifact/v0.1",
        "autonomous": "autonomous-learning-gate/v0.1",
    }[kind]
    if summary.get("schema_version") != expected_schema:
        fail("artifact_zip_proof_summary_schema_mismatch", kind)
    if summary.get("status") != "passed":
        fail("artifact_zip_proof_summary_not_passed", kind)
    invocation = summary.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("git_commit") != remote_sha:
        fail("artifact_zip_proof_summary_commit_mismatch", kind)
    return {
        "artifact_id": contract["artifact_id"],
        "run_id": contract["run_id"],
        "zip_sha256": zip_sha256,
        "summary_path": summary_path,
    }


if not manifest_path.is_file():
    fail("artifact_zip_proof_manifest_missing", str(manifest_path.relative_to(root)))
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception as exc:
    fail("artifact_zip_proof_manifest_invalid_json", str(exc))
if manifest.get("schema_version") != "openmako-artifact-zip-proof/v0.1":
    fail("artifact_zip_proof_manifest_schema_mismatch")
if manifest.get("status") != "passed":
    fail("artifact_zip_proof_manifest_not_passed")
if manifest.get("git_commit") != remote_sha:
    fail("artifact_zip_proof_manifest_commit_mismatch")
artifacts = manifest.get("artifacts")
if not isinstance(artifacts, dict) or set(artifacts) != {"focused", "autonomous"}:
    fail("artifact_zip_proof_manifest_artifacts_malformed")
required_not_proof = {
    "unauthenticated GitHub Actions API artifact zip download",
    "external review",
    "endorsement",
    "stars",
    "reposts",
    "native live autonomy",
    "broad unknown-repository repair",
    "external benchmark standing",
    "independent external held-out benchmark",
}
if not required_not_proof.issubset(set(manifest.get("not_proof") or [])):
    fail("artifact_zip_proof_not_proof_boundary_mismatch")
focused = verify_artifact("focused", artifacts["focused"])
autonomous = verify_artifact("autonomous", artifacts["autonomous"])
latest = {}
if latest_path.is_file():
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if latest.get("latest_artifact_zip_proof_commit") != remote_sha:
        fail("artifact_zip_proof_latest_index_commit_mismatch")

print(f"remote-artifact-zip-proof-snapshot: repo={repo}")
print(f"remote-artifact-zip-proof-snapshot: branch={branch}")
print(f"remote-artifact-zip-proof-snapshot: remote-main-sha={remote_sha}")
print(f"remote-artifact-zip-proof-snapshot: manifest=artifact_zip_proofs/{remote_sha}/manifest.json")
print(f"remote-artifact-zip-proof-snapshot: status={manifest['status']}")
print(f"remote-artifact-zip-proof-snapshot: focused-run-id={focused['run_id']}")
print(f"remote-artifact-zip-proof-snapshot: focused-artifact-id={focused['artifact_id']}")
print(f"remote-artifact-zip-proof-snapshot: focused-zip-sha256={focused['zip_sha256']}")
print(f"remote-artifact-zip-proof-snapshot: autonomous-run-id={autonomous['run_id']}")
print(f"remote-artifact-zip-proof-snapshot: autonomous-artifact-id={autonomous['artifact_id']}")
print(f"remote-artifact-zip-proof-snapshot: autonomous-zip-sha256={autonomous['zip_sha256']}")
print(f"remote-artifact-zip-proof-snapshot: latest-index={'present' if latest else 'missing'}")
print(
    "remote-artifact-zip-proof-snapshot: "
    "artifact-zip-proof=verified-by-public-evidence-branch"
)
print(
    "remote-artifact-zip-proof-snapshot: "
    "not-proof=unauthenticated GitHub Actions API artifact zip download; "
    "external review; endorsement; stars; reposts; native live autonomy; "
    "broad unknown-repository repair; external benchmark standing; "
    "independent external held-out benchmark"
)
print("remote-artifact-zip-proof-snapshot: PASS")
PY
