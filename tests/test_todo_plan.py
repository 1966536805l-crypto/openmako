from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.task_state import add_task, load_tasks
from quantagent.todo import load_task_plan, render_task_plan, set_plan_item


class TodoPlanTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent todo plan ")

    def test_task_bound_plan_updates_task_runtime_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = add_task(project, "implement checkpoint transcript")

            items = set_plan_item(project, task.id, "1", "in_progress", title="Add transcript replay")
            reloaded = load_task_plan(project, task.id)
            tasks = load_tasks(project)
            rendered = render_task_plan(task.id, reloaded)

            self.assertEqual(items[0].status, "in_progress")
            self.assertEqual(reloaded[0].title, "Add transcript replay")
            self.assertIn("in_progress", rendered)
            self.assertTrue(tasks[0].evidence)
            self.assertEqual(tasks[0].history[-1]["note"], "plan item 1 -> in_progress")


if __name__ == "__main__":
    unittest.main()
