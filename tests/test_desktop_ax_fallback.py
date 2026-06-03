from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quantagent.desktop_intelligence as desktop_intelligence
from quantagent.desktop_control import DesktopResult
from quantagent.desktop_eval import BLOCKED, STOPPED, SUCCESS, run_desktop_eval
from quantagent.desktop_intelligence import (
    DesktopToken,
    DesktopTokenization,
    build_desktop_tokenization,
    run_desktop_daemon,
)
from quantagent.desktop_soak import run_desktop_soak


class DesktopAxFallbackTest(unittest.TestCase):
    def write_image(self, project: Path, name: str = "shot.png") -> Path:
        image = project / name
        image.write_bytes(b"fake png bytes")
        return image

    def cached_tokenization(self, image: Path) -> DesktopTokenization:
        token = DesktopToken(
            "AX0001",
            "Search",
            "AXButton",
            "ax",
            bbox=(10, 20, 110, 50),
            center=(60, 35),
            clickable=True,
            confidence=0.9,
            raw={"recovered_from": "cached_ax"},
        )
        return DesktopTokenization(
            True,
            "ok",
            "cached AX tokenization",
            str(image),
            800,
            600,
            (token,),
            sources={"ax": {"status": "ok", "source": "cache"}},
            path="",
            observation_id="obs-cached",
            screen_hash="cached-screen",
            created_at="2026-05-26T12:00:00",
            front_app="Safari",
        )

    def assert_fallback_evidence(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        self.assertIn("ax", encoded)
        self.assertIn("timeout", encoded)
        self.assertTrue("fallback" in encoded or "recovery" in encoded or "cached" in encoded, encoded)

    def test_ax_timeout_tokenization_falls_back_to_screenshot_only_grid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop ax fallback grid ") as tmp:
            project = Path(tmp)
            image = self.write_image(project)
            timeout = subprocess.TimeoutExpired(cmd=["osascript", "-e", "AX"], timeout=25)

            with patch.object(desktop_intelligence, "_image_size", return_value=(800, 600)), patch.object(
                desktop_intelligence, "ax_snapshot", side_effect=timeout
            ), patch.object(desktop_intelligence, "ocr_image", return_value=DesktopResult("ocr", False, "ocr disabled", {})):
                result = build_desktop_tokenization(
                    project,
                    image_path=image,
                    include_ax=True,
                    include_ocr=False,
                    include_som=False,
                    include_grid=True,
                    name="ax_timeout_grid",
                )

            payload = result.to_payload()

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.tokens)
        self.assertTrue(any(token.source == "grid" for token in result.tokens))
        self.assertFalse(any(token.source == "ax" for token in result.tokens))
        self.assert_fallback_evidence(payload)

    def test_ax_timeout_tokenization_recovers_cached_ax_when_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop ax fallback cache ") as tmp:
            project = Path(tmp)
            image = self.write_image(project)
            directory = project / ".quantagent" / "desktop" / "intelligence"
            directory.mkdir(parents=True)
            latest = directory / "latest_tokenize.json"
            latest.write_text(self.cached_tokenization(image).to_json() + "\n", encoding="utf-8")
            timeout = subprocess.TimeoutExpired(cmd=["osascript", "-e", "AX"], timeout=25)

            with patch.object(desktop_intelligence, "_image_size", return_value=(800, 600)), patch.object(
                desktop_intelligence, "ax_snapshot", side_effect=timeout
            ), patch.object(desktop_intelligence, "ocr_image", return_value=DesktopResult("ocr", False, "ocr disabled", {})):
                result = build_desktop_tokenization(
                    project,
                    image_path=image,
                    include_ax=True,
                    include_ocr=False,
                    include_som=False,
                    include_grid=False,
                    name="ax_timeout_cached",
                )

            payload = result.to_payload()

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "ok")
        self.assertTrue(any(token.source == "ax" for token in result.tokens))
        self.assertTrue(any(token.raw.get("recovered_from") == "cached_ax" for token in result.tokens))
        self.assert_fallback_evidence(payload)

    def test_daemon_ax_timeout_fallback_still_allows_high_risk_block(self) -> None:
        cached = self.cached_tokenization(Path("shot.png"))
        timeout = subprocess.TimeoutExpired(cmd=["osascript", "-e", "AX"], timeout=25)

        def timeout_then_cached(_project: Path, **_kwargs: object) -> DesktopTokenization:
            raise timeout

        with tempfile.TemporaryDirectory(prefix="desktop ax fallback daemon ") as tmp:
            project = Path(tmp)
            directory = project / ".quantagent" / "desktop" / "intelligence"
            directory.mkdir(parents=True)
            (directory / "latest_tokenize.json").write_text(cached.to_json() + "\n", encoding="utf-8")

            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=timeout_then_cached):
                result = run_desktop_daemon(project, "delete all files", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

            state = json.loads(Path(result.state_path).read_text(encoding="utf-8"))
            query_events = Path(result.query_events_path).read_text(encoding="utf-8").lower()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("high-risk", result.summary)
        self.assertIn("tokenize", [record.phase for record in result.records])
        self.assert_fallback_evidence(state)
        self.assertIn("timeout", query_events)

    def test_eval_counts_expected_blocked_and_stopped_as_successful_scenarios(self) -> None:
        scenarios = [
            {
                "id": "high-risk-block-after-ax-timeout",
                "name": "high risk remains blocked after AX timeout fallback",
                "goal": "delete all files",
                "expected_status": BLOCKED,
            },
            {
                "id": "operator-stop-after-ax-timeout",
                "name": "operator stop remains stopped after AX timeout fallback",
                "goal": "wait until stopped",
                "expected_status": STOPPED,
            },
        ]

        def runner(scenario, context):
            self.assertTrue(context["execute"])
            return {
                "status": scenario["expected_status"],
                "summary": f"expected {scenario['expected_status']} after AX timeout fallback",
                "steps": 1,
                "data": {
                    "failure_evidence": {"phase": "tokenize", "error": "osascript AX timeout"},
                    "recovery_evidence": {"fallback": "cached_ax"},
                },
            }

        with tempfile.TemporaryDirectory(prefix="desktop ax fallback eval ") as tmp:
            result = run_desktop_eval(
                tmp,
                scenario=scenarios,
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=runner,
            )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, SUCCESS)
        self.assertEqual([scenario.ok for scenario in result.scenarios], [True, True])
        self.assertEqual([scenario.status for scenario in result.scenarios], [BLOCKED, STOPPED])
        self.assertEqual(result.metrics[BLOCKED], 1)
        self.assertEqual(result.metrics[STOPPED], 1)
        self.assertEqual(result.metrics["crashes"], 0)
        self.assert_fallback_evidence(result.to_payload())

    def test_soak_continues_when_eval_reports_expected_blocked_or_stopped_with_ax_evidence(self) -> None:
        clock = [0.0]

        def now() -> float:
            return clock[0]

        def run_eval(_project, **_kwargs):
            clock[0] += 1.0
            return {
                "ok": True,
                "status": SUCCESS,
                "summary": "eval accepted expected blocked/stopped after AX timeout fallback",
                "run_id": "eval-ax-fallback",
                "json_path": "/tmp/eval-ax-fallback.json",
                "report_path": "/tmp/eval-ax-fallback.md",
                "metrics": {
                    "total": 2,
                    "success": 2,
                    "blocked": 1,
                    "stopped": 1,
                    "failure": 0,
                    "timeout": 0,
                    "steps": 2,
                    "crashes": 0,
                    "misoperations": 0,
                    "recovery_attempts": 1,
                    "recovery_successes": 1,
                    "autopsies": 1,
                    "ax_fallbacks": 1,
                },
            }

        with tempfile.TemporaryDirectory(prefix="desktop ax fallback soak ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                run_eval=run_eval,
                now=now,
            )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, SUCCESS)
        self.assertEqual(result.metrics["runs"], 1)
        self.assertEqual(result.metrics[BLOCKED], 1)
        self.assertEqual(result.metrics[STOPPED], 1)
        self.assertEqual(result.metrics["crashes"], 0)
        self.assert_fallback_evidence(result.to_payload())


if __name__ == "__main__":
    unittest.main()
