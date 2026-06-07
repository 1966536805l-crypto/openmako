from __future__ import annotations

import contextlib
import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.coding_bench import (
    builtin_coding_bench_tasks,
    render_coding_bench_json,
    render_coding_bench_markdown,
    render_coding_bench_stability_json,
    render_coding_bench_stability_markdown,
    run_coding_bench,
    run_coding_bench_stability,
)
from quantagent.skills import install_skill


class CodingBenchTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako coding bench ")

    def test_builtin_tasks_are_30_broken_programming_fixtures(self) -> None:
        tasks = builtin_coding_bench_tasks()
        ids = [task.id for task in tasks]

        self.assertEqual(len(tasks), 30)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(task.files for task in tasks))
        self.assertTrue(all(task.max_iterations == 5 for task in tasks))

    def test_coding_bench_requires_real_agent_command(self) -> None:
        with self.make_project() as tmp:
            with self.assertRaisesRegex(ValueError, "agent_command is required"):
                run_coding_bench(tmp, limit=1)
            with self.assertRaisesRegex(ValueError, "built-in canned"):
                run_coding_bench(tmp, agent="openmako", limit=1)

    def test_coding_bench_rejects_canned_self_agent_command(self) -> None:
        with self.make_project() as tmp:
            with self.assertRaisesRegex(ValueError, "built-in canned"):
                run_coding_bench(tmp, agent_command="openmako-self-agent", limit=1)

    def test_coding_bench_runs_real_agent_command_until_validation_passes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "bench_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "instruction = sys.argv[2]\n"
                "failure = Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "if 'add_numbers' in instruction and 'AssertionError' in failure:\n"
                "    (workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                limit=1,
                keep_workspaces=True,
            )
            payload = json.loads(render_coding_bench_json(run))
            markdown = render_coding_bench_markdown(run)

        self.assertEqual(run.summary()["solved"], 1)
        self.assertEqual(run.summary()["success_rate"], 100.0)
        self.assertEqual(run.results[0].baseline.returncode, 1)
        self.assertEqual(run.results[0].iterations, 1)
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["cheated"], 0)
        self.assertIn("[PASS] add_numbers", markdown)

    def test_coding_bench_run_ids_do_not_collide_for_back_to_back_runs(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "bench_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            command = "{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}"

            first = run_coding_bench(project, agent_command=command, limit=1)
            second = run_coding_bench(project, agent_command=command, limit=1)

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertNotEqual(first.artifact_dir, second.artifact_dir)
        self.assertTrue(first.run_id.startswith("cbench-"))
        self.assertTrue(second.run_id.startswith("cbench-"))

    def test_coding_bench_ignores_cli_agent_result_artifact_for_fast_repairs(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "combine_score_fast_repair",
                                "instruction": "Repair subject.py combine_score so the unit tests pass.",
                                "files": {
                                    "subject.py": "def combine_score(a, b):\n    return a - b\n",
                                    "test_subject.py": (
                                        "import unittest\n"
                                        "from subject import combine_score\n\n"
                                        "class TestSubject(unittest.TestCase):\n"
                                        "    def test_adds_values(self):\n"
                                        "        self.assertEqual(combine_score(2, 3), 5)\n"
                                        "        self.assertEqual(combine_score(-4, 9), 5)\n"
                                    ),
                                },
                                "test_command": "{python} -m unittest test_subject -q",
                                "max_iterations": 1,
                                "timeout_seconds": 30,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            command = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                "--json --max-steps 12 --learning-context off {instruction}"
            )

            run = run_coding_bench(
                project,
                agent_command=command,
                task_file=task_file,
                keep_workspaces=True,
            )
            result = run.results[0]
            workspace = Path(result.workspace)
            root_result_exists = (workspace / "QUANTAGENT_AGENT_V3_LAST.json").exists()
            communication_result_exists = (workspace / "AI_协作交接" / "QUANTAGENT_AGENT_V3_LAST.json").exists()

        self.assertEqual(result.status, "solved")
        self.assertEqual(result.patch_metrics.changed_files, ("subject.py",))
        self.assertEqual(result.patch_metrics.out_of_scope_files, ())
        self.assertEqual(result.patch_metrics.workspace_modified_files, ("subject.py",))
        self.assertFalse(root_result_exists)
        self.assertTrue(communication_result_exists)

    def test_coding_bench_marks_test_file_modification_as_cheated(self) -> None:
        with self.make_project() as tmp:
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
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agent = project / "cheating_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject_test.py').write_text('import unittest\\n\\nclass SubjectTest(unittest.TestCase):\\n    def test_value(self):\\n        self.assertEqual(1, 1)\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                task_file=task_file,
                keep_workspaces=True,
            )
            result = run.results[0]
            markdown = render_coding_bench_markdown(run)

        self.assertEqual(result.status, "cheated")
        self.assertFalse(result.solved)
        self.assertEqual(run.summary()["cheated"], 1)
        self.assertEqual(run.summary()["failed"], 0)
        self.assertIn("subject_test.py", result.message)
        self.assertIn("subject_test.py", result.patch_metrics.out_of_scope_files)
        self.assertIn("[CHEATED] subject_test_guard", markdown)

    def test_coding_bench_marks_test_command_referenced_file_as_cheated(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "nonstandard_verifier_guard",
                                "instruction": "fix value without changing verifier",
                                "files": {
                                    "subject.py": "def value():\n    return 1\n",
                                    "verifier.py": "from subject import value\nif value() != 2:\n    raise AssertionError(value())\n",
                                },
                                "test_command": "{python} verifier.py",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agent = project / "cheating_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'verifier.py').write_text('def check():\\n    return None\\n\\ncheck()\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                task_file=task_file,
                keep_workspaces=True,
            )
            result = run.results[0]

        self.assertEqual(result.status, "cheated")
        self.assertFalse(result.solved)
        self.assertIn("verifier.py", result.message)
        self.assertIn("verifier.py", result.patch_metrics.out_of_scope_files)

    def test_coding_bench_marks_new_helper_file_as_out_of_scope_cheat(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "helper_shadow_guard",
                                "instruction": "fix add_numbers without creating helper files",
                                "files": {
                                    "subject.py": "def add_numbers(a, b):\n    return a - b\n",
                                    "test_subject.py": "import unittest\nfrom subject import add_numbers\n\nclass TestSubject(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add_numbers(2, 3), 5)\n",
                                },
                                "test_command": "{python} -m unittest test_subject -q",
                                "max_iterations": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agent = project / "helper_cheat_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n"
                "(workspace / 'helper.py').write_text('VALUE = 5\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                task_file=task_file,
                keep_workspaces=True,
            )
            result = run.results[0]

        self.assertEqual(result.status, "cheated")
        self.assertFalse(result.solved)
        self.assertIn("helper.py", result.message)
        self.assertEqual(result.patch_metrics.changed_files, ("subject.py",))
        self.assertEqual(result.patch_metrics.out_of_scope_files, ("helper.py",))
        self.assertEqual(result.patch_metrics.workspace_added_files, ("helper.py",))
        self.assertEqual(result.patch_metrics.workspace_modified_files, ("subject.py",))
        self.assertEqual(result.patch_metrics.workspace_deleted_files, ())
        self.assertEqual(run.summary()["cheated"], 1)

    def test_coding_bench_same_step_learning_context_ablation_solves_without_cheating(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task_file = self.write_juno_fold_task_file(project)
            command = (
                "{python} -m quantagent.cli --no-trust-prompt agent --project {workspace} "
                f"--learning-project {shlex.quote(str(project))} --json --max-steps 12 "
                "--learning-context {mode} {instruction}"
            )

            off = run_coding_bench(
                project,
                agent_command=command.replace("{mode}", "off"),
                task_file=task_file,
            )
            on = run_coding_bench(
                project,
                agent_command=command.replace("{mode}", "on"),
                task_file=task_file,
            )
            off_result = off.results[0]
            task_payload = json.loads(task_file.read_text(encoding="utf-8"))

        self.assertEqual(off.summary()["solved"], 0)
        self.assertEqual(off.summary()["total"], 20)
        self.assertEqual(on.summary()["solved"], 20)
        self.assertEqual(on.summary()["total"], 20)
        self.assertTrue(
            all(not key.startswith(".quantagent/skills/") for task in task_payload["tasks"] for key in task["files"]),
            "stage2 CodingBench tasks must not preseed approved skill files",
        )
        self.assertTrue(
            all("skill.json" not in task["files"] for task in task_payload["tasks"]),
            "stage2 CodingBench tasks must not preseed skill manifests",
        )
        self.assertEqual(off_result.status, "failed")
        self.assertTrue(all(result.status == "failed" for result in off.results))
        self.assertTrue(all(result.status == "solved" for result in on.results))
        self.assertTrue(all(result.patch_metrics.changed_files == ("subject.py",) for result in on.results))
        self.assertTrue(all(result.patch_metrics.out_of_scope_files == () for result in on.results))
        self.assertEqual(on.summary()["cheated"], 0)
        self.assertTrue(all(result.attempts[0].agent.returncode == 0 for result in on.results))
        self.assertTrue(all(result.attempts[0].validation.returncode == 0 for result in on.results))

    def test_coding_bench_cli_list_and_run_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "fake_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                list_code = main(["--no-trust-prompt", "coding-bench", "--project", tmp, "--limit", "1", "list", "--json"])
                run_code = main(
                    [
                        "--no-trust-prompt",
                        "coding-bench",
                        "--project",
                        tmp,
                        "--limit",
                        "1",
                        "run",
                        "--agent-command",
                        "{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                        "--json",
                    ]
                )
            output = stdout.getvalue()

        self.assertEqual(list_code, 0)
        self.assertEqual(run_code, 0)
        self.assertIn("add_numbers", output)
        self.assertIn('"success_rate": 100.0', output)

    def write_juno_fold_task_file(self, project: Path) -> Path:
        skill_source_dir = project / "hidden_skill_source"
        skill_source_dir.mkdir()

        def install_hidden_skill(name: str, description: str, triggers: str, source_code: str) -> None:
            function_name = next(line.split("def ", 1)[1].split("(", 1)[0] for line in source_code.splitlines() if line.startswith("def "))
            hint = {"target": "subject.py", "function": function_name, "source": source_code}
            skill_text = (
                "---\n"
                f"name: {name}\n"
                f"description: {description}\n"
                f"triggers: {triggers}\n"
                "---\n"
                f"# {name}\n\n"
                "```openmako-repair\n"
                f"{json.dumps(hint, sort_keys=True)}\n"
                "```\n"
            )
            skill_dir = skill_source_dir / name
            skill_dir.mkdir()
            skill_source = skill_dir / "SKILL.md"
            skill_source.write_text(skill_text, encoding="utf-8")
            install_skill(project, skill_dir)

        hidden_specs = [
            {
                "function": "juno_fold",
                "source": (
                    "def juno_fold(items):\n"
                    "    result = []\n"
                    "    for item in items:\n"
                    "        if result and result[-1][0] == item:\n"
                    "            value, count = result[-1]\n"
                    "            result[-1] = (value, count + 1)\n"
                    "        else:\n"
                    "            result.append((item, 1))\n"
                    "    return result\n"
                ),
                "broken": "def juno_fold(items):\n    return [(item, 1) for item in items]\n",
                "tests": (
                    "import unittest\n"
                    "from subject import juno_fold\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_keeps_adjacent_runs_and_boundaries(self):\n"
                    "        self.assertEqual(juno_fold(['A', 'A', 'B', 'A']), [('A', 2), ('B', 1), ('A', 1)])\n"
                    "    def test_empty(self):\n"
                    "        self.assertEqual(juno_fold([]), [])\n"
                    "    def test_uses_equality_not_hashing(self):\n"
                    "        left = ['x']\n"
                    "        right = ['x']\n"
                    "        self.assertEqual(juno_fold([left, right, ['y']]), [(['x'], 2), (['y'], 1)])\n"
                ),
            },
            {
                "function": "normalize_label",
                "source": (
                    "import re\n\n\n"
                    "def normalize_label(text):\n"
                    "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(text).strip().lower())\n"
                    "    return cleaned.strip(\"-\")\n"
                ),
                "broken": "def normalize_label(text):\n    return str(text)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import normalize_label\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_normalizes_symbols(self):\n"
                    "        self.assertEqual(normalize_label('  Alpha Beta  '), 'alpha-beta')\n"
                    "        self.assertEqual(normalize_label('READY__Now!!'), 'ready-now')\n"
                ),
            },
            {
                "function": "project_fields",
                "source": (
                    "def project_fields(row, keys):\n"
                    "    return {key: row[key] for key in keys if key in row}\n"
                ),
                "broken": "def project_fields(row, keys):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import project_fields\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_projects_known_keys_in_requested_order(self):\n"
                    "        row = {'id': 7, 'name': 'Ada', 'extra': True}\n"
                    "        self.assertEqual(project_fields(row, ['name', 'missing', 'id']), {'name': 'Ada', 'id': 7})\n"
                ),
            },
            {
                "function": "compact_spaces",
                "source": (
                    "def compact_spaces(text):\n"
                    "    return \" \".join(str(text).split())\n"
                ),
                "broken": "def compact_spaces(text):\n    return str(text)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import compact_spaces\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_compacts_all_whitespace(self):\n"
                    "        self.assertEqual(compact_spaces('  Alpha\\n\\tBeta   Gamma '), 'Alpha Beta Gamma')\n"
                ),
            },
            {
                "function": "last_seen_index",
                "source": (
                    "def last_seen_index(items):\n"
                    "    result = {}\n"
                    "    for index, item in enumerate(items):\n"
                    "        result[item] = index\n"
                    "    return result\n"
                ),
                "broken": "def last_seen_index(items):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import last_seen_index\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_keeps_last_position(self):\n"
                    "        self.assertEqual(last_seen_index(['a', 'b', 'a']), {'a': 2, 'b': 1})\n"
                ),
            },
            {
                "function": "split_pairs",
                "source": (
                    "def split_pairs(text):\n"
                    "    result = []\n"
                    "    for chunk in str(text).split(';'):\n"
                    "        if not chunk.strip():\n"
                    "            continue\n"
                    "        key, value = chunk.split('=', 1)\n"
                    "        result.append((key.strip(), value.strip()))\n"
                    "    return result\n"
                ),
                "broken": "def split_pairs(text):\n    return []\n",
                "tests": (
                    "import unittest\n"
                    "from subject import split_pairs\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_splits_semicolon_pairs(self):\n"
                    "        self.assertEqual(split_pairs(' a = 1 ; b= two ; '), [('a', '1'), ('b', 'two')])\n"
                ),
            },
            {
                "function": "group_by_prefix",
                "source": (
                    "def group_by_prefix(items):\n"
                    "    result = {}\n"
                    "    for item in items:\n"
                    "        key = str(item)[:1]\n"
                    "        result.setdefault(key, []).append(item)\n"
                    "    return result\n"
                ),
                "broken": "def group_by_prefix(items):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import group_by_prefix\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_groups_by_first_character(self):\n"
                    "        self.assertEqual(group_by_prefix(['ax', 'by', 'az']), {'a': ['ax', 'az'], 'b': ['by']})\n"
                ),
            },
            {
                "function": "merge_counts",
                "source": (
                    "def merge_counts(left, right):\n"
                    "    result = dict(left)\n"
                    "    for key, value in right.items():\n"
                    "        result[key] = result.get(key, 0) + value\n"
                    "    return result\n"
                ),
                "broken": "def merge_counts(left, right):\n    return dict(left)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import merge_counts\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_merges_and_adds_counts(self):\n"
                    "        self.assertEqual(merge_counts({'a': 2, 'b': 1}, {'a': 3, 'c': 4}), {'a': 5, 'b': 1, 'c': 4})\n"
                ),
            },
            {
                "function": "drop_none_pairs",
                "source": (
                    "def drop_none_pairs(pairs):\n"
                    "    return [(key, value) for key, value in pairs if value is not None]\n"
                ),
                "broken": "def drop_none_pairs(pairs):\n    return list(pairs)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import drop_none_pairs\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_drops_only_none_values(self):\n"
                    "        self.assertEqual(drop_none_pairs([('a', 0), ('b', None), ('c', '')]), [('a', 0), ('c', '')])\n"
                ),
            },
            {
                "function": "rotate_left",
                "source": (
                    "def rotate_left(items, n):\n"
                    "    values = list(items)\n"
                    "    if not values:\n"
                    "        return []\n"
                    "    offset = n % len(values)\n"
                    "    return values[offset:] + values[:offset]\n"
                ),
                "broken": "def rotate_left(items, n):\n    return list(items)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import rotate_left\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_rotates_modulo_length(self):\n"
                    "        self.assertEqual(rotate_left(['a', 'b', 'c', 'd'], 5), ['b', 'c', 'd', 'a'])\n"
                    "        self.assertEqual(rotate_left([], 3), [])\n"
                ),
            },
            {
                "function": "take_until",
                "source": (
                    "def take_until(items, stop):\n"
                    "    result = []\n"
                    "    for item in items:\n"
                    "        if item == stop:\n"
                    "            break\n"
                    "        result.append(item)\n"
                    "    return result\n"
                ),
                "broken": "def take_until(items, stop):\n    return list(items)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import take_until\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_excludes_stop_marker(self):\n"
                    "        self.assertEqual(take_until(['a', 'b', 'stop', 'c'], 'stop'), ['a', 'b'])\n"
                ),
            },
            {
                "function": "expand_ranges",
                "source": (
                    "def expand_ranges(ranges):\n"
                    "    result = []\n"
                    "    for start, end in ranges:\n"
                    "        step = 1 if end >= start else -1\n"
                    "        result.extend(range(start, end + step, step))\n"
                    "    return result\n"
                ),
                "broken": "def expand_ranges(ranges):\n    return []\n",
                "tests": (
                    "import unittest\n"
                    "from subject import expand_ranges\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_expands_inclusive_ranges(self):\n"
                    "        self.assertEqual(expand_ranges([(1, 3), (5, 4)]), [1, 2, 3, 5, 4])\n"
                ),
            },
            {
                "function": "invert_mapping",
                "source": (
                    "def invert_mapping(mapping):\n"
                    "    result = {}\n"
                    "    for key, value in mapping.items():\n"
                    "        result.setdefault(value, []).append(key)\n"
                    "    return result\n"
                ),
                "broken": "def invert_mapping(mapping):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import invert_mapping\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_groups_keys_by_value(self):\n"
                    "        self.assertEqual(invert_mapping({'a': 1, 'b': 1, 'c': 2}), {1: ['a', 'b'], 2: ['c']})\n"
                ),
            },
            {
                "function": "pad_right",
                "source": (
                    "def pad_right(text, width, fill=' '):\n"
                    "    value = str(text)\n"
                    "    if len(fill) != 1:\n"
                    "        raise ValueError('fill must be one character')\n"
                    "    if len(value) >= width:\n"
                    "        return value\n"
                    "    return value + fill * (width - len(value))\n"
                ),
                "broken": "def pad_right(text, width, fill=' '):\n    return str(text)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import pad_right\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_pads_to_width(self):\n"
                    "        self.assertEqual(pad_right('go', 5, '.'), 'go...')\n"
                    "        self.assertEqual(pad_right('long', 2), 'long')\n"
                ),
            },
            {
                "function": "safe_get",
                "source": (
                    "def safe_get(data, path, default=None):\n"
                    "    current = data\n"
                    "    for key in path:\n"
                    "        try:\n"
                    "            current = current[key]\n"
                    "        except (KeyError, IndexError, TypeError):\n"
                    "            return default\n"
                    "    return current\n"
                ),
                "broken": "def safe_get(data, path, default=None):\n    return default\n",
                "tests": (
                    "import unittest\n"
                    "from subject import safe_get\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_walks_dicts_and_lists(self):\n"
                    "        data = {'a': [{'b': 3}]}\n"
                    "        self.assertEqual(safe_get(data, ['a', 0, 'b'], default='x'), 3)\n"
                    "        self.assertEqual(safe_get(data, ['a', 1], default='x'), 'x')\n"
                ),
            },
            {
                "function": "pairwise_deltas",
                "source": (
                    "def pairwise_deltas(values):\n"
                    "    return [values[index + 1] - values[index] for index in range(len(values) - 1)]\n"
                ),
                "broken": "def pairwise_deltas(values):\n    return []\n",
                "tests": (
                    "import unittest\n"
                    "from subject import pairwise_deltas\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_adjacent_deltas(self):\n"
                    "        self.assertEqual(pairwise_deltas([10, 7, 9, 12]), [-3, 2, 3])\n"
                ),
            },
            {
                "function": "trim_dict_values",
                "source": (
                    "def trim_dict_values(row):\n"
                    "    return {key: value.strip() if isinstance(value, str) else value for key, value in row.items()}\n"
                ),
                "broken": "def trim_dict_values(row):\n    return dict(row)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import trim_dict_values\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_trims_only_strings(self):\n"
                    "        self.assertEqual(trim_dict_values({'name': ' Ada ', 'age': 36}), {'name': 'Ada', 'age': 36})\n"
                ),
            },
            {
                "function": "bool_flags",
                "source": (
                    "def bool_flags(names):\n"
                    "    return {str(name): False for name in names}\n"
                ),
                "broken": "def bool_flags(names):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import bool_flags\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_builds_false_flags(self):\n"
                    "        self.assertEqual(bool_flags(['ready', 3]), {'ready': False, '3': False})\n"
                ),
            },
            {
                "function": "zip_dict",
                "source": (
                    "def zip_dict(keys, values):\n"
                    "    return {key: value for key, value in zip(keys, values)}\n"
                ),
                "broken": "def zip_dict(keys, values):\n    return {}\n",
                "tests": (
                    "import unittest\n"
                    "from subject import zip_dict\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_zips_until_shorter_input(self):\n"
                    "        self.assertEqual(zip_dict(['a', 'b', 'c'], [1, 2]), {'a': 1, 'b': 2})\n"
                ),
            },
            {
                "function": "filter_prefix",
                "source": (
                    "def filter_prefix(items, prefix):\n"
                    "    return [item for item in items if str(item).startswith(prefix)]\n"
                ),
                "broken": "def filter_prefix(items, prefix):\n    return list(items)\n",
                "tests": (
                    "import unittest\n"
                    "from subject import filter_prefix\n\n"
                    "class TestSubject(unittest.TestCase):\n"
                    "    def test_filters_by_string_prefix(self):\n"
                    "        self.assertEqual(filter_prefix(['aa', 'ba', 'ab'], 'a'), ['aa', 'ab'])\n"
                ),
            },
        ]
        tasks = []
        for item in hidden_specs:
            function = item["function"]
            skill_name = "hidden-" + function.replace("_", "-") + "-repair"
            install_hidden_skill(
                skill_name,
                f"learned subject.py repair for hidden {function} tasks.",
                f"{function}, {function.replace('_', ' ')}, hidden-{function.replace('_', '-')}",
                item["source"],
            )
            tasks.append(
                {
                    "id": f"hidden_{function}_skill_ablation",
                    "instruction": f"Repair subject.py {function} with learned {function.replace('_', ' ')} contract.",
                    "files": {
                        "subject.py": item["broken"],
                        "test_subject.py": item["tests"],
                    },
                    "test_command": "{python} -m unittest test_subject -q",
                    "max_iterations": 1,
                    "timeout_seconds": 30,
                    "tags": ["coding", "hidden", "learning-context", "non-arithmetic", "skill-ablation"],
                }
            )
        task_file = project / "juno_fold_tasks.json"
        task_file.write_text(
            json.dumps(
                {"tasks": tasks},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return task_file

    def test_coding_bench_stability_repeats_same_agent_and_reports_spread(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "stable_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench_stability(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                limit=1,
                repeats=3,
            )
            payload = json.loads(render_coding_bench_stability_json(run))
            markdown = render_coding_bench_stability_markdown(run)

        self.assertEqual(payload["summary"]["runs"], 3)
        self.assertEqual(payload["summary"]["total_task_attempts"], 3)
        self.assertEqual(payload["summary"]["overall_success_rate"], 100.0)
        self.assertEqual(payload["summary"]["success_rate_spread"], 0.0)
        self.assertEqual(payload["summary"]["unstable_task_count"], 0)
        self.assertIn("CodingBench Stability", markdown)

    def test_coding_bench_stability_flags_flaky_agent_outcomes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            state = project / "state.txt"
            task_file = project / "tasks.json"
            task_file.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "add_numbers",
                                "instruction": "Fix add_numbers so it returns arithmetic sum for ints and floats.",
                                "files": {
                                    "subject.py": "def add_numbers(a, b):\n    return a - b\n",
                                    "test_subject.py": "import unittest\nfrom subject import add_numbers\n\nclass TestSubject(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add_numbers(2, 3), 5)\n",
                                },
                                "max_iterations": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agent = project / "flaky_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "state = Path(sys.argv[4])\n"
                "count = int(state.read_text(encoding='utf-8')) if state.exists() else 0\n"
                "state.write_text(str(count + 1), encoding='utf-8')\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "if count % 2 == 0:\n"
                "    (workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench_stability(
                project,
                agent_command="{python} "
                + shlex.quote(str(agent))
                + " {workspace} {instruction} {failure_file} "
                + shlex.quote(str(state)),
                task_file=task_file,
                repeats=3,
            )
            summary = run.summary()
            markdown = render_coding_bench_stability_markdown(run)

        self.assertEqual(summary["overall_success_rate"], 66.67)
        self.assertEqual(summary["success_rate_spread"], 100.0)
        self.assertEqual(summary["unstable_tasks"], ["add_numbers"])
        self.assertEqual(summary["failure_classes"], {"no_patch": 1})
        self.assertIn("add_numbers", markdown)

    def test_coding_bench_failed_result_classifies_no_patch(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "noop_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                limit=1,
            )
            result = run.results[0]

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "no_patch")
        self.assertEqual(result.patch_metrics.changed_files, ())

    def test_coding_bench_failed_result_classifies_validation_failure_with_changed_files(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "wrong_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a * b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )

            run = run_coding_bench(
                project,
                agent_command="{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                limit=1,
            )
            result = run.results[0]

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "validation_failed")
        self.assertEqual(result.patch_metrics.changed_files, ("subject.py",))

    def test_coding_bench_failed_result_classifies_agent_command_failed(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            run = run_coding_bench(
                project,
                agent_command="{python} -c 'import sys; sys.exit(7)'",
                limit=1,
            )
            result = run.results[0]

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "agent_command_failed")
        self.assertEqual(result.patch_metrics.changed_files, ())

    def test_coding_bench_uses_reported_agent_failure_class_from_json_stdout(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            run = run_coding_bench(
                project,
                agent_command="{python} -c 'import json, sys; print(json.dumps({{\"failure_class\":\"step_limit\", \"status\":\"failed\"}})); sys.exit(1)'",
                limit=1,
            )
            result = run.results[0]

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "step_limit")
        self.assertEqual(result.patch_metrics.changed_files, ())

    def test_coding_bench_uses_reported_failure_class_from_truncated_json_stdout(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            run = run_coding_bench(
                project,
                agent_command="{python} -c 'import json, sys; print(json.dumps(dict(failure_class=\"step_limit\", observations=[\"x\" * 5000]))); sys.exit(1)'",
                limit=1,
            )
            result = run.results[0]

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "step_limit")
        self.assertEqual(result.patch_metrics.changed_files, ())

    def test_coding_bench_cli_repeats_json_outputs_stability_summary(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent = project / "stable_agent.py"
            agent.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "workspace = Path(sys.argv[1])\n"
                "Path(sys.argv[3]).read_text(encoding='utf-8')\n"
                "(workspace / 'subject.py').write_text('def add_numbers(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "coding-bench",
                        "--project",
                        tmp,
                        "--limit",
                        "1",
                        "run",
                        "--agent-command",
                        "{python} " + shlex.quote(str(agent)) + " {workspace} {instruction} {failure_file}",
                        "--repeats",
                        "2",
                        "--json",
                    ]
                )
            output = stdout.getvalue()

        self.assertEqual(code, 0)
        self.assertIn('"repeats": 2', output)
        self.assertIn('"success_rate_spread": 0.0', output)


if __name__ == "__main__":
    unittest.main()
