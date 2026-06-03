from __future__ import annotations

import unittest

from quantagent.iteration_budget import EXHAUSTED_REASON, IterationBudget


class IterationBudgetTest(unittest.TestCase):
    def test_consume_reaches_exhaustion_without_negative_remaining(self) -> None:
        budget = IterationBudget(max_iterations=2)

        self.assertEqual(budget.remaining, 2)
        self.assertFalse(budget.exhausted)
        self.assertTrue(budget.consume())
        self.assertEqual(budget.remaining, 1)
        self.assertTrue(budget.consume())
        self.assertEqual(budget.remaining, 0)
        self.assertTrue(budget.exhausted)

    def test_consume_after_exhaustion_returns_false_and_reason(self) -> None:
        budget = IterationBudget(max_iterations=1)

        self.assertTrue(budget.consume())
        self.assertFalse(budget.consume())

        self.assertEqual(budget.remaining, 0)
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.reason, EXHAUSTED_REASON)

    def test_invalid_budget_rejected(self) -> None:
        with self.assertRaises(ValueError):
            IterationBudget(max_iterations=0)
        with self.assertRaises(ValueError):
            IterationBudget(max_iterations=-1)
        with self.assertRaises(TypeError):
            IterationBudget(max_iterations=True)
        with self.assertRaises(TypeError):
            IterationBudget(max_iterations=1.5)  # type: ignore[arg-type]

    def test_to_dict_has_stable_shape(self) -> None:
        budget = IterationBudget(max_iterations=2)

        self.assertEqual(
            budget.to_dict(),
            {
                "max_iterations": 2,
                "remaining": 2,
                "exhausted": False,
                "reason": "",
            },
        )

        budget.consume()
        budget.consume()

        self.assertEqual(
            budget.to_dict(),
            {
                "max_iterations": 2,
                "remaining": 0,
                "exhausted": True,
                "reason": EXHAUSTED_REASON,
            },
        )


if __name__ == "__main__":
    unittest.main()
