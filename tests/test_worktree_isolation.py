from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from quantagent.worktree_isolation import (
    SandboxCapability,
    apply_isolation_review,
    build_sandboxed_command,
    create_isolated_worktree,
    create_isolation_review,
    detect_sandbox_backend,
    list_isolated_worktrees,
    load_isolated_worktree,
    load_isolation_review,
    remove_isolated_worktree,
    render_isolation_review,
    run_in_isolated_worktree,
    sandbox_exec_profile,
)


class WorktreeIsolationTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent isolation ")

    def test_create_isolated_worktree_copies_project_files(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            (project / ".git").mkdir()
            (project / ".git" / "config").write_text("secret\n", encoding="utf-8")

            record = create_isolated_worktree(project, reason="test")
            loaded = load_isolated_worktree(project, record.worktree_id)

            self.assertEqual(loaded.worktree_id, record.worktree_id)
            self.assertTrue((Path(record.workspace_path) / "module.py").exists())
            self.assertFalse((Path(record.workspace_path) / ".git" / "config").exists())
            self.assertEqual(list_isolated_worktrees(project)[0].worktree_id, record.worktree_id)

    def test_isolated_run_does_not_modify_source_project(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = run_in_isolated_worktree(
                project,
                ["python3", "-c", "from pathlib import Path; Path('module.py').write_text('VALUE = 2\\n')"],
                allow_risky=True,
            )

            self.assertTrue(result.ok, result.reason or result.stderr_preview)
            self.assertIn(result.sandbox_backend, {"sandbox-exec", "worktree"})
            self.assertTrue(result.network_policy)
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertEqual((Path(result.worktree.workspace_path) / "module.py").read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_detect_sandbox_backend_prefers_sandbox_exec_when_available(self) -> None:
        with mock.patch("quantagent.worktree_isolation._sandbox_exec_path", return_value="/usr/bin/sandbox-exec"):
            capability = detect_sandbox_backend("auto")

        self.assertEqual(capability.backend, "sandbox-exec")
        self.assertTrue(capability.available)
        self.assertEqual(capability.executable, "/usr/bin/sandbox-exec")
        self.assertEqual(capability.network_policy, "deny")
        self.assertTrue(capability.supports_filesystem_scope)

    def test_detect_sandbox_backend_falls_back_to_worktree(self) -> None:
        with mock.patch("quantagent.worktree_isolation._sandbox_exec_path", return_value=""):
            auto = detect_sandbox_backend("auto")
            explicit = detect_sandbox_backend("sandbox-exec")

        self.assertEqual(auto.backend, "worktree")
        self.assertTrue(auto.available)
        self.assertEqual(auto.network_policy, "not_enforced_deny_requested")
        self.assertEqual(explicit.backend, "sandbox-exec")
        self.assertFalse(explicit.available)

    def test_sandbox_exec_command_wrapper_scopes_writes_and_network(self) -> None:
        with self.make_project() as tmp:
            workspace = Path(tmp) / "workspace"
            capability = SandboxCapability(
                backend="sandbox-exec",
                available=True,
                executable="/usr/bin/sandbox-exec",
                supports_filesystem_scope=True,
                supports_network_policy=True,
            )

            wrapped, profile = build_sandboxed_command(
                ["python3", "-c", "print('ok')"],
                workspace,
                capability=capability,
                network=False,
            )
            network_profile = sandbox_exec_profile(workspace, network=True)

            self.assertEqual(wrapped[:2], ["/usr/bin/sandbox-exec", "-p"])
            self.assertEqual(wrapped[2], profile)
            self.assertEqual(wrapped[-3:], ["python3", "-c", "print('ok')"])
            self.assertIn("(deny default)", profile)
            self.assertIn("(deny network*)", profile)
            self.assertIn("(allow file-read-metadata)", profile)
            self.assertIn("(allow file-write*", profile)
            self.assertIn(str(workspace.resolve(strict=False)), profile)
            self.assertNotIn("(allow network*)", profile)
            self.assertIn("(allow network*)", network_profile)

    def test_worktree_backend_run_records_unenforced_network_policy(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = run_in_isolated_worktree(
                project,
                ["python3", "-c", "from pathlib import Path; Path('module.py').write_text('VALUE = 2\\n')"],
                allow_risky=True,
                sandbox_backend="worktree",
            )

            self.assertTrue(result.ok, result.reason or result.stderr_preview)
            self.assertEqual(result.sandbox_backend, "worktree")
            self.assertEqual(result.network_policy, "not_enforced_deny_requested")
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_sandbox_exec_blocks_absolute_source_project_write_when_available(self) -> None:
        capability = detect_sandbox_backend("sandbox-exec")
        if not capability.available:
            self.skipTest("sandbox-exec is not available")
        with self.make_project() as tmp:
            project = Path(tmp)
            source_file = project / "module.py"
            source_file.write_text("VALUE = 1\n", encoding="utf-8")

            result = run_in_isolated_worktree(
                project,
                [
                    "python3",
                    "-c",
                    f"from pathlib import Path; Path({str(source_file)!r}).write_text('VALUE = 9\\n')",
                ],
                allow_risky=True,
                sandbox_backend="sandbox-exec",
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.sandbox_backend, "sandbox-exec")
            self.assertEqual(result.network_policy, "deny")
            self.assertEqual(source_file.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_remove_isolated_worktree_deletes_copy(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            record = create_isolated_worktree(project)

            removed = remove_isolated_worktree(project, record.worktree_id)

            self.assertEqual(removed.status, "removed")
            self.assertFalse(Path(record.workspace_path).exists())

    def test_review_detects_changes_and_apply_requires_reviewed_flag(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            record = create_isolated_worktree(project)
            (Path(record.workspace_path) / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
            (Path(record.workspace_path) / "new.py").write_text("NEW = True\n", encoding="utf-8")

            review = create_isolation_review(project, record.worktree_id)
            loaded = load_isolation_review(project, review.review_id)
            rendered = render_isolation_review(loaded, include_diff=True)

            self.assertIn("module.py", loaded.changed_paths)
            self.assertIn("new.py", loaded.new_paths)
            self.assertIn("-VALUE = 1", rendered)
            with self.assertRaises(PermissionError):
                apply_isolation_review(project, review.review_id)
            applied = apply_isolation_review(project, review.review_id, reviewed=True)
            self.assertEqual(applied.status, "applied")
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue((project / "new.py").exists())


if __name__ == "__main__":
    unittest.main()
