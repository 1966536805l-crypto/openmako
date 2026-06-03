from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.retrieval_daemon import (
    build_retrieval_index,
    ensure_retrieval_index,
    load_retrieval_daemon_state,
    load_retrieval_index,
    related_retrieval_paths,
    render_retrieval_hits,
    render_retrieval_index,
    render_retrieval_state,
    retrieval_health,
    retrieval_index_path,
    retrieval_state_path,
    search_retrieval_index,
    start_retrieval_daemon,
    stop_retrieval_daemon,
    write_retrieval_index,
)


class RetrievalDaemonTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent retrieval ")

    def test_retrieval_index_builds_vectors_fingerprints_and_persists(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "risk_engine.py").write_text(
                "class RiskEngine:\n"
                "    def estimate_drawdown(self):\n"
                "        return 'portfolio risk capacity slippage'\n",
                encoding="utf-8",
            )

            index = build_retrieval_index(project, rebuild_code_index=True)
            path = write_retrieval_index(project, index)
            loaded = load_retrieval_index(project)
            rendered = render_retrieval_index(loaded)

            self.assertEqual(path, retrieval_index_path(project))
            self.assertEqual(index.version, 1)
            self.assertEqual(len(loaded.records), 1)
            self.assertEqual(loaded.dimensions, len(loaded.records[0].vector))
            self.assertTrue(loaded.records[0].vector)
            self.assertTrue(loaded.records[0].fingerprints)
            self.assertTrue(loaded.records[0].sha256)
            self.assertIn("RiskEngine", loaded.records[0].symbols)
            self.assertIn("records: 1", rendered)

    def test_retrieval_search_returns_relevant_file_with_reasons(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "risk_engine.py").write_text(
                "class RiskEngine:\n"
                "    def estimate_slippage_capacity(self):\n"
                "        return 'portfolio risk capacity slippage drawdown'\n",
                encoding="utf-8",
            )
            (project / "ui.py").write_text(
                "def render_palette():\n"
                "    return 'button toolbar theme'\n",
                encoding="utf-8",
            )
            ensure_retrieval_index(project, rebuild=True)

            hits = search_retrieval_index(project, "slippage capacity risk drawdown", limit=2)
            rendered = render_retrieval_hits(hits)

            self.assertTrue(hits)
            self.assertEqual(hits[0].path, "risk_engine.py")
            self.assertGreater(hits[0].score, 0)
            self.assertTrue({"lexical", "vector", "fingerprint", "symbol"} & set(hits[0].reasons))
            self.assertIn("risk_engine.py", rendered)

    def test_related_retrieval_paths_use_import_graph(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text(
                "import beta\n"
                "\n"
                "def alpha_signal():\n"
                "    return beta.capacity_report()\n",
                encoding="utf-8",
            )
            (project / "beta.py").write_text(
                "def capacity_report():\n"
                "    return 'slippage risk capacity portfolio'\n",
                encoding="utf-8",
            )
            ensure_retrieval_index(project, rebuild=True)

            hits = related_retrieval_paths(project, ["alpha.py"], limit=3)

            self.assertTrue(hits)
            self.assertEqual(hits[0].path, "beta.py")
            self.assertIn("graph", hits[0].reasons)
            self.assertGreater(hits[0].graph_score, 0)

    def test_retrieval_daemon_state_can_start_status_stop(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("def alpha():\n    return 'risk capacity'\n", encoding="utf-8")

            started = start_retrieval_daemon(project, rebuild=True)
            loaded = load_retrieval_daemon_state(project)
            health = retrieval_health(project)
            stopped = stop_retrieval_daemon(project)
            stopped_health = retrieval_health(project)
            rendered = render_retrieval_state(stopped)

            self.assertEqual(started.status, "running")
            self.assertIsInstance(started.pid, int)
            self.assertEqual(started.records, 1)
            self.assertEqual(loaded, started)
            self.assertTrue(retrieval_state_path(project).exists())
            self.assertTrue(health.ok, health.diagnostics)
            self.assertEqual(health.status, "running")
            self.assertEqual(stopped.daemon_id, started.daemon_id)
            self.assertEqual(stopped.status, "stopped")
            self.assertIsNone(stopped.pid)
            self.assertEqual(stopped_health.status, "stopped")
            self.assertIn("Retrieval Daemon", rendered)


if __name__ == "__main__":
    unittest.main()
