from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from quantagent.runtime_store import runtime_db_path
from quantagent.sessions import append_message, create_session, export_session, search_session_messages


class SessionSearchExportTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent session search ")

    def test_session_search_uses_runtime_store_messages(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "debug")
            append_message(project, session.session_id, "user", "slippage failure traceback")

            rows = search_session_messages(project, "slippage")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_id"], session.session_id)

    def test_session_export_json_and_markdown_include_meta(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            session = create_session(project, "cost")
            append_message(project, session.session_id, "assistant", "done", meta={"token_count": 12, "reasoning_summary": "short", "tool_name": "status"})

            exported = json.loads(export_session(project, session.session_id))
            markdown = export_session(project, session.session_id, format="markdown")
            conn = sqlite3.connect(runtime_db_path(project))
            try:
                row = conn.execute("SELECT token_count, reasoning, tool_name FROM messages").fetchone()
            finally:
                conn.close()

            self.assertEqual(exported["messages"][0]["meta"]["token_count"], 12)
            self.assertIn("reasoning_summary", markdown)
            self.assertEqual(row, (12, "short", "status"))


if __name__ == "__main__":
    unittest.main()
