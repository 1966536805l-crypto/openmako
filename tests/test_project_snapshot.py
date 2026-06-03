from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent import project as project_mod


class ProjectSnapshotTest(unittest.TestCase):
    def test_baseline_scan_skips_system_state_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project snapshot ") as tmp:
            project = Path(tmp)
            expected = project / "data" / "tick_data_request_real.csv"
            expected.parent.mkdir()
            expected.write_text("ok\n", encoding="utf-8")
            skipped = (
                project
                / "Library"
                / "Containers"
                / "app"
                / "Data"
                / "Library"
                / "Saved Application State"
                / "demo.savedState"
                / "tick_data_request_hidden.csv"
            )
            skipped.parent.mkdir(parents=True)
            skipped.write_text("skip\n", encoding="utf-8")

            found = project_mod.find_baseline_files(project)

            self.assertEqual(found, [expected])

    def test_baseline_scan_returns_partial_results_when_walk_is_interrupted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project snapshot ") as tmp:
            project = Path(tmp)
            expected = project / "tick_data_request_real.csv"
            expected.write_text("ok\n", encoding="utf-8")
            original_walk = project_mod.os.walk

            def interrupted_walk(*args, **kwargs):
                yield from original_walk(*args, **kwargs)
                raise InterruptedError(4, "Interrupted system call", str(project / "Library"))

            with patch.object(project_mod.os, "walk", interrupted_walk):
                found = project_mod.find_baseline_files(project)

            self.assertEqual(found, [expected])


if __name__ == "__main__":
    unittest.main()
