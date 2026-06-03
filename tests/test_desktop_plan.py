from __future__ import annotations

import unittest

from quantagent.desktop_plan import plan_click, render_click_plan


def sample_grid() -> dict[str, object]:
    return {
        "image_path": "shot.png",
        "width": 300,
        "height": 200,
        "cols": 3,
        "rows": 2,
        "cells": [
            {"id": "A01", "row": 1, "col": 1, "x": 50, "y": 50, "bounds": [0, 0, 100, 100], "label": "New file"},
            {"id": "B01", "row": 1, "col": 2, "x": 150, "y": 50, "bounds": [100, 0, 200, 100], "label": "Save"},
            {"id": "C01", "row": 1, "col": 3, "x": 250, "y": 50, "bounds": [200, 0, 300, 100]},
            {"id": "A02", "row": 2, "col": 1, "x": 50, "y": 150, "bounds": [0, 100, 100, 200]},
            {"id": "B02", "row": 2, "col": 2, "x": 150, "y": 150, "bounds": [100, 100, 200, 200], "text": "Run tests"},
            {"id": "C02", "row": 2, "col": 3, "x": 250, "y": 150, "bounds": [200, 100, 300, 200], "ocr_text": "Cancel"},
        ],
    }


class DesktopPlanTest(unittest.TestCase):
    def test_cell_id_query_wins_deterministically(self) -> None:
        plan = plan_click(sample_grid(), "click b2 please")

        self.assertTrue(plan.ok)
        self.assertEqual(plan.target_cell, "B02")
        self.assertEqual(plan.coordinate, (150, 150))
        self.assertTrue(plan.requires_confirmation)
        self.assertIn("cell id", plan.reason)

    def test_row_col_query_supports_number_and_letter_columns(self) -> None:
        numeric = plan_click(sample_grid(), "row 2 col 3")
        letter = plan_click(sample_grid(), "column C row 2")

        self.assertEqual(numeric.target_cell, "C02")
        self.assertEqual(numeric.coordinate, (250, 150))
        self.assertEqual(letter.target_cell, "C02")

    def test_text_label_query_uses_cell_labels(self) -> None:
        plan = plan_click(sample_grid(), "press save")

        self.assertTrue(plan.ok)
        self.assertEqual(plan.target_cell, "B01")
        self.assertEqual(plan.coordinate, (150, 50))
        self.assertIn("text label", plan.reason)

    def test_no_match_returns_non_clicking_plan(self) -> None:
        plan = plan_click(sample_grid(), "open preferences")

        self.assertFalse(plan.ok)
        self.assertIsNone(plan.coordinate)
        self.assertEqual(plan.target_cell, "")
        self.assertTrue(plan.requires_confirmation)

    def test_render_click_plan_is_operator_readable(self) -> None:
        plan = plan_click(sample_grid(), "run tests")
        rendered = render_click_plan(plan)

        self.assertIn("Desktop Click Plan", rendered)
        self.assertIn("Target: B02", rendered)
        self.assertIn("Coordinate: 150,150", rendered)
        self.assertIn("Requires confirmation: true", rendered)


if __name__ == "__main__":
    unittest.main()
