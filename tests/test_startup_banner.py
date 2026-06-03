from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from quantagent.chat_ui import BLACK, MASCOT, ORANGE, print_startup_banner
from quantagent.startup_banner import collect_startup_warnings, render_startup_banner


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class StartupBannerTest(unittest.TestCase):
    def test_banner_shows_model_provider_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent banner ") as tmp:
            project = Path(tmp)

            banner = render_startup_banner(project, "gpt-test", base_url="https://example.test/v1")

            self.assertIn("Mako v", banner)
            self.assertIn("gpt-test", banner)
            self.assertIn("https://example.test/v1", banner)
            self.assertIn(str(project), banner)
            self.assertIn("/model to change", banner)

    def test_chat_banner_renders_cute_filled_mascot_with_large_black_eyes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent banner ") as tmp:
            stdout = TtyStringIO()

            with contextlib.redirect_stdout(stdout):
                print_startup_banner(Path(tmp), "gpt-test")

            rendered = stdout.getvalue()
            self.assertIn(ORANGE + MASCOT[0], rendered)
            self.assertIn(ORANGE + MASCOT[1][:2], rendered)
            self.assertIn(BLACK + MASCOT[1][2:3], rendered)
            self.assertIn(ORANGE + MASCOT[1][3:5], rendered)
            self.assertIn(BLACK + MASCOT[1][5:6], rendered)
            self.assertIn(ORANGE + MASCOT[1][6:], rendered)
            self.assertIn(ORANGE + MASCOT[2], rendered)
            self.assertIn("╭████╮", rendered)
            self.assertIn("│", rendered)
            self.assertIn("⬤", rendered)
            self.assertIn("╰████╯", rendered)
            for partial in ("▐", "▛", "▜", "▌", "▝", "▘", "▄"):
                self.assertNotIn(partial, rendered)

    def test_auth_conflicts_render_as_startup_warnings(self) -> None:
        warnings = collect_startup_warnings(
            home="/tmp/no-such-home",
            env={
                "QUANTAGENT_OPENAI_API_KEY": "qa-key",
                "OPENAI_API_KEY": "openai-key",
                "ANTHROPIC_AUTH_TOKEN": "token",
                "ANTHROPIC_API_KEY": "anthropic-key",
            },
        )

        rendered = "\n".join(item.title + " " + item.detail for item in warnings)
        self.assertIn("Auth conflict", rendered)
        self.assertIn("QUANTAGENT_OPENAI_API_KEY", rendered)
        self.assertIn("Anthropic auth conflict", rendered)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", rendered)

    def test_missing_zshrc_source_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent banner ") as tmp:
            home = Path(tmp)
            (home / ".zshrc").write_text(
                "source $HOME/.openclaw/completions/openclaw.zsh\n",
                encoding="utf-8",
            )

            warnings = collect_startup_warnings(home=home, env={"HOME": str(home)})

            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0].title, "Shell startup file missing")
            self.assertIn(".openclaw/completions/openclaw.zsh", warnings[0].detail)

    def test_existing_zshrc_source_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent banner ") as tmp:
            home = Path(tmp)
            target = home / ".openclaw" / "completions" / "openclaw.zsh"
            target.parent.mkdir(parents=True)
            target.write_text("# ok\n", encoding="utf-8")
            (home / ".zshrc").write_text("source $HOME/.openclaw/completions/openclaw.zsh\n", encoding="utf-8")

            warnings = collect_startup_warnings(home=home, env={"HOME": str(home)})

            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
