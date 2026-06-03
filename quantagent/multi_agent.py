from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .context_pack import build_context_pack


REVIEW_TEMPLATE = """# Mako Review Request

- created_at: {created_at}
- primary_model: {primary_model}
- review_model: {review_model}
- task: {task}

## Review Instructions

Act as an adversarial quant auditor. Look for:

- future leakage
- duplicate or polluted samples
- unrealistic execution assumptions
- PF improvements caused by filtering good trades
- 2025-only degradation hidden by full-period metrics
- missing verification commands

Return findings first, then a pass/fail recommendation.

## Context

{context}
"""


def create_review_request(project: Path, task: str, primary_model: str, review_model: str) -> Path:
    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"QUANTAGENT_REVIEW_REQUEST_{stamp}.md"
    context = build_context_pack(project).text
    out_path.write_text(
        REVIEW_TEMPLATE.format(
            created_at=datetime.now().isoformat(timespec="seconds"),
            primary_model=primary_model,
            review_model=review_model,
            task=task,
            context=context,
        ),
        encoding="utf-8",
    )
    return out_path

