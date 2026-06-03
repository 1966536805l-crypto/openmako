from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.doctor import render_doctor_json, run_doctor
from quantagent.runtime_store import reserve_model_budget, runtime_db_path
from quantagent.skills import install_skill
from quantagent.task_state import add_task


class DoctorTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent doctor ")

    def test_doctor_checks_runtime_store_and_json_output(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            add_task(project, "doctor task")

            checks = run_doctor(project)
            payload = json.loads(render_doctor_json(project, checks))
            by_name = {check["name"]: check for check in payload["checks"]}

            self.assertTrue(runtime_db_path(project).exists())
            self.assertIn("runtime_store", by_name)
            self.assertTrue(by_name["runtime_store"]["ok"])
            self.assertEqual(by_name["runtime_store"]["category"], "runtime")
            self.assertIn("budget_reservations", by_name)
            self.assertTrue(by_name["budget_reservations"]["ok"])
            self.assertEqual(by_name["budget_reservations"]["category"], "runtime")
            self.assertIn("plugin_state_store", by_name)
            self.assertTrue(by_name["plugin_state_store"]["ok"])
            self.assertEqual(by_name["plugin_state_store"]["category"], "plugins")

    def test_doctor_flags_stale_budget_reservation(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            with patch.dict("os.environ", {"QUANTAGENT_MODEL_MAX_SESSION_CALLS": "2"}, clear=False):
                decision = reserve_model_budget(
                    project,
                    session_id="sess-doctor-budget",
                    query_id="qa-doctor-budget",
                    model="gpt-test",
                    provider="fake",
                    estimated_tokens=1,
                )
            now_ms = int(time.time() * 1000)
            with sqlite3.connect(runtime_db_path(project)) as conn:
                conn.execute(
                    """
                    UPDATE budget_reservations
                    SET created_at = ?, updated_at = ?, expires_at = ?
                    WHERE reservation_id = ?
                    """,
                    (now_ms - 700_000, now_ms - 700_000, now_ms + 700_000, decision["reservation_id"]),
                )

            checks = run_doctor(project)
            budget = next(check for check in checks if check.name == "budget_reservations")

            self.assertFalse(budget.ok)
            self.assertEqual(budget.severity, "warn")
            self.assertIn("stale=1", budget.detail)

    def test_doctor_counts_project_skills(self) -> None:
        with self.make_project() as project_tmp, tempfile.TemporaryDirectory(prefix="doctor skill ") as source_tmp:
            source = Path(source_tmp)
            (source / "SKILL.md").write_text("# Demo Skill\n\nTriggers: demo\n\nBody.\n", encoding="utf-8")
            install_skill(Path(project_tmp), source)

            checks = run_doctor(Path(project_tmp))
            built_in = next(check for check in checks if check.name == "built_in_skills")

            self.assertTrue(built_in.ok)
            self.assertIn("project", built_in.detail)

    def test_doctor_reports_bad_plugin_manifest(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "bad"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text('{"id":', encoding="utf-8")

            checks = run_doctor(project)
            plugin_check = next(check for check in checks if check.name == "plugin_registry")

            self.assertFalse(plugin_check.ok)
            self.assertEqual(plugin_check.category, "plugins")
            self.assertIn("plugin registry error", plugin_check.detail)

    def test_doctor_security_hygiene_passes_on_clean_project(self) -> None:
        with self.make_project() as tmp:
            checks = run_doctor(Path(tmp))
            security = next(check for check in checks if check.name == "security_hygiene")

            self.assertTrue(security.ok)
            self.assertEqual(security.category, "security")

    def test_doctor_security_hygiene_flags_unsafe_plugins_and_mcp_commands(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            plugin_dir = config_dir / "plugins" / "bad"
            plugin_dir.mkdir(parents=True)
            os.chmod(plugin_dir, 0o777)
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"bad": {"command": "bash", "args": ["-c", "rm -rf /tmp/qa-nope"]}}}),
                encoding="utf-8",
            )

            checks = run_doctor(project)
            security = next(check for check in checks if check.name == "security_hygiene")

            self.assertFalse(security.ok)
            self.assertEqual(security.category, "security")
            self.assertIn("security hygiene issue", security.detail)
            self.assertTrue(any("plugins/bad" in path for path in security.paths))
            self.assertTrue(any(path.endswith("mcp_servers.json") for path in security.paths))

    def test_doctor_security_hygiene_flags_broken_quantagent_symlink(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            link = config_dir / "stale-link"
            try:
                link.symlink_to(config_dir / "missing-target")
            except OSError as exc:
                self.skipTest(f"symlink unsupported: {exc}")

            checks = run_doctor(project)
            security = next(check for check in checks if check.name == "security_hygiene")

            self.assertFalse(security.ok)
            self.assertTrue(any(path.endswith("stale-link") for path in security.paths))


if __name__ == "__main__":
    unittest.main()
