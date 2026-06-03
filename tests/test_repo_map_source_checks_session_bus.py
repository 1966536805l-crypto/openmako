from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.event_log import read_runtime_events
from quantagent.repo_map import build_repo_map, related_repo_paths, render_repo_context, search_repo_map
from quantagent.runtime_store import list_runtime_sessions
from quantagent.session_bus import (
    list_bus_messages,
    send_bus_message,
    session_bus_summary,
    start_session_bus,
    status_session_bus,
)
from quantagent.sessions import load_session
from quantagent.source_checks import FAIL, PASS, SKIP, load_source_checks, parse_source_check, run_source_checks


class RepoMapTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent repo map ")

    def test_python_symbols_imports_search_and_context_rendering(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            package = project / "pkg"
            package.mkdir()
            (package / "trading.py").write_text(
                "\n".join(
                    [
                        "import math",
                        "from collections import Counter",
                        "",
                        "class AlphaEngine:",
                        '    """Plan alpha trades."""',
                        "",
                        "    def plan(self, prices):",
                        "        counts = Counter(prices)",
                        "        return price_signal(counts, math.sqrt(len(prices)))",
                        "",
                        "def price_signal(counts, scale):",
                        "    return max(counts.values()) / scale",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (project / "README.md").write_text("# Trading Notes\nAlphaEngine handles risk.\n", encoding="utf-8")

            repo_map = build_repo_map(project)
            summary = next(item for item in repo_map.files if item.path == "pkg/trading.py")
            symbols = {symbol.qualname: symbol for symbol in summary.symbols}

            self.assertEqual(summary.imports, ("collections", "math"))
            self.assertEqual(symbols["AlphaEngine"].kind, "class")
            self.assertEqual(symbols["AlphaEngine.plan"].kind, "function")
            self.assertEqual(symbols["price_signal"].kind, "function")
            self.assertIn("Counter", symbols["AlphaEngine.plan"].refs)
            self.assertIn("price_signal", symbols["AlphaEngine.plan"].calls)

            hits = search_repo_map(project, "AlphaEngine plan", limit=3, rebuild=True)
            self.assertTrue(hits)
            self.assertEqual(hits[0].path, "pkg/trading.py")
            self.assertIn("AlphaEngine.plan", hits[0].symbols)
            self.assertIn("symbol:alphaengine", hits[0].reason)

            context = render_repo_context(project, "price_signal", rebuild=False)
            self.assertIn("# Repo Context Map", context)
            self.assertIn("## pkg/trading.py", context)
            self.assertIn("imports: collections, math", context)
            self.assertIn("- class AlphaEngine:", context)
            self.assertIn("- function AlphaEngine.plan:", context)
            self.assertIn("- function price_signal:", context)

    def test_aider_style_graph_ranks_referenced_definitions(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            package = project / "pkg"
            package.mkdir()
            (package / "signals.py").write_text(
                "def make_signal(rows):\n"
                "    return len(rows)\n",
                encoding="utf-8",
            )
            (package / "runner.py").write_text(
                "from pkg.signals import make_signal\n\n"
                "def run_strategy(rows):\n"
                "    return make_signal(rows)\n",
                encoding="utf-8",
            )
            (package / "unrelated.py").write_text("def other():\n    return 1\n", encoding="utf-8")

            related = related_repo_paths(project, "pkg/runner.py", rebuild=True)
            search = search_repo_map(project, "make_signal", limit=3, rebuild=False)

            self.assertTrue(related)
            self.assertEqual(related[0].path, "pkg/signals.py")
            self.assertIn("aider_graph=make_signal", related[0].reason)
            self.assertEqual(search[0].path, "pkg/signals.py")
            self.assertIn("aider_graph:make_signal", search[0].reason)


class SourceChecksTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent source checks ")

    def test_frontmatter_glob_matching_and_required_forbidden_results(self) -> None:
        check_text = """---
id: python-style
description: Require Alpha classes and forbid debug prints
globs:
  - "src/*.py"
required_patterns:
  - "class Alpha"
forbidden_patterns:
  - "print\\("
severity: warning
---
Python source should define Alpha without debug prints.
"""
        parsed = parse_source_check(check_text, ".quantagent/checks/python-style.md")

        self.assertEqual(parsed.check_id, "python-style")
        self.assertEqual(parsed.description, "Require Alpha classes and forbid debug prints")
        self.assertEqual(parsed.globs, ("src/*.py",))
        self.assertEqual(parsed.required_patterns, ("class Alpha",))
        self.assertEqual(parsed.forbidden_patterns, ("print\\(",))
        self.assertEqual(parsed.severity, "warning")
        self.assertIn("Alpha without debug prints", parsed.body)

        with self.make_project() as tmp:
            project = Path(tmp)
            checks_dir = project / ".quantagent" / "checks"
            checks_dir.mkdir(parents=True)
            (checks_dir / "python-style.md").write_text(check_text, encoding="utf-8")
            src = project / "src"
            src.mkdir()
            (src / "good.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
            (src / "bad.py").write_text("print('debug')\n", encoding="utf-8")
            docs = project / "docs"
            docs.mkdir()
            (docs / "readme.md").write_text("# Notes\n", encoding="utf-8")

            loaded = load_source_checks(project)
            self.assertEqual([check.check_id for check in loaded], ["python-style"])

            passing = run_source_checks(project, paths=["src/good.py"])
            self.assertEqual([result.status for result in passing], [PASS, PASS])
            self.assertEqual({result.paths for result in passing}, {("src/good.py",)})

            failing = run_source_checks(project, paths=["src/bad.py"])
            self.assertEqual([result.status for result in failing], [FAIL, FAIL])
            self.assertIn("required pattern missing", failing[0].message)
            self.assertIn("forbidden pattern found", failing[1].message)

            skipped = run_source_checks(project, paths=["docs/readme.md"])
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0].status, SKIP)
            self.assertIn("does not match changed paths", skipped[0].message)


class SessionBusTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent session bus ")

    def test_start_send_list_status_and_runtime_chain(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            initial = status_session_bus(project)
            self.assertEqual(initial.status, "stopped")
            self.assertEqual(initial.channels, ())

            state = start_session_bus(project, owner="worker-c", channels=("cli", "review", "cli"))
            self.assertEqual(state.status, "running")
            self.assertEqual(state.owner, "worker-c")
            self.assertEqual(state.channels, ("cli", "review"))

            message = send_bus_message(
                project,
                channel="review",
                sender="worker-c",
                content="please inspect runtime event",
                target="agent",
                metadata={"priority": "high"},
            )

            current = status_session_bus(project)
            self.assertEqual(current.bus_id, state.bus_id)
            self.assertEqual(current.status, "running")

            messages = list_bus_messages(project)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].message_id, message.message_id)
            self.assertEqual(messages[0].session_id, message.session_id)
            self.assertEqual(messages[0].metadata["priority"], "high")
            self.assertEqual(list_bus_messages(project, channel="review"), messages)
            self.assertEqual(list_bus_messages(project, channel="other"), [])

            session = load_session(project, message.session_id)
            self.assertEqual(len(session.messages), 1)
            self.assertEqual(session.messages[0].role, "user")
            self.assertEqual(session.messages[0].content, "please inspect runtime event")
            self.assertEqual(session.messages[0].meta["bus_message_id"], message.message_id)

            runtime_sessions = list_runtime_sessions(project)
            self.assertEqual(len(runtime_sessions), 1)
            self.assertEqual(runtime_sessions[0].id, message.session_id)
            self.assertEqual(runtime_sessions[0].message_count, 1)

            events = read_runtime_events(project, kind="message", correlation_id=message.message_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].session_id, message.session_id)
            self.assertEqual(events[0].status, "queued")
            self.assertEqual(events[0].data["content"], "please inspect runtime event")

            summary = session_bus_summary(project)
            self.assertEqual(summary["messages"], 1)
            self.assertEqual(summary["sessions"], 1)
            self.assertEqual(summary["channels"], ["review"])


if __name__ == "__main__":
    unittest.main()
