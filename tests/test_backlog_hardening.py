from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from quantagent.coding_bench import load_coding_bench_tasks, run_coding_bench
from quantagent.eval_harness import EvalCase, build_eval_snapshot, run_eval_cases
from quantagent.plugin_runtime import build_plugin_registry, discover_plugin_manifests, load_manifest, plugin_execution_decision


class BacklogHardeningTest(unittest.TestCase):
    def test_run_eval_cases_rejects_empty_case_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mako eval empty ") as tmp:
            with self.assertRaisesRegex(ValueError, "no eval cases selected"):
                run_eval_cases(Path(tmp), [])

    def test_dirty_snapshot_hashes_untracked_nested_quoted_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mako eval dirty ") as tmp:
            project = Path(tmp)
            self.run_git(project, "init")
            self.run_git(project, "config", "user.email", "test@example.com")
            self.run_git(project, "config", "user.name", "Test User")
            tracked = project / "tracked.txt"
            tracked.write_text("clean\n", encoding="utf-8")
            self.run_git(project, "add", "tracked.txt")
            self.run_git(project, "commit", "-m", "initial")
            dirty_file = project / "untracked dir" / 'quote "file".txt'
            dirty_file.parent.mkdir()
            dirty_file.write_text("alpha\n", encoding="utf-8")
            first = build_eval_snapshot(project)["openmako"]
            dirty_file.write_text("beta\n", encoding="utf-8")
            second = build_eval_snapshot(project)["openmako"]

        self.assertEqual(first["status"], "dirty")
        self.assertTrue(first["dirty_diff_sha256"])
        self.assertNotEqual(first["dirty_diff_sha256"], second["dirty_diff_sha256"])

    def test_coding_bench_task_file_paths_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mako bench paths ") as tmp:
            task_file = Path(tmp) / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "escape",
                                "instruction": "must reject escaped path",
                                "files": {"../escape.py": "BAD = True\n", "test_subject.py": "import unittest\n"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unsafe task file path"):
                load_coding_bench_tasks(task_file)

    def test_coding_bench_protects_nonstandard_test_file_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mako bench guard ") as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "subject_test_guard",
                                "instruction": "fix value without changing tests",
                                "files": {
                                    "subject.py": "def value():\n    return 1\n",
                                    "subject_test.py": "import unittest\nfrom subject import value\n\nclass SubjectTest(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value(), 2)\n",
                                },
                                "test_command": "{python} -m unittest subject_test -q",
                                "max_iterations": 2,
                                "tags": ["phase2", "item15"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agent = project / "cheating_agent.py"
            agent.write_text(
                "from pathlib import Path\n"
                "Path('subject_test.py').write_text('import unittest\\n\\nclass SubjectTest(unittest.TestCase):\\n    def test_value(self):\\n        self.assertEqual(1, 1)\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)),
                task_file=task_file,
                keep_workspaces=True,
            )
            result = run.results[0]

        self.assertEqual(result.status, "cheated")
        self.assertEqual(result.failure_class, "policy")
        self.assertIn("subject_test.py", result.message)
        self.assertIn("subject_test.py", result.patch_metrics.out_of_scope_files)

    def test_incompatible_plugin_is_not_discoverable_or_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mako plugin compat ") as tmp:
            project = Path(tmp)
            plugin = project / ".quantagent" / "plugins" / "future"
            plugin.mkdir(parents=True)
            manifest_path = plugin / "quantagent.plugin.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "id": "future",
                        "name": "Future",
                        "version": "1.0.0",
                        "tools": [{"name": "future.run"}],
                        "tool_permissions": {"future.run": "allow"},
                        "compatibility": {"quantagent": ">9999.0.0"},
                    }
                ),
                encoding="utf-8",
            )

            registry = build_plugin_registry(project)
            discovered = discover_plugin_manifests(project)
            loaded = load_manifest(manifest_path, allowed_root=project / ".quantagent" / "plugins")
            decision = plugin_execution_decision(loaded, isolation="worktree", owner_approved=True, tool="future.run")

        self.assertEqual(registry.plugins, ())
        self.assertEqual(discovered, [])
        self.assertTrue(any(item.level == "error" and "compatibility" in item.message for item in registry.diagnostics))
        self.assertEqual(decision.action, "deny")
        self.assertIn("compatibility", decision.reason)

    def run_git(self, project: Path, *args: str) -> None:
        completed = subprocess.run(["git", "-C", str(project), *args], text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {completed.stderr}")


if __name__ == "__main__":
    unittest.main()
