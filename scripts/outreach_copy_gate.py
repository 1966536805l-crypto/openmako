#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

PROMO_PATTERNS = (
    r"\bplease\s+star\b",
    r"\bstar\s+if\s+it\s+looks\s+good\b",
    r"\bbetter\s+than\s+(hermes|openclaw|cline|aider|openhands)\b",
    r"\bsolved\s+autonomous\s+coding\b",
    r"\b10,?000\s+stars?\b",
    r"\bgame[- ]changing\b",
    r"\brevolutionary\b",
    r"\bworld[- ]class\b",
    r"\bstate[- ]of[- ]the[- ]art\b",
)

REQUIRED_SIGNALS = {
    "boundary-reader": (
        "not asking for stars",
        "not stars or endorsement",
        "not a promotion",
        "not giving endorsement",
        "do not use it to ask for stars",
    ),
    "evidence-reader": ("evidence", "proof", "artifact", "ci", "command"),
    "reviewer-reader": ("question", "check whether", "boundary criticism", "review question"),
}

DEFAULT_PATHS = (
    "docs/PUBLIC_REVIEW_ENTRYPOINTS.md",
    "docs/REVIEWER_OUTREACH_QUEUE.md",
    "docs/OPEN_SOURCE_TRACTION_GAP.md",
)


def strip_fenced_blocks(text: str) -> str:
    return FENCE_RE.sub("", text)


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text_lower = text.lower()
    plain_lower = strip_fenced_blocks(text).lower()
    failures: list[str] = []

    for pattern in PROMO_PATTERNS:
        if re.search(pattern, plain_lower):
            failures.append(f"skeptic-reader: promotional or overclaim phrase matched `{pattern}`")

    for reader, signals in REQUIRED_SIGNALS.items():
        if not any(signal in text_lower for signal in signals):
            failures.append(f"{reader}: missing one of {', '.join(signals)}")

    if path.name == "REVIEWER_OUTREACH_QUEUE.md":
        if "do not contact reviewers until all of these are true:" not in text_lower:
            failures.append("send-operator: missing send gate")
        if "stop outreach for this slice if:" not in text_lower:
            failures.append("send-operator: missing stop conditions")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate OpenMako outreach copy before public posting.")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Markdown files to check. Defaults to the public review/outreach docs.",
    )
    args = parser.parse_args(argv)

    paths = args.paths or list(DEFAULT_PATHS)
    all_failures: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            all_failures.append(f"{path}: missing file")
            continue
        for failure in check_file(path):
            all_failures.append(f"{path}: {failure}")

    if all_failures:
        print("outreach-copy-gate: FAIL")
        for failure in all_failures:
            print(f"- {failure}")
        return 1

    readers = "skeptic-reader,boundary-reader,evidence-reader,reviewer-reader,send-operator"
    print(f"outreach-copy-gate: PASS readers={readers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
