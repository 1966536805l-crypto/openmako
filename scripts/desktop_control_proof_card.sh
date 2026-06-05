#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

commit="$(git rev-parse --short HEAD 2>/dev/null || printf 'unknown')"

echo "openmako-desktop-control-proof-card: START"
echo "repo: https://github.com/1966536805l-crypto/openmako"
echo "commit: ${commit}"
echo "proof-command: bash scripts/desktop_control_local_gate.sh"
echo

bash scripts/desktop_control_local_gate.sh

echo
echo "openmako-desktop-control-proof-card: PASS"
echo "scope: local desktop intelligence tests; daemon policy guards; suite_l4 dry-run plan"
echo "recent-fast-path-evidence: AX-only target preflight; focused type/hotkey fences; OCR fallback after failed AX type verify"
echo "not-proof: live desktop control; L4; L5; external endorsement; star or repost traction"
echo "public-claim-boundary: optional implementation evidence outside the v0.1 launch claim"
