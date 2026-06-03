from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.mode_router import route_agent_mode


class ModeRouterTest(unittest.TestCase):
    def test_create_file_task_routes_to_build_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent mode router ") as tmp:
            route = route_agent_mode(
                Path(tmp),
                "create hello.py with greet function and test it",
                input_provenance="agent",
            )

        self.assertEqual(route.mode, "build")


if __name__ == "__main__":
    unittest.main()
