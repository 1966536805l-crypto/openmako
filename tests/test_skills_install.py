from __future__ import annotations

import tempfile
import unittest
import contextlib
import io
import json
from pathlib import Path

from quantagent.cli import main
from quantagent.skills import (
    PACKAGED_HERMES_SKILLS_ROOT,
    build_skill_snapshot,
    install_skill,
    list_skills,
    load_skill_manifest,
    load_skill_file,
    load_vendored_hermes_skills,
    render_skill_context,
    select_skills,
    skill_manifest_path,
)


class SkillInstallTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent skills project ")

    def make_skill_source(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent skill source ")

    def test_load_skill_file_from_frontmatter(self) -> None:
        with self.make_skill_source() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "---\n"
                "name: p4-review\n"
                "description: Review P4 evidence safely.\n"
                "triggers: p4, tick, evidence\n"
                "---\n"
                "# P4 Review\n\n"
                "Check evidence paths before conclusions.\n",
                encoding="utf-8",
            )

            skill = load_skill_file(path)

            self.assertEqual(skill.name, "p4-review")
            self.assertEqual(skill.description, "Review P4 evidence safely.")
            self.assertEqual(skill.triggers, ("p4", "tick", "evidence"))
            self.assertIn("Check evidence paths", skill.body)

    def test_install_project_skill_and_match_it(self) -> None:
        with self.make_project() as project_tmp, self.make_skill_source() as source_tmp:
            source_dir = Path(source_tmp)
            (source_dir / "SKILL.md").write_text(
                "# Local Capacity Review\n\n"
                "Triggers: liquidity, capacity\n\n"
                "Audit volume assumptions and market impact before approving capacity claims.\n",
                encoding="utf-8",
            )

            installed = install_skill(Path(project_tmp), source_dir)
            manifest = load_skill_manifest(skill_manifest_path(Path(project_tmp), installed.name))
            names = {skill.name for skill in list_skills(Path(project_tmp))}
            selected = select_skills("check liquidity capacity", project=Path(project_tmp))

            self.assertEqual(installed.source, "project")
            self.assertTrue(Path(installed.path).exists())
            self.assertTrue(manifest.approved)
            self.assertEqual(manifest.name, "local-capacity-review")
            self.assertEqual(manifest.source, "project")
            self.assertEqual(len(manifest.body_hash), 16)
            self.assertIn("local-capacity-review", names)
            self.assertEqual(selected[0].name, "local-capacity-review")
            self.assertIn("source=project", render_skill_context(selected))

    def test_install_refuses_overwrite_without_force(self) -> None:
        with self.make_project() as project_tmp, self.make_skill_source() as source_tmp:
            source_dir = Path(source_tmp)
            (source_dir / "SKILL.md").write_text("# Demo Skill\n\nTriggers: demo\n\nBody.\n", encoding="utf-8")

            install_skill(Path(project_tmp), source_dir)
            with self.assertRaises(FileExistsError):
                install_skill(Path(project_tmp), source_dir)

            replaced = install_skill(Path(project_tmp), source_dir, force=True)
            self.assertEqual(replaced.name, "demo-skill")

    def test_skill_snapshot_is_stable_and_records_hashes(self) -> None:
        first = build_skill_snapshot("P4逐笔验证要检查滑点容量和证据hash")
        second = build_skill_snapshot("P4逐笔验证要检查滑点容量和证据hash")

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertIn("p4-tick-validation", first.skill_filter)
        self.assertTrue(first.skills)
        self.assertIn("body_hash", first.skills[0])
        self.assertIn("[p4-tick-validation", first.prompt)

    def test_systematic_debugging_skill_is_selected_for_failures(self) -> None:
        selected = select_skills("测试失败 traceback 需要 debug 最小修复")
        names = [skill.name for skill in selected]

        self.assertIn("systematic-debugging", names)

    def test_tdd_skill_is_selected_for_code_patch_tasks(self) -> None:
        selected = select_skills("改代码 patch 先加测试再实现")
        names = [skill.name for skill in selected]

        self.assertIn("tdd-code-change", names)

    def test_vendored_hermes_skills_are_available(self) -> None:
        skills = load_vendored_hermes_skills()
        names = {skill.name for skill in skills}

        self.assertIn("quant-backtesting", names)
        self.assertIn("subagent-driven-development", names)
        self.assertTrue(all(skill.source == "hermes" for skill in skills))
        self.assertTrue(all(skill.license == "MIT" for skill in skills))

    def test_vendored_hermes_skills_are_packaged_resources(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        setup_py = (project_root / "setup.py").read_text(encoding="utf-8")
        manifest = (project_root / "MANIFEST.in").read_text(encoding="utf-8")

        self.assertTrue((PACKAGED_HERMES_SKILLS_ROOT / "finance" / "quant-backtesting" / "SKILL.md").exists())
        self.assertTrue((PACKAGED_HERMES_SKILLS_ROOT / "software-development" / "subagent-driven-development" / "SKILL.md").exists())
        self.assertIn("vendor/hermes/skills/*/*/SKILL.md", pyproject)
        self.assertIn("vendor/hermes/skills/*/*/SKILL.md", setup_py)
        self.assertIn("recursive-include quantagent/vendor/hermes/skills *.md", manifest)

    def test_chinese_quant_task_selects_hermes_backtesting(self) -> None:
        selected = select_skills("这个策略咋样，帮我回测并检查未来函数和过拟合")
        names = [skill.name for skill in selected]

        self.assertIn("quant-backtesting", names)

    def test_subagent_task_selects_hermes_subagent_workflow(self) -> None:
        selected = select_skills("用子agent并行做两阶段review")
        names = [skill.name for skill in selected]

        self.assertIn("subagent-driven-development", names)

    def test_skill_snapshot_records_hermes_license(self) -> None:
        snapshot = build_skill_snapshot("这个策略咋样，回测一下", limit=5)
        hermes_records = [record for record in snapshot.skills if record["source"] == "hermes"]

        self.assertTrue(hermes_records)
        self.assertEqual(hermes_records[0]["license"], "MIT")

    def test_skills_cli_json_returns_registry_records(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = main(["--no-trust-prompt", "skills", "--match", "debug traceback", "--json"])
        payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertTrue(payload)
        self.assertIn("body_hash", payload[0])
        self.assertIn("approved", payload[0])
        self.assertIn("triggers", payload[0])

    def test_skills_install_json_returns_project_registry_record(self) -> None:
        with self.make_project() as project_tmp, self.make_skill_source() as source_tmp:
            source_dir = Path(source_tmp)
            (source_dir / "SKILL.md").write_text("# Demo Skill\n\nTriggers: demo\n\nBody.\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "skills", "--project", project_tmp, "--install", str(source_dir), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["name"], "demo-skill")
        self.assertEqual(payload["source"], "project")
        self.assertTrue(payload["approved"])
        self.assertEqual(len(payload["body_hash"]), 16)


if __name__ == "__main__":
    unittest.main()
