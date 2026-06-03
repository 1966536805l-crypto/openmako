from __future__ import annotations

import io
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from quantagent.cli import _requires_workspace_trust
from quantagent.workspace_trust import (
    TRUST_STORE_ENV,
    ensure_workspace_trusted,
    is_workspace_trusted,
    render_workspace_trust_prompt,
    trust_store_path,
)


class WorkspaceTrustTest(unittest.TestCase):
    def test_prompt_contains_workspace_safety_language(self) -> None:
        prompt = render_workspace_trust_prompt("/tmp/example")

        self.assertIn("Accessing workspace:", prompt)
        self.assertIn("Mako", prompt)
        self.assertIn("╭████╮", prompt)
        self.assertIn("│⬤██⬤│", prompt)
        self.assertIn("╰████╯", prompt)
        for partial in ("▐", "▛", "▜", "▌", "▝", "▘", "▄"):
            self.assertNotIn(partial, prompt)
        self.assertIn("/tmp/example", prompt)
        self.assertIn("Quick safety check", prompt)
        self.assertIn("Security guide", prompt)
        self.assertIn("❯ 1.", prompt)
        self.assertIn("Yes, I trust this folder", prompt)
        self.assertIn("No, exit", prompt)

    def test_enter_trusts_workspace_and_persists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent trust ") as tmp:
            project = Path(tmp) / "project"
            store = Path(tmp) / "trusted.json"
            project.mkdir()
            old = os.environ.get(TRUST_STORE_ENV)
            os.environ[TRUST_STORE_ENV] = str(store)
            try:
                output = io.StringIO()
                trusted = ensure_workspace_trusted(
                    project,
                    interactive=True,
                    input_func=lambda _prompt: "",
                    output=output,
                )

                self.assertTrue(trusted)
                self.assertTrue(is_workspace_trusted(project))
                self.assertEqual(trust_store_path(), store)
                self.assertTrue(store.exists())
                self.assertIn("Accessing workspace", output.getvalue())
            finally:
                if old is None:
                    os.environ.pop(TRUST_STORE_ENV, None)
                else:
                    os.environ[TRUST_STORE_ENV] = old

    def test_decline_exits_without_persisting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent trust ") as tmp:
            project = Path(tmp) / "project"
            store = Path(tmp) / "trusted.json"
            project.mkdir()
            old = os.environ.get(TRUST_STORE_ENV)
            os.environ[TRUST_STORE_ENV] = str(store)
            try:
                trusted = ensure_workspace_trusted(
                    project,
                    interactive=True,
                    input_func=lambda _prompt: "2",
                    output=io.StringIO(),
                )

                self.assertFalse(trusted)
                self.assertFalse(store.exists())
            finally:
                if old is None:
                    os.environ.pop(TRUST_STORE_ENV, None)
                else:
                    os.environ[TRUST_STORE_ENV] = old

    def test_noninteractive_requires_existing_or_explicit_trust(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent trust ") as tmp:
            project = Path(tmp) / "project"
            store = Path(tmp) / "trusted.json"
            project.mkdir()
            old = os.environ.get(TRUST_STORE_ENV)
            os.environ[TRUST_STORE_ENV] = str(store)
            try:
                self.assertFalse(ensure_workspace_trusted(project, interactive=False))

                self.assertTrue(ensure_workspace_trusted(project, interactive=False, assume_yes=True))
                self.assertTrue(ensure_workspace_trusted(project, interactive=False))
            finally:
                if old is None:
                    os.environ.pop(TRUST_STORE_ENV, None)
                else:
                    os.environ[TRUST_STORE_ENV] = old

    def test_noninteractive_can_be_explicitly_disabled_for_automation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent trust ") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            self.assertTrue(ensure_workspace_trusted(project, interactive=False, disabled=True))

    def test_workspace_trust_gate_only_for_workspace_commands(self) -> None:
        self.assertTrue(_requires_workspace_trust(Namespace(command="chat", project=None)))
        self.assertTrue(_requires_workspace_trust(Namespace(command="status", project="/tmp/project")))
        self.assertFalse(_requires_workspace_trust(Namespace(command="tools")))
        self.assertFalse(_requires_workspace_trust(Namespace(command="sandbox")))
        self.assertFalse(_requires_workspace_trust(Namespace(command="skills", project=None, install=None)))
        self.assertTrue(_requires_workspace_trust(Namespace(command="skills", project=None, install="./my-skill")))


if __name__ == "__main__":
    unittest.main()
