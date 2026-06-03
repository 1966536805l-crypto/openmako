from __future__ import annotations

from datetime import datetime
from pathlib import Path


def journal_path(project: Path) -> Path:
    comm = project / "AI_协作交接"
    return (comm if comm.exists() else project) / "QUANTAGENT_JOURNAL.md"


def append_journal(project: Path, title: str, body: str) -> Path:
    path = journal_path(project)
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = f"\n## {timestamp} - {title}\n\n{body.strip()}\n"
    if path.exists():
        previous = path.read_text(encoding="utf-8", errors="replace")
    else:
        previous = "# Mako Journal\n"
    path.write_text(previous.rstrip() + "\n" + entry, encoding="utf-8")
    return path

