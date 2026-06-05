from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.cli import main
from quantagent.desktop_control import DesktopResult
import quantagent.desktop_intelligence as desktop_intelligence
from quantagent.desktop_intelligence import (
    DesktopDecision,
    DesktopToken,
    DesktopTokenization,
    build_desktop_tokenization,
    decide_desktop_action,
    desktop_decision_marker,
    run_desktop_daemon,
    tokens_from_ax,
    tokens_from_ocr,
)
from quantagent.desktop_workflow import DesktopElement, DesktopTextBlock, DesktopStep
from quantagent.tool_execution import execute_tool


class DesktopIntelligenceTest(unittest.TestCase):
    def tokenization(self, tokens: tuple[DesktopToken, ...] | None = None, *, observation_id: str = "obs-test", screen_hash: str = "hash-test") -> DesktopTokenization:
        if tokens is None:
            token = DesktopToken("AX0001", "Search", "AXButton", "ax", bbox=(10, 20, 110, 50), center=(60, 35), clickable=True, confidence=0.9)
            tokens = (token,)
        return DesktopTokenization(
            True,
            "ok",
            f"{len(tokens)} token(s)",
            "shot.png",
            800,
            600,
            tokens,
            path="tokens.json",
            observation_id=observation_id,
            screen_hash=screen_hash,
        )

    def click_decision(self) -> DesktopDecision:
        tokenized = self.tokenization()
        token = tokenized.tokens[0]
        target_hash = desktop_intelligence._token_hash(token)
        return DesktopDecision(
            True,
            "action",
            "click",
            {"x": 60, "y": 35, "target_id": "AX0001", "target_hash": target_hash, "observation_id": tokenized.observation_id},
            "AX0001",
            "click test",
            True,
            (),
            0.9,
            DesktopStep("click", {"x": 60, "y": 35, "target_id": "AX0001", "target_hash": target_hash, "observation_id": tokenized.observation_id}, "click test"),
        )

    def focused_text_tokenization(self) -> DesktopTokenization:
        field = DesktopToken("AX0002", "Search field", "AXTextField", "ax", bbox=(10, 80, 210, 110), center=(110, 95), clickable=True, confidence=0.9, raw={"role": "AXTextField", "focused": "true", "value": ""})
        return self.tokenization((field,), observation_id="obs-field", screen_hash="screen-field")

    def test_tokens_from_ax_and_ocr_normalize_bounds_and_clickability(self) -> None:
        ax = [DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 100, 30))]
        ocr = [DesktopTextBlock("OCR0001", "Result", bounds=(200, 100, 260, 130), confidence=0.8)]

        ax_tokens = tokens_from_ax(ax)
        ocr_tokens = tokens_from_ocr(ocr)

        self.assertEqual(ax_tokens[0].bbox, (10, 20, 110, 50))
        self.assertEqual(ax_tokens[0].center, (60, 35))
        self.assertTrue(ax_tokens[0].clickable)
        self.assertEqual(ocr_tokens[0].center, (230, 115))

    def test_build_tokenization_merges_ax_ocr_and_writes_latest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop intelligence ") as tmp:
            project = Path(tmp)
            image = project / "shot.png"
            image.write_bytes(b"fake")
            desktop_dir = project / ".quantagent" / "desktop"
            desktop_dir.mkdir(parents=True)
            ax_path = desktop_dir / "ax_test.json"
            ocr_path = desktop_dir / "ocr_test.json"
            ax_element = DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 100, 30))
            ax_path.write_text(json.dumps({"app": "Safari", "elements": [ax_element.to_payload()]}), encoding="utf-8")
            ocr_block = DesktopTextBlock("OCR0001", "OpenMako", bounds=(120, 40, 220, 70), confidence=0.7)
            ocr_path.write_text(json.dumps({"blocks": [ocr_block.to_payload()]}), encoding="utf-8")

            with patch.object(desktop_intelligence, "_image_size", return_value=(800, 600)), patch.object(
                desktop_intelligence,
                "ax_snapshot",
                return_value=DesktopResult("ax", True, "ax ok", {"path": str(ax_path)}),
            ), patch.object(
                desktop_intelligence,
                "ocr_image",
                return_value=DesktopResult("ocr", True, "ocr ok", {"path": str(ocr_path)}),
            ):
                result = build_desktop_tokenization(project, image_path=image, include_grid=True, name="tokenize_test")

            latest = project / ".quantagent" / "desktop" / "intelligence" / "latest_tokenize.json"
            self.assertTrue(result.ok)
            self.assertTrue(latest.exists())
            self.assertTrue(result.observation_id.startswith("obs-"))
            self.assertTrue(result.screen_hash)
            self.assertGreaterEqual(len(result.tokens), 2)
            self.assertTrue(any(token.source == "som" for token in result.tokens))

    def test_build_ax_only_tokenization_can_skip_screenshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop ax only fast ") as tmp:
            project = Path(tmp)
            desktop_dir = project / ".quantagent" / "desktop"
            desktop_dir.mkdir(parents=True)
            ax_path = desktop_dir / "ax_fast.json"
            ax_element = DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 100, 30))
            ax_path.write_text(json.dumps({"app": "Safari", "elements": [ax_element.to_payload()]}), encoding="utf-8")

            with patch.object(desktop_intelligence, "screenshot") as screenshot, patch.object(
                desktop_intelligence,
                "_image_size",
            ) as image_size, patch.object(
                desktop_intelligence,
                "ax_snapshot",
                return_value=DesktopResult("ax", True, "ax ok", {"path": str(ax_path)}),
            ):
                result = build_desktop_tokenization(
                    project,
                    include_ax=True,
                    include_ocr=False,
                    include_som=False,
                    include_grid=False,
                    skip_screenshot_if_ax_only=True,
                    name="ax_only_fast",
                )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.image_path, "")
        self.assertEqual((result.width, result.height), (0, 0))
        self.assertEqual(result.screen_hash, "")
        self.assertTrue(result.observation_id.startswith("obs-"))
        self.assertTrue(any(token.source == "ax" for token in result.tokens))
        self.assertTrue(result.sources["screenshot"]["skipped"])
        self.assertEqual(result.sources["screenshot"]["reason"], "ax_only_tokenization")
        screenshot.assert_not_called()
        image_size.assert_not_called()

    def test_decider_clicks_best_matching_token(self) -> None:
        decision = decide_desktop_action("点击 Search", self.tokenization())

        self.assertTrue(decision.ok)
        self.assertEqual(decision.status, "action")
        self.assertEqual(decision.action, "click")
        self.assertEqual(decision.args["x"], 60)
        self.assertEqual(decision.target_id, "AX0001")
        self.assertEqual(decision.args["observation_id"], "obs-test")
        self.assertTrue(decision.args["target_hash"])

    def test_decider_blocks_high_risk_goal(self) -> None:
        decision = decide_desktop_action("一整晚帮我买入股票", self.tokenization())

        self.assertFalse(decision.ok)
        self.assertEqual(decision.status, "blocked")
        self.assertIn("high-risk", decision.reason)

    def test_decider_search_state_machine_is_single_step(self) -> None:
        first = decide_desktop_action("搜索 OpenMako", self.tokenization(), browser="Safari")
        second = decide_desktop_action("搜索 OpenMako", self.tokenization(), last_action=desktop_decision_marker(first))
        third = decide_desktop_action("搜索 OpenMako", self.focused_text_tokenization(), last_action=desktop_decision_marker(second))
        fourth = decide_desktop_action("搜索 OpenMako", self.tokenization(), last_action=desktop_decision_marker(third))

        self.assertEqual(first.action, "activate")
        self.assertEqual(second.args["keys"], ["cmd", "l"])
        self.assertEqual(third.action, "type")
        self.assertIn("OpenMako", third.args["text"])
        self.assertEqual(third.target_id, "AX0002")
        self.assertEqual(third.args["observation_id"], "obs-field")
        self.assertTrue(third.args["target_hash"])
        self.assertEqual(fourth.args["keys"], ["return"])

    def test_decider_types_into_focused_text_target_with_observation_fence(self) -> None:
        decision = decide_desktop_action("输入 OpenMako", self.focused_text_tokenization())

        self.assertTrue(decision.ok)
        self.assertEqual(decision.action, "type")
        self.assertEqual(decision.target_id, "AX0002")
        self.assertEqual(decision.args["target_id"], "AX0002")
        self.assertEqual(decision.args["observation_id"], "obs-field")
        self.assertTrue(decision.args["target_hash"])

    def test_decider_binds_focused_text_hotkey_with_observation_fence(self) -> None:
        decision = decide_desktop_action("按 enter", self.focused_text_tokenization())

        self.assertTrue(decision.ok)
        self.assertEqual(decision.action, "hotkey")
        self.assertEqual(decision.target_id, "AX0002")
        self.assertEqual(decision.args["target_id"], "AX0002")
        self.assertEqual(decision.args["observation_id"], "obs-field")
        self.assertTrue(decision.args["target_hash"])

    def test_decider_keeps_modifier_hotkey_global(self) -> None:
        decision = decide_desktop_action("按 cmd+l", self.focused_text_tokenization())

        self.assertTrue(decision.ok)
        self.assertEqual(decision.action, "hotkey")
        self.assertEqual(decision.target_id, "")
        self.assertNotIn("target_id", decision.args)

    def test_decider_does_not_bind_type_to_selected_text_target(self) -> None:
        selected = DesktopToken("AX0003", "Search field", "AXTextField", "ax", bbox=(10, 80, 210, 110), center=(110, 95), clickable=True, confidence=0.9, raw={"role": "AXTextField", "selected": "true", "value": ""})
        decision = decide_desktop_action("输入 OpenMako", self.tokenization((selected,)))

        self.assertTrue(decision.ok)
        self.assertEqual(decision.action, "type")
        self.assertEqual(decision.target_id, "")
        self.assertNotIn("target_id", decision.args)

    def test_daemon_skips_side_effects_without_required_flags(self) -> None:
        click = self.click_decision()
        with tempfile.TemporaryDirectory(prefix="desktop daemon ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=False, max_steps=1, delay=0)
                state_exists = Path(result.state_path).exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "skipped")
        self.assertIn("--execute", result.summary)
        self.assertTrue(state_exists)

    def test_daemon_executes_one_action_then_holds_after_verification(self) -> None:
        calls: list[str] = []
        click = self.click_decision()
        hold = DesktopDecision(True, "hold", "", {}, "", "done", False, (), 0.0, None)
        pre = self.tokenization()
        post = self.tokenization(())

        def fake_execute(project: Path, step: DesktopStep) -> DesktopResult:
            calls.append(step.action)
            return DesktopResult(step.action, True, f"{step.action} ok", {"action": step.action})

        with tempfile.TemporaryDirectory(prefix="desktop daemon ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, post, post]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[click, hold],
            ), patch.object(desktop_intelligence, "_execute_step", side_effect=fake_execute):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["click"])
        self.assertTrue(any(record.phase == "verify" for record in result.records))

    def test_daemon_blocks_stale_target_before_execute(self) -> None:
        click = self.click_decision()
        moved = DesktopToken("AX0001", "Search", "AXButton", "ax", bbox=(30, 20, 130, 50), center=(80, 35), clickable=True, confidence=0.9)
        with tempfile.TemporaryDirectory(prefix="desktop daemon stale ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[self.tokenization(), self.tokenization((moved,))]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("target changed", result.summary)
        execute.assert_not_called()

    def test_daemon_preflight_uses_ax_only_refresh_for_ax_target(self) -> None:
        click = self.click_decision()
        after_click = self.tokenization((), observation_id="obs-after-click", screen_hash="screen-after-click")
        with tempfile.TemporaryDirectory(prefix="desktop daemon fast preflight ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[self.tokenization(), self.tokenization(), after_click]) as tokenize, patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertGreaterEqual(tokenize.call_count, 3)
        preflight_kwargs = tokenize.call_args_list[1].kwargs
        self.assertEqual(preflight_kwargs["include_ax"], True)
        self.assertEqual(preflight_kwargs["include_ocr"], False)
        self.assertEqual(preflight_kwargs["include_som"], False)
        self.assertEqual(preflight_kwargs["include_grid"], False)
        self.assertEqual(preflight_kwargs["skip_screenshot_if_ax_only"], True)
        verify_kwargs = tokenize.call_args_list[2].kwargs
        self.assertEqual(verify_kwargs["include_ax"], True)
        self.assertEqual(verify_kwargs["include_ocr"], False)
        self.assertEqual(verify_kwargs["include_som"], False)
        self.assertEqual(verify_kwargs["include_grid"], False)
        self.assertEqual(verify_kwargs["skip_screenshot_if_ax_only"], True)

    def test_daemon_ax_click_uses_fast_ax_preflight_and_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon ax preflight capture ") as tmp:
            project = Path(tmp)
            image = project / "shot.png"
            image.write_bytes(b"fake")
            desktop_dir = project / ".quantagent" / "desktop"
            desktop_dir.mkdir(parents=True)
            ax_path = desktop_dir / "ax_preflight.json"
            ax_changed_path = desktop_dir / "ax_verified.json"
            source_element = DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 100, 30))
            changed_element = DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search result", bounds=(10, 20, 100, 30))
            ax_path.write_text(json.dumps({"app": "Safari", "elements": [source_element.to_payload()]}), encoding="utf-8")
            ax_changed_path.write_text(json.dumps({"app": "Safari", "elements": [changed_element.to_payload()]}), encoding="utf-8")

            def fake_screenshot(_project: Path, **_kwargs: object) -> DesktopResult:
                return DesktopResult("screenshot", True, "shot ok", {"path": str(image)})

            with patch.object(desktop_intelligence, "screenshot", side_effect=fake_screenshot) as screenshot, patch.object(
                desktop_intelligence,
                "_image_size",
                return_value=(800, 600),
            ), patch.object(
                desktop_intelligence,
                "ax_snapshot",
                side_effect=[
                    DesktopResult("ax", True, "ax initial", {"path": str(ax_path)}),
                    DesktopResult("ax", True, "ax preflight", {"path": str(ax_path)}),
                    DesktopResult("ax", True, "ax verified", {"path": str(ax_changed_path)}),
                ],
            ), patch.object(
                desktop_intelligence,
                "ocr_image",
                return_value=DesktopResult("ocr", False, "ocr disabled", {}),
            ), patch.object(
                desktop_intelligence,
                "build_som_targets",
                return_value=[],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")):
                result = run_desktop_daemon(project, "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(screenshot.call_count, 1)
        self.assertIn("semantic verify passed", [record.summary for record in result.records if record.phase == "verify"][0])

    def test_daemon_ax_preflight_blocks_cached_ax_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon ax cached preflight ") as tmp:
            project = Path(tmp)
            image = project / "shot.png"
            image.write_bytes(b"fake")
            desktop_dir = project / ".quantagent" / "desktop"
            desktop_dir.mkdir(parents=True)
            ax_path = desktop_dir / "ax_initial.json"
            source_element = DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(10, 20, 100, 30))
            ax_path.write_text(json.dumps({"app": "Safari", "elements": [source_element.to_payload()]}), encoding="utf-8")

            def fake_screenshot(_project: Path, **_kwargs: object) -> DesktopResult:
                return DesktopResult("screenshot", True, "shot ok", {"path": str(image)})

            with patch.object(desktop_intelligence, "screenshot", side_effect=fake_screenshot) as screenshot, patch.object(
                desktop_intelligence,
                "_image_size",
                return_value=(800, 600),
            ), patch.object(
                desktop_intelligence,
                "ax_snapshot",
                side_effect=[
                    DesktopResult("ax", True, "ax initial", {"path": str(ax_path)}),
                    RuntimeError("AX timeout"),
                ],
            ), patch.object(
                desktop_intelligence,
                "ocr_image",
                return_value=DesktopResult("ocr", False, "ocr disabled", {}),
            ), patch.object(
                desktop_intelligence,
                "build_som_targets",
                return_value=[],
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(project, "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok, result.to_json())
        self.assertEqual(result.status, "blocked")
        self.assertIn("cached AX fallback", result.summary)
        self.assertEqual(screenshot.call_count, 1)
        execute.assert_not_called()

    def test_daemon_ax_verification_blocks_cached_ax_fallback(self) -> None:
        source = self.tokenization()
        cached = DesktopToken(
            "AX0001",
            "Search",
            "AXButton",
            "ax",
            bbox=(10, 20, 110, 50),
            center=(60, 35),
            clickable=False,
            confidence=0.25,
            raw={"recovered_from": "cached_ax"},
        )
        verified = self.tokenization((cached,), observation_id="obs-cached-verify", screen_hash="")
        click = self.click_decision()
        with tempfile.TemporaryDirectory(prefix="desktop daemon ax cached verify ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[source, source, verified]) as tokenize, patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok, result.to_json())
        self.assertEqual(result.status, "verify_failed")
        self.assertIn("cached AX fallback", result.summary)
        self.assertEqual(execute.call_count, 1)
        verify_kwargs = tokenize.call_args_list[2].kwargs
        self.assertEqual(verify_kwargs["skip_screenshot_if_ax_only"], True)

    def test_daemon_rejects_target_action_without_observation_metadata(self) -> None:
        stale_click = DesktopDecision(True, "action", "click", {"x": 60, "y": 35, "target_id": "AX0001"}, "AX0001", "old decision", True, (), 0.9, DesktopStep("click", {"x": 60, "y": 35, "target_id": "AX0001"}, "old decision"))
        with tempfile.TemporaryDirectory(prefix="desktop daemon missing fence ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=stale_click,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("missing observation fence", result.summary)
        execute.assert_not_called()

    def test_daemon_semantic_verify_type_text_passes_and_fails(self) -> None:
        field = DesktopToken("AX0002", "Search field", "AXTextField", "ax", bbox=(10, 80, 210, 110), center=(110, 95), clickable=True, confidence=0.9, raw={"focused": "true", "value": ""})
        pre = self.tokenization((field,), observation_id="obs-field", screen_hash="screen-field")
        type_args = {"text": "OpenMako", "target_id": field.token_id, "target_hash": desktop_intelligence._token_hash(field), "observation_id": pre.observation_id}
        type_step = DesktopStep("type", type_args, "type text")
        type_decision = DesktopDecision(True, "action", "type", type_args, field.token_id, "type text", True, (), 0.8, type_step)
        hold = DesktopDecision(True, "hold", "", {}, "", "done", False, (), 0.0, None)
        visible = self.tokenization((DesktopToken("OCR0001", "OpenMako", "text", "ocr", bbox=(1, 1, 100, 30), center=(50, 15), clickable=True, confidence=0.8),))

        with tempfile.TemporaryDirectory(prefix="desktop daemon type pass ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, pre, visible, visible]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, hold],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("type", True, "typed")):
                passed = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        with tempfile.TemporaryDirectory(prefix="desktop daemon type fail ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, pre, pre]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=type_decision,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("type", True, "typed")):
                failed = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(passed.ok)
        self.assertEqual(passed.status, "completed")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.status, "verify_failed")
        self.assertIn("typed text not visible", failed.summary)

    def test_daemon_type_decision_uses_focused_target_fast_preflight(self) -> None:
        pre = self.focused_text_tokenization()
        ax_visible = self.tokenization(
            (
                DesktopToken(
                    "AX0002",
                    "Search field OpenMako",
                    "AXTextField",
                    "ax",
                    bbox=(10, 80, 210, 110),
                    center=(110, 95),
                    clickable=True,
                    confidence=0.9,
                    raw={"role": "AXTextField", "focused": "true", "value": "OpenMako"},
                ),
            ),
            observation_id="obs-ax-visible",
            screen_hash="",
        )
        with tempfile.TemporaryDirectory(prefix="desktop daemon focused type ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, ax_visible]) as tokenize, patch.object(
                desktop_intelligence,
                "_execute_step",
                return_value=DesktopResult("type", True, "typed"),
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(execute.call_count, 1)
        preflight_kwargs = tokenize.call_args_list[1].kwargs
        self.assertEqual(preflight_kwargs["include_ax"], True)
        self.assertEqual(preflight_kwargs["include_ocr"], False)
        self.assertEqual(preflight_kwargs["include_som"], False)
        self.assertEqual(preflight_kwargs["skip_screenshot_if_ax_only"], True)
        verify_kwargs = tokenize.call_args_list[2].kwargs
        self.assertEqual(verify_kwargs["include_ax"], True)
        self.assertEqual(verify_kwargs["include_ocr"], False)
        self.assertEqual(verify_kwargs["include_som"], False)
        self.assertEqual(verify_kwargs["skip_screenshot_if_ax_only"], True)
        verify_records = [record for record in result.records if record.phase == "verify"]
        self.assertTrue(verify_records)
        self.assertIn("typed text visible in AX", verify_records[0].summary)
        self.assertFalse(verify_records[0].data["fast_type_verify"]["fallback_required"])

    def test_daemon_type_verify_falls_back_to_ocr_when_ax_value_is_not_updated(self) -> None:
        pre = self.focused_text_tokenization()
        ax_unchanged = self.focused_text_tokenization()
        visible = self.tokenization((DesktopToken("OCR0001", "OpenMako", "text", "ocr", bbox=(1, 1, 100, 30), center=(50, 15), clickable=True, confidence=0.8),))
        with tempfile.TemporaryDirectory(prefix="desktop daemon focused type fallback ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, ax_unchanged, visible]) as tokenize, patch.object(
                desktop_intelligence,
                "_execute_step",
                return_value=DesktopResult("type", True, "typed"),
            ):
                result = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(tokenize.call_count, 4)
        fast_kwargs = tokenize.call_args_list[2].kwargs
        self.assertEqual(fast_kwargs["include_ax"], True)
        self.assertEqual(fast_kwargs["include_ocr"], False)
        self.assertEqual(fast_kwargs["skip_screenshot_if_ax_only"], True)
        fallback_kwargs = tokenize.call_args_list[3].kwargs
        self.assertEqual(fallback_kwargs["include_ax"], False)
        self.assertEqual(fallback_kwargs["include_ocr"], True)
        self.assertEqual(fallback_kwargs["include_som"], False)
        verify_records = [record for record in result.records if record.phase == "verify"]
        self.assertTrue(verify_records)
        self.assertTrue(verify_records[0].data["fast_type_verify"]["fallback_required"])
        self.assertEqual(verify_records[0].data["fast_type_verify"]["fallback_reason"], "typed_text_not_visible_in_target_ax")

    def test_daemon_type_fast_verify_is_bound_to_original_target(self) -> None:
        pre = self.focused_text_tokenization()
        target_unchanged = DesktopToken(
            "AX0002",
            "Search field",
            "AXTextField",
            "ax",
            bbox=(10, 80, 210, 110),
            center=(110, 95),
            clickable=True,
            confidence=0.9,
            raw={"role": "AXTextField", "focused": "true", "value": ""},
        )
        unrelated_visible = DesktopToken(
            "AX0099",
            "OpenMako result",
            "AXStaticText",
            "ax",
            bbox=(240, 80, 340, 110),
            center=(290, 95),
            clickable=False,
            confidence=0.7,
            raw={"role": "AXStaticText", "value": "OpenMako"},
        )
        ax_unrelated_match = self.tokenization((target_unchanged, unrelated_visible), observation_id="obs-ax-unrelated", screen_hash="")
        visible = self.tokenization((DesktopToken("OCR0001", "OpenMako", "text", "ocr", bbox=(1, 1, 100, 30), center=(50, 15), clickable=True, confidence=0.8),))
        with tempfile.TemporaryDirectory(prefix="desktop daemon target scoped type ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, ax_unrelated_match, visible]) as tokenize, patch.object(
                desktop_intelligence,
                "_execute_step",
                return_value=DesktopResult("type", True, "typed"),
            ):
                result = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(tokenize.call_count, 4)
        fallback_kwargs = tokenize.call_args_list[3].kwargs
        self.assertEqual(fallback_kwargs["include_ax"], False)
        self.assertEqual(fallback_kwargs["include_ocr"], True)
        verify_records = [record for record in result.records if record.phase == "verify"]
        self.assertTrue(verify_records)
        self.assertTrue(verify_records[0].data["fast_type_verify"]["fallback_required"])
        self.assertEqual(verify_records[0].data["fast_type_verify"]["fallback_reason"], "typed_text_not_visible_in_target_ax")

    def test_daemon_does_not_execute_type_for_selected_only_target(self) -> None:
        selected = DesktopToken("AX0003", "Search field", "AXTextField", "ax", bbox=(10, 80, 210, 110), center=(110, 95), clickable=True, confidence=0.9, raw={"role": "AXTextField", "selected": "true", "value": ""})
        with tempfile.TemporaryDirectory(prefix="desktop daemon selected type ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization((selected,))), patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "输入 OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("missing observation fence", result.summary)
        execute.assert_not_called()

    def test_hotkey_verify_fails_on_stagnant_desktop_state(self) -> None:
        tokenized = self.tokenization()
        token = tokenized.tokens[0]
        args = {"keys": ["tab"], "target_id": token.token_id, "target_hash": desktop_intelligence._token_hash(token), "observation_id": tokenized.observation_id}
        hotkey = DesktopDecision(True, "action", "hotkey", args, token.token_id, "press tab", True, (), 0.8, DesktopStep("hotkey", args, "press tab"))
        with tempfile.TemporaryDirectory(prefix="desktop daemon loop ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[tokenized, tokenized, tokenized, tokenized]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=hotkey,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("hotkey", True, "hotkey ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "按 tab", execute=True, reviewed=True, allow_actions=True, max_steps=3, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "verify_failed")
        self.assertIn("no visible progress after hotkey", result.summary)
        self.assertEqual(execute.call_count, 1)

    def test_targeted_hotkey_uses_fast_ax_preflight_and_verification(self) -> None:
        pre = self.focused_text_tokenization()
        changed = self.tokenization(
            (
                DesktopToken(
                    "AX0002",
                    "Search field submitted",
                    "AXTextField",
                    "ax",
                    bbox=(10, 80, 210, 110),
                    center=(110, 95),
                    clickable=True,
                    confidence=0.9,
                    raw={"role": "AXTextField", "focused": "true", "value": "submitted"},
                ),
            ),
            observation_id="obs-hotkey-visible",
            screen_hash="",
        )
        with tempfile.TemporaryDirectory(prefix="desktop daemon focused hotkey ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, changed]) as tokenize, patch.object(
                desktop_intelligence,
                "_execute_step",
                return_value=DesktopResult("hotkey", True, "hotkey ok"),
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "按 enter", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(execute.call_count, 1)
        preflight_kwargs = tokenize.call_args_list[1].kwargs
        self.assertEqual(preflight_kwargs["include_ax"], True)
        self.assertEqual(preflight_kwargs["include_ocr"], False)
        self.assertEqual(preflight_kwargs["include_som"], False)
        self.assertEqual(preflight_kwargs["skip_screenshot_if_ax_only"], True)
        verify_kwargs = tokenize.call_args_list[2].kwargs
        self.assertEqual(verify_kwargs["include_ax"], True)
        self.assertEqual(verify_kwargs["include_ocr"], False)
        self.assertEqual(verify_kwargs["include_som"], False)
        self.assertEqual(verify_kwargs["skip_screenshot_if_ax_only"], True)
        verify_records = [record for record in result.records if record.phase == "verify"]
        self.assertTrue(verify_records)
        self.assertIn("focused hotkey changed AX state", verify_records[0].summary)
        self.assertFalse(verify_records[0].data["fast_hotkey_verify"]["fallback_required"])

    def test_cli_desktop_decide_reads_latest_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop decide cli ") as tmp:
            project = Path(tmp)
            directory = project / ".quantagent" / "desktop" / "intelligence"
            directory.mkdir(parents=True)
            latest = directory / "latest_tokenize.json"
            latest.write_text(self.tokenization().to_json() + "\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "--json", "decide", "点击 Search"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["action"], "click")
        self.assertEqual(payload["target_id"], "AX0001")

    def test_legacy_tokenization_decide_still_loads_without_observation_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop legacy decide ") as tmp:
            project = Path(tmp)
            directory = project / ".quantagent" / "desktop" / "intelligence"
            directory.mkdir(parents=True)
            latest = directory / "latest_tokenize.json"
            latest.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "ok",
                        "summary": "legacy",
                        "image_path": "shot.png",
                        "width": 800,
                        "height": 600,
                        "tokens": [self.tokenization().tokens[0].to_payload()],
                        "errors": [],
                        "sources": {},
                        "path": str(latest),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "--json", "decide", "点击 Search"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["action"], "click")
        self.assertEqual(payload["args"]["observation_id"], "")

    def test_agent_tool_executor_can_decide_from_tokens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop decide tool ") as tmp:
            project = Path(tmp)
            tokens = project / "tokens.json"
            tokens.write_text(self.tokenization().to_json() + "\n", encoding="utf-8")
            result = execute_tool(project, "desktop.decide", {"goal": "点击 Search", "tokens": str(tokens)})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["action"], "click")


if __name__ == "__main__":
    unittest.main()
