from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.desktop_workflow import (
    DesktopElement,
    DesktopPlan,
    DesktopStep,
    DesktopTextBlock,
    SomTarget,
    build_grid_payload_for_image,
    build_som_targets,
    execute_desktop_plan,
    load_desktop_plan,
    open_target,
    parse_ax_snapshot,
    parse_ocr_payload,
    plan_web_search,
    plan_open_target,
    render_desktop_plan,
    search_ax_elements,
    search_grid_payload,
    search_ocr_blocks,
    search_som_targets,
    search_url,
)
from quantagent.tool_execution import execute_tool


class DesktopWorkflowTest(unittest.TestCase):
    def test_parse_ax_snapshot_and_search_text_targets(self) -> None:
        text = "\n".join(
            [
                "Safari",
                "depth\trole\ttitle\tvalue\tdescription\thelp\tenabled\tfocused\tx\ty\tw\th",
                "0\tAXApplication\tSafari\t\t\t\ttrue\tfalse\t0\t0\t1200\t800",
                "1\tAXButton\tReload\t\tReload this page\t\ttrue\tfalse\t10\t20\t80\t30",
                "1\tAXTextField\tAddress and Search\tquant agent\t\t\ttrue\ttrue\t100\t20\t500\t30",
            ]
        )

        elements = parse_ax_snapshot(text)
        hits = search_ax_elements(elements, "search")

        self.assertEqual(len(elements), 3)
        self.assertEqual(hits[0].element.element_id, "AX0003")
        self.assertEqual(hits[0].target.center(), (350, 35))

    def test_grid_search_uses_labels_and_cell_targets(self) -> None:
        grid = {
            "cells": [
                {"id": "A01", "bounds": [0, 0, 100, 80], "label": "Cancel"},
                {"id": "B01", "bounds": [100, 0, 200, 80], "text": "Search"},
            ]
        }

        hits = search_grid_payload(grid, "search")

        self.assertEqual(hits[0].target.kind, "grid_cell")
        self.assertEqual(hits[0].target.value, "B01")

    def test_ocr_payload_searches_text_blocks(self) -> None:
        blocks = parse_ocr_payload(
            {
                "blocks": [
                    {"text": "Run Backtest", "confidence": 0.91, "bounds": [10, 20, 210, 60]},
                    {"text": "", "confidence": 0.1, "bounds": [0, 0, 1, 1]},
                ]
            }
        )
        hits = search_ocr_blocks(blocks, "backtest")

        self.assertEqual(len(blocks), 1)
        self.assertEqual(hits[0].target.center(), (110, 40))
        self.assertEqual(hits[0].source, "ocr")

    def test_som_targets_merge_ax_ocr_and_grid_marks(self) -> None:
        ax = [DesktopElement("AX0001", "Safari", 1, role="AXButton", title="Search", bounds=(20, 30, 100, 40))]
        ocr = [DesktopTextBlock("OCR0001", "Result Table", bounds=(300, 100, 520, 140), confidence=0.88)]
        grid = build_grid_payload_for_image(Path("shot.png"), 600, 400, cols=3, rows=2)

        targets = build_som_targets(
            image_path=Path("shot.png"),
            width=600,
            height=400,
            ax_elements=ax,
            ocr_blocks=ocr,
            grid_payload=grid,
            include_grid=True,
        )
        hits = search_som_targets(targets, "result")

        self.assertTrue(targets[0].mark_id.startswith("M"))
        self.assertTrue(any(target.source == "ax" for target in targets))
        self.assertTrue(any(target.source == "ocr" for target in targets))
        self.assertTrue(any(target.source == "grid" for target in targets))
        self.assertEqual(hits[0].source, "som")

    def test_web_search_plan_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            plan = plan_web_search("NVDA earnings", browser="Safari", engine="duckduckgo")
            run = execute_desktop_plan(project, plan)

            self.assertTrue(run.ok)
            self.assertEqual(run.status, "preview")
            self.assertIn("duckduckgo", plan.steps[2].args["text"])
            self.assertTrue(Path(run.log_path).exists())

    def test_web_search_execute_blocks_before_unreviewed_activate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            plan = plan_web_search("NVDA earnings", browser="Safari", engine="duckduckgo")
            run = execute_desktop_plan(project, plan, execute=True, reviewed=False)

            self.assertFalse(run.ok)
            self.assertEqual(run.status, "blocked")
            self.assertIn("step 1 activate requires --reviewed", run.summary)
            self.assertEqual(run.results, ())

    def test_auto_marked_side_effect_still_blocks_without_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = DesktopPlan("bad loaded plan", (DesktopStep("activate", {"app": "Safari"}, "bad", requires_review=False),))
            run = execute_desktop_plan(Path(tmp), plan, execute=True, reviewed=False)

            self.assertFalse(run.ok)
            self.assertEqual(run.status, "blocked")
            self.assertEqual(run.results, ())

    def test_loaded_desktop_plan_cannot_disable_review_for_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            plan_path = project / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "objective": "bad loaded plan",
                        "steps": [
                            {
                                "action": "activate",
                                "args": {"app": "Safari"},
                                "reason": "bad",
                                "requires_review": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            plan = load_desktop_plan(plan_path)
            run = execute_desktop_plan(project, plan, execute=True, reviewed=False)

            self.assertFalse(run.ok)
            self.assertEqual(run.status, "blocked")
            self.assertIn("activate requires --reviewed", run.summary)

    def test_open_target_plan_supports_terminal_url_and_app_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            terminal_plan = plan_open_target(project, "terminal", kind="terminal", cwd=".")
            url_plan = plan_open_target(project, "https://example.com", kind="url", browser="Safari")
            app_run = open_target(project, "Safari")

            self.assertEqual(terminal_plan.steps[0].action, "open")
            self.assertIn("Terminal", terminal_plan.steps[0].args["command"])
            self.assertEqual(url_plan.steps[0].args["command"][:3], ["open", "-a", "Safari"])
            self.assertTrue(app_run.ok)
            self.assertEqual(app_run.status, "preview")

    def test_execution_blocks_side_effects_without_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = DesktopPlan("type something", (DesktopStep("type", {"text": "hello"}, "test"),))
            run = execute_desktop_plan(Path(tmp), plan, execute=True, reviewed=False)

            self.assertFalse(run.ok)
            self.assertEqual(run.status, "blocked")
            self.assertIn("requires --reviewed", run.summary)

    def test_execution_preview_accepts_verify_flag_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = DesktopPlan("type something", (DesktopStep("type", {"text": "hello"}, "test"),))
            run = execute_desktop_plan(Path(tmp), plan, verify_after=True)

            self.assertTrue(run.ok)
            self.assertEqual(run.status, "preview")

    def test_search_url_and_plan_renderer_are_operator_readable(self) -> None:
        plan = plan_web_search("alpha beta", browser="Chrome", engine="bing")
        rendered = render_desktop_plan(plan)

        self.assertEqual(search_url("alpha beta", engine="google"), "https://www.google.com/search?q=alpha+beta")
        self.assertIn("Desktop Plan", rendered)
        self.assertIn("Chrome", rendered)
        self.assertIn("https://www.bing.com/search?q=alpha+beta", json.dumps(plan.to_payload()))

    def test_element_payload_preserves_bounds_and_label(self) -> None:
        element = DesktopElement("AX0001", "Finder", 1, role="AXButton", title="Open", bounds=(10, 20, 40, 20))
        payload = element.to_payload()

        self.assertEqual(element.center(), (30, 30))
        self.assertEqual(payload["bounds"], [10, 20, 40, 20])
        self.assertEqual(payload["label"], "Open")

    def test_agent_tool_executor_can_preview_desktop_search_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(Path(tmp), "desktop.web-search", {"query": "quant agent", "engine": "duckduckgo"})

            self.assertTrue(result.ok)
            self.assertEqual(result.data["status"], "preview")
            self.assertIn("desktop.web-search", result.name)

    def test_agent_tool_executor_can_preview_desktop_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(Path(tmp), "desktop.open", {"target": "terminal", "kind": "terminal"})

            self.assertTrue(result.ok)
            self.assertEqual(result.name, "desktop.open")
            self.assertEqual(result.data["status"], "preview")

    def test_agent_tool_executor_knows_som_preview_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(Path(tmp), "desktop.som", {"image": "missing.png", "include_ocr": False})

            self.assertFalse(result.ok)
            self.assertEqual(result.name, "desktop.som")

    def test_agent_tool_executor_blocks_unapproved_desktop_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_tool(
                Path(tmp),
                "desktop.web-search",
                {"query": "quant agent", "execute": True, "reviewed": True},
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.blocked)
            self.assertIn("requires --reviewed", result.summary)


if __name__ == "__main__":
    unittest.main()
