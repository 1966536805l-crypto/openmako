from __future__ import annotations

from pathlib import Path

import yaml


def test_technical_boundary_issue_template_is_review_not_promotion() -> None:
    root = Path(__file__).resolve().parents[1]
    template = root / ".github" / "ISSUE_TEMPLATE" / "technical-boundary-review.yml"
    text = template.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    assert data["name"] == "Technical boundary review"
    assert data["description"] == "Check whether an OpenMako claim matches the repo evidence."
    assert "technical-boundary" in data["labels"]
    assert "review-wanted" in data["labels"]

    body_by_id = {item.get("id"): item for item in data["body"] if "id" in item}
    for required_id in ("claim_area", "claim_text", "evidence_checked", "verdict", "issue_detail"):
        assert body_by_id[required_id]["validations"]["required"] is True

    verdict_options = body_by_id["verdict"]["attributes"]["options"]
    assert "Claim matches evidence" in verdict_options
    assert "Claim is too broad" in verdict_options
    assert "Evidence is missing or indirect" in verdict_options
    assert "Cannot reproduce" in verdict_options

    checkbox = body_by_id["non_endorsement"]["attributes"]["options"][0]
    assert checkbox["required"] is True
    assert checkbox["label"] == (
        "I am reporting technical boundary feedback, not giving endorsement, "
        "promotion, or star-bait."
    )

    lowered = text.lower()
    assert "boundary criticism, not endorsement" in lowered
    assert "specific claim, command, artifact, or file" in lowered
    assert "please star" not in lowered
    assert "repost" not in lowered
    assert "promote openmako" not in lowered
