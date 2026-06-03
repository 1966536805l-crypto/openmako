from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.ecosystem import (
    build_ecosystem_catalog,
    ecosystem_catalog_path,
    filter_ecosystem_catalog,
    render_ecosystem_catalog,
    write_ecosystem_catalog,
)


class EcosystemCatalogTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent ecosystem ")

    def test_catalog_unifies_skills_plugins_tools_mcp_and_upstreams(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            skill_dir = project / ".quantagent" / "skills" / "alpha-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: alpha-skill\ndescription: Alpha workflow skill.\ntriggers: alpha, signal\n---\nBody.\n",
                encoding="utf-8",
            )
            plugin_dir = project / ".quantagent" / "plugins" / "alpha-plugin"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "quantagent.plugin.json").write_text(
                json.dumps(
                    {
                        "id": "alpha-plugin",
                        "name": "Alpha Plugin",
                        "version": "0.1.0",
                        "description": "Alpha plugin package.",
                        "tools": [{"name": "alpha.scan", "description": "Scan alpha signals", "risk": "low"}],
                        "skills": [{"name": "alpha-plugin-skill", "triggers": ["alpha"]}],
                    }
                ),
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir(exist_ok=True)
            (config_dir / "mcp_servers.json").write_text(
                json.dumps({"mcp_servers": {"alpha-mcp": {"command": "python3", "args": ["server.py"], "permissions": {"*": "ask"}}}}),
                encoding="utf-8",
            )

            catalog = build_ecosystem_catalog(project)
            rendered = render_ecosystem_catalog(catalog, limit=200)
            alpha = filter_ecosystem_catalog(catalog, query="alpha")
            path = write_ecosystem_catalog(project, catalog)

            self.assertGreaterEqual(catalog.counts["skill"], 1)
            self.assertGreaterEqual(catalog.counts["tool"], 1)
            self.assertGreaterEqual(catalog.counts["plugin"], 1)
            self.assertGreaterEqual(catalog.counts["mcp"], 1)
            self.assertGreaterEqual(catalog.counts["upstream"], 1)
            self.assertTrue(any(item.kind == "tool" and item.name == "alpha.scan" for item in catalog.items))
            self.assertTrue(any(item.kind == "mcp" and item.name == "alpha-mcp" for item in catalog.items))
            self.assertTrue(any(item.kind == "upstream" and item.name == "openclaw-selected" for item in catalog.items))
            openclaw = next(item for item in catalog.items if item.kind == "upstream" and item.name == "openclaw-selected")
            hermes = next(item for item in catalog.items if item.kind == "upstream" and item.name == "hermes-skills")
            self.assertEqual(openclaw.metadata["copy_policy"], "direct_copy_ok")
            self.assertTrue(openclaw.metadata["license_verified"])
            self.assertTrue(openclaw.metadata["manifest_verified"])
            self.assertEqual(hermes.metadata["copy_policy"], "direct_copy_ok")
            self.assertTrue(hermes.metadata["license_verified"])
            self.assertTrue(hermes.metadata["manifest_verified"])
            self.assertTrue(any(item.kind == "skill" and item.name == "alpha-skill" for item in alpha.items))
            self.assertIn("Mako Ecosystem", rendered)
            self.assertEqual(path, ecosystem_catalog_path(project))
            self.assertTrue(path.exists())

    def test_kind_filter_keeps_counts_for_filtered_items(self) -> None:
        with self.make_project() as tmp:
            catalog = build_ecosystem_catalog(Path(tmp))

            upstream = filter_ecosystem_catalog(catalog, kind="upstream")

            self.assertEqual(set(upstream.counts), {"upstream"})
            self.assertTrue(all(item.kind == "upstream" for item in upstream.items))


if __name__ == "__main__":
    unittest.main()
