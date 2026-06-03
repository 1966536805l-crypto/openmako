from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_eval_scenarios import (
    DesktopEvalScenario,
    builtin_desktop_eval_suites,
    load_desktop_eval_suite,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "desktop_eval"
REQUIRED_KEYS = {"id", "goal", "expected_status", "max_steps", "tags", "risk_level"}
REQUIRED_COVERAGE = {"screenshot", "stop", "search", "type", "stale-target", "timeout", "high-risk", "multi-app"}
REQUIRED_LIVE_COVERAGE = {
    "live",
    "readiness",
    "network",
    "offline",
    "guardian",
    "loop",
    "dry-run",
    "task-pool",
    "click",
    "input",
    "hotkey",
    "window-switch",
    "file",
    "browser",
    "privacy",
    "permission",
    "timeout",
    "ocr",
    "ax",
    "fluctuation",
    "real-desktop",
}


class DesktopEvalScenariosTest(unittest.TestCase):
    def test_builtin_suites_export_l4_and_l5_scenarios(self) -> None:
        suites = builtin_desktop_eval_suites()

        self.assertEqual(set(suites), {"suite_l4", "suite_l5", "suite_live"})
        self.assertTrue(all(isinstance(item, DesktopEvalScenario) for item in suites["suite_l4"]))
        self.assertTrue(all(isinstance(item, DesktopEvalScenario) for item in suites["suite_l5"]))
        self.assertTrue(all(isinstance(item, DesktopEvalScenario) for item in suites["suite_live"]))
        self.assertGreaterEqual(len(suites["suite_l4"]), 4)
        self.assertGreaterEqual(len(suites["suite_l5"]), 4)
        self.assertGreaterEqual(len(suites["suite_live"]), 30)

    def test_payload_contract_has_runner_fields_and_required_coverage(self) -> None:
        l4_scenarios = load_desktop_eval_suite("suite_l4")
        scenarios = l4_scenarios + load_desktop_eval_suite("suite_l5")
        live_scenarios = load_desktop_eval_suite("suite_live")
        ids = [scenario.id for scenario in scenarios + live_scenarios]
        l4_tags = {tag for scenario in l4_scenarios for tag in scenario.tags}
        live_tags = {tag for scenario in live_scenarios for tag in scenario.tags}

        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(REQUIRED_COVERAGE.issubset(l4_tags))
        self.assertTrue(REQUIRED_LIVE_COVERAGE.issubset(live_tags))
        for scenario in scenarios + live_scenarios:
            payload = scenario.to_payload()
            self.assertTrue(REQUIRED_KEYS.issubset(payload), payload)
            self.assertIsInstance(payload["tags"], list)
            self.assertIsInstance(payload["max_steps"], int)
            self.assertGreaterEqual(payload["max_steps"], 1)
            self.assertIn(payload["risk_level"], {"low", "medium", "high", "critical"})

    def test_load_suite_from_fixture_path_matches_builtin_payloads(self) -> None:
        for name in ("suite_l4", "suite_l5", "suite_live"):
            with self.subTest(name=name):
                fixture_scenarios = load_desktop_eval_suite(FIXTURE_DIR / f"{name}.json")
                builtin_scenarios = load_desktop_eval_suite(name)

                self.assertEqual(
                    [scenario.to_payload() for scenario in fixture_scenarios],
                    [scenario.to_payload() for scenario in builtin_scenarios],
                )

    def test_loader_accepts_cases_alias_for_external_runner_fixtures(self) -> None:
        payload = {
            "suite": "custom",
            "cases": [
                {
                    "id": "custom-1",
                    "goal": "observe desktop",
                    "expected_status": "completed",
                    "max_steps": 1,
                    "tags": ["custom"],
                    "risk_level": "low",
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="desktop eval scenarios ") as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            scenarios = load_desktop_eval_suite(path)

        self.assertEqual(len(scenarios), 1)
        self.assertEqual(scenarios[0].suite, "custom")
        self.assertEqual(scenarios[0].to_payload()["id"], "custom-1")

    def test_invalid_scenarios_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            DesktopEvalScenario.from_payload(
                {
                    "id": "bad",
                    "goal": "observe desktop",
                    "expected_status": "completed",
                    "max_steps": 0,
                    "tags": [],
                    "risk_level": "low",
                }
            )
        with self.assertRaises(ValueError):
            DesktopEvalScenario.from_payload(
                {
                    "id": "bad-risk",
                    "goal": "observe desktop",
                    "expected_status": "completed",
                    "max_steps": 1,
                    "tags": [],
                    "risk_level": "unknown",
                }
            )
        with self.assertRaises(ValueError):
            load_desktop_eval_suite("not_a_suite")


if __name__ == "__main__":
    unittest.main()
