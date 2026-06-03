from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_learning import (
    extract_autopsy_signal,
    intercepts_path,
    learn_intercepts_from_autopsy,
    load_intercept_rules,
    match_intercept_rule,
)


class DesktopLearningTest(unittest.TestCase):
    def test_learns_rule_from_daemon_markdown_and_persists_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop learning ") as tmp:
            project = Path(tmp)
            autopsy = project / "openmako-autopsy.md"
            autopsy.write_text(
                "\n".join(
                    [
                        "# Desktop Daemon Autopsy: paused",
                        "",
                        "- source_agent: desktop_daemon",
                        "- command: click Search",
                        "- status: FAILED",
                        "- failure_class: verify_failed",
                        "- failed_at: verify:semantic step 2",
                        "",
                        "## Sources",
                        "",
                        "- tokens.json",
                        "- state.json",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            rules = learn_intercepts_from_autopsy(project, autopsy, action={"action": "click", "target": "Search"})
            saved = json.loads(intercepts_path(project).read_text(encoding="utf-8"))
            reloaded = load_intercept_rules(project)

        self.assertEqual(saved["version"], 1)
        self.assertEqual(len(rules), 1)
        self.assertEqual(reloaded, rules)
        self.assertEqual(rules[0].failure_class, "verify_failed")
        self.assertEqual(rules[0].failed_at, "verify:semantic step 2")
        self.assertEqual(rules[0].sources, ("tokens.json", "state.json"))
        self.assertIn("failure_class=verify_failed", rules[0].intercept)

    def test_learns_jsonl_once_and_matches_similar_goal_or_action(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop learning jsonl ") as tmp:
            project = Path(tmp)
            autopsy = project / "daemon.jsonl"
            events = [
                {
                    "kind": "query_start",
                    "summary": "query started: click Search",
                    "data": {"task": "click Search", "mode": "desktop_daemon"},
                },
                {
                    "kind": "action",
                    "content": "desktop-daemon step 1 act: click Search",
                    "step": 1,
                    "ok": True,
                    "meta": {"phase": "act", "action": "click Search"},
                },
                {
                    "kind": "test",
                    "content": "semantic verification failed",
                    "step": 2,
                    "ok": False,
                    "meta": {
                        "phase": "verify",
                        "failed_at": "verify step 2",
                        "failure_class": "verify_failed",
                        "sources": ["tokens.json"],
                    },
                },
            ]
            autopsy.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")

            first = learn_intercepts_from_autopsy(project, autopsy)
            second = learn_intercepts_from_autopsy(project, autopsy)
            hit = match_intercept_rule(project, goal="click Search again", action={"action": "click", "target": "Search"})
            miss = match_intercept_rule(project, goal="open Settings", action={"action": "click", "target": "Settings"})

        self.assertEqual(first, second)
        self.assertEqual(len(second), 1)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score if hit else 0.0, 0.5)
        self.assertIn("action", hit.matched_on if hit else ())
        self.assertIsNone(miss)

    def test_extracts_agent_autopsy_json_payload_without_string_hacks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop learning json ") as tmp:
            autopsy = Path(tmp) / "autopsy.json"
            autopsy.write_text(
                json.dumps(
                    {
                        "failure_class": "verify_failed",
                        "failed_at": "verify step 4",
                        "sources": ["ignored top-level source"],
                        "evidence": [
                            {
                                "kind": "stop_failure",
                                "summary": "daemon failed",
                                "ok": False,
                                "data": {
                                    "failure_class": "verify_failed",
                                    "failed_at": "verify step 4",
                                    "sources": ["tokens.json"],
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            signal = extract_autopsy_signal(autopsy)

        self.assertEqual(signal["failure_class"], "verify_failed")
        self.assertEqual(signal["failed_at"], "verify step 4")
        self.assertEqual(signal["sources"], ["ignored top-level source", "tokens.json"])


if __name__ == "__main__":
    unittest.main()
