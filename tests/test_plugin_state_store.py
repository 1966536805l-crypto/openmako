from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from quantagent.plugin_runtime import load_manifest, open_plugin_state_store
from quantagent.plugin_state_store import (
    PluginStateStoreError,
    create_plugin_state_keyed_store,
    plugin_state_db_path,
    probe_plugin_state_store,
    sweep_expired_plugin_state_entries,
)


class PluginStateStoreTest(unittest.TestCase):
    def test_register_lookup_persists_and_scopes_by_plugin_namespace_and_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            project = Path(tmp)
            store = create_plugin_state_keyed_store(project, "demo", namespace="data", max_entries=10)
            store.register("greeting", {"msg": "hello"})

            reopened = create_plugin_state_keyed_store(project, "demo", namespace="data", max_entries=10)
            other_plugin = create_plugin_state_keyed_store(project, "other", namespace="data", max_entries=10)
            other_namespace = create_plugin_state_keyed_store(project, "demo", namespace="other", max_entries=10)

            entries = reopened.entries()

            self.assertTrue(plugin_state_db_path(project).exists())
            self.assertEqual(reopened.lookup("greeting"), {"msg": "hello"})
            self.assertIsNone(other_plugin.lookup("greeting"))
            self.assertIsNone(other_namespace.lookup("greeting"))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].plugin_id, "demo")
            self.assertEqual(entries[0].namespace, "data")
            self.assertEqual(entries[0].key, "greeting")
            self.assertEqual(entries[0].value, {"msg": "hello"})
            self.assertIsInstance(entries[0].created_at, int)

    def test_register_if_absent_consume_delete_and_clear_are_targeted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            project = Path(tmp)
            store = create_plugin_state_keyed_store(project, "demo", namespace="tokens", max_entries=10)
            sibling = create_plugin_state_keyed_store(project, "demo", namespace="sibling", max_entries=10)

            self.assertTrue(store.register_if_absent("one-shot", {"token": "abc"}))
            self.assertFalse(store.register_if_absent("one-shot", {"token": "new"}))
            self.assertEqual(store.lookup("one-shot"), {"token": "abc"})

            self.assertEqual(store.consume("one-shot"), {"token": "abc"})
            self.assertIsNone(store.consume("one-shot"))

            store.register("delete-me", 1)
            self.assertTrue(store.delete("delete-me"))
            self.assertFalse(store.delete("delete-me"))

            store.register("clear-me", 2)
            sibling.register("keep-me", 3)
            self.assertEqual(store.clear(), 1)
            self.assertIsNone(store.lookup("clear-me"))
            self.assertEqual(sibling.lookup("keep-me"), 3)

    def test_ttl_default_override_and_sweep(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            project = Path(tmp)
            store = create_plugin_state_keyed_store(project, "demo", namespace="ttl", max_entries=10, default_ttl_ms=500)

            store.register("default-expiry", {"v": 1})
            store.register("explicit-no-expiry", {"v": 2}, ttl_ms=None)
            store.register("long-expiry", {"v": 3}, ttl_ms=60_000)
            time.sleep(0.65)

            self.assertIsNone(store.lookup("default-expiry"))
            self.assertEqual(store.lookup("explicit-no-expiry"), {"v": 2})
            self.assertEqual(store.lookup("long-expiry"), {"v": 3})
            self.assertGreaterEqual(sweep_expired_plugin_state_entries(project), 1)
            self.assertEqual({entry.key for entry in store.entries()}, {"explicit-no-expiry", "long-expiry"})

    def test_max_entries_evicts_oldest_live_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            project = Path(tmp)
            store = create_plugin_state_keyed_store(project, "demo", namespace="capped", max_entries=2)

            store.register("a", 1)
            store.register("b", 2)
            store.register("c", 3)

            self.assertIsNone(store.lookup("a"))
            self.assertEqual(store.lookup("b"), 2)
            self.assertEqual(store.lookup("c"), 3)
            self.assertEqual([entry.key for entry in store.entries()], ["b", "c"])

    def test_validation_and_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            project = Path(tmp)

            with self.assertRaises(PluginStateStoreError) as invalid_namespace:
                create_plugin_state_keyed_store(project, "demo", namespace="../bad", max_entries=10)
            self.assertEqual(invalid_namespace.exception.code, "PLUGIN_STATE_INVALID_INPUT")

            with self.assertRaises(PluginStateStoreError):
                create_plugin_state_keyed_store(project, "demo", namespace="ok", max_entries=0)

            store = create_plugin_state_keyed_store(project, "demo", namespace="ok", max_entries=10)
            with self.assertRaises(PluginStateStoreError):
                store.register("", {"bad": True})
            with self.assertRaises(PluginStateStoreError):
                store.register("bad-json", {"items": {1, 2, 3}})

            result = probe_plugin_state_store(project)
            rendered = json.dumps(result.to_dict(), sort_keys=True)

            self.assertTrue(result.ok)
            self.assertIn("plugin_state.sqlite", result.db_path)
            self.assertNotIn("probe-value", rendered)

    def test_plugin_runtime_helper_binds_manifest_plugin_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent plugin state ") as tmp:
            root = Path(tmp)
            project = root / "project"
            plugin = root / "plugins" / "demo"
            plugin.mkdir(parents=True)
            manifest = plugin / "quantagent.plugin.json"
            manifest.write_text('{"id":"demo","name":"Demo","version":"0.1.0"}\n', encoding="utf-8")

            loaded = load_manifest(manifest, allowed_root=root / "plugins")
            store = open_plugin_state_store(project, loaded, namespace="runtime", max_entries=10)
            other = create_plugin_state_keyed_store(project, "other", namespace="runtime", max_entries=10)

            store.register("k", {"owner": "demo"})

            self.assertEqual(store.lookup("k"), {"owner": "demo"})
            self.assertIsNone(other.lookup("k"))


if __name__ == "__main__":
    unittest.main()
