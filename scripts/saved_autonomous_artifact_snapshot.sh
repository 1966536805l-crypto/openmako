#!/usr/bin/env bash
set -euo pipefail

CALLER_DIR="$(pwd)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: bash scripts/saved_autonomous_artifact_snapshot.sh RUNS_JSON ARTIFACTS_JSON ARTIFACT_ZIP [REMOTE_MAIN_SHA]

Verify a saved autonomous-learning workflow evidence bundle without depending on
a fresh GitHub API or artifact download. RUNS_JSON and ARTIFACTS_JSON should be
captured from the matching GitHub Actions run metadata, and ARTIFACT_ZIP should
be the downloaded autonomous-learning-gate-summary artifact for that run.

This is saved public CI artifact evidence only, not external review,
endorsement, stars, reposts, live autonomy, broad unknown-repository repair, or
external benchmark standing.
EOF
}

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  usage >&2
  exit 64
fi

absolute_path() {
  python3 - "$CALLER_DIR" "$1" <<'PY'
from pathlib import Path
import sys

base = Path(sys.argv[1])
path = Path(sys.argv[2]).expanduser()
if not path.is_absolute():
    path = base / path
print(path.resolve())
PY
}

runs_json="$(absolute_path "$1")"
artifacts_json="$(absolute_path "$2")"
artifact_zip="$(absolute_path "$3")"

for input_path in "$runs_json" "$artifacts_json" "$artifact_zip"; do
  if [ ! -f "$input_path" ]; then
    echo "saved-autonomous-artifact-snapshot: missing input file: $input_path" >&2
    exit 66
  fi
done

if [ "$#" -eq 4 ]; then
  remote_sha="$4"
else
  REMOTE="${OPENMAKO_REMOTE:-openmako}"
  remote_sha="$(git ls-remote "$REMOTE" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$remote_sha" ]; then
  echo "saved-autonomous-artifact-snapshot: could not resolve remote main SHA" >&2
  exit 2
fi

echo "saved-autonomous-artifact-snapshot: runs-json=$runs_json"
echo "saved-autonomous-artifact-snapshot: artifacts-json=$artifacts_json"
echo "saved-autonomous-artifact-snapshot: artifact-zip=$artifact_zip"
echo "saved-autonomous-artifact-snapshot: remote-main-sha=$remote_sha"
echo \
  "saved-autonomous-artifact-snapshot: not-proof=external review; endorsement; stars; reposts; live autonomy; broad unknown-repository repair; external benchmark standing"

OPENMAKO_REMOTE_MAIN_SHA="$remote_sha" \
OPENMAKO_AUTONOMOUS_RUNS_JSON="$runs_json" \
OPENMAKO_AUTONOMOUS_ARTIFACTS_JSON="$artifacts_json" \
OPENMAKO_AUTONOMOUS_ARTIFACT_ZIP="$artifact_zip" \
  bash scripts/remote_autonomous_learning_snapshot.sh
