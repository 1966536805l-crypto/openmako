#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

commit="$(git rev-parse --short HEAD 2>/dev/null || printf 'unknown')"

echo "openmako-public-proof-card: START"
echo "repo: https://github.com/1966536805l-crypto/openmako"
echo "commit: ${commit}"
echo "proof-command: ./scripts/public_review_gate.sh"
echo

./scripts/public_review_gate.sh

echo
echo "openmako-public-proof-card: PASS"
echo "scope: focused learning-effect gate; public metadata boundary; supplied Evidence Court audit; artifact provenance; SWTBench patch artifact; supplied transcript adapter matrix"
echo "not-proof: broad unknown-repository SWE repair; external endorsement; star or repost traction"
echo "review-request: https://github.com/1966536805l-crypto/openmako/issues/2"
echo "record-external-review: https://github.com/1966536805l-crypto/openmako/issues/new?template=external-review-record.yml"
