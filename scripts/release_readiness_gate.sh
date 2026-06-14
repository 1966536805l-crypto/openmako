#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "release-readiness-gate: START"

python3 - <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path.cwd()
pyproject = root / "pyproject.toml"
license_candidates = (
    root / "LICENSE",
    root / "LICENSE.md",
    root / "LICENSE.txt",
    root / "COPYING",
    root / "COPYING.md",
    root / "COPYING.txt",
)


def project_table_text(text: str) -> str:
    match = re.search(r"(?ms)^\[project\]\s*(?P<body>.*?)(?=^\[|\Z)", text)
    if not match:
        return ""
    return match.group("body")


errors: list[str] = []

root_license = next((path for path in license_candidates if path.is_file()), None)
if root_license is None:
    errors.append("root-license=[NEEDS OWNER DECISION: LICENSE]")
else:
    print(f"release-readiness-gate: root-license={root_license.name}")

if not pyproject.is_file():
    errors.append("pyproject.toml=missing")
else:
    text = pyproject.read_text(encoding="utf-8")
    project_body = project_table_text(text)
    has_license_metadata = bool(
        re.search(r"(?m)^\s*license\s*=", project_body)
        or re.search(r"(?m)^\s*license-files\s*=", project_body)
    )
    if has_license_metadata:
        print("release-readiness-gate: pyproject-license=present")
    else:
        errors.append("pyproject-license=[NEEDS OWNER DECISION: LICENSE]")

print("release-readiness-gate: not-proof=legal advice; owner license decision; external review; endorsement; release announcement")

if errors:
    for error in errors:
        print(f"release-readiness-gate: {error}", file=sys.stderr)
    print("release-readiness-gate: FAIL", file=sys.stderr)
    sys.exit(1)

print("release-readiness-gate: PASS")
PY
