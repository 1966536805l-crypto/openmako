from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.checkpoints import create_checkpoint, list_checkpoints, load_checkpoint, render_checkpoint_detail, restore_checkpoint
from quantagent.code_index import (
    build_code_index,
    dependency_graph,
    diagnose_code_index,
    editor_diagnostics,
    related_files,
    render_code_index_health,
    render_editor_diagnostics,
    render_related_files,
    search_code_index,
    similar_code_chunks,
    write_code_index,
)


class CodeIndexCheckpointTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent index checkpoint ")

    def test_bm25_code_index_finds_symbols(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("class TradeEngine:\n    def apply_slippage(self):\n        return 1\n", encoding="utf-8")
            index = build_code_index(project)
            write_code_index(project, index)

            hits = search_code_index(project, "slippage trade engine")

            self.assertTrue(hits)
            self.assertEqual(hits[0].path, "alpha.py")
            self.assertIn("TradeEngine", hits[0].symbols)

    def test_code_index_tracks_imports(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("import sqlite3\nfrom pathlib import Path\n\ndef open_store():\n    return Path('.')\n", encoding="utf-8")
            write_code_index(project, build_code_index(project))

            hits = search_code_index(project, "sqlite pathlib open store")

            self.assertTrue(hits)
            self.assertIn("sqlite3", hits[0].imports)
            self.assertIn("pathlib", hits[0].imports)

    def test_code_index_stores_semantic_fingerprints_and_vectors(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("class RiskEngine:\n    def estimate_drawdown(self):\n        return 1\n", encoding="utf-8")

            index = build_code_index(project)

            self.assertEqual(index.version, 2)
            self.assertTrue(index.chunks[0].semantic_fingerprint)
            self.assertTrue(index.chunks[0].lexical_vector)
            self.assertIn("risk", index.chunks[0].semantic_fingerprint)

    def test_similar_chunks_and_related_files_use_lightweight_semantic_vectors(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text(
                "class RiskEngine:\n"
                "    def estimate_slippage_capacity(self):\n"
                "        return 'risk capacity slippage'\n",
                encoding="utf-8",
            )
            (project / "beta.py").write_text(
                "def capacity_risk_report():\n"
                "    return 'slippage adjusted portfolio capacity risk'\n",
                encoding="utf-8",
            )
            (project / "notes.md").write_text("Release notes for the command palette.\n", encoding="utf-8")
            write_code_index(project, build_code_index(project))

            chunk_hits = similar_code_chunks(project, "portfolio slippage capacity risk", limit=3)
            file_hits = related_files(project, "alpha.py", limit=2)
            rendered = render_related_files(file_hits)

            self.assertTrue(any(hit.path == "beta.py" for hit in chunk_hits))
            self.assertEqual(file_hits[0].path, "beta.py")
            self.assertIn("Related Files", rendered)
            self.assertIn("capacity", ",".join(file_hits[0].shared_fingerprints))

    def test_code_index_diagnose_rebuilds_missing_index(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")

            health = diagnose_code_index(project)
            rendered = render_code_index_health(health)

            self.assertEqual(health.files, 1)
            self.assertTrue(any(item.code == "missing_index" for item in health.diagnostics))
            self.assertIn("Code Index Diagnostics", rendered)

    def test_code_index_diagnose_detects_stale_file_and_duplicate_symbol(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("class Shared:\n    pass\n", encoding="utf-8")
            (project / "beta.py").write_text("class Shared:\n    pass\n", encoding="utf-8")
            write_code_index(project, build_code_index(project))
            (project / "alpha.py").write_text("class Shared:\n    value = 2\n", encoding="utf-8")

            health = diagnose_code_index(project)
            codes = {item.code for item in health.diagnostics}

            self.assertIn("stale_file_index", codes)
            self.assertIn("duplicate_symbol", codes)

    def test_editor_diagnostics_detects_syntax_todo_and_unresolved_import(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "bad.py").write_text("def broken(:\n    return 1\n", encoding="utf-8")
            (project / "alpha.py").write_text(
                "import definitely_missing_quantagent_package\n"
                "\n"
                "# TODO: validate import resolver output\n"
                "def alpha():\n"
                "    return 1\n",
                encoding="utf-8",
            )

            diagnostics = editor_diagnostics(project)
            health = diagnose_code_index(project, include_editor_diagnostics=True)
            rendered = render_editor_diagnostics(diagnostics)
            codes = {item.code for item in diagnostics}

            self.assertIn("python_syntax_error", codes)
            self.assertIn("todo_comment", codes)
            self.assertIn("unresolved_import", codes)
            self.assertTrue(any(item.source == "editor_diagnostics" for item in health.diagnostics))
            self.assertIn("Editor Diagnostics", rendered)
            self.assertIn("bad.py:1", rendered)

    def test_dependency_graph_lists_imports_by_file(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("import sqlite3\nfrom pathlib import Path\n", encoding="utf-8")
            write_code_index(project, build_code_index(project))

            graph = dependency_graph(project)

            self.assertEqual(graph["alpha.py"], ["pathlib", "sqlite3"])

    def test_checkpoint_restores_modified_and_deleted_files(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "a.txt"
            missing = project / "new.txt"
            target.write_text("old\n", encoding="utf-8")
            checkpoint = create_checkpoint(project, ["a.txt", "new.txt"], reason="before edit")

            target.write_text("new\n", encoding="utf-8")
            missing.write_text("created\n", encoding="utf-8")
            restored = restore_checkpoint(project, checkpoint.checkpoint_id)

            self.assertEqual(restored.checkpoint_id, checkpoint.checkpoint_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertFalse(missing.exists())
            self.assertEqual(list_checkpoints(project)[0].checkpoint_id, checkpoint.checkpoint_id)

    def test_checkpoint_show_detail_is_readable(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            checkpoint = create_checkpoint(project, ["a.txt"], task_id="qa-1", reason="before edit")

            loaded = load_checkpoint(project, checkpoint.checkpoint_id)
            rendered = render_checkpoint_detail(loaded, include_text=True)

            self.assertIn(checkpoint.checkpoint_id, rendered)
            self.assertIn("a.txt [present]", rendered)
            self.assertIn("old", rendered)


if __name__ == "__main__":
    unittest.main()
