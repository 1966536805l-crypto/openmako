#!/usr/bin/env bash
set -euo pipefail

if [ -n "${OPENMAKO_REPRO_LOG:-}" ] && [ -z "${OPENMAKO_REPRO_LOG_ACTIVE:-}" ]; then
  mkdir -p "$(dirname "$OPENMAKO_REPRO_LOG")"
  set +e
  OPENMAKO_REPRO_LOG_ACTIVE=1 bash "$0" "$@" 2>&1 | tee "$OPENMAKO_REPRO_LOG"
  status=${PIPESTATUS[0]}
  if [ -f "$OPENMAKO_REPRO_LOG" ]; then
    log_sha="$(shasum -a 256 "$OPENMAKO_REPRO_LOG" | awk '{print $1}')"
    line_count="$(wc -l < "$OPENMAKO_REPRO_LOG" | tr -d ' ')"
    echo "fresh-clone-reproduction: log=$OPENMAKO_REPRO_LOG"
    echo "fresh-clone-reproduction: log-sha256=$log_sha"
    echo "fresh-clone-reproduction: log-lines=$line_count"
  fi
  exit "$status"
fi

CLONE_URL="${OPENMAKO_REPRO_CLONE_URL:-https://github.com/1966536805l-crypto/openmako.git}"
REF="${OPENMAKO_REPRO_REF:-}"
PYTHON_BIN="${OPENMAKO_REPRO_PYTHON:-python3}"
WORKDIR="${OPENMAKO_REPRO_WORKDIR:-}"
REPRO_REMOTE="${OPENMAKO_REPRO_REMOTE:-origin}"
PUBLIC_EVIDENCE_REMOTE="${OPENMAKO_REPRO_PUBLIC_EVIDENCE_REMOTE:-$CLONE_URL}"

if [ -z "$WORKDIR" ]; then
  WORKDIR="$(mktemp -d /tmp/openmako-fresh-clone.XXXXXX)"
else
  mkdir -p "$WORKDIR"
fi

if [ -z "$REF" ]; then
  REF="$(git ls-remote "$CLONE_URL" refs/heads/main | awk '{print $1}')"
fi

if [ -z "$REF" ]; then
  echo "fresh-clone-reproduction: could not resolve refs/heads/main for $CLONE_URL" >&2
  exit 2
fi

REPO_DIR="$WORKDIR/repo"
VENV_DIR="$WORKDIR/venv"

echo "fresh-clone-reproduction: clone-url=$CLONE_URL"
echo "fresh-clone-reproduction: workdir=$WORKDIR"
echo "fresh-clone-reproduction: requested-ref=$REF"

git clone "$CLONE_URL" "$REPO_DIR"
cd "$REPO_DIR"
git checkout "$REF"
actual_sha="$(git rev-parse HEAD)"
echo "fresh-clone-reproduction: checkout-sha=$actual_sha"

if [ "$actual_sha" != "$REF" ]; then
  echo "fresh-clone-reproduction: checkout SHA does not match requested ref" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e . pytest
echo "fresh-clone-reproduction: install=PASS"

bash scripts/release_readiness_gate.sh
echo "fresh-clone-reproduction: release-readiness=PASS"

bash scripts/public_review_gate.sh
echo "fresh-clone-reproduction: public-review=PASS"

OPENMAKO_REMOTE="$REPRO_REMOTE" \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE="$PUBLIC_EVIDENCE_REMOTE" \
  bash scripts/remote_public_evidence_snapshot.sh
echo "fresh-clone-reproduction: remote-public-evidence=PASS"

OPENMAKO_REMOTE="$REPRO_REMOTE" \
OPENMAKO_PUBLIC_EVIDENCE_REMOTE="$PUBLIC_EVIDENCE_REMOTE" \
  bash scripts/remote_autonomous_public_evidence_snapshot.sh
echo "fresh-clone-reproduction: remote-autonomous-public-evidence=PASS"

echo "fresh-clone-reproduction: PASS"
echo "fresh-clone-reproduction: not-proof=external review; endorsement; stars; reposts; independent external benchmark standing; GitHub Actions artifact zip contents; live autonomy; broad unknown-repository repair"
