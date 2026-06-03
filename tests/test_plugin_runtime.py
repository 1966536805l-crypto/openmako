from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.plugin_runtime import (
    build_plugin_registry,
    discover_plugin_manifests,
    load_manifest,
    plugin_registry_path,
    plugin_execution_decision,
    render_plugins,
    write_plugin_registry,
)


class PluginRuntimeTest(unittest.TestCase):
    def test_loads_manifest_metadata_without_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin ") as tmp:
            root = Path(tmp)
            plugin = root / "demo"
            plugin.mkdir()
            manifest = plugin / "quantagent.plugin.json"
            manifest.write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "name": "Demo Plugin",
                        "version": "0.1.0",
                        "description": "metadata only",
                        "tools": [{"name": "demo.read", "risk": "low"}],
                        "skills": [{"name": "demo-skill", "triggers": ["demo"]}],
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_manifest(manifest, allowed_root=root)

            self.assertEqual(loaded.plugin_id, "demo")
            self.assertEqual(loaded.tools[0].name, "demo.read")
            self.assertEqual(loaded.skills[0].triggers, ("demo",))

    def test_manifest_records_runtime_policy_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin ") as tmp:
            root = Path(tmp)
            plugin = root / "demo"
            plugin.mkdir()
            manifest = plugin / "quantagent.plugin.json"
            manifest.write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "name": "Demo Plugin",
                        "version": "0.1.0",
                        "startup_hooks": ["before_tool_call"],
                        "tool_permissions": {"mcp.github.*": "ask"},
                        "env_requirements": ["GITHUB_TOKEN"],
                        "compatibility": {"quantagent": ">=0.1.0"},
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_manifest(manifest, allowed_root=root)
            record = loaded.to_record()

            self.assertEqual(loaded.startup_hooks, ("before_tool_call",))
            self.assertEqual(record["tool_permissions"], {"mcp.github.*": "ask"})
            self.assertEqual(loaded.env_requirements, ("GITHUB_TOKEN",))
            self.assertEqual(record["compatibility"]["quantagent"], ">=0.1.0")

    def test_discovers_project_plugins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "demo"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text(
                '{"id":"demo","name":"Demo","version":"0.1.0"}\n',
                encoding="utf-8",
            )

            manifests = discover_plugin_manifests(project)
            rendered = render_plugins(manifests)

            self.assertEqual(len(manifests), 1)
            self.assertIn("demo", rendered)

    def test_registry_records_hash_and_bad_manifest_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            good = project / ".quantagent" / "plugins" / "good"
            bad = project / ".quantagent" / "plugins" / "bad"
            good.mkdir(parents=True)
            bad.mkdir(parents=True)
            manifest = good / "quantagent.plugin.json"
            manifest.write_text('{"id":"good","name":"Good","version":"0.1.0","enabled":false}\n', encoding="utf-8")
            (bad / "quantagent.plugin.json").write_text('{"id":', encoding="utf-8")

            registry = build_plugin_registry(project)

            self.assertEqual(len(registry.plugins), 1)
            self.assertFalse(registry.plugins[0].enabled)
            self.assertEqual(len(registry.plugins[0].manifest_hash), 64)
            self.assertEqual(len(registry.diagnostics), 1)
            self.assertEqual(discover_plugin_manifests(project), [])

    def test_registry_detects_duplicate_plugin_ids_and_can_refresh(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            for name in ("one", "two"):
                plugin = project / ".quantagent" / "plugins" / name
                plugin.mkdir(parents=True)
                (plugin / "quantagent.plugin.json").write_text(
                    '{"id":"dupe","name":"Dupe","version":"0.1.0"}\n',
                    encoding="utf-8",
                )

            registry = build_plugin_registry(project)
            path = write_plugin_registry(project, registry)

            self.assertEqual(path, plugin_registry_path(project))
            self.assertTrue(path.exists())
            self.assertEqual(len(registry.plugins), 1)
            self.assertEqual(len(registry.diagnostics), 1)
            self.assertIn("duplicate plugin id", registry.diagnostics[0].message)

    def test_registry_validates_tool_permission_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "bad-policy"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text(
                json.dumps(
                    {
                        "id": "bad-policy",
                        "name": "Bad Policy",
                        "version": "0.1.0",
                        "tool_permissions": {"shell": "always"},
                    }
                ),
                encoding="utf-8",
            )

            registry = build_plugin_registry(project)

            self.assertTrue(any(item.level == "error" and "allow, ask, or deny" in item.message for item in registry.diagnostics))

    def test_registry_warns_on_missing_env_requirement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "needs-env"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text(
                json.dumps(
                    {
                        "id": "needs-env",
                        "name": "Needs Env",
                        "version": "0.1.0",
                        "env_requirements": ["QUANTAGENT_TEST_MISSING_ENV_SHOULD_NOT_EXIST"],
                    }
                ),
                encoding="utf-8",
            )

            registry = build_plugin_registry(project)

            self.assertTrue(any(item.level == "warn" and "not set" in item.message for item in registry.diagnostics))

    def test_registry_rejects_unknown_startup_hook(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent project ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "bad-hook"
            plugin.mkdir(parents=True)
            (plugin / "quantagent.plugin.json").write_text(
                '{"id":"bad-hook","name":"Bad Hook","version":"0.1.0","startup_hooks":["not_a_hook"]}\n',
                encoding="utf-8",
            )

            registry = build_plugin_registry(project)

            self.assertTrue(any(item.level == "error" and "unknown startup hook" in item.message for item in registry.diagnostics))

    def test_plugin_execution_requires_worktree_isolation_and_owner_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin ") as tmp:
            root = Path(tmp)
            plugin = root / "demo"
            plugin.mkdir()
            manifest = plugin / "quantagent.plugin.json"
            manifest.write_text('{"id":"demo","name":"Demo","version":"0.1.0"}\n', encoding="utf-8")
            loaded = load_manifest(manifest, allowed_root=root)

            no_isolation = plugin_execution_decision(loaded)
            ask = plugin_execution_decision(loaded, isolation="worktree")
            allowed = plugin_execution_decision(loaded, isolation="worktree", owner_approved=True)

            self.assertEqual(no_isolation.action, "deny")
            self.assertEqual(ask.action, "ask")
            self.assertTrue(allowed.allowed)


if __name__ == "__main__":
    unittest.main()
