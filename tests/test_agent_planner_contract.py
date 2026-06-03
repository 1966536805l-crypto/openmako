from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path


class AgentPlannerContractTest(unittest.TestCase):
    """Red tests for Phase 3: planner contract.

    These tests define the expected interface between task text and operations.
    They should FAIL until a planner is implemented that converts natural language
    tasks into structured file operations.
    """

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent planner contract ")

    def install_normalize_label_skill(self, project: Path) -> None:
        from quantagent.skills import install_skill

        source = project / "_skill_source"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-normalize-label-repair\n"
            "description: learned subject.py repair for hidden normalize label tasks.\n"
            "triggers: normalize label, subject.py, tests pass, learned-normalize-label\n"
            "---\n"
            "# Hidden Normalize Label Repair\n\n"
            "Only use for learned-normalize-label subject.py repair tasks.\n\n"
            "```openmako-repair\n"
            "{\"target\":\"subject.py\",\"function\":\"normalize_label\",\"source\":\"import re\\n\\n\\ndef normalize_label(text):\\n    cleaned = re.sub(r\\\"[^a-z0-9]+\\\", \\\"-\\\", str(text).strip().lower())\\n    return cleaned.strip(\\\"-\\\")\\n\"}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_juno_fold_skill(self, project: Path, *, source_override: str | None = None) -> None:
        from quantagent.skills import install_skill

        source_code = source_override or (
            "def juno_fold(items):\n"
            "    result = []\n"
            "    for item in items:\n"
            "        if result and result[-1][0] == item:\n"
            "            value, count = result[-1]\n"
            "            result[-1] = (value, count + 1)\n"
            "        else:\n"
            "            result.append((item, 1))\n"
            "    return result\n"
        )
        source = project / "_juno_skill_source"
        source.mkdir()
        hint = {"target": "subject.py", "function": "juno_fold", "source": source_code}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-juno-fold-repair\n"
            "description: learned subject.py repair for hidden Juno fold tasks.\n"
            "triggers: juno fold, juno_fold, subject.py, skill-ablation, learning-context\n"
            "---\n"
            "# Hidden Juno Fold Repair\n\n"
            "Juno fold means contiguous-run compression using equality only.\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_clean_flip_bundle_skill(self, project: Path, *, source_override: str | None = None) -> None:
        from quantagent.skills import install_skill

        source_code = source_override or (
            "def clean_token(value):\n"
            "    return str(value).strip().lower()\n\n\n"
            "def flip_items(items):\n"
            "    return list(reversed(items))\n"
        )
        source = project / "_clean_flip_bundle_skill_source"
        source.mkdir()
        hint = {"target": "subject.py", "functions": ["clean_token", "flip_items"], "source": source_code}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-clean-flip-bundle-repair\n"
            "description: learned subject.py bundle repair for clean_token and flip_items tasks.\n"
            "triggers: clean_token, flip_items, clean flip bundle, subject.py, learning-context\n"
            "---\n"
            "# Hidden Clean Flip Bundle Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_format_label_multifile_skill(self, project: Path, *, files_override: dict[str, str] | None = None) -> None:
        from quantagent.skills import install_skill

        files = files_override or {
            "subject.py": (
                "from label_helper import normalize_piece\n\n\n"
                "def format_label(text):\n"
                "    return normalize_piece(text)\n"
            ),
            "label_helper.py": (
                "import re\n\n\n"
                "def normalize_piece(value):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            ),
        }
        source = project / "_format_label_multifile_skill_source"
        source.mkdir()
        hint = {"target": "multi_file", "functions": ["format_label"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-format-label-multifile-repair\n"
            "description: learned multi-file repair for format_label and label_helper.\n"
            "triggers: format_label, label helper, multi file repair, subject.py, learning-context\n"
            "---\n"
            "# Hidden Format Label Multi-file Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_package_label_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "compact_label, mako_pkg/labels.py, mako_pkg.labels, learned package label",
    ) -> None:
        from quantagent.skills import install_skill

        files = files_override or {
            "mako_pkg/labels.py": (
                "import re\n\n\n"
                "def compact_label(value):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            )
        }
        source = project / "_package_label_file_bundle_skill_source"
        source.mkdir()
        hint = {"target": "file_bundle", "functions": ["compact_label"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-package-label-file-bundle-repair\n"
            "description: learned package-module repair for mako_pkg.labels compact_label.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden Package Label File Bundle Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_js_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-openclaw-js-parse-finite-number-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js"
        source_code = (
            "function normalizeNumericString(value) {\n"
            "\tconst trimmed = value.trim();\n"
            "\treturn trimmed ? trimmed : void 0;\n"
            "}\n"
            "function parseFiniteNumber(value) {\n"
            "\tif (typeof value === \"number\" && Number.isFinite(value)) return value;\n"
            "\tif (typeof value === \"string\") {\n"
            "\t\tconst parsed = Number.parseFloat(value);\n"
            "\t\tif (Number.isFinite(parsed)) return parsed;\n"
            "\t}\n"
            "}\n"
            "function parseStrictInteger(value) {\n"
            "\tif (typeof value === \"number\") return Number.isSafeInteger(value) ? value : void 0;\n"
            "\tif (typeof value !== \"string\") return;\n"
            "\tconst normalized = normalizeNumericString(value);\n"
            "\tif (!normalized || !/^[+-]?\\d+$/.test(normalized)) return;\n"
            "\tconst parsed = Number(normalized);\n"
            "\treturn Number.isSafeInteger(parsed) ? parsed : void 0;\n"
            "}\n"
            "function parseStrictPositiveInteger(value) {\n"
            "\tconst parsed = parseStrictInteger(value);\n"
            "\treturn parsed !== void 0 && parsed > 0 ? parsed : void 0;\n"
            "}\n"
            "function parseStrictNonNegativeInteger(value) {\n"
            "\tconst parsed = parseStrictInteger(value);\n"
            "\treturn parsed !== void 0 && parsed >= 0 ? parsed : void 0;\n"
            "}\n"
            "export { parseStrictPositiveInteger as i, parseStrictInteger as n, parseStrictNonNegativeInteger as r, parseFiniteNumber as t };\n"
        )
        files = files_override or {target: source_code}
        source = project / "_openclaw_js_file_bundle_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["parseStrictInteger"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-js-file-bundle-repair\n"
            "description: learned OpenClaw JavaScript parse-finite-number repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw JS File Bundle Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_balanced_json_js_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-openclaw-js-balanced-json-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "third_party/openclaw/selected/balanced-json-YUc2rvlg.js"
        source_code = _openclaw_balanced_json_source()
        files = files_override or {target: source_code}
        source = project / "_openclaw_balanced_json_js_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["extractBalancedJsonFragments", "extractBalancedJsonPrefix"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-balanced-json-js-repair\n"
            "description: learned OpenClaw JavaScript balanced-json repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw Balanced JSON JS Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_json_pointer_js_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-openclaw-js-json-pointer-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "third_party/openclaw/selected/json-pointer-BRH9eAOA.js"
        source_code = _openclaw_json_pointer_source()
        files = files_override or {target: source_code}
        source = project / "_openclaw_json_pointer_js_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["decodeJsonPointerToken", "encodeJsonPointerToken", "readJsonPointer"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-json-pointer-js-repair\n"
            "description: learned OpenClaw JavaScript json-pointer repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw JSON Pointer JS Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_combined_js_file_bundle_skill(
        self,
        project: Path,
        *,
        triggers: str = "opaque-openclaw-js-combined-1",
    ) -> None:
        from quantagent.skills import install_skill

        files = {
            "third_party/openclaw/selected/balanced-json-YUc2rvlg.js": _openclaw_balanced_json_source(),
            "third_party/openclaw/selected/json-pointer-BRH9eAOA.js": _openclaw_json_pointer_source(),
        }
        source = project / "_openclaw_combined_js_skill_source"
        source.mkdir()
        hint = {
            "target": "js_file_bundle",
            "functions": [
                "decodeJsonPointerToken",
                "encodeJsonPointerToken",
                "extractBalancedJsonFragments",
                "extractBalancedJsonPrefix",
                "readJsonPointer",
            ],
            "files": files,
        }
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-combined-js-repair\n"
            "description: learned OpenClaw JavaScript multi-file repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw Combined JS Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_command_poll_js_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-openclaw-js-command-poll-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"
        files = files_override or {target: _openclaw_command_poll_source()}
        source = project / "_openclaw_command_poll_js_skill_source"
        source.mkdir()
        hint = {
            "target": "js_file_bundle",
            "functions": ["calculateBackoffMs", "pruneStaleCommandPolls", "recordCommandPoll", "resetCommandPollCount"],
            "files": files,
        }
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-command-poll-js-repair\n"
            "description: learned OpenClaw JavaScript command-poll backoff repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw Command Poll JS Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_openclaw_async_lock_js_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-openclaw-js-async-lock-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "third_party/openclaw/selected/async-lock-BcLS4KOc.js"
        files = files_override or {target: _openclaw_async_lock_source()}
        source = project / "_openclaw_async_lock_js_skill_source"
        source.mkdir()
        hint = {
            "target": "js_file_bundle",
            "functions": ["createAsyncLock"],
            "files": files,
        }
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-openclaw-async-lock-js-repair\n"
            "description: learned OpenClaw JavaScript async-lock repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden OpenClaw Async Lock JS Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_mako_js_labels_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-mako-js-labels-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "mako_js/labels.js"
        files = files_override or {target: _mako_js_labels_source()}
        source = project / "_mako_js_labels_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["compactLabel", "labelKey"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-mako-js-labels-repair\n"
            "description: learned package-level JavaScript labels repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden Mako JS Labels Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_mako_js_async_records_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-mako-js-async-records-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "mako_js/async_records.js"
        files = files_override or {target: _mako_js_async_records_source()}
        source = project / "_mako_js_async_records_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["loadUserSummaries", "normalizeUserId", "summarizeUser"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-mako-js-async-records-repair\n"
            "description: learned package-level async JavaScript records repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden Mako JS Async Records Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_mako_js_io_boundary_file_bundle_skill(
        self,
        project: Path,
        *,
        files_override: dict[str, str] | None = None,
        triggers: str = "opaque-mako-js-io-boundary-1",
    ) -> None:
        from quantagent.skills import install_skill

        target = "mako_js/io_boundary.js"
        files = files_override or {target: _mako_js_io_boundary_source()}
        source = project / "_mako_js_io_boundary_skill_source"
        source.mkdir()
        hint = {"target": "js_file_bundle", "functions": ["scanWorkspaceManifest"], "files": files}
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-mako-js-io-boundary-repair\n"
            "description: learned package-level mocked I/O JavaScript repair.\n"
            f"triggers: {triggers}\n"
            "---\n"
            "# Hidden Mako JS I/O Boundary Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_tool_name_function_bundle_skill(self, project: Path) -> None:
        from quantagent.skills import install_skill

        replacement = (
            "def validate_tool_name(name):\n"
            "    warnings = []\n"
            "    if not name:\n"
            "        return ToolNameValidationResult(is_valid=False, warnings=[\"Tool name cannot be empty\"])\n"
            "    if not TOOL_NAME_REGEX.match(name):\n"
            "        warnings.append(\"Tool name contains invalid characters\")\n"
            "        return ToolNameValidationResult(is_valid=False, warnings=warnings)\n"
            "    return ToolNameValidationResult(is_valid=True, warnings=warnings)\n"
        )
        source = project / "_tool_name_function_bundle_skill_source"
        source.mkdir()
        hint = {
            "target": "file_function_bundle",
            "functions": ["validate_tool_name"],
            "files": {"mcp/shared/tool_name_validation.py": {"validate_tool_name": replacement}},
        }
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-tool-name-function-bundle-repair\n"
            "description: learned function-level repair for a complex MCP tool-name module.\n"
            "triggers: opaque-upstream-function-contract-1\n"
            "---\n"
            "# Hidden Tool Name Function Bundle Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def install_complex_package_function_bundle_skill(self, project: Path) -> None:
        from quantagent.skills import install_skill

        files = {
            "mcp/shared/tool_name_validation.py": (
                "def is_valid_tool_name(name):\n"
                "    value = str(name).strip()\n"
                "    return bool(value) and len(value) <= MAX_TOOL_NAME_LENGTH and TOOL_NAME_PATTERN.fullmatch(value) is not None\n"
            )
        }
        source = project / "_complex_package_function_bundle_skill_source"
        source.mkdir()
        hint = {
            "target": "file_bundle",
            "mode": "replace_functions",
            "functions": ["is_valid_tool_name"],
            "files": files,
        }
        (source / "SKILL.md").write_text(
            "---\n"
            "name: hidden-complex-package-function-repair\n"
            "description: learned function-level repair for a complex upstream package module.\n"
            "triggers: opaque-complex-package-contract-1\n"
            "---\n"
            "# Hidden Complex Package Function Repair\n\n"
            "```openmako-repair\n"
            f"{json.dumps(hint, sort_keys=True)}\n"
            "```\n",
            encoding="utf-8",
        )
        install_skill(project, source)

    def write_juno_fold_project(self, project: Path) -> None:
        (project / "subject.py").write_text("def juno_fold(items):\n    return [(item, 1) for item in items]\n", encoding="utf-8")
        (project / "test_subject.py").write_text(
            "import unittest\nfrom subject import juno_fold\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_keeps_adjacent_runs_and_boundaries(self):\n"
            "        self.assertEqual(juno_fold(['A', 'A', 'B', 'A']), [('A', 2), ('B', 1), ('A', 1)])\n"
            "    def test_empty(self):\n"
            "        self.assertEqual(juno_fold([]), [])\n"
            "    def test_uses_equality_not_hashing(self):\n"
            "        left = ['x']\n"
            "        right = ['x']\n"
            "        self.assertEqual(juno_fold([left, right, ['y']]), [(['x'], 2), (['y'], 1)])\n",
            encoding="utf-8",
        )

    def write_clean_flip_project(self, project: Path) -> None:
        (project / "subject.py").write_text(
            "def clean_token(value):\n"
            "    return str(value)\n\n\n"
            "def flip_items(items):\n"
            "    return list(items)\n",
            encoding="utf-8",
        )
        (project / "test_subject.py").write_text(
            "import unittest\nfrom subject import clean_token, flip_items\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_clean_token(self):\n"
            "        self.assertEqual(clean_token('  Alpha  '), 'alpha')\n"
            "    def test_flip_items(self):\n"
            "        self.assertEqual(flip_items(['a', 'b']), ['b', 'a'])\n",
            encoding="utf-8",
        )

    def write_format_label_multifile_project(self, project: Path) -> None:
        (project / "subject.py").write_text(
            "from label_helper import normalize_piece\n\n\n"
            "def format_label(text):\n"
            "    return str(text)\n",
            encoding="utf-8",
        )
        (project / "label_helper.py").write_text(
            "def normalize_piece(value):\n"
            "    return str(value)\n",
            encoding="utf-8",
        )
        (project / "test_subject.py").write_text(
            "import unittest\nfrom subject import format_label\n\n"
            "class TestSubject(unittest.TestCase):\n"
            "    def test_slug_style(self):\n"
            "        self.assertEqual(format_label('  Alpha Beta!!  '), 'alpha-beta')\n"
            "    def test_symbols(self):\n"
            "        self.assertEqual(format_label('READY__Now'), 'ready-now')\n",
            encoding="utf-8",
        )

    def write_package_label_project(self, project: Path) -> None:
        (project / "mako_pkg").mkdir()
        (project / "mako_pkg" / "__init__.py").write_text("", encoding="utf-8")
        (project / "mako_pkg" / "labels.py").write_text(
            "def compact_label(value):\n"
            "    return str(value)\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_labels.py").write_text(
            "import unittest\nfrom mako_pkg.labels import compact_label\n\n"
            "class TestLabels(unittest.TestCase):\n"
            "    def test_slug_style(self):\n"
            "        self.assertEqual(compact_label('  Alpha Beta!!  '), 'alpha-beta')\n"
            "    def test_symbols(self):\n"
            "        self.assertEqual(compact_label('READY__Now'), 'ready-now')\n",
            encoding="utf-8",
        )

    def write_complex_package_label_project(self, project: Path) -> None:
        (project / "mako_pkg").mkdir()
        (project / "mako_pkg" / "__init__.py").write_text("", encoding="utf-8")
        (project / "mako_pkg" / "labels.py").write_text(
            "import re\n\n\n"
            "LABEL_KIND = 'label'\n\n\n"
            "class LabelPolicy:\n"
            "    def __init__(self, prefix=LABEL_KIND):\n"
            "        self.prefix = prefix\n\n\n"
            "def compact_label(value):\n"
            "    return str(value)\n\n\n"
            "def describe_label(value):\n"
            "    return f'{LABEL_KIND}:{value}'\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_labels.py").write_text(
            "import unittest\nfrom mako_pkg.labels import compact_label\n\n"
            "class TestLabels(unittest.TestCase):\n"
            "    def test_slug_style(self):\n"
            "        self.assertEqual(compact_label('  Alpha Beta!!  '), 'alpha-beta')\n"
            "    def test_symbols(self):\n"
            "        self.assertEqual(compact_label('READY__Now'), 'ready-now')\n",
            encoding="utf-8",
        )

    def write_tool_name_project(self, project: Path) -> None:
        module = project / "mcp" / "shared"
        module.mkdir(parents=True)
        (project / "mcp" / "__init__.py").write_text("", encoding="utf-8")
        (module / "__init__.py").write_text("", encoding="utf-8")
        (module / "tool_name_validation.py").write_text(
            "import re\n"
            "from dataclasses import dataclass, field\n\n\n"
            "TOOL_NAME_REGEX = re.compile(r\"^[A-Za-z0-9._-]{1,128}$\")\n\n\n"
            "@dataclass\n"
            "class ToolNameValidationResult:\n"
            "    is_valid: bool\n"
            "    warnings: list[str] = field(default_factory=list)\n\n\n"
            "def validate_tool_name(name):\n"
            "    return ToolNameValidationResult(is_valid=True, warnings=[])\n\n\n"
            "def issue_tool_name_warning(name, warnings):\n"
            "    return bool(name) and bool(warnings)\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_tool_name_validation.py").write_text(
            "import unittest\nfrom mcp.shared.tool_name_validation import validate_tool_name, issue_tool_name_warning\n\n"
            "class TestToolNameValidation(unittest.TestCase):\n"
            "    def test_empty_name_is_invalid(self):\n"
            "        result = validate_tool_name('')\n"
            "        self.assertFalse(result.is_valid)\n"
            "        self.assertEqual(result.warnings, ['Tool name cannot be empty'])\n"
            "    def test_invalid_characters(self):\n"
            "        result = validate_tool_name('bad name')\n"
            "        self.assertFalse(result.is_valid)\n"
            "    def test_unrelated_function_stays_available(self):\n"
            "        self.assertTrue(issue_tool_name_warning('bad name', ['warning']))\n",
            encoding="utf-8",
        )

    def write_complex_package_project(self, project: Path) -> None:
        module_dir = project / "mcp" / "shared"
        module_dir.mkdir(parents=True)
        (project / "mcp" / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "tool_name_validation.py").write_text(
            "import re\n\n"
            "MAX_TOOL_NAME_LENGTH = 64\n"
            "TOOL_NAME_PATTERN = re.compile(r\"^[A-Za-z0-9_-]+$\")\n\n\n"
            "def normalize_tool_name(value):\n"
            "    return str(value).strip()\n\n\n"
            "def is_valid_tool_name(name):\n"
            "    return bool(name)\n\n\n"
            "class ToolNamePolicy:\n"
            "    def __init__(self, max_length=MAX_TOOL_NAME_LENGTH):\n"
            "        self.max_length = max_length\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_tool_name_validation.py").write_text(
            "import unittest\n"
            "from mcp.shared.tool_name_validation import is_valid_tool_name\n\n"
            "class TestToolNameValidation(unittest.TestCase):\n"
            "    def test_accepts_safe_names(self):\n"
            "        self.assertTrue(is_valid_tool_name('alpha_1'))\n"
            "    def test_rejects_spaces_symbols_and_empty(self):\n"
            "        self.assertFalse(is_valid_tool_name('bad name'))\n"
            "        self.assertFalse(is_valid_tool_name(''))\n"
            "        self.assertFalse(is_valid_tool_name('x' * 65))\n",
            encoding="utf-8",
        )

    def write_pandera_scale_project(self, project: Path) -> None:
        module_dir = project / "pandera"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "dtypes.py").write_text(
            "import decimal\n\n"
            "SUPPORTED_SCALES = (0, 1, 2, 3, 4)\n\n\n"
            "def stable_decimal(value):\n"
            "    return decimal.Decimal(str(value))\n\n\n"
            "def _scale_to_exp(scale: int) -> decimal.Decimal:\n"
            "    return decimal.Decimal('1')\n\n\n"
            "class DecimalPolicy:\n"
            "    name = 'fixed'\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_dtypes.py").write_text(
            "import decimal\n"
            "import unittest\n"
            "from pandera.dtypes import _scale_to_exp\n\n"
            "class TestDTypes(unittest.TestCase):\n"
            "    def test_scale_two(self):\n"
            "        self.assertEqual(_scale_to_exp(2), decimal.Decimal('0.01'))\n"
            "    def test_scale_four(self):\n"
            "        self.assertEqual(_scale_to_exp(4), decimal.Decimal('0.0001'))\n",
            encoding="utf-8",
        )

    def write_pandera_dtype_predicate_project(self, project: Path) -> None:
        module_dir = project / "pandera"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "dtypes.py").write_text(
            "from __future__ import annotations\n\n"
            "from typing import Union\n\n\n"
            "class DataType:\n"
            "    pass\n\n\n"
            "class Bool(DataType):\n"
            "    pass\n\n\n"
            "class String(DataType):\n"
            "    pass\n\n\n"
            "class Int(DataType):\n"
            "    pass\n\n\n"
            "def is_subdtype(arg1, arg2) -> bool:\n"
            "    arg1_cls = arg1 if isinstance(arg1, type) else arg1.__class__\n"
            "    arg2_cls = arg2 if isinstance(arg2, type) else arg2.__class__\n"
            "    return issubclass(arg1_cls, arg2_cls)\n\n\n"
            "def is_bool(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n"
            "    return False\n\n\n"
            "def is_string(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n"
            "    return is_subdtype(pandera_dtype, String)\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_dtypes.py").write_text(
            "import unittest\n"
            "import pandera.dtypes as dtypes\n"
            "from pandera.dtypes import is_bool\n\n"
            "class TestDTypes(unittest.TestCase):\n"
            "    def test_bool_predicate_accepts_bool_class_and_instance(self):\n"
            "        self.assertTrue(is_bool(dtypes.Bool))\n"
            "        self.assertTrue(is_bool(dtypes.Bool()))\n"
            "    def test_bool_predicate_rejects_other_dtypes(self):\n"
            "        self.assertFalse(is_bool(dtypes.String))\n"
            "        self.assertFalse(is_bool(dtypes.Int()))\n",
            encoding="utf-8",
        )

    def write_result_format_project(self, project: Path) -> None:
        module_dir = project / "great_expectations" / "expectations"
        module_dir.mkdir(parents=True)
        (project / "great_expectations" / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "expectation_configuration.py").write_text(
            "from typing import Union\n\n\n"
            "DEFAULT_RESULT_FORMAT = 'BASIC'\n\n\n"
            "def parse_result_format(result_format: Union[str, dict]) -> dict:\n"
            "    return {'result_format': result_format}\n\n\n"
            "class ExpectationConfiguration:\n"
            "    pass\n\n\n"
            "class ExpectationConfigurationSchema:\n"
            "    pass\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_expectation_configuration.py").write_text(
            "import unittest\n"
            "from great_expectations.expectations.expectation_configuration import parse_result_format\n\n"
            "class TestResultFormat(unittest.TestCase):\n"
            "    def test_string_result_format(self):\n"
            "        self.assertEqual(parse_result_format('SUMMARY'), {\n"
            "            'result_format': 'SUMMARY',\n"
            "            'partial_unexpected_count': 20,\n"
            "            'include_unexpected_rows': False,\n"
            "            'map_expectation_unexpected_rows_as_dict': False,\n"
            "        })\n"
            "    def test_dict_result_format_gets_defaults(self):\n"
            "        self.assertEqual(parse_result_format({'result_format': 'COMPLETE'}), {\n"
            "            'result_format': 'COMPLETE',\n"
            "            'partial_unexpected_count': 20,\n"
            "            'include_unexpected_rows': False,\n"
            "            'map_expectation_unexpected_rows_as_dict': False,\n"
            "        })\n"
            "    def test_include_unexpected_rows_requires_explicit_result_format(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            parse_result_format({'include_unexpected_rows': True})\n",
            encoding="utf-8",
        )

    def write_aider_color_project(self, project: Path) -> None:
        module_dir = project / "aider"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("", encoding="utf-8")
        (module_dir / "repomap.py").write_text(
            "import colorsys\n"
            "import random\n\n\n"
            "CACHE_VERSION = 3\n\n\n"
            "def get_random_color():\n"
            "    return '#000000'\n\n\n"
            "def find_src_files(directory):\n"
            "    return [directory]\n\n\n"
            "class RepoMap:\n"
            "    pass\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (project / "tests" / "test_repomap_color.py").write_text(
            "import unittest\n"
            "import aider.repomap as repomap\n"
            "from aider.repomap import get_random_color\n\n"
            "class TestRepoMapColor(unittest.TestCase):\n"
            "    def test_zero_hue_is_dark_red(self):\n"
            "        repomap.random.random = lambda: 0.0\n"
            "        self.assertEqual(get_random_color(), '#bf0000')\n"
            "    def test_green_hue_is_formatted_hex(self):\n"
            "        repomap.random.random = lambda: 0.3333333333333333\n"
            "        self.assertEqual(get_random_color(), '#00bf00')\n",
            encoding="utf-8",
        )

    def write_openclaw_parse_strict_integer_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "parse-finite-number-C3Woj8eC.js").write_text(
            "function normalizeNumericString(value) {\n"
            "\tconst trimmed = value.trim();\n"
            "\treturn trimmed ? trimmed : void 0;\n"
            "}\n"
            "function parseFiniteNumber(value) {\n"
            "\tif (typeof value === \"number\" && Number.isFinite(value)) return value;\n"
            "\tif (typeof value === \"string\") {\n"
            "\t\tconst parsed = Number.parseFloat(value);\n"
            "\t\tif (Number.isFinite(parsed)) return parsed;\n"
            "\t}\n"
            "}\n"
            "function parseStrictInteger(value) {\n"
            "\tif (typeof value === \"number\") return value;\n"
            "\tif (typeof value === \"string\") return Number.parseInt(value, 10);\n"
            "}\n"
            "function parseStrictPositiveInteger(value) {\n"
            "\treturn parseStrictInteger(value);\n"
            "}\n"
            "function parseStrictNonNegativeInteger(value) {\n"
            "\treturn parseStrictInteger(value);\n"
            "}\n"
            "export { parseStrictPositiveInteger as i, parseStrictInteger as n, parseStrictNonNegativeInteger as r, parseFiniteNumber as t };\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_parse_finite_number.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { n as parseStrictInteger, i as parseStrictPositiveInteger, r as parseStrictNonNegativeInteger } from '../third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js';\n\n"
            "assert.equal(parseStrictInteger(' 42 '), 42);\n"
            "assert.equal(parseStrictInteger('+17'), 17);\n"
            "assert.equal(parseStrictInteger('42px'), undefined);\n"
            "assert.equal(parseStrictInteger(Number.MAX_SAFE_INTEGER + 1), undefined);\n"
            "assert.equal(parseStrictPositiveInteger('7'), 7);\n"
            "assert.equal(parseStrictPositiveInteger('0'), undefined);\n"
            "assert.equal(parseStrictNonNegativeInteger('0'), 0);\n",
            encoding="utf-8",
        )

    def write_openclaw_parse_timeout_package_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "parse-timeout-91AFhn8L.js").write_text(
            _broken_openclaw_parse_timeout_source(_openclaw_parse_timeout_source()),
            encoding="utf-8",
        )
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/openclaw-timeout-fixture",
                    "type": "module",
                    "exports": {"./timeout": "./src/timeout.js"},
                    "scripts": {"test": "node tests/test_parse_timeout.mjs"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (project / "src").mkdir()
        (project / "src" / "timeout.js").write_text(
            "export { n as parseTimeoutMsWithFallback, t as parseTimeoutMs } from \"../third_party/openclaw/selected/parse-timeout-91AFhn8L.js\";\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_parse_timeout.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { parseTimeoutMs, parseTimeoutMsWithFallback } from '../src/timeout.js';\n\n"
            "assert.equal(parseTimeoutMs(' 2500ms '), 2500);\n"
            "assert.equal(parseTimeoutMs(15n), 15);\n"
            "assert.equal(parseTimeoutMs({ value: 1 }), undefined);\n"
            "assert.equal(parseTimeoutMsWithFallback(undefined, 30000), 30000);\n"
            "assert.equal(parseTimeoutMsWithFallback(' 1200 ', 30000), 1200);\n"
            "assert.throws(() => parseTimeoutMsWithFallback('0', 30000), /Invalid --timeout/);\n"
            "assert.throws(() => parseTimeoutMsWithFallback({}, 30000, { invalidType: 'error' }), /Invalid --timeout/);\n",
            encoding="utf-8",
        )

    def write_openclaw_arg_split_package_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "arg-split-DM7vx6uc.js").write_text(
            _broken_openclaw_arg_split_source(_openclaw_arg_split_source()),
            encoding="utf-8",
        )
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/openclaw-arg-split-fixture",
                    "type": "module",
                    "exports": {"./args": "./src/args.js"},
                    "scripts": {"test": "node tests/test_arg_split.mjs"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (project / "src").mkdir()
        (project / "src" / "args.js").write_text(
            "export { t as splitArgsPreservingQuotes } from \"../third_party/openclaw/selected/arg-split-DM7vx6uc.js\";\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_arg_split.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { splitArgsPreservingQuotes } from '../src/args.js';\n\n"
            "assert.deepEqual(splitArgsPreservingQuotes('run \"hello world\" now'), ['run', 'hello world', 'now']);\n"
            "assert.deepEqual(splitArgsPreservingQuotes('cmd a\\\\ b \"c d\"', { escapeMode: 'backslash' }), ['cmd', 'a b', 'c d']);\n"
            "assert.deepEqual(splitArgsPreservingQuotes(\"deploy 'west zone'\", { quoteChars: [\"'\"] }), ['deploy', 'west zone']);\n",
            encoding="utf-8",
        )

    def write_openclaw_balanced_json_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "balanced-json-YUc2rvlg.js").write_text(
            _broken_openclaw_balanced_json_source(),
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_balanced_json.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n\n"
            "assert.deepEqual(extractBalancedJsonPrefix('xx {\"a\":[1,{\"b\":\"}\"}]} tail'), { json: '{\"a\":[1,{\"b\":\"}\"}]}', startIndex: 3, endIndex: 21 });\n"
            "assert.deepEqual(extractBalancedJsonPrefix('skip [1,{\"x\":\"[\"}] rest', { openers: ['['] }), { json: '[1,{\"x\":\"[\"}]', startIndex: 5, endIndex: 17 });\n"
            "assert.deepEqual(extractBalancedJsonFragments('a {\"a\":1} b [2,{\"c\":3}]'), [\n"
            "  { json: '{\"a\":1}', startIndex: 2, endIndex: 8 },\n"
            "  { json: '[2,{\"c\":3}]', startIndex: 12, endIndex: 22 },\n"
            "]);\n",
            encoding="utf-8",
        )

    def write_openclaw_json_pointer_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "json-pointer-BRH9eAOA.js").write_text(
            _broken_openclaw_json_pointer_source(),
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_json_pointer.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
            "const root = {\n"
            "  providers: { openai: { 'api/key': 'sk-live', 'tilde~name': 'escaped' } },\n"
            "  list: [{ name: 'zero' }, { name: 'one' }]\n"
            "};\n"
            "assert.equal(readJsonPointer(root, '/providers/openai/api~1key'), 'sk-live');\n"
            "assert.equal(readJsonPointer(root, '/providers/openai/tilde~0name'), 'escaped');\n"
            "assert.deepEqual(readJsonPointer(root, '/list/1'), { name: 'one' });\n"
            "assert.equal(readJsonPointer(root, '/list/5', { onMissing: 'undefined' }), undefined);\n"
            "assert.equal(readJsonPointer(root, 'providers/openai', { onMissing: 'undefined' }), undefined);\n"
            "assert.equal(encodeJsonPointerToken('api/key~prod'), 'api~1key~0prod');\n",
            encoding="utf-8",
        )

    def write_openclaw_combined_js_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "balanced-json-YUc2rvlg.js").write_text(
            _broken_openclaw_balanced_json_source(),
            encoding="utf-8",
        )
        (module_dir / "json-pointer-BRH9eAOA.js").write_text(
            _broken_openclaw_json_pointer_source(),
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_combined_openclaw_js.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { n as extractBalancedJsonPrefix, t as extractBalancedJsonFragments } from '../third_party/openclaw/selected/balanced-json-YUc2rvlg.js';\n"
            "import { n as readJsonPointer, t as encodeJsonPointerToken } from '../third_party/openclaw/selected/json-pointer-BRH9eAOA.js';\n\n"
            "assert.deepEqual(extractBalancedJsonPrefix('xx {\"a\":[1,{\"b\":\"}\"}]} tail'), { json: '{\"a\":[1,{\"b\":\"}\"}]}', startIndex: 3, endIndex: 21 });\n"
            "assert.deepEqual(extractBalancedJsonFragments('a {\"a\":1} b [2,{\"c\":3}]'), [\n"
            "  { json: '{\"a\":1}', startIndex: 2, endIndex: 8 },\n"
            "  { json: '[2,{\"c\":3}]', startIndex: 12, endIndex: 22 },\n"
            "]);\n"
            "const root = { providers: { openai: { 'api/key': 'sk-live', 'tilde~name': 'escaped' } } };\n"
            "assert.equal(readJsonPointer(root, '/providers/openai/api~1key'), 'sk-live');\n"
            "assert.equal(readJsonPointer(root, '/providers/openai/tilde~0name'), 'escaped');\n"
            "assert.equal(encodeJsonPointerToken('api/key~prod'), 'api~1key~0prod');\n",
            encoding="utf-8",
        )

    def write_openclaw_command_poll_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "command-poll-backoff-DmjJeZIx.js").write_text(
            _broken_openclaw_command_poll_source(),
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_command_poll_backoff.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { n as recordCommandPoll, r as resetCommandPollCount, t as pruneStaleCommandPolls } from '../third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js';\n\n"
            "const originalNow = Date.now;\n"
            "Date.now = () => 1000;\n"
            "try {\n"
            "  const state = {};\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 5000);\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 10000);\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 30000);\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 60000);\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', false), 60000);\n"
            "  assert.equal(state.commandPollCounts.get('cmd-a').count, 4);\n"
            "  assert.equal(recordCommandPoll(state, 'cmd-a', true), 5000);\n"
            "  assert.equal(state.commandPollCounts.get('cmd-a').count, 0);\n"
            "  resetCommandPollCount(state, 'cmd-a');\n"
            "  assert.equal(state.commandPollCounts.has('cmd-a'), false);\n"
            "  state.commandPollCounts.set('old', { count: 3, lastPollAt: 0 });\n"
            "  state.commandPollCounts.set('fresh', { count: 1, lastPollAt: 999 });\n"
            "  pruneStaleCommandPolls(state, 500);\n"
            "  assert.equal(state.commandPollCounts.has('old'), false);\n"
            "  assert.equal(state.commandPollCounts.has('fresh'), true);\n"
            "} finally {\n"
            "  Date.now = originalNow;\n"
            "}\n",
            encoding="utf-8",
        )

    def write_openclaw_async_lock_project(self, project: Path) -> None:
        module_dir = project / "third_party" / "openclaw" / "selected"
        module_dir.mkdir(parents=True)
        (module_dir / "async-lock-BcLS4KOc.js").write_text(
            _broken_openclaw_async_lock_source(),
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_async_lock.mjs").write_text(
            _openclaw_async_lock_stage1_tests(),
            encoding="utf-8",
        )

    def write_mako_js_labels_project(self, project: Path) -> None:
        module_dir = project / "mako_js"
        module_dir.mkdir()
        (module_dir / "index.js").write_text(
            "export { compactLabel, labelKey } from \"./labels.js\";\n",
            encoding="utf-8",
        )
        (module_dir / "labels.js").write_text(
            _broken_mako_js_labels_source(),
            encoding="utf-8",
        )
        (project / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_labels.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { compactLabel, labelKey } from '../mako_js/index.js';\n\n"
            "assert.equal(compactLabel('  Alpha Beta!!  '), 'alpha-beta');\n"
            "assert.equal(compactLabel('READY__Now'), 'ready-now');\n"
            "assert.equal(compactLabel(null), '');\n"
            "assert.equal(labelKey('  Alpha Beta!!  '), 'label:alpha-beta');\n"
            "assert.equal(labelKey(' !!! '), 'label');\n",
            encoding="utf-8",
        )

    def write_mako_js_async_records_project(self, project: Path) -> None:
        module_dir = project / "mako_js"
        module_dir.mkdir()
        (module_dir / "index.js").write_text(
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n",
            encoding="utf-8",
        )
        (module_dir / "async_records.js").write_text(
            _broken_mako_js_async_records_source(),
            encoding="utf-8",
        )
        (project / "package.json").write_text("{\"type\":\"module\"}\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_async_records.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { loadUserSummaries, normalizeUserId, summarizeUser } from '../mako_js/index.js';\n\n"
            "const calls = [];\n"
            "const client = {\n"
            "  async fetchUser(id) {\n"
            "    calls.push(id);\n"
            "    if (id === 'missing') throw new Error('not found');\n"
            "    return { id, name: id === 'ada' ? ' Ada Lovelace ' : '', roles: ['Admin', '', 'user'] };\n"
            "  }\n"
            "};\n"
            "const report = await loadUserSummaries(client, [' Ada ', 'bad id!', 'ADA', 'missing'], { concurrency: 2 });\n"
            "assert.deepEqual(calls, ['ada', 'missing']);\n"
            "assert.deepEqual(report.users, [{ id: 'ada', name: 'Ada Lovelace', roles: ['admin', 'user'] }]);\n"
            "assert.deepEqual(report.errors, [{ id: 'missing', message: 'not found' }]);\n"
            "assert.equal(normalizeUserId(' Team_01 '), 'team_01');\n"
            "assert.deepEqual(summarizeUser({ id: ' Bob ', roles: ['Viewer'] }), { id: 'bob', name: 'bob', roles: ['viewer'] });\n",
            encoding="utf-8",
        )

    def write_mako_js_io_boundary_project(self, project: Path) -> None:
        module_dir = project / "mako_js"
        module_dir.mkdir()
        (module_dir / "index.js").write_text(
            "export { compactLabel, labelKey } from \"./labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"./async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"./io_boundary.js\";\n",
            encoding="utf-8",
        )
        (module_dir / "labels.js").write_text(_mako_js_labels_source(), encoding="utf-8")
        (module_dir / "async_records.js").write_text(_mako_js_async_records_source(), encoding="utf-8")
        (module_dir / "io_boundary.js").write_text(_broken_mako_js_io_boundary_source(), encoding="utf-8")
        (project / "package.json").write_text(
            "{\"type\":\"module\",\"scripts\":{\"test\":\"node tests/test_io_boundary.mjs\"}}\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_io_boundary.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { scanWorkspaceManifest } from '../mako_js/index.js';\n\n"
            "const files = new Map([\n"
            "  ['/repo/package.json', JSON.stringify({ name: ' Stage-One ', version: '1.2.3', private: true })],\n"
            "  ['/repo/mako.json', JSON.stringify({ owner: ' Team-A ', tasks: ['lint', 'test'] })],\n"
            "  ['/repo/bad.json', '{broken json'],\n"
            "]);\n"
            "const calls = [];\n"
            "async function readText(path) {\n"
            "  calls.push(path);\n"
            "  if (files.has(path)) return files.get(path);\n"
            "  const error = new Error(`missing ${path}`);\n"
            "  error.code = 'ENOENT';\n"
            "  throw error;\n"
            "}\n"
            "assert.deepEqual(await scanWorkspaceManifest(readText, '/repo', ['package.json', 'mako.json', 'missing.json', 'bad.json']), {\n"
            "  root: '/repo',\n"
            "  found: [\n"
            "    { path: '/repo/package.json', kind: 'package', name: 'stage-one', version: '1.2.3', private: true },\n"
            "    { path: '/repo/mako.json', kind: 'mako', owner: 'team-a', taskCount: 2 },\n"
            "  ],\n"
            "  missing: ['/repo/missing.json'],\n"
            "  invalid: [{ path: '/repo/bad.json', reason: 'json' }],\n"
            "  errors: [],\n"
            "});\n"
            "assert.deepEqual(calls, ['/repo/package.json', '/repo/mako.json', '/repo/missing.json', '/repo/bad.json']);\n",
            encoding="utf-8",
        )

    def write_mako_js_fs_manifest_project(self, project: Path) -> None:
        module_dir = project / "mako_js"
        module_dir.mkdir()
        (module_dir / "index.js").write_text(
            "export { scanFsPackageManifest } from \"./fs_manifest.js\";\n",
            encoding="utf-8",
        )
        (module_dir / "fs_manifest.js").write_text(_broken_mako_js_fs_manifest_source(), encoding="utf-8")
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/fs-manifest-fixture",
                    "type": "module",
                    "dependencies": {"@openmako/local-helper": "file:fixtures/local-helper"},
                    "scripts": {
                        "pretest": "npm install --package-lock-only --ignore-scripts",
                        "test": "node tests/test_fs_manifest.mjs",
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        helper = project / "fixtures" / "local-helper"
        helper.mkdir(parents=True)
        (helper / "package.json").write_text(
            "{\"name\":\"@openmako/local-helper\",\"version\":\"1.0.0\",\"type\":\"module\"}\n",
            encoding="utf-8",
        )
        fixture_root = project / "fixtures" / "workspace"
        (fixture_root / "packages" / "core").mkdir(parents=True)
        (fixture_root / "package.json").write_text(
            json.dumps({"name": " Stage Fs ", "version": "1.2.3", "dependencies": {"local": "file:../local-helper"}}, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (fixture_root / "team.mako.json").write_text(json.dumps({"owner": " Ops ", "tasks": ["scan", "test"]}) + "\n", encoding="utf-8")
        (fixture_root / "packages" / "core" / "package.json").write_text(
            json.dumps({"name": "@openmako/core", "version": "2.0.0"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (fixture_root / "broken.json").write_text("{broken json\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_fs_manifest.mjs").write_text(_mako_js_fs_manifest_stage1_tests(), encoding="utf-8")

    def write_mako_js_http_manifest_project(self, project: Path) -> None:
        module_dir = project / "mako_js"
        module_dir.mkdir()
        (module_dir / "index.js").write_text(
            "export { fetchPackageMetadata } from \"./http_manifest.js\";\n",
            encoding="utf-8",
        )
        (module_dir / "http_manifest.js").write_text(_broken_mako_js_http_manifest_source(), encoding="utf-8")
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/http-manifest-fixture",
                    "type": "module",
                    "scripts": {"test": "node tests/test_http_manifest.mjs"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (project / "tests").mkdir()
        (project / "tests" / "test_http_manifest.mjs").write_text(_mako_js_http_manifest_stage1_tests(), encoding="utf-8")

    def write_less_pinned_mako_js_io_boundary_project(self, project: Path) -> None:
        self.write_mako_js_io_boundary_project(project)
        (project / "mako_js" / "index.js").unlink()
        runtime_dir = project / "src" / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "index.js").write_text(
            "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n",
            encoding="utf-8",
        )
        (project / "src" / "cli.js").write_text(
            "import { scanWorkspaceManifest } from './runtime/index.js';\n"
            "export { scanWorkspaceManifest };\n",
            encoding="utf-8",
        )
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/mock-workspace-manifest",
                    "type": "module",
                    "exports": {"./runtime": "./src/runtime/index.js"},
                    "bin": {"mako-manifest": "./src/cli.js"},
                    "scripts": {"test": "node tests/test_io_boundary.mjs"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        test_path = project / "tests" / "test_io_boundary.mjs"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace("../mako_js/index.js", "../src/runtime/index.js"),
            encoding="utf-8",
        )

    def write_multi_package_mako_js_io_boundary_project(self, project: Path) -> None:
        (project / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openmako/workspace-root",
                    "private": True,
                    "type": "module",
                    "workspaces": ["packages/*", "apps/*"],
                    "scripts": {"test": "node tests/test_io_boundary.mjs"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        core_module_dir = project / "packages" / "core" / "mako_js"
        core_module_dir.mkdir(parents=True)
        (core_module_dir / "labels.js").write_text(_mako_js_labels_source(), encoding="utf-8")
        (core_module_dir / "async_records.js").write_text(_mako_js_async_records_source(), encoding="utf-8")
        (core_module_dir / "io_boundary.js").write_text(_broken_mako_js_io_boundary_source(), encoding="utf-8")
        core_runtime_dir = project / "packages" / "core" / "src" / "runtime"
        core_runtime_dir.mkdir(parents=True)
        (core_runtime_dir / "index.js").write_text(
            "export { compactLabel, labelKey } from \"../../mako_js/labels.js\";\n"
            "export { loadUserSummaries, normalizeUserId, summarizeUser } from \"../../mako_js/async_records.js\";\n"
            "export { scanWorkspaceManifest } from \"../../mako_js/io_boundary.js\";\n",
            encoding="utf-8",
        )
        app_runtime_dir = project / "apps" / "cli" / "src" / "runtime"
        app_runtime_dir.mkdir(parents=True)
        (app_runtime_dir / "index.js").write_text(
            "export { scanWorkspaceManifest } from \"../../../../packages/core/src/runtime/index.js\";\n",
            encoding="utf-8",
        )
        tools_dir = project / "packages" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "package.json").write_text("{\"name\":\"@openmako/tools\",\"type\":\"module\"}\n", encoding="utf-8")
        (tools_dir / "index.js").write_text("export const untouchedTool = 'tools';\n", encoding="utf-8")
        (project / "README.md").write_text("# OpenMako mock workspace\n", encoding="utf-8")
        (project / "tests").mkdir()
        (project / "tests" / "test_io_boundary.mjs").write_text(
            "import assert from 'node:assert/strict';\n"
            "import { scanWorkspaceManifest } from '../apps/cli/src/runtime/index.js';\n\n"
            "const files = new Map([\n"
            "  ['/repo/package.json', JSON.stringify({ name: ' Multi-Package ', version: '2.0.0', private: true })],\n"
            "  ['/repo/mako.json', JSON.stringify({ owner: ' Platform-Team ', tasks: ['build', 'test', 'lint'] })],\n"
            "  ['/repo/packages/core/package.json', JSON.stringify({ name: '@openmako/core', version: '2.0.0', private: false })],\n"
            "  ['/repo/bad.json', '{broken json'],\n"
            "]);\n"
            "const calls = [];\n"
            "async function readText(path) {\n"
            "  calls.push(path);\n"
            "  if (files.has(path)) return files.get(path);\n"
            "  const error = new Error(`missing ${path}`);\n"
            "  error.code = 'ENOENT';\n"
            "  throw error;\n"
            "}\n"
            "assert.deepEqual(await scanWorkspaceManifest(readText, '/repo/', ['package.json', './skip.json', 'packages/core/package.json', 'mako.json', 'missing.json', 'bad.json']), {\n"
            "  root: '/repo',\n"
            "  found: [\n"
            "    { path: '/repo/package.json', kind: 'package', name: 'multi-package', version: '2.0.0', private: true },\n"
            "    { path: '/repo/packages/core/package.json', kind: 'package', name: 'openmako-core', version: '2.0.0', private: false },\n"
            "    { path: '/repo/mako.json', kind: 'mako', owner: 'platform-team', taskCount: 3 },\n"
            "  ],\n"
            "  missing: ['/repo/missing.json'],\n"
            "  invalid: [{ path: '/repo/bad.json', reason: 'json' }],\n"
            "  errors: [],\n"
            "});\n"
            "assert.deepEqual(calls, ['/repo/package.json', '/repo/packages/core/package.json', '/repo/mako.json', '/repo/missing.json', '/repo/bad.json']);\n",
            encoding="utf-8",
        )

    def test_planner_converts_create_hello_task_to_write_text_operation(self) -> None:
        """Planner should convert 'create hello.py with greet function' into write_text operation."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            task = "create hello.py with a greet function that takes a name parameter"
            result = plan_task_to_operations(Path(tmp), task)

            self.assertTrue(result["ok"], result.get("error"))
            self.assertIn("operations", result)
            operations = result["operations"]
            self.assertGreater(len(operations), 0, "planner should generate at least one operation")

            # Verify first operation is write_text for hello.py
            op = operations[0]
            self.assertEqual(op["op"], "write_text")
            self.assertEqual(op["path"], "hello.py")
            self.assertIn("text", op)
            self.assertIn("greet", op["text"], "generated code should contain greet function")
            self.assertIn("name", op["text"], "generated code should use name parameter")

    def test_planner_rejects_path_escape_operation(self) -> None:
        """Planner should reject tasks that would create files outside project."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            task = "create ../escape.py outside the project"
            result = plan_task_to_operations(Path(tmp), task)

            # Planner should either refuse to generate the operation,
            # or mark it as invalid
            if result.get("ok"):
                operations = result.get("operations", [])
                for op in operations:
                    if op.get("op") == "write_text":
                        path = op.get("path", "")
                        self.assertFalse(
                            path.startswith(".."),
                            "planner should not generate path escape operations"
                        )
            else:
                # Planner refused the task
                self.assertIn("error", result)

    def test_planner_output_matches_implement_operations_schema(self) -> None:
        """Planner output schema must match implement tool's operations input schema."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            task = "create hello.py with a greet function"
            result = plan_task_to_operations(Path(tmp), task)

            self.assertTrue(result["ok"], result.get("error"))
            self.assertIn("operations", result)
            operations = result["operations"]

            # Verify schema matches what implement expects
            for op in operations:
                self.assertIn("op", op, "operation must have 'op' field")
                self.assertEqual(op["op"], "write_text", "only write_text is supported")
                self.assertIn("path", op, "operation must have 'path' field")
                self.assertIn("text", op, "operation must have 'text' field")
                self.assertIsInstance(op["path"], str, "path must be string")
                self.assertIsInstance(op["text"], str, "text must be string")

    def test_planner_rejects_unsupported_create_task_without_operations(self) -> None:
        """Unsupported deterministic tasks must not emit placeholder write operations."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create calculator.py with add function and test it",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])
            self.assertIn("unsupported", result.get("error", "").lower())

    def test_planner_rejects_simple_function_placeholder_without_operations(self) -> None:
        """The deterministic planner must not legalize generic example() placeholders."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(Path(tmp), "create sample.py with a simple function")

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])
            self.assertIn("unsupported", result.get("error", "").lower())

    def test_planner_rejects_partial_multi_function_tasks(self) -> None:
        """The planner must not claim success when it can only implement part of a request."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with greet and farewell functions",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_rejects_greet_task_with_conflicting_return_semantics(self) -> None:
        """Supported greet generation must not ignore explicit conflicting return semantics."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with greet function that returns Hi, name",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_rejects_greet_task_with_unsupported_modifiers(self) -> None:
        """Unsupported shape modifiers must fail closed instead of being silently ignored."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            for task in (
                "create hello.py with async greet function",
                "create hello.py with class Greeter",
                "create hello.py with CLI greet command",
            ):
                result = plan_task_to_operations(Path(tmp), task)
                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_rejects_mixed_create_and_extra_actions(self) -> None:
        """Mixed edit/delete tasks are outside the deterministic planner contract."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with greet function and test it plus delete old.py",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_rejects_existing_file_without_overwrite_policy(self) -> None:
        """write_text operations must not silently overwrite existing files."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "hello.py").write_text("# existing\n", encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(project, "create hello.py with greet function")

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])
            self.assertIn("exists", result.get("error", "").lower())

    def test_planner_repairs_existing_add_numbers_without_test_operations(self) -> None:
        """Supported repair tasks may overwrite subject.py but must not modify tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def add_numbers(a, b):\n    return a - b\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import add_numbers\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_sum(self):\n"
                "        self.assertEqual(add_numbers(2, 3), 5)\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix add_numbers so it returns arithmetic sum for ints and floats.",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(len(result["operations"]), 1)
            op = result["operations"][0]
            self.assertEqual(op["op"], "write_text")
            self.assertEqual(op["path"], "subject.py")
            self.assertIn("return a + b", op["text"])
            self.assertFalse(any("test_subject.py" in item["path"] for item in result["operations"]))

    def test_planner_rejects_unsupported_existing_file_repair_without_operations(self) -> None:
        """Unsupported repair tasks must fail closed instead of writing placeholders."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def multiply_numbers(a, b):\n    return a + b\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import multiply_numbers\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_product(self):\n"
                "        self.assertEqual(multiply_numbers(2, 3), 6)\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix multiply_numbers so it returns product.",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])
            self.assertIn("unsupported", result.get("error", "").lower())

    def test_planner_infers_renamed_binary_sum_from_tests(self) -> None:
        """Hidden-style function names should be inferred from tests, not only recipe names."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def combine_values(a, b):\n    return a - b\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import combine_values\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_positive(self):\n"
                "        self.assertEqual(combine_values(2, 3), 5)\n"
                "    def test_mixed(self):\n"
                "        self.assertEqual(combine_values(-1, 4), 3)\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix subject.py so the unit tests pass.",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["operations"], [
                {"op": "write_text", "path": "subject.py", "text": "def combine_values(a, b):\n    return a + b\n"}
            ])

    def test_planner_learning_context_repairs_hidden_non_arithmetic_subject_only(self) -> None:
        """Approved project skills should affect only the learned context path."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def normalize_label(text):\n    return str(text)\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import normalize_label\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_slug_style(self):\n"
                "        self.assertEqual(normalize_label('  Alpha Beta  '), 'alpha-beta')\n"
                "    def test_symbols(self):\n"
                "        self.assertEqual(normalize_label('READY__Now!!'), 'ready-now')\n",
                encoding="utf-8",
            )
            self.install_normalize_label_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            task = "Fix subject.py normalize label so tests pass with learned-normalize-label."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["subject.py"])
            self.assertIn("def normalize_label", on["operations"][0]["text"])
            self.assertIn("re.sub", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-normalize-label-repair")

    def test_planner_ignores_unapproved_or_tampered_learning_skill(self) -> None:
        """Planner learning context must not trust raw project skill files."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def normalize_label(text):\n    return str(text)\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import normalize_label\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_slug_style(self):\n"
                "        self.assertEqual(normalize_label('Alpha Beta'), 'alpha-beta')\n",
                encoding="utf-8",
            )
            self.install_normalize_label_skill(project)
            installed = project / ".quantagent" / "skills" / "hidden-normalize-label-repair" / "SKILL.md"
            installed.write_text(installed.read_text(encoding="utf-8") + "\nTampered after approval.\n", encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix subject.py normalize label so tests pass with learned-normalize-label.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_repairs_juno_fold_subject_only(self) -> None:
        """A non-arithmetic hidden task should require approved learning context."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_juno_fold_project(project)
            self.install_juno_fold_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair subject.py juno_fold with learned juno fold contract."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["subject.py"])
            self.assertIn("result[-1]", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-juno-fold-repair")

    def test_planner_learning_context_repairs_multi_function_bundle_subject_only(self) -> None:
        """Approved bundle skills may repair a matching multi-function subject.py only as one scoped write."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_clean_flip_project(project)
            self.install_clean_flip_bundle_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair subject.py clean_token and flip_items with learned clean flip bundle contract."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual(on["operations"], [
                {
                    "op": "write_text",
                    "path": "subject.py",
                    "text": (
                        "def clean_token(value):\n"
                        "    return str(value).strip().lower()\n\n\n"
                        "def flip_items(items):\n"
                        "    return list(reversed(items))\n"
                    ),
                }
            ])
            self.assertEqual(on["learning_context"]["functions"], ["clean_token", "flip_items"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-clean-flip-bundle-repair")

    def test_planner_learning_context_repairs_multi_file_subject_and_helper(self) -> None:
        """Approved multi-file skills may repair subject.py plus an existing helper module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_format_label_multifile_project(project)
            self.install_format_label_multifile_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair subject.py format_label and label_helper with learned multi file repair contract."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["subject.py", "label_helper.py"])
            self.assertIn("from label_helper import normalize_piece", on["operations"][0]["text"])
            self.assertIn("re.sub", on["operations"][1]["text"])
            self.assertEqual(on["learning_context"]["files"], ["subject.py", "label_helper.py"])
            self.assertEqual(on["learning_context"]["functions"], ["format_label"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-format-label-multifile-repair")

    def test_planner_learning_context_repairs_package_module_file_bundle(self) -> None:
        """Approved file-bundle skills may repair existing package modules without subject.py."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_package_label_project(project)
            self.install_package_label_file_bundle_skill(project)
            test_before = (project / "tests" / "test_labels.py").read_text(encoding="utf-8")
            init_before = (project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair mako_pkg/labels.py compact_label with learned package label contract."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["mako_pkg/labels.py"])
            self.assertIn("def compact_label", on["operations"][0]["text"])
            self.assertIn("re.sub", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["target"], "file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["mako_pkg/labels.py"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-package-label-file-bundle-repair")
            self.assertEqual((project / "tests" / "test_labels.py").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8"), init_before)

    def test_planner_learning_context_reuses_openclaw_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair the narrow OpenClaw JS module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_parse_strict_integer_project(project)
            self.install_openclaw_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_parse_finite_number.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw parse finite number using approved learning contract opaque-openclaw-js-parse-finite-number-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js"])
            self.assertIn("Number.isSafeInteger(parsed)", on["operations"][0]["text"])
            self.assertIn("parseStrictPositiveInteger as i", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-js-file-bundle-repair")
            self.assertEqual((project / "tests" / "test_parse_finite_number.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_openclaw_balanced_json_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair the second pinned OpenClaw JS module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_balanced_json_project(project)
            self.install_openclaw_balanced_json_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_balanced_json.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw balanced json using approved learning contract opaque-openclaw-js-balanced-json-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["third_party/openclaw/selected/balanced-json-YUc2rvlg.js"])
            self.assertIn("function extractBalancedJsonPrefix", on["operations"][0]["text"])
            self.assertIn("function extractBalancedJsonFragments", on["operations"][0]["text"])
            self.assertIn("stack.push(char)", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["third_party/openclaw/selected/balanced-json-YUc2rvlg.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-balanced-json-js-repair")
            self.assertEqual((project / "tests" / "test_balanced_json.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_openclaw_json_pointer_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair the third pinned OpenClaw JS module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_json_pointer_project(project)
            self.install_openclaw_json_pointer_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_json_pointer.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw json pointer using approved learning contract opaque-openclaw-js-json-pointer-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["third_party/openclaw/selected/json-pointer-BRH9eAOA.js"])
            self.assertIn("function readJsonPointer", on["operations"][0]["text"])
            self.assertIn("function encodeJsonPointerToken", on["operations"][0]["text"])
            self.assertIn("Object.hasOwn(current, token)", on["operations"][0]["text"])
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["third_party/openclaw/selected/json-pointer-BRH9eAOA.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-json-pointer-js-repair")
            self.assertEqual((project / "tests" / "test_json_pointer.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_openclaw_combined_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair an exact multi-file OpenClaw JS bundle."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_combined_js_project(project)
            self.install_openclaw_combined_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_combined_openclaw_js.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw combined JavaScript using approved learning contract opaque-openclaw-js-combined-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual(
                [item["path"] for item in on["operations"]],
                [
                    "third_party/openclaw/selected/balanced-json-YUc2rvlg.js",
                    "third_party/openclaw/selected/json-pointer-BRH9eAOA.js",
                ],
            )
            operations = {item["path"]: item["text"] for item in on["operations"]}
            balanced_text = operations["third_party/openclaw/selected/balanced-json-YUc2rvlg.js"]
            pointer_text = operations["third_party/openclaw/selected/json-pointer-BRH9eAOA.js"]
            self.assertIn("function extractBalancedJsonPrefix", balanced_text)
            self.assertIn("function extractBalancedJsonFragments", balanced_text)
            self.assertIn("stack.push(char)", balanced_text)
            self.assertIn("extractBalancedJsonPrefix(raw.slice(offset), opts)", balanced_text)
            self.assertNotIn("function extractBalancedJsonPrefix(raw, opts = {}) {\n\treturn null;\n}", balanced_text)
            self.assertNotIn("function extractBalancedJsonFragments(raw, opts = {}) {\n\treturn [];\n}", balanced_text)
            self.assertIn("function readJsonPointer", pointer_text)
            self.assertIn("function decodeJsonPointerToken", pointer_text)
            self.assertIn("function encodeJsonPointerToken", pointer_text)
            self.assertIn("Object.hasOwn(current, token)", pointer_text)
            self.assertNotIn("return root[pointer];", pointer_text)
            self.assertNotIn("return token;", pointer_text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(
                on["learning_context"]["files"],
                [
                    "third_party/openclaw/selected/balanced-json-YUc2rvlg.js",
                    "third_party/openclaw/selected/json-pointer-BRH9eAOA.js",
                ],
            )
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-combined-js-repair")
            self.assertEqual((project / "tests" / "test_combined_openclaw_js.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_openclaw_command_poll_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair the stateful OpenClaw command-poll module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_command_poll_project(project)
            self.install_openclaw_command_poll_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_command_poll_backoff.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw command poll backoff using approved learning contract opaque-openclaw-js-command-poll-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"])
            text = on["operations"][0]["text"]
            self.assertIn("function recordCommandPoll", text)
            self.assertIn("new Map()", text)
            self.assertIn("const now = Date.now()", text)
            self.assertIn("const newCount = (existing?.count ?? -1) + 1", text)
            self.assertIn("state.commandPollCounts?.delete(commandId)", text)
            self.assertIn("now - data.lastPollAt > maxAgeMs", text)
            self.assertNotIn("return 0", text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-command-poll-js-repair")
            self.assertEqual((project / "tests" / "test_command_poll_backoff.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_openclaw_async_lock_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair the OpenClaw async lock module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_async_lock_project(project)
            self.install_openclaw_async_lock_js_file_bundle_skill(project)
            test_before = (project / "tests" / "test_async_lock.mjs").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair OpenClaw async lock using approved learning contract opaque-openclaw-js-async-lock-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["third_party/openclaw/selected/async-lock-BcLS4KOc.js"])
            text = on["operations"][0]["text"]
            self.assertIn("function createAsyncLock", text)
            self.assertIn("let lock = Promise.resolve()", text)
            self.assertIn("const previous = lock", text)
            self.assertIn("lock = new Promise((resolve) =>", text)
            self.assertIn("await previous", text)
            self.assertIn("finally", text)
            self.assertIn("release?.()", text)
            self.assertNotIn("return await fn();\n\t};", text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["third_party/openclaw/selected/async-lock-BcLS4KOc.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-openclaw-async-lock-js-repair")
            self.assertEqual((project / "tests" / "test_async_lock.mjs").read_text(encoding="utf-8"), test_before)

    def test_planner_learning_context_reuses_package_level_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair an exact package-level JavaScript module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_labels_project(project)
            self.install_mako_js_labels_file_bundle_skill(project)
            test_before = (project / "tests" / "test_labels.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair package-level JavaScript labels using approved learning contract opaque-mako-js-labels-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["mako_js/labels.js"])
            text = on["operations"][0]["text"]
            self.assertIn("function compactLabel", text)
            self.assertIn("function labelKey", text)
            self.assertIn("String(value ?? \"\").trim().toLowerCase()", text)
            self.assertIn("replace(/[^a-z0-9]+/g, \"-\")", text)
            self.assertIn("return compacted ? `label:${compacted}` : \"label\"", text)
            self.assertNotIn("return String(value)", text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["mako_js/labels.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-mako-js-labels-repair")
            self.assertEqual((project / "tests" / "test_labels.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)

    def test_planner_learning_context_reuses_package_level_async_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair an exact async package-level JavaScript module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_async_records_project(project)
            self.install_mako_js_async_records_file_bundle_skill(project)
            test_before = (project / "tests" / "test_async_records.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair package-level async JavaScript records using approved learning contract opaque-mako-js-async-records-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["mako_js/async_records.js"])
            text = on["operations"][0]["text"]
            self.assertIn("async function loadUserSummaries", text)
            self.assertIn("await Promise.all", text)
            self.assertIn("await client.fetchUser(id)", text)
            self.assertIn("function normalizeUserId", text)
            self.assertIn("function summarizeUser", text)
            self.assertNotIn("return { users: []", text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["mako_js/async_records.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-mako-js-async-records-repair")
            self.assertEqual((project / "tests" / "test_async_records.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)

    def test_planner_learning_context_reuses_package_level_io_boundary_js_file_bundle_skill(self) -> None:
        """Approved js_file_bundle skills may repair a mocked I/O boundary package module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_io_boundary_project(project)
            self.install_mako_js_io_boundary_file_bundle_skill(project)
            test_before = (project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            labels_before = (project / "mako_js" / "labels.js").read_text(encoding="utf-8")
            records_before = (project / "mako_js" / "async_records.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            task = "Repair package-level JavaScript mocked I/O boundary tests using approved learning contract opaque-mako-js-io-boundary-1."
            off = plan_task_to_operations(project, task, learning_context="off")
            on = plan_task_to_operations(project, task, learning_context="on")

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["mako_js/io_boundary.js"])
            text = on["operations"][0]["text"]
            self.assertIn("async function scanWorkspaceManifest", text)
            self.assertIn("await readText(path)", text)
            self.assertIn("JSON.parse", text)
            self.assertIn("code === \"ENOENT\"", text)
            self.assertNotIn("return { root, found: []", text)
            self.assertEqual(on["learning_context"]["target"], "js_file_bundle")
            self.assertEqual(on["learning_context"]["files"], ["mako_js/io_boundary.js"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-mako-js-io-boundary-repair")
            self.assertEqual((project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)
            self.assertEqual((project / "mako_js" / "labels.js").read_text(encoding="utf-8"), labels_before)
            self.assertEqual((project / "mako_js" / "async_records.js").read_text(encoding="utf-8"), records_before)

    def test_planner_learning_context_rejects_file_bundle_protected_targets(self) -> None:
        """File-bundle learned repairs must not target tests, runtime artifacts, or escapes."""
        bad_files = [
            {"tests/test_labels.py": "def test_shadow():\n    assert True\n"},
            {"conftest.py": "def pytest_configure():\n    return None\n"},
            {"../escape.py": "def compact_label(value):\n    return 'unsafe'\n"},
            {".quantagent/skills/x.py": "def compact_label(value):\n    return 'unsafe'\n"},
            {"AI_协作交接/run.py": "def compact_label(value):\n    return 'unsafe'\n"},
            {"mako_pkg/__init__.py": "def compact_label(value):\n    return 'unsafe'\n"},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_package_label_project(project)
                self.install_package_label_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair mako_pkg/labels.py compact_label with learned package label contract.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_js_file_bundle_unsafe_targets(self) -> None:
        """JavaScript learned repairs are limited to the pinned OpenClaw selected module."""
        bad_files = [
            {"tests/test_parse_finite_number.mjs": "console.log('unsafe');\n"},
            {"third_party/openclaw/selected/balanced-json.js": "function parseStrictInteger(value) { return value; }\n"},
            {"../parse-finite-number-C3Woj8eC.js": "function parseStrictInteger(value) { return value; }\n"},
            {
                "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js": (
                    "import fs from 'node:fs';\n"
                    "function normalizeNumericString(value) { return value; }\n"
                    "function parseFiniteNumber(value) { return value; }\n"
                    "function parseStrictInteger(value) { return eval(value); }\n"
                    "function parseStrictPositiveInteger(value) { return value; }\n"
                    "function parseStrictNonNegativeInteger(value) { return value; }\n"
                    "export { parseStrictPositiveInteger as i, parseStrictInteger as n, parseStrictNonNegativeInteger as r, parseFiniteNumber as t };\n"
                )
            },
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_openclaw_parse_strict_integer_project(project)
                self.install_openclaw_js_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair OpenClaw parse finite number using approved learning contract opaque-openclaw-js-parse-finite-number-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_balanced_json_js_file_bundle_unsafe_overrides(self) -> None:
        """Balanced-json learned JS repairs must fail closed on bad paths and bad sources."""
        target = "third_party/openclaw/selected/balanced-json-YUc2rvlg.js"
        valid_source = _openclaw_balanced_json_source()
        bad_files = [
            {"../balanced-json-YUc2rvlg.js": valid_source},
            {"third_party/openclaw/selected/balanced-json.js": valid_source},
            {
                target: valid_source.replace(
                    "export { extractBalancedJsonPrefix as n, extractBalancedJsonFragments as t };",
                    "export { extractBalancedJsonPrefix as n };",
                )
            },
            {
                target: valid_source.replace(
                    "stack.push(char)",
                    "stack.push(char);\n\t\t\tfetch(\"https://example.invalid\");",
                )
            },
            {target: valid_source.replace("offset += fragment.endIndex + 1", "offset = 0")},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_openclaw_balanced_json_project(project)
                self.install_openclaw_balanced_json_js_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair OpenClaw balanced json using approved learning contract opaque-openclaw-js-balanced-json-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_json_pointer_js_file_bundle_unsafe_overrides(self) -> None:
        """JSON pointer learned JS repairs must fail closed on bad paths and bad sources."""
        target = "third_party/openclaw/selected/json-pointer-BRH9eAOA.js"
        valid_source = _openclaw_json_pointer_source()
        bad_files = [
            {"../json-pointer-BRH9eAOA.js": valid_source},
            {"third_party/openclaw/selected/json-pointer.js": valid_source},
            {
                target: valid_source.replace(
                    "export { readJsonPointer as n, encodeJsonPointerToken as t };",
                    "export { readJsonPointer as n };",
                )
            },
            {
                target: valid_source.replace(
                    "Object.hasOwn(current, token)",
                    "Object.hasOwn(current, token) || globalThis.secret",
                )
            },
            {target: valid_source.replace("current = current[token]", "current = root")},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_openclaw_json_pointer_project(project)
                self.install_openclaw_json_pointer_js_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair OpenClaw json pointer using approved learning contract opaque-openclaw-js-json-pointer-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_command_poll_js_file_bundle_unsafe_overrides(self) -> None:
        """Command-poll learned JS repairs may use Date.now but must fail closed on bad sources."""
        target = "third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"
        valid_source = _openclaw_command_poll_source()
        bad_files = [
            {"../command-poll-backoff-DmjJeZIx.js": valid_source},
            {"third_party/openclaw/selected/command-poll-backoff.js": valid_source},
            {
                target: valid_source.replace(
                    "export { recordCommandPoll as n, resetCommandPollCount as r, pruneStaleCommandPolls as t };",
                    "export { recordCommandPoll as n };",
                )
            },
            {target: valid_source.replace("Date.now()", "Date.parse('2020-01-01')", 1)},
            {target: valid_source + "\nDate.now = () => 0;\n"},
            {target: valid_source.replace("state.commandPollCounts?.delete(commandId)", "state.commandPollCounts = new Map()")},
            {target: valid_source.replace("return calculateBackoffMs(newCount)", "return 0")},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_openclaw_command_poll_project(project)
                self.install_openclaw_command_poll_js_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair OpenClaw command poll backoff using approved learning contract opaque-openclaw-js-command-poll-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_async_lock_js_file_bundle_unsafe_overrides(self) -> None:
        """Async-lock learned JS repairs must preserve queueing and release-on-rejection."""
        target = "third_party/openclaw/selected/async-lock-BcLS4KOc.js"
        valid_source = _openclaw_async_lock_source()
        bad_files = [
            {"tests/test_async_lock.mjs": "console.log('unsafe');\n"},
            {"../async-lock-BcLS4KOc.js": valid_source},
            {"third_party/openclaw/selected/async-lock.js": valid_source},
            {target: valid_source.replace("export { createAsyncLock as t };", "export {};")},
            {target: valid_source.replace("let lock = Promise.resolve();", "let lock;")},
            {target: valid_source.replace("await previous;", "")},
            {target: valid_source.replace("try {", "{")},
            {target: valid_source.replace("release?.();", "")},
            {target: valid_source + "\nsetTimeout(() => {}, 1);\n"},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_openclaw_async_lock_project(project)
                self.install_openclaw_async_lock_js_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair OpenClaw async lock using approved learning contract opaque-openclaw-js-async-lock-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_package_level_js_file_bundle_unsafe_overrides(self) -> None:
        """Package-level JS repairs must stay on the exact safe module and source shape."""
        target = "mako_js/labels.js"
        valid_source = _mako_js_labels_source()
        bad_files = [
            {"tests/test_labels.mjs": "console.log('unsafe');\n"},
            {"package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"true\"}}\n"},
            {"../mako_js/labels.js": valid_source},
            {"mako_js/index.js": valid_source},
            {target: valid_source.replace("export { compactLabel, labelKey };", "export { compactLabel };")},
            {target: valid_source.replace("String(value ?? \"\")", "process.env.SECRET")},
            {target: valid_source + "\nimport fs from 'node:fs';\n"},
            {target: valid_source.replace("return compacted ? `label:${compacted}` : \"label\";", "return compactLabel('constant');")},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_mako_js_labels_project(project)
                self.install_mako_js_labels_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair package-level JavaScript labels using approved learning contract opaque-mako-js-labels-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_package_level_async_js_file_bundle_unsafe_overrides(self) -> None:
        """Async package-level JS repairs must stay on the exact safe module and source shape."""
        target = "mako_js/async_records.js"
        valid_source = _mako_js_async_records_source()
        bad_files = [
            {"tests/test_async_records.mjs": "console.log('unsafe');\n"},
            {"package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"true\"}}\n"},
            {"../mako_js/async_records.js": valid_source},
            {"mako_js/index.js": valid_source},
            {target: valid_source.replace("export { loadUserSummaries, normalizeUserId, summarizeUser };", "export { loadUserSummaries };")},
            {target: valid_source.replace("await client.fetchUser(id)", "await fetch(id)")},
            {target: valid_source.replace("return { users, errors };", "return { users: [], errors: [] };")},
            {target: valid_source + "\nprocess.env.SECRET;\n"},
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_mako_js_async_records_project(project)
                self.install_mako_js_async_records_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair package-level async JavaScript records using approved learning contract opaque-mako-js-async-records-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_package_level_io_boundary_js_file_bundle_unsafe_overrides(self) -> None:
        """Package-level mocked I/O JS repairs must stay exact-target and sandbox-safe."""
        target = "mako_js/io_boundary.js"
        valid_source = _mako_js_io_boundary_source()
        bad_files = [
            {"tests/test_io_boundary.mjs": "console.log('unsafe');\n"},
            {"package.json": "{\"type\":\"module\",\"scripts\":{\"test\":\"true\"}}\n"},
            {"../mako_js/io_boundary.js": valid_source},
            {"mako_js/index.js": valid_source},
            {target: valid_source.replace("export { scanWorkspaceManifest };", "export {};")},
            {target: valid_source.replace("await readText(path)", "process.env.SECRET")},
            {target: valid_source.replace("await readText(path)", "process?.env?.SECRET")},
            {target: valid_source + "\nimport fs from 'node:fs';\n"},
            {target: valid_source + "\nfetch('https://example.invalid');\n"},
            {target: valid_source.replace("JSON.parse(String(text ?? \"\"))", "JSON.parse('{\"hardcoded\":true}')")},
            {
                target: valid_source.replace(
                    "const safeRoot = normalizeRoot(root);",
                    "const safeRoot = root === \"/tmp/ws\" ? \"/tmp/ws\" : normalizeRoot(root);",
                )
            },
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for files in bad_files:
            with self.subTest(files=files), self.make_project() as tmp:
                project = Path(tmp)
                self.write_mako_js_io_boundary_project(project)
                self.install_mako_js_io_boundary_file_bundle_skill(project, files_override=files)

                result = plan_task_to_operations(
                    project,
                    "Repair package-level JavaScript mocked I/O boundary tests using approved learning contract opaque-mako-js-io-boundary-1.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_no_seed_infers_package_module_file_bundle_from_tests(self) -> None:
        """No-seed package-module repair may infer a safe existing module from tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_package_label_project(project)
            test_before = (project / "tests" / "test_labels.py").read_text(encoding="utf-8")
            init_before = (project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair mako_pkg/labels.py compact_label so unit tests pass.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_pkg/labels.py"])
            self.assertIn("def compact_label", result["operations"][0]["text"])
            self.assertIn("re.sub", result["operations"][0]["text"])
            self.assertEqual(result["inference"]["source"], "package_module_tests")
            self.assertEqual((project / "tests" / "test_labels.py").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8"), init_before)

    def test_planner_no_seed_discovers_package_module_without_target_name(self) -> None:
        """No-seed package-module repair may discover a target from package tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_package_label_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_pkg/labels.py"])
            self.assertIn("re.sub", result["operations"][0]["text"])

    def test_planner_no_seed_repairs_package_level_js_module(self) -> None:
        """No-seed JavaScript inference may repair an exact package-level JS module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_labels_project(project)
            test_before = (project / "tests" / "test_labels.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level JavaScript labels tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/labels.js"])
            text = result["operations"][0]["text"]
            self.assertIn("function compactLabel", text)
            self.assertIn("function labelKey", text)
            self.assertIn("replace(/[^a-z0-9]+/g, \"-\")", text)
            self.assertNotIn("return String(value)", text)
            self.assertEqual((project / "tests" / "test_labels.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)

    def test_planner_no_seed_repairs_package_level_async_js_module(self) -> None:
        """No-seed JavaScript inference may repair an exact async package-level JS module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_async_records_project(project)
            test_before = (project / "tests" / "test_async_records.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level async JavaScript records tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/async_records.js"])
            text = result["operations"][0]["text"]
            self.assertIn("async function loadUserSummaries", text)
            self.assertIn("await Promise.all", text)
            self.assertIn("await client.fetchUser(id)", text)
            self.assertIn("function normalizeUserId", text)
            self.assertIn("function summarizeUser", text)
            self.assertNotIn("return { users: []", text)
            self.assertEqual((project / "tests" / "test_async_records.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)

    def test_planner_no_seed_repairs_package_level_io_boundary_js_module(self) -> None:
        """No-seed JavaScript inference may repair mocked I/O boundary package tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_io_boundary_project(project)
            test_before = (project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            labels_before = (project / "mako_js" / "labels.js").read_text(encoding="utf-8")
            records_before = (project / "mako_js" / "async_records.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level JavaScript mocked I/O boundary tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/io_boundary.js"])
            text = result["operations"][0]["text"]
            self.assertIn("async function scanWorkspaceManifest", text)
            self.assertIn("await readText(path)", text)
            self.assertIn("JSON.parse", text)
            self.assertIn("code === \"ENOENT\"", text)
            self.assertNotIn("return { root, found: []", text)
            self.assertEqual((project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)
            self.assertEqual((project / "mako_js" / "labels.js").read_text(encoding="utf-8"), labels_before)
            self.assertEqual((project / "mako_js" / "async_records.js").read_text(encoding="utf-8"), records_before)

    def test_planner_no_seed_repairs_package_level_fs_manifest_js_module(self) -> None:
        """No-seed JavaScript inference may repair real Node fs package-manifest tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_fs_manifest_project(project)
            test_before = (project / "tests" / "test_fs_manifest.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            helper_before = (project / "fixtures" / "local-helper" / "package.json").read_text(encoding="utf-8")
            fixture_before = (project / "fixtures" / "workspace" / "package.json").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level JavaScript real fs manifest tests without editing tests, fixtures, entrypoints, or package config.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/fs_manifest.js"])
            text = result["operations"][0]["text"]
            self.assertIn("import { readdir, readFile, stat } from \"node:fs/promises\"", text)
            self.assertIn("async function scanFsPackageManifest", text)
            self.assertIn("await readdir(dir, { withFileTypes: true })", text)
            self.assertIn("const info = await stat(filePath)", text)
            self.assertIn("await readFile(filePath, \"utf8\")", text)
            self.assertIn("kind: \"package-lock\"", text)
            self.assertNotIn("return { root, found: []", text)
            self.assertEqual((project / "tests" / "test_fs_manifest.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)
            self.assertEqual((project / "fixtures" / "local-helper" / "package.json").read_text(encoding="utf-8"), helper_before)
            self.assertEqual((project / "fixtures" / "workspace" / "package.json").read_text(encoding="utf-8"), fixture_before)

    def test_planner_no_seed_repairs_package_level_http_manifest_js_module(self) -> None:
        """No-seed JavaScript inference may repair real fetch package metadata tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_mako_js_http_manifest_project(project)
            test_before = (project / "tests" / "test_http_manifest.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            index_before = (project / "mako_js" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level JavaScript real fetch metadata tests without editing tests, entrypoints, or package config.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/http_manifest.js"])
            text = result["operations"][0]["text"]
            self.assertIn("async function fetchPackageMetadata", text)
            self.assertIn("response = await fetch(url", text)
            self.assertIn("encodeURIComponent(name)", text)
            self.assertIn("response.status === 404", text)
            self.assertIn("invalid.push({ name, reason: \"json\" })", text)
            self.assertNotIn("return { baseUrl, found: []", text)
            self.assertNotIn("async async function fetchPackageMetadata", text)
            self.assertNotIn("async function normalizePackageName", text)
            self.assertEqual((project / "tests" / "test_http_manifest.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "mako_js" / "index.js").read_text(encoding="utf-8"), index_before)

    def test_planner_no_seed_repairs_less_pinned_package_io_boundary_js_module(self) -> None:
        """No-seed JavaScript inference may follow a package runtime re-export to the safe target."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_less_pinned_mako_js_io_boundary_project(project)
            test_before = (project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            entry_before = (project / "src" / "runtime" / "index.js").read_text(encoding="utf-8")
            cli_before = (project / "src" / "cli.js").read_text(encoding="utf-8")
            labels_before = (project / "mako_js" / "labels.js").read_text(encoding="utf-8")
            records_before = (project / "mako_js" / "async_records.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package-level JavaScript mocked I/O boundary tests without editing tests, src entrypoints, sibling modules, or package config.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_js/io_boundary.js"])
            text = result["operations"][0]["text"]
            self.assertIn("async function scanWorkspaceManifest", text)
            self.assertIn("await readText(path)", text)
            self.assertIn("JSON.parse", text)
            self.assertIn("code === \"ENOENT\"", text)
            self.assertNotIn("return { root, found: []", text)
            self.assertEqual((project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), entry_before)
            self.assertEqual((project / "src" / "cli.js").read_text(encoding="utf-8"), cli_before)
            self.assertEqual((project / "mako_js" / "labels.js").read_text(encoding="utf-8"), labels_before)
            self.assertEqual((project / "mako_js" / "async_records.js").read_text(encoding="utf-8"), records_before)

    def test_planner_no_seed_repairs_multi_package_io_boundary_js_module(self) -> None:
        """No-seed JavaScript inference may follow nested workspace re-exports to the safe target."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_multi_package_mako_js_io_boundary_project(project)
            test_before = (project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            app_entry_before = (project / "apps" / "cli" / "src" / "runtime" / "index.js").read_text(encoding="utf-8")
            core_entry_before = (project / "packages" / "core" / "src" / "runtime" / "index.js").read_text(encoding="utf-8")
            labels_before = (project / "packages" / "core" / "mako_js" / "labels.js").read_text(encoding="utf-8")
            records_before = (project / "packages" / "core" / "mako_js" / "async_records.js").read_text(encoding="utf-8")
            tools_before = (project / "packages" / "tools" / "index.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing multi-package JavaScript workspace mocked I/O boundary tests without editing tests, app entrypoints, package entrypoints, sibling packages, or package config.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["packages/core/mako_js/io_boundary.js"])
            text = result["operations"][0]["text"]
            self.assertIn("async function scanWorkspaceManifest", text)
            self.assertIn("await readText(path)", text)
            self.assertIn("JSON.parse", text)
            self.assertIn("code === \"ENOENT\"", text)
            self.assertNotIn("return { root, found: []", text)
            self.assertEqual((project / "tests" / "test_io_boundary.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "apps" / "cli" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), app_entry_before)
            self.assertEqual((project / "packages" / "core" / "src" / "runtime" / "index.js").read_text(encoding="utf-8"), core_entry_before)
            self.assertEqual((project / "packages" / "core" / "mako_js" / "labels.js").read_text(encoding="utf-8"), labels_before)
            self.assertEqual((project / "packages" / "core" / "mako_js" / "async_records.js").read_text(encoding="utf-8"), records_before)
            self.assertEqual((project / "packages" / "tools" / "index.js").read_text(encoding="utf-8"), tools_before)

    def test_planner_no_seed_repairs_function_inside_complex_package_module(self) -> None:
        """No-seed package-module inference may merge one inferred function into a complex module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_complex_package_label_project(project)
            before = (project / "mako_pkg" / "labels.py").read_text(encoding="utf-8")
            test_before = (project / "tests" / "test_labels.py").read_text(encoding="utf-8")
            init_before = (project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"]["source"], "package_module_tests")
            self.assertEqual([item["path"] for item in result["operations"]], ["mako_pkg/labels.py"])
            text = result["operations"][0]["text"]
            self.assertIn("import re", text)
            self.assertIn("LABEL_KIND = 'label'", text)
            self.assertIn("class LabelPolicy", text)
            self.assertIn("def describe_label", text)
            self.assertIn("re.sub", text)
            self.assertNotIn("def compact_label(value):\n    return str(value)", text)
            namespace: dict[str, object] = {}
            exec(text, namespace)
            self.assertEqual(namespace["compact_label"]("  Alpha Beta!!  "), "alpha-beta")
            self.assertEqual(namespace["describe_label"]("ready"), "label:ready")
            self.assertEqual((project / "tests" / "test_labels.py").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "mako_pkg" / "__init__.py").read_text(encoding="utf-8"), init_before)
            self.assertEqual(
                _top_level_hashes_without(before, "compact_label"),
                _top_level_hashes_without(text, "compact_label"),
            )

    def test_planner_no_seed_package_module_fails_closed_on_ambiguous_imports(self) -> None:
        """Targetless package-test inference must not guess among several imports from one module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_complex_package_label_project(project)
            (project / "tests" / "test_labels.py").write_text(
                "import unittest\n"
                "from mako_pkg.labels import compact_label, describe_label\n\n"
                "class TestLabels(unittest.TestCase):\n"
                "    def test_slug_style(self):\n"
                "        self.assertEqual(compact_label('  Alpha Beta!!  '), 'alpha-beta')\n"
                "    def test_unrelated_import(self):\n"
                "        self.assertEqual(describe_label('ready'), 'label:ready')\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertFalse(result.get("ok", True), result)
        self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_uses_contract_trigger_without_target_name(self) -> None:
        """Approved file-bundle skills may be selected by opaque contract trigger alone."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_package_label_project(project)
            self.install_package_label_file_bundle_skill(project, triggers="opaque-package-contract-1")
            from quantagent.agent_planner import plan_task_to_operations

            off = plan_task_to_operations(
                project,
                "Fix the failing package tests using approved learning contract opaque-package-contract-1.",
                learning_context="off",
            )
            on = plan_task_to_operations(
                project,
                "Fix the failing package tests using approved learning contract opaque-package-contract-1.",
                learning_context="on",
            )

            self.assertFalse(off.get("ok", True), off)
            self.assertEqual(off.get("operations", []), [])
            self.assertTrue(on["ok"], on.get("error"))
            self.assertEqual([item["path"] for item in on["operations"]], ["mako_pkg/labels.py"])
            self.assertEqual(on["learning_context"]["skill"], "hidden-package-label-file-bundle-repair")

    def test_planner_learning_context_replaces_function_inside_complex_package_module(self) -> None:
        """Function-level file-bundle skills must preserve unrelated upstream module code."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_complex_package_project(project)
            self.install_complex_package_function_bundle_skill(project)
            module_path = project / "mcp" / "shared" / "tool_name_validation.py"
            before = module_path.read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            off = plan_task_to_operations(
                project,
                "Fix failing package tests using approved learning contract opaque-complex-package-contract-1.",
                learning_context="off",
            )
            on = plan_task_to_operations(
                project,
                "Fix failing package tests using approved learning contract opaque-complex-package-contract-1.",
                learning_context="on",
            )

        self.assertFalse(off.get("ok", True), off)
        self.assertEqual(off.get("operations", []), [])
        self.assertTrue(on["ok"], on.get("error"))
        self.assertEqual([item["path"] for item in on["operations"]], ["mcp/shared/tool_name_validation.py"])
        text = on["operations"][0]["text"]
        self.assertIn("MAX_TOOL_NAME_LENGTH = 64", text)
        self.assertIn("def normalize_tool_name", text)
        self.assertIn("class ToolNamePolicy", text)
        self.assertIn("TOOL_NAME_PATTERN.fullmatch", text)
        self.assertEqual(on["learning_context"]["merge_mode"], "replace_functions")
        self.assertIn("return bool(name)", before)
        self.assertNotIn("return bool(name)", text)

    def test_planner_learning_context_repairs_file_function_bundle_with_module_symbols(self) -> None:
        """Nested function-bundle hints may call safe symbols already present in the target module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_tool_name_project(project)
            self.install_tool_name_function_bundle_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            off = plan_task_to_operations(
                project,
                "Fix failing package tests using approved learning contract opaque-upstream-function-contract-1.",
                learning_context="off",
            )
            on = plan_task_to_operations(
                project,
                "Fix failing package tests using approved learning contract opaque-upstream-function-contract-1.",
                learning_context="on",
            )

        self.assertFalse(off.get("ok", True), off)
        self.assertEqual(off.get("operations", []), [])
        self.assertTrue(on["ok"], on.get("error"))
        self.assertEqual([item["path"] for item in on["operations"]], ["mcp/shared/tool_name_validation.py"])
        text = on["operations"][0]["text"]
        self.assertIn("class ToolNameValidationResult", text)
        self.assertIn("TOOL_NAME_REGEX = re.compile", text)
        self.assertIn("def issue_tool_name_warning", text)
        self.assertIn("ToolNameValidationResult(is_valid=False", text)
        self.assertNotIn("return ToolNameValidationResult(is_valid=True, warnings=[])\n\n\ndef issue_tool_name_warning", text)
        self.assertEqual(on["learning_context"]["target"], "file_function_bundle")
        self.assertEqual(on["learning_context"]["functions"], ["validate_tool_name"])

    def test_planner_no_seed_repairs_tool_name_validation_inside_complex_package_module(self) -> None:
        """No-seed inference may repair dataclass/regex validation logic in a complex module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_tool_name_project(project)
            module_path = project / "mcp" / "shared" / "tool_name_validation.py"
            before = module_path.read_text(encoding="utf-8")
            (project / "tests" / "test_tool_name_validation.py").write_text(
                "import unittest\n"
                "from mcp.shared.tool_name_validation import validate_tool_name\n\n"
                "class TestToolNameValidation(unittest.TestCase):\n"
                "    def test_accepts_valid_tool_names(self):\n"
                "        self.assertTrue(validate_tool_name('desktop.find-click').is_valid)\n"
                "    def test_rejects_empty_and_invalid_names(self):\n"
                "        self.assertFalse(validate_tool_name('').is_valid)\n"
                "        self.assertFalse(validate_tool_name('bad/name').is_valid)\n"
                "    def test_warns_on_invalid_character(self):\n"
                "        result = validate_tool_name('bad name')\n"
                "        self.assertFalse(result.is_valid)\n"
                "        self.assertTrue(result.warnings)\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertNotIn("learning_context", result)
        self.assertEqual(result["inference"], {"source": "package_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["mcp/shared/tool_name_validation.py"])
        text = result["operations"][0]["text"]
        self.assertIn("class ToolNameValidationResult", text)
        self.assertIn("TOOL_NAME_REGEX = re.compile", text)
        self.assertIn("def issue_tool_name_warning", text)
        self.assertIn("invalid_chars", text)
        self.assertIn("Tool name contains invalid characters", text)
        self.assertNotIn("return ToolNameValidationResult(is_valid=True, warnings=[])\n\n\ndef issue_tool_name_warning", text)
        self.assertEqual(
            _top_level_hashes_without(before, "validate_tool_name"),
            _top_level_hashes_without(text, "validate_tool_name"),
        )

    def test_planner_no_seed_repairs_single_function_inside_complex_package_module(self) -> None:
        """No-seed package-test inference may replace one safe function in a complex module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_pandera_scale_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "package_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["pandera/dtypes.py"])
        text = result["operations"][0]["text"]
        self.assertIn("SUPPORTED_SCALES = (0, 1, 2, 3, 4)", text)
        self.assertIn("def stable_decimal(value):", text)
        self.assertIn("class DecimalPolicy:", text)
        self.assertIn("scale_fmt = format(10**-scale", text)
        self.assertIn("return decimal.Decimal(scale_fmt)", text)
        self.assertNotIn("return decimal.Decimal('1')", text)

    def test_planner_no_seed_repairs_dtype_predicate_inside_complex_package_module(self) -> None:
        """No-seed inference may repair class-hierarchy predicate wrappers."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_pandera_dtype_predicate_project(project)
            module_path = project / "pandera" / "dtypes.py"
            before = module_path.read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "package_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["pandera/dtypes.py"])
        text = result["operations"][0]["text"]
        self.assertIn("class Bool(DataType):", text)
        self.assertIn("class String(DataType):", text)
        self.assertIn("def is_subdtype", text)
        self.assertIn("def is_string", text)
        self.assertIn("return is_subdtype(pandera_dtype, Bool)", text)
        self.assertNotIn("def is_bool(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n    return False", text)
        self.assertEqual(
            _top_level_hashes_without(before, "is_bool"),
            _top_level_hashes_without(text, "is_bool"),
        )

    def test_planner_no_seed_repairs_result_format_parser_inside_complex_package_module(self) -> None:
        """No-seed inference may repair dict-default and raise behavior in a complex module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_result_format_project(project)
            module_path = project / "great_expectations" / "expectations" / "expectation_configuration.py"
            before = module_path.read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "package_module_tests"})
        self.assertEqual(
            [item["path"] for item in result["operations"]],
            ["great_expectations/expectations/expectation_configuration.py"],
        )
        text = result["operations"][0]["text"]
        self.assertIn("DEFAULT_RESULT_FORMAT = 'BASIC'", text)
        self.assertIn("class ExpectationConfiguration:", text)
        self.assertIn("class ExpectationConfigurationSchema:", text)
        self.assertIn('"partial_unexpected_count": 20', text)
        self.assertIn("raise ValueError", text)
        self.assertNotIn("return {'result_format': result_format}", text)
        self.assertEqual(
            _top_level_hashes_without(before, "parse_result_format"),
            _top_level_hashes_without(text, "parse_result_format"),
        )

    def test_planner_no_seed_repairs_random_color_inside_complex_package_module(self) -> None:
        """No-seed inference may repair deterministic HSV-to-hex behavior in a complex module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_aider_color_project(project)
            module_path = project / "aider" / "repomap.py"
            before = module_path.read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing package tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "package_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["aider/repomap.py"])
        text = result["operations"][0]["text"]
        self.assertIn("CACHE_VERSION = 3", text)
        self.assertIn("def find_src_files(directory):", text)
        self.assertIn("class RepoMap:", text)
        self.assertIn("colorsys.hsv_to_rgb(hue, 1, 0.75)", text)
        self.assertIn("f\"#{r:02x}{g:02x}{b:02x}\"", text)
        self.assertNotIn("return '#000000'", text)
        self.assertEqual(
            _top_level_hashes_without(before, "get_random_color"),
            _top_level_hashes_without(text, "get_random_color"),
        )

    def test_planner_no_seed_repairs_openclaw_parse_strict_integer_js_module(self) -> None:
        """No-seed JavaScript inference may repair one OpenClaw selected module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_parse_strict_integer_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js"])
        text = result["operations"][0]["text"]
        self.assertIn("function normalizeNumericString(value)", text)
        self.assertIn("function parseFiniteNumber(value)", text)
        self.assertIn("function parseStrictInteger(value)", text)
        self.assertIn("/^[+-]?\\d+$/.test(normalized)", text)
        self.assertIn("Number.isSafeInteger(parsed)", text)
        self.assertIn("parseStrictPositiveInteger as i", text)
        self.assertNotIn("return Number.parseInt(value, 10)", text)

    def test_planner_no_seed_repairs_openclaw_parse_timeout_package_js_module(self) -> None:
        """No-seed JavaScript inference may repair an OpenClaw module behind a package entrypoint."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_parse_timeout_package_project(project)
            test_before = (project / "tests" / "test_parse_timeout.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            entry_before = (project / "src" / "timeout.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript parse-timeout tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/parse-timeout-91AFhn8L.js"])
            text = result["operations"][0]["text"]
            self.assertIn("function parseTimeoutMs(raw)", text)
            self.assertIn("function parseTimeoutMsWithFallback(raw, fallbackMs, options = {})", text)
            self.assertIn("throw invalidTimeout(value)", text)
            self.assertIn("typeof raw === \"bigint\"", text)
            self.assertNotIn("return fallbackMs;", text.split("function parseTimeoutMsWithFallback", 1)[1].split("}", 1)[0])
            self.assertEqual((project / "tests" / "test_parse_timeout.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "src" / "timeout.js").read_text(encoding="utf-8"), entry_before)

    def test_planner_no_seed_repairs_openclaw_arg_split_package_js_module(self) -> None:
        """No-seed JavaScript inference may repair an OpenClaw CLI parser behind a package entrypoint."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_arg_split_package_project(project)
            test_before = (project / "tests" / "test_arg_split.mjs").read_text(encoding="utf-8")
            package_before = (project / "package.json").read_text(encoding="utf-8")
            entry_before = (project / "src" / "args.js").read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript arg-split tests without editing tests.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
            self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/arg-split-DM7vx6uc.js"])
            text = result["operations"][0]["text"]
            self.assertIn("function splitArgsPreservingQuotes(value, options)", text)
            self.assertIn("quoteChars.has(char)", text)
            self.assertIn("escapeMode === \"backslash\"", text)
            self.assertIn("quoteStart === \"anywhere\"", text)
            self.assertNotIn("value.trim().split", text)
            self.assertEqual((project / "tests" / "test_arg_split.mjs").read_text(encoding="utf-8"), test_before)
            self.assertEqual((project / "package.json").read_text(encoding="utf-8"), package_before)
            self.assertEqual((project / "src" / "args.js").read_text(encoding="utf-8"), entry_before)

    def test_planner_no_seed_repairs_openclaw_balanced_json_js_module(self) -> None:
        """No-seed JavaScript inference may repair the second OpenClaw selected module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_balanced_json_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript balanced-json tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/balanced-json-YUc2rvlg.js"])
        text = result["operations"][0]["text"]
        self.assertIn("function extractBalancedJsonPrefix", text)
        self.assertIn("function extractBalancedJsonFragments", text)
        self.assertIn("const stack = []", text)
        self.assertIn("stack.push(char)", text)
        self.assertIn("extractBalancedJsonPrefix(raw.slice(offset), opts)", text)
        self.assertNotIn("function extractBalancedJsonPrefix(raw, opts = {}) {\n\treturn null;\n}", text)
        self.assertNotIn("function extractBalancedJsonFragments(raw, opts = {}) {\n\treturn [];\n}", text)

    def test_planner_no_seed_repairs_openclaw_json_pointer_js_module(self) -> None:
        """No-seed JavaScript inference may repair the third OpenClaw selected module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_json_pointer_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript json-pointer tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/json-pointer-BRH9eAOA.js"])
        text = result["operations"][0]["text"]
        self.assertIn("function readJsonPointer", text)
        self.assertIn("function decodeJsonPointerToken", text)
        self.assertIn("function encodeJsonPointerToken", text)
        self.assertIn("Object.hasOwn(current, token)", text)
        self.assertNotIn("return root[pointer];", text)
        self.assertNotIn("return token;", text)

    def test_planner_no_seed_repairs_openclaw_combined_js_modules(self) -> None:
        """No-seed JavaScript inference may repair multiple exact OpenClaw selected modules."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_combined_js_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript OpenClaw combined tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual(
            [item["path"] for item in result["operations"]],
            [
                "third_party/openclaw/selected/balanced-json-YUc2rvlg.js",
                "third_party/openclaw/selected/json-pointer-BRH9eAOA.js",
            ],
        )
        operations = {item["path"]: item["text"] for item in result["operations"]}
        balanced_text = operations["third_party/openclaw/selected/balanced-json-YUc2rvlg.js"]
        pointer_text = operations["third_party/openclaw/selected/json-pointer-BRH9eAOA.js"]
        self.assertIn("function extractBalancedJsonPrefix", balanced_text)
        self.assertIn("function extractBalancedJsonFragments", balanced_text)
        self.assertIn("stack.push(char)", balanced_text)
        self.assertIn("extractBalancedJsonPrefix(raw.slice(offset), opts)", balanced_text)
        self.assertNotIn("function extractBalancedJsonPrefix(raw, opts = {}) {\n\treturn null;\n}", balanced_text)
        self.assertNotIn("function extractBalancedJsonFragments(raw, opts = {}) {\n\treturn [];\n}", balanced_text)
        self.assertIn("function readJsonPointer", pointer_text)
        self.assertIn("function decodeJsonPointerToken", pointer_text)
        self.assertIn("function encodeJsonPointerToken", pointer_text)
        self.assertIn("Object.hasOwn(current, token)", pointer_text)
        self.assertNotIn("return root[pointer];", pointer_text)
        self.assertNotIn("return token;", pointer_text)

    def test_planner_no_seed_repairs_openclaw_command_poll_js_module(self) -> None:
        """No-seed JavaScript inference may repair the stateful OpenClaw command-poll module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_command_poll_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript command-poll backoff tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js"])
        text = result["operations"][0]["text"]
        self.assertIn("function calculateBackoffMs", text)
        self.assertIn("function recordCommandPoll", text)
        self.assertIn("function resetCommandPollCount", text)
        self.assertIn("function pruneStaleCommandPolls", text)
        self.assertIn("new Map()", text)
        self.assertIn("const now = Date.now()", text)
        self.assertIn("const newCount = (existing?.count ?? -1) + 1", text)
        self.assertIn("state.commandPollCounts?.delete(commandId)", text)
        self.assertIn("now - data.lastPollAt > maxAgeMs", text)
        self.assertNotIn("return 0", text)

    def test_planner_no_seed_repairs_openclaw_async_lock_js_module(self) -> None:
        """No-seed JavaScript inference may repair the OpenClaw async lock module."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_async_lock_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript async-lock tests without editing tests.",
                learning_context="off",
            )

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["inference"], {"source": "javascript_module_tests"})
        self.assertEqual([item["path"] for item in result["operations"]], ["third_party/openclaw/selected/async-lock-BcLS4KOc.js"])
        text = result["operations"][0]["text"]
        self.assertIn("function createAsyncLock", text)
        self.assertIn("let lock = Promise.resolve()", text)
        self.assertIn("const previous = lock", text)
        self.assertIn("lock = new Promise((resolve) =>", text)
        self.assertIn("await previous", text)
        self.assertIn("finally", text)
        self.assertIn("release?.()", text)
        self.assertNotIn("return await fn();\n\t};", text)

    def test_planner_no_seed_js_repair_does_not_modify_tests(self) -> None:
        """JavaScript repair planning must only produce source-file operations."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_parse_strict_integer_project(project)
            test_path = project / "tests" / "test_parse_finite_number.mjs"
            before = test_path.read_text(encoding="utf-8")
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript tests without editing tests.",
                learning_context="off",
            )

            after = test_path.read_text(encoding="utf-8")

        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(before, after)
        self.assertFalse(any(item["path"].startswith("tests/") for item in result["operations"]))

    def test_planner_no_seed_js_repair_rejects_learning_contract_aliases(self) -> None:
        """No-seed JavaScript inference must not solve approved-learning ablation prompts."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_openclaw_parse_strict_integer_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix failing JavaScript tests using approved learning contract opaque-openclaw-js.",
                learning_context="off",
            )

        self.assertFalse(result.get("ok", True), result)
        self.assertEqual(result.get("operations", []), [])

    def test_planner_no_seed_js_repair_rejects_unknown_js_task(self) -> None:
        """Unknown JavaScript modules should fail closed instead of receiving placeholder edits."""
        with self.make_project() as tmp:
            project = Path(tmp)
            source = project / "src"
            source.mkdir()
            (source / "balanced-json-YUc2rvlg.js").write_text(
                "function extractBalancedJsonPrefix(raw) {\n"
                "\treturn null;\n"
                "}\n"
                "export { extractBalancedJsonPrefix as n };\n",
                encoding="utf-8",
            )
            (project / "tests").mkdir()
            (project / "tests" / "test_balanced_json.mjs").write_text(
                "import assert from 'node:assert/strict';\n"
                "import { n as extractBalancedJsonPrefix } from '../src/balanced-json-YUc2rvlg.js';\n"
                "assert.deepEqual(extractBalancedJsonPrefix('{\"a\":1}'), { json: '{\"a\":1}', startIndex: 0, endIndex: 6 });\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Fix the failing JavaScript tests without editing tests.",
                learning_context="off",
            )

        self.assertFalse(result.get("ok", True), result)
        self.assertEqual(result.get("operations", []), [])

    def test_planner_no_seed_package_module_rejects_learning_contract_aliases(self) -> None:
        """No-seed package-module inference must not solve learning-contract ablations."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_package_label_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair mako_pkg/labels.py compact_label with approved learning contract.",
                learning_context="off",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_no_seed_infers_multi_file_subject_and_helper_from_tests(self) -> None:
        """No-seed repair may infer a narrow existing helper-module repair from tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_format_label_multifile_project(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py format_label and label_helper so the unit tests pass.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual([item["path"] for item in result["operations"]], ["subject.py", "label_helper.py"])
            self.assertIn("from label_helper import normalize_piece", result["operations"][0]["text"])
            self.assertIn("def format_label(text):", result["operations"][0]["text"])
            self.assertIn("def normalize_piece(value):", result["operations"][1]["text"])
            self.assertIn("re.sub", result["operations"][1]["text"])
            self.assertNotIn("learning_context", result)

    def test_planner_no_seed_infers_multi_function_bundle_from_tests(self) -> None:
        """No-seed repair may infer a narrow multi-function subject.py bundle from tests."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text(
                "def clean_token(value):\n"
                "    return str(value)\n\n\n"
                "def flip_items(items):\n"
                "    return list(items)\n",
                encoding="utf-8",
            )
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import clean_token, flip_items\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_clean_token(self):\n"
                "        self.assertEqual(clean_token('  Alpha  '), 'alpha')\n"
                "        self.assertEqual(clean_token('Beta MIX  '), 'beta mix')\n"
                "    def test_flip_items(self):\n"
                "        self.assertEqual(flip_items(['a', 'b', 'c']), ['c', 'b', 'a'])\n"
                "        self.assertEqual(flip_items([1, 2]), [2, 1])\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py clean_token and flip_items so the unit tests pass.",
                learning_context="off",
            )

            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["operations"], [
                {
                    "op": "write_text",
                    "path": "subject.py",
                    "text": (
                        "def clean_token(value):\n"
                        "    return str(value).strip().lower()\n\n\n"
                        "def flip_items(items):\n"
                        "    return list(reversed(items))\n"
                    ),
                }
            ])
            self.assertNotIn("learning_context", result)

    def test_planner_no_seed_bundle_rejects_learning_contract_aliases(self) -> None:
        """No-seed bundle inference must not satisfy tasks that ask for approved skill reuse."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text(
                "def clean_token(value):\n"
                "    return str(value)\n\n\n"
                "def flip_items(items):\n"
                "    return list(items)\n",
                encoding="utf-8",
            )
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import clean_token, flip_items\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_clean_token(self):\n"
                "        self.assertEqual(clean_token('  Alpha  '), 'alpha')\n"
                "        self.assertEqual(clean_token('Beta MIX  '), 'beta mix')\n"
                "    def test_flip_items(self):\n"
                "        self.assertEqual(flip_items(['a', 'b', 'c']), ['c', 'b', 'a'])\n"
                "        self.assertEqual(flip_items([1, 2]), [2, 1])\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py clean_token and flip_items with approved skill contract.",
                learning_context="off",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_no_seed_bundle_rejects_module_state_loss(self) -> None:
        """No-seed bundle inference must not drop non-function subject.py module state."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text(
                "VERSION = 'keep'\n\n\n"
                "def clean_token(value):\n"
                "    return str(value)\n\n\n"
                "def flip_items(items):\n"
                "    return list(items)\n",
                encoding="utf-8",
            )
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import clean_token, flip_items\n\n"
                "class TestSubject(unittest.TestCase):\n"
                "    def test_clean_token(self):\n"
                "        self.assertEqual(clean_token('  Alpha  '), 'alpha')\n"
                "        self.assertEqual(clean_token('Beta MIX  '), 'beta mix')\n"
                "    def test_flip_items(self):\n"
                "        self.assertEqual(flip_items(['a', 'b', 'c']), ['c', 'b', 'a'])\n"
                "        self.assertEqual(flip_items([1, 2]), [2, 1])\n",
                encoding="utf-8",
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py clean_token and flip_items so the unit tests pass.",
                learning_context="off",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_multifile_new_helper_file(self) -> None:
        """Multi-file repair skills must not create helper files outside the workspace contract."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_format_label_multifile_project(project)
            (project / "label_helper.py").unlink()
            self.install_format_label_multifile_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py format_label and label_helper with learned multi file repair contract.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_rejects_partial_named_multi_function_bundle_repair(self) -> None:
        """A task naming only one function must not silently overwrite the whole bundle."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_clean_flip_project(project)
            self.install_clean_flip_bundle_skill(project)
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair clean_token with learned clean flip bundle contract.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_malicious_hint_source(self) -> None:
        """Approved hints are parsed, but unsafe generated source is rejected."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_juno_fold_project(project)
            self.install_juno_fold_skill(
                project,
                source_override=(
                    "def juno_fold(items):\n"
                    "    __import__('os').system('echo unsafe')\n"
                    "    return []\n"
                ),
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py juno_fold with learned juno fold contract.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_indirect_builtin_escape(self) -> None:
        """Approved repair hints must not reach files/imports through dynamic builtins."""
        malicious_sources = [
            (
                "def juno_fold(items):\n"
                "    getattr(__builtins__, 'open')('/tmp/openmako_escape', 'w')\n"
                "    return []\n"
            ),
            (
                "def juno_fold(items):\n"
                "    globals()['__builtins__']['__import__']('os')\n"
                "    return []\n"
            ),
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for source in malicious_sources:
            with self.subTest(source=source), self.make_project() as tmp:
                project = Path(tmp)
                self.write_juno_fold_project(project)
                self.install_juno_fold_skill(project, source_override=source)

                result = plan_task_to_operations(
                    project,
                    "Repair subject.py juno_fold with learned juno fold contract.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_multifile_test_target(self) -> None:
        """Multi-file learned repairs must not include tests as writable targets."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_format_label_multifile_project(project)
            self.install_format_label_multifile_skill(
                project,
                files_override={
                    "subject.py": "def format_label(text):\n    return 'ok'\n",
                    "test_subject.py": "def test_hidden():\n    assert True\n",
                },
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py format_label and label_helper with learned multi file repair contract.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_multifile_reserved_module_targets(self) -> None:
        """Existing reserved module files are not valid learned repair targets."""
        from quantagent.agent_planner import plan_task_to_operations

        for helper_path in ("os.py", "__init__.py", ".hidden.py"):
            with self.subTest(helper_path=helper_path), self.make_project() as tmp:
                project = Path(tmp)
                self.write_format_label_multifile_project(project)
                (project / helper_path).write_text("def normalize_piece(value):\n    return str(value)\n", encoding="utf-8")
                self.install_format_label_multifile_skill(
                    project,
                    files_override={
                        "subject.py": (
                            f"from {Path(helper_path).stem} import normalize_piece\n\n\n"
                            "def format_label(text):\n"
                            "    return normalize_piece(text)\n"
                        ),
                        helper_path: "def normalize_piece(value):\n    return str(value).strip().lower()\n",
                    },
                )

                result = plan_task_to_operations(
                    project,
                    "Repair subject.py format_label and label_helper with learned multi file repair contract.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_function_local_import_escape(self) -> None:
        """Safe learned repairs must reject dangerous imports even inside a repair function."""
        malicious_sources = [
            (
                "def juno_fold(items):\n"
                "    import builtins\n"
                "    builtins.open('/tmp/openmako_escape', 'w')\n"
                "    return []\n"
            ),
            (
                "def juno_fold(items):\n"
                "    import importlib\n"
                "    importlib.import_module('os').system('echo unsafe')\n"
                "    return []\n"
            ),
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for source in malicious_sources:
            with self.subTest(source=source), self.make_project() as tmp:
                project = Path(tmp)
                self.write_juno_fold_project(project)
                self.install_juno_fold_skill(project, source_override=source)

                result = plan_task_to_operations(
                    project,
                    "Repair subject.py juno_fold with learned juno fold contract.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_bundle_signature_mismatch(self) -> None:
        """A bundle with matching names but incompatible signatures must fail before mutation."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_clean_flip_project(project)
            self.install_clean_flip_bundle_skill(
                project,
                source_override=(
                    "def clean_token(value, unexpected):\n"
                    "    return str(value).strip().lower()\n\n\n"
                    "def flip_items(items):\n"
                    "    return list(reversed(items))\n"
                ),
            )
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                project,
                "Repair subject.py clean_token and flip_items with learned clean flip bundle contract.",
                learning_context="on",
            )

            self.assertFalse(result.get("ok", True), result)
            self.assertEqual(result.get("operations", []), [])

    def test_planner_learning_context_rejects_dynamic_call_and_decorator(self) -> None:
        """Learned repair sources must be plain functions, not dynamic dispatch wrappers."""
        malicious_sources = [
            (
                "def juno_fold(items, marker=locals()):\n"
                "    return []\n"
            ),
            (
                "@property\n"
                "def juno_fold(items):\n"
                "    return []\n"
            ),
            (
                "def juno_fold(items):\n"
                "    name = 'str'\n"
                "    return locals()[name](items)\n"
            ),
        ]
        from quantagent.agent_planner import plan_task_to_operations

        for source in malicious_sources:
            with self.subTest(source=source), self.make_project() as tmp:
                project = Path(tmp)
                self.write_juno_fold_project(project)
                self.install_juno_fold_skill(project, source_override=source)

                result = plan_task_to_operations(
                    project,
                    "Repair subject.py juno_fold with learned juno fold contract.",
                    learning_context="on",
                )

                self.assertFalse(result.get("ok", True), result)
                self.assertEqual(result.get("operations", []), [])

    def test_agent_loop_same_step_learning_context_ablation(self) -> None:
        """Mainline loop should differ only by approved learning context."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_juno_fold_project(project)
            self.install_juno_fold_skill(project)
            test_before = (project / "test_subject.py").read_text(encoding="utf-8")
            from quantagent.agent_loop_core import run_agent_loop

            task = "Repair subject.py juno_fold with learned juno fold contract."
            off = run_agent_loop(
                project,
                task,
                explicit_mode="repair",
                include_validation=True,
                max_steps=12,
                learning_context="off",
            )
            on = run_agent_loop(
                project,
                task,
                explicit_mode="repair",
                include_validation=True,
                max_steps=12,
                learning_context="on",
            )

            self.assertFalse(off.ok, off.to_dict())
            self.assertTrue(on.ok, on.to_dict())
            off_impl = next(item for item in off.observations if item.name == "implement")
            on_impl = next(item for item in on.observations if item.name == "implement")
            self.assertFalse(off_impl.data["planner"]["ok"])
            self.assertTrue(on_impl.data["planner"]["ok"])
            self.assertEqual(on_impl.data["planner"]["learning_context"]["skill"], "hidden-juno-fold-repair")
            self.assertEqual(on_impl.data["files_touched"], ["subject.py"])
            self.assertEqual((project / "test_subject.py").read_text(encoding="utf-8"), test_before)

    def test_agent_cli_learning_context_flag_reaches_planner(self) -> None:
        """The public CLI flag must control the same planner learning path."""
        with self.make_project() as tmp:
            project = Path(tmp)
            self.write_juno_fold_project(project)
            self.install_juno_fold_skill(project)
            task = "Repair subject.py juno_fold with learned juno fold contract."
            from quantagent.cli import main

            off_stdout = io.StringIO()
            with contextlib.redirect_stdout(off_stdout):
                off_code = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        str(project),
                        "--json",
                        "--learning-context",
                        "off",
                        "--max-steps",
                        "12",
                        task,
                    ]
                )
            on_stdout = io.StringIO()
            with contextlib.redirect_stdout(on_stdout):
                on_code = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        str(project),
                        "--json",
                        "--learning-context",
                        "on",
                        "--max-steps",
                        "12",
                        task,
                    ]
                )

            off_payload = json.loads(off_stdout.getvalue())
            on_payload = json.loads(on_stdout.getvalue())
            self.assertEqual(off_code, 1, off_payload)
            self.assertEqual(on_code, 0, on_payload)
            off_impl = next(item for item in off_payload["observations"] if item["name"] == "implement")
            on_impl = next(item for item in on_payload["observations"] if item["name"] == "implement")
            self.assertFalse(off_impl["data"]["planner"]["ok"])
            self.assertEqual(on_impl["data"]["planner"]["learning_context"]["skill"], "hidden-juno-fold-repair")

    def test_agent_cli_reads_learning_context_from_separate_learning_project(self) -> None:
        """Fresh workspaces can reuse centrally approved skills without preseeded skill files."""
        with self.make_project() as workspace_tmp, self.make_project() as learning_tmp:
            workspace = Path(workspace_tmp)
            learning_project = Path(learning_tmp)
            self.write_juno_fold_project(workspace)
            self.install_juno_fold_skill(learning_project)
            task = "Repair subject.py juno_fold with learned juno fold contract."
            from quantagent.cli import main

            no_learning_project = io.StringIO()
            with contextlib.redirect_stdout(no_learning_project):
                missing_code = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        str(workspace),
                        "--json",
                        "--learning-context",
                        "on",
                        "--max-steps",
                        "12",
                        task,
                    ]
                )
            with_learning_project = io.StringIO()
            with contextlib.redirect_stdout(with_learning_project):
                reuse_code = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        str(workspace),
                        "--learning-project",
                        str(learning_project),
                        "--json",
                        "--learning-context",
                        "on",
                        "--max-steps",
                        "12",
                        task,
                    ]
                )

            missing_payload = json.loads(no_learning_project.getvalue())
            reuse_payload = json.loads(with_learning_project.getvalue())
            self.assertEqual(missing_code, 1, missing_payload)
            self.assertEqual(reuse_code, 0, reuse_payload)
            self.assertFalse((workspace / ".quantagent" / "skills" / "hidden-juno-fold-repair").exists())
            reuse_impl = next(item for item in reuse_payload["observations"] if item["name"] == "implement")
            learning_context = reuse_impl["data"]["planner"]["learning_context"]
            self.assertEqual(learning_context["skill"], "hidden-juno-fold-repair")
            self.assertEqual(learning_context["project"], str(learning_project.resolve()))

    def test_planner_adds_test_operation_for_test_request(self) -> None:
        """Planner should emit an explicit test file operation when task asks to test it."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create hello.py with greet function and test it",
            )

            self.assertTrue(result["ok"], result.get("error"))
            paths = [op["path"] for op in result["operations"]]
            self.assertIn("hello.py", paths)
            self.assertIn("tests/test_hello.py", paths)
            test_op = next(op for op in result["operations"] if op["path"] == "tests/test_hello.py")
            self.assertIn("from hello import greet", test_op["text"])
            self.assertIn("greet(\"Mako\")", test_op["text"])

    def test_planner_does_not_generate_test_for_invalid_module_name(self) -> None:
        """Planner must not generate unimportable test modules for invalid Python module names."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            result = plan_task_to_operations(
                Path(tmp),
                "create bad-name.py with a greet function and test it",
            )

            self.assertTrue(result["ok"], result.get("error"))
            paths = [op["path"] for op in result["operations"]]
            self.assertIn("bad-name.py", paths)
            self.assertNotIn("tests/test_bad-name.py", paths)
            self.assertFalse(
                any("from bad-name import" in op["text"] for op in result["operations"]),
                result["operations"],
            )

    def test_planner_rejects_absolute_path_operation(self) -> None:
        """Planner should reject tasks with absolute paths to prevent path injection."""
        with self.make_project() as tmp:
            from quantagent.agent_planner import plan_task_to_operations

            # Test Unix absolute paths
            unix_paths = [
                "create /tmp/escape.py with malicious code",
                "create /etc/passwd as a backup",
            ]
            for task in unix_paths:
                result = plan_task_to_operations(Path(tmp), task)
                self.assertFalse(
                    result.get("ok", True),
                    f"planner should reject absolute path in task: {task}"
                )
                self.assertIn("error", result, "rejection must include error message")
                self.assertIn("absolute", result["error"].lower())
                operations = result.get("operations", [])
                self.assertEqual(
                    len(operations), 0,
                    f"planner should not generate operations for absolute path: {task}"
                )

            # Test Windows absolute path (cross-platform safety)
            windows_task = r"create C:\escape.py with code"
            result = plan_task_to_operations(Path(tmp), windows_task)
            self.assertFalse(result.get("ok", True))
            self.assertIn("absolute", result.get("error", "").lower())
            self.assertEqual(result.get("operations", []), [])


def _top_level_hashes_without(source: str, excluded_name: str) -> dict[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    hashes: dict[str, str] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        if not names or excluded_name in names:
            continue
        end = getattr(node, "end_lineno", None)
        if not isinstance(end, int):
            continue
        digest = hashlib.sha256("".join(lines[node.lineno - 1 : end]).encode("utf-8")).hexdigest()
        for name in names:
            hashes[name] = digest
    return hashes


def _openclaw_balanced_json_source() -> str:
    return (
        "const CLOSING_DELIMITER = {\n"
        "\t\"{\": \"}\",\n"
        "\t\"[\": \"]\"\n"
        "};\n"
        "function isJsonOpeningDelimiter(char, openers) {\n"
        "\treturn char === \"{\" ? openers.includes(\"{\") : char === \"[\" && openers.includes(\"[\");\n"
        "}\n"
        "function extractBalancedJsonPrefix(raw, opts = {}) {\n"
        "\tconst openers = opts.openers ?? [\"{\", \"[\"];\n"
        "\tlet start = 0;\n"
        "\twhile (start < raw.length && !isJsonOpeningDelimiter(raw[start], openers)) start += 1;\n"
        "\tif (start >= raw.length) return null;\n"
        "\tconst stack = [];\n"
        "\tlet inString = false;\n"
        "\tlet escaped = false;\n"
        "\tfor (let i = start; i < raw.length; i += 1) {\n"
        "\t\tconst char = raw[i];\n"
        "\t\tif (char === void 0) break;\n"
        "\t\tif (inString) {\n"
        "\t\t\tif (escaped) escaped = false;\n"
        "\t\t\telse if (char === \"\\\\\") escaped = true;\n"
        "\t\t\telse if (char === \"\\\"\") inString = false;\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (char === \"\\\"\") {\n"
        "\t\t\tinString = true;\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (isJsonOpeningDelimiter(char, openers)) {\n"
        "\t\t\tstack.push(char);\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tconst opener = stack.at(-1);\n"
        "\t\tif (opener && char === CLOSING_DELIMITER[opener]) {\n"
        "\t\t\tstack.pop();\n"
        "\t\t\tif (stack.length === 0) return {\n"
        "\t\t\t\tjson: raw.slice(start, i + 1),\n"
        "\t\t\t\tstartIndex: start,\n"
        "\t\t\t\tendIndex: i\n"
        "\t\t\t};\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn null;\n"
        "}\n"
        "function extractBalancedJsonFragments(raw, opts = {}) {\n"
        "\tconst fragments = [];\n"
        "\tlet offset = 0;\n"
        "\twhile (offset < raw.length) {\n"
        "\t\tconst fragment = extractBalancedJsonPrefix(raw.slice(offset), opts);\n"
        "\t\tif (!fragment) break;\n"
        "\t\tfragments.push({\n"
        "\t\t\tjson: fragment.json,\n"
        "\t\t\tstartIndex: offset + fragment.startIndex,\n"
        "\t\t\tendIndex: offset + fragment.endIndex\n"
        "\t\t});\n"
        "\t\toffset += fragment.endIndex + 1;\n"
        "\t}\n"
        "\treturn fragments;\n"
        "}\n"
        "export { extractBalancedJsonPrefix as n, extractBalancedJsonFragments as t };\n"
    )


def _broken_openclaw_balanced_json_source() -> str:
    source = _openclaw_balanced_json_source()
    source = source.replace(
        "function extractBalancedJsonPrefix(raw, opts = {}) {\n"
        "\tconst openers = opts.openers ?? [\"{\", \"[\"];\n"
        "\tlet start = 0;\n"
        "\twhile (start < raw.length && !isJsonOpeningDelimiter(raw[start], openers)) start += 1;\n"
        "\tif (start >= raw.length) return null;\n"
        "\tconst stack = [];\n"
        "\tlet inString = false;\n"
        "\tlet escaped = false;\n"
        "\tfor (let i = start; i < raw.length; i += 1) {\n"
        "\t\tconst char = raw[i];\n"
        "\t\tif (char === void 0) break;\n"
        "\t\tif (inString) {\n"
        "\t\t\tif (escaped) escaped = false;\n"
        "\t\t\telse if (char === \"\\\\\") escaped = true;\n"
        "\t\t\telse if (char === \"\\\"\") inString = false;\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (char === \"\\\"\") {\n"
        "\t\t\tinString = true;\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (isJsonOpeningDelimiter(char, openers)) {\n"
        "\t\t\tstack.push(char);\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tconst opener = stack.at(-1);\n"
        "\t\tif (opener && char === CLOSING_DELIMITER[opener]) {\n"
        "\t\t\tstack.pop();\n"
        "\t\t\tif (stack.length === 0) return {\n"
        "\t\t\t\tjson: raw.slice(start, i + 1),\n"
        "\t\t\t\tstartIndex: start,\n"
        "\t\t\t\tendIndex: i\n"
        "\t\t\t};\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn null;\n"
        "}",
        "function extractBalancedJsonPrefix(raw, opts = {}) {\n"
        "\treturn null;\n"
        "}",
    )
    return source.replace(
        "function extractBalancedJsonFragments(raw, opts = {}) {\n"
        "\tconst fragments = [];\n"
        "\tlet offset = 0;\n"
        "\twhile (offset < raw.length) {\n"
        "\t\tconst fragment = extractBalancedJsonPrefix(raw.slice(offset), opts);\n"
        "\t\tif (!fragment) break;\n"
        "\t\tfragments.push({\n"
        "\t\t\tjson: fragment.json,\n"
        "\t\t\tstartIndex: offset + fragment.startIndex,\n"
        "\t\t\tendIndex: offset + fragment.endIndex\n"
        "\t\t});\n"
        "\t\toffset += fragment.endIndex + 1;\n"
        "\t}\n"
        "\treturn fragments;\n"
        "}",
        "function extractBalancedJsonFragments(raw, opts = {}) {\n"
        "\treturn [];\n"
        "}",
    )


def _openclaw_json_pointer_source() -> str:
    return (
        "function failOrUndefined(params) {\n"
        "\tif (params.onMissing === \"throw\") throw new Error(params.message);\n"
        "}\n"
        "function isJsonObject(value) {\n"
        "\treturn typeof value === \"object\" && value !== null && !Array.isArray(value);\n"
        "}\n"
        "function decodeJsonPointerToken(token) {\n"
        "\treturn token.replace(/~1/g, \"/\").replace(/~0/g, \"~\");\n"
        "}\n"
        "function encodeJsonPointerToken(token) {\n"
        "\treturn token.replace(/~/g, \"~0\").replace(/\\//g, \"~1\");\n"
        "}\n"
        "function readJsonPointer(root, pointer, options = {}) {\n"
        "\tconst onMissing = options.onMissing ?? \"throw\";\n"
        "\tif (!pointer.startsWith(\"/\")) return failOrUndefined({\n"
        "\t\tonMissing,\n"
        "\t\tmessage: \"File-backed secret ids must be absolute JSON pointers (for example: \\\"/providers/openai/apiKey\\\").\"\n"
        "\t});\n"
        "\tconst tokens = pointer.slice(1).split(\"/\").map((token) => decodeJsonPointerToken(token));\n"
        "\tlet current = root;\n"
        "\tfor (const token of tokens) {\n"
        "\t\tif (Array.isArray(current)) {\n"
        "\t\t\tconst index = Number.parseInt(token, 10);\n"
        "\t\t\tif (!Number.isFinite(index) || index < 0 || index >= current.length) return failOrUndefined({\n"
        "\t\t\t\tonMissing,\n"
        "\t\t\t\tmessage: `JSON pointer segment \"${token}\" is out of bounds.`\n"
        "\t\t\t});\n"
        "\t\t\tcurrent = current[index];\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (!isJsonObject(current)) return failOrUndefined({\n"
        "\t\t\tonMissing,\n"
        "\t\t\tmessage: `JSON pointer segment \"${token}\" does not exist.`\n"
        "\t\t});\n"
        "\t\tif (!Object.hasOwn(current, token)) return failOrUndefined({\n"
        "\t\t\tonMissing,\n"
        "\t\t\tmessage: `JSON pointer segment \"${token}\" does not exist.`\n"
        "\t\t});\n"
        "\t\tcurrent = current[token];\n"
        "\t}\n"
        "\treturn current;\n"
        "}\n"
        "export { readJsonPointer as n, encodeJsonPointerToken as t };\n"
    )


def _broken_openclaw_json_pointer_source() -> str:
    source = _openclaw_json_pointer_source()
    source = source.replace(
        "function decodeJsonPointerToken(token) {\n"
        "\treturn token.replace(/~1/g, \"/\").replace(/~0/g, \"~\");\n"
        "}",
        "function decodeJsonPointerToken(token) {\n"
        "\treturn token;\n"
        "}",
    )
    source = source.replace(
        "function encodeJsonPointerToken(token) {\n"
        "\treturn token.replace(/~/g, \"~0\").replace(/\\//g, \"~1\");\n"
        "}",
        "function encodeJsonPointerToken(token) {\n"
        "\treturn token;\n"
        "}",
    )
    return source.replace(
        "function readJsonPointer(root, pointer, options = {}) {\n"
        "\tconst onMissing = options.onMissing ?? \"throw\";\n"
        "\tif (!pointer.startsWith(\"/\")) return failOrUndefined({\n"
        "\t\tonMissing,\n"
        "\t\tmessage: \"File-backed secret ids must be absolute JSON pointers (for example: \\\"/providers/openai/apiKey\\\").\"\n"
        "\t});\n"
        "\tconst tokens = pointer.slice(1).split(\"/\").map((token) => decodeJsonPointerToken(token));\n"
        "\tlet current = root;\n"
        "\tfor (const token of tokens) {\n"
        "\t\tif (Array.isArray(current)) {\n"
        "\t\t\tconst index = Number.parseInt(token, 10);\n"
        "\t\t\tif (!Number.isFinite(index) || index < 0 || index >= current.length) return failOrUndefined({\n"
        "\t\t\t\tonMissing,\n"
        "\t\t\t\tmessage: `JSON pointer segment \"${token}\" is out of bounds.`\n"
        "\t\t\t});\n"
        "\t\t\tcurrent = current[index];\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (!isJsonObject(current)) return failOrUndefined({\n"
        "\t\t\tonMissing,\n"
        "\t\t\tmessage: `JSON pointer segment \"${token}\" does not exist.`\n"
        "\t\t});\n"
        "\t\tif (!Object.hasOwn(current, token)) return failOrUndefined({\n"
        "\t\t\tonMissing,\n"
        "\t\t\tmessage: `JSON pointer segment \"${token}\" does not exist.`\n"
        "\t\t});\n"
        "\t\tcurrent = current[token];\n"
        "\t}\n"
        "\treturn current;\n"
        "}",
        "function readJsonPointer(root, pointer, options = {}) {\n"
        "\tif (!pointer.startsWith(\"/\")) return undefined;\n"
        "\treturn root[pointer];\n"
        "}",
    )


def _openclaw_command_poll_source() -> str:
    return (
        "const BACKOFF_SCHEDULE_MS = [\n"
        "\t5e3,\n"
        "\t1e4,\n"
        "\t3e4,\n"
        "\t6e4\n"
        "];\n"
        "function calculateBackoffMs(consecutiveNoOutputPolls) {\n"
        "\treturn BACKOFF_SCHEDULE_MS[Math.min(consecutiveNoOutputPolls, BACKOFF_SCHEDULE_MS.length - 1)] ?? 6e4;\n"
        "}\n"
        "function recordCommandPoll(state, commandId, hasNewOutput) {\n"
        "\tif (!state.commandPollCounts) state.commandPollCounts = /* @__PURE__ */ new Map();\n"
        "\tconst existing = state.commandPollCounts.get(commandId);\n"
        "\tconst now = Date.now();\n"
        "\tif (hasNewOutput) {\n"
        "\t\tstate.commandPollCounts.set(commandId, {\n"
        "\t\t\tcount: 0,\n"
        "\t\t\tlastPollAt: now\n"
        "\t\t});\n"
        "\t\treturn BACKOFF_SCHEDULE_MS[0] ?? 5e3;\n"
        "\t}\n"
        "\tconst newCount = (existing?.count ?? -1) + 1;\n"
        "\tstate.commandPollCounts.set(commandId, {\n"
        "\t\tcount: newCount,\n"
        "\t\tlastPollAt: now\n"
        "\t});\n"
        "\treturn calculateBackoffMs(newCount);\n"
        "}\n"
        "function resetCommandPollCount(state, commandId) {\n"
        "\tstate.commandPollCounts?.delete(commandId);\n"
        "}\n"
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5) {\n"
        "\tif (!state.commandPollCounts) return;\n"
        "\tconst now = Date.now();\n"
        "\tfor (const [commandId, data] of state.commandPollCounts.entries()) if (now - data.lastPollAt > maxAgeMs) state.commandPollCounts.delete(commandId);\n"
        "}\n"
        "export { recordCommandPoll as n, resetCommandPollCount as r, pruneStaleCommandPolls as t };\n"
    )


def _broken_openclaw_command_poll_source() -> str:
    source = _openclaw_command_poll_source()
    source = source.replace(
        "function calculateBackoffMs(consecutiveNoOutputPolls) {\n"
        "\treturn BACKOFF_SCHEDULE_MS[Math.min(consecutiveNoOutputPolls, BACKOFF_SCHEDULE_MS.length - 1)] ?? 6e4;\n"
        "}",
        "function calculateBackoffMs(consecutiveNoOutputPolls) {\n"
        "\treturn 0;\n"
        "}",
    )
    source = source.replace(
        "function recordCommandPoll(state, commandId, hasNewOutput) {\n"
        "\tif (!state.commandPollCounts) state.commandPollCounts = /* @__PURE__ */ new Map();\n"
        "\tconst existing = state.commandPollCounts.get(commandId);\n"
        "\tconst now = Date.now();\n"
        "\tif (hasNewOutput) {\n"
        "\t\tstate.commandPollCounts.set(commandId, {\n"
        "\t\t\tcount: 0,\n"
        "\t\t\tlastPollAt: now\n"
        "\t\t});\n"
        "\t\treturn BACKOFF_SCHEDULE_MS[0] ?? 5e3;\n"
        "\t}\n"
        "\tconst newCount = (existing?.count ?? -1) + 1;\n"
        "\tstate.commandPollCounts.set(commandId, {\n"
        "\t\tcount: newCount,\n"
        "\t\tlastPollAt: now\n"
        "\t});\n"
        "\treturn calculateBackoffMs(newCount);\n"
        "}",
        "function recordCommandPoll(state, commandId, hasNewOutput) {\n"
        "\tif (!state.commandPollCounts) state.commandPollCounts = new Map();\n"
        "\tstate.commandPollCounts.set(commandId, { count: 0, lastPollAt: Date.now() });\n"
        "\treturn 0;\n"
        "}",
    )
    source = source.replace(
        "function resetCommandPollCount(state, commandId) {\n"
        "\tstate.commandPollCounts?.delete(commandId);\n"
        "}",
        "function resetCommandPollCount(state, commandId) {\n"
        "\tstate.commandPollCounts = new Map();\n"
        "}",
    )
    return source.replace(
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5) {\n"
        "\tif (!state.commandPollCounts) return;\n"
        "\tconst now = Date.now();\n"
        "\tfor (const [commandId, data] of state.commandPollCounts.entries()) if (now - data.lastPollAt > maxAgeMs) state.commandPollCounts.delete(commandId);\n"
        "}",
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5) {\n"
        "\treturn;\n"
        "}",
    )


def _openclaw_async_lock_source() -> str:
    return (
        "function createAsyncLock() {\n"
        "\tlet lock = Promise.resolve();\n"
        "\treturn async function withLock(fn) {\n"
        "\t\tconst previous = lock;\n"
        "\t\tlet release;\n"
        "\t\tlock = new Promise((resolve) => {\n"
        "\t\t\trelease = resolve;\n"
        "\t\t});\n"
        "\t\tawait previous;\n"
        "\t\ttry {\n"
        "\t\t\treturn await fn();\n"
        "\t\t} finally {\n"
        "\t\t\trelease?.();\n"
        "\t\t}\n"
        "\t};\n"
        "}\n"
        "export { createAsyncLock as t };\n"
    )


def _broken_openclaw_async_lock_source() -> str:
    return _openclaw_async_lock_source().replace(
        "function createAsyncLock() {\n"
        "\tlet lock = Promise.resolve();\n"
        "\treturn async function withLock(fn) {\n"
        "\t\tconst previous = lock;\n"
        "\t\tlet release;\n"
        "\t\tlock = new Promise((resolve) => {\n"
        "\t\t\trelease = resolve;\n"
        "\t\t});\n"
        "\t\tawait previous;\n"
        "\t\ttry {\n"
        "\t\t\treturn await fn();\n"
        "\t\t} finally {\n"
        "\t\t\trelease?.();\n"
        "\t\t}\n"
        "\t};\n"
        "}",
        "function createAsyncLock() {\n"
        "\treturn async function withLock(fn) {\n"
        "\t\treturn await fn();\n"
        "\t};\n"
        "}",
    )


def _openclaw_arg_split_source() -> str:
    return (
        "function splitArgsPreservingQuotes(value, options) {\n"
        "\tconst args = [];\n"
        "\tlet current = \"\";\n"
        "\tlet quoteChar = null;\n"
        "\tconst escapeMode = options?.escapeMode ?? \"none\";\n"
        "\tconst quoteChars = new Set(options?.quoteChars ?? [\"\\\"\"]);\n"
        "\tconst quoteStart = options?.quoteStart ?? \"anywhere\";\n"
        "\tfor (let i = 0; i < value.length; i++) {\n"
        "\t\tconst char = value[i];\n"
        "\t\tif (escapeMode === \"backslash\" && char === \"\\\\\") {\n"
        "\t\t\tif (i + 1 < value.length) {\n"
        "\t\t\t\tcurrent += value[i + 1];\n"
        "\t\t\t\ti++;\n"
        "\t\t\t}\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (escapeMode === \"backslash-quote-only\" && char === \"\\\\\" && i + 1 < value.length && value[i + 1] === \"\\\"\") {\n"
        "\t\t\tcurrent += \"\\\"\";\n"
        "\t\t\ti++;\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (quoteChars.has(char)) {\n"
        "\t\t\tif (quoteChar === char) {\n"
        "\t\t\t\tquoteChar = null;\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tconst canOpenQuote = quoteStart === \"anywhere\" || current.length === 0;\n"
        "\t\t\tif (!quoteChar && canOpenQuote) {\n"
        "\t\t\t\tquoteChar = char;\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t\tif (!quoteChar && /\\s/.test(char)) {\n"
        "\t\t\tif (current) {\n"
        "\t\t\t\targs.push(current);\n"
        "\t\t\t\tcurrent = \"\";\n"
        "\t\t\t}\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tcurrent += char;\n"
        "\t}\n"
        "\tif (current) args.push(current);\n"
        "\treturn args;\n"
        "}\n"
        "export { splitArgsPreservingQuotes as t };\n"
    )


def _broken_openclaw_arg_split_source(source: str) -> str:
    original = _openclaw_arg_split_source().removesuffix("export { splitArgsPreservingQuotes as t };\n").rstrip()
    broken = (
        "function splitArgsPreservingQuotes(value, options) {\n"
        "\treturn value.trim() ? value.trim().split(/\\s+/) : [];\n"
        "}"
    )
    if original not in source:
        raise AssertionError("OpenClaw arg-split source fingerprint changed")
    return source.replace(original, broken)


def _openclaw_parse_timeout_source() -> str:
    return (
        "function parseTimeoutMs(raw) {\n"
        "\tif (raw === void 0 || raw === null) return;\n"
        "\tlet value = NaN;\n"
        "\tif (typeof raw === \"number\") value = raw;\n"
        "\telse if (typeof raw === \"bigint\") value = Number(raw);\n"
        "\telse if (typeof raw === \"string\") {\n"
        "\t\tconst trimmed = raw.trim();\n"
        "\t\tif (!trimmed) return;\n"
        "\t\tvalue = Number.parseInt(trimmed, 10);\n"
        "\t}\n"
        "\treturn Number.isFinite(value) ? value : void 0;\n"
        "}\n"
        "function invalidTimeout(value) {\n"
        "\tconst suffix = value ? ` Received: \"${value}\".` : \"\";\n"
        "\treturn /* @__PURE__ */ new Error(`Invalid --timeout. Use a positive millisecond value, e.g. --timeout 30000.${suffix}`);\n"
        "}\n"
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {}) {\n"
        "\tif (raw === void 0 || raw === null) return fallbackMs;\n"
        "\tconst value = typeof raw === \"string\" ? raw.trim() : typeof raw === \"number\" || typeof raw === \"bigint\" ? String(raw) : null;\n"
        "\tif (value === null) {\n"
        "\t\tif (options.invalidType === \"error\") throw invalidTimeout();\n"
        "\t\treturn fallbackMs;\n"
        "\t}\n"
        "\tif (!value) return fallbackMs;\n"
        "\tconst parsed = Number.parseInt(value, 10);\n"
        "\tif (!Number.isFinite(parsed) || parsed <= 0) throw invalidTimeout(value);\n"
        "\treturn parsed;\n"
        "}\n"
        "export { parseTimeoutMsWithFallback as n, parseTimeoutMs as t };\n"
    )


def _broken_openclaw_parse_timeout_source(source: str) -> str:
    broken = source.replace(
        "function parseTimeoutMs(raw) {\n"
        "\tif (raw === void 0 || raw === null) return;\n"
        "\tlet value = NaN;\n"
        "\tif (typeof raw === \"number\") value = raw;\n"
        "\telse if (typeof raw === \"bigint\") value = Number(raw);\n"
        "\telse if (typeof raw === \"string\") {\n"
        "\t\tconst trimmed = raw.trim();\n"
        "\t\tif (!trimmed) return;\n"
        "\t\tvalue = Number.parseInt(trimmed, 10);\n"
        "\t}\n"
        "\treturn Number.isFinite(value) ? value : void 0;\n"
        "}",
        "function parseTimeoutMs(raw) {\n"
        "\treturn Number.parseInt(raw, 10) || 0;\n"
        "}",
    )
    return broken.replace(
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {}) {\n"
        "\tif (raw === void 0 || raw === null) return fallbackMs;\n"
        "\tconst value = typeof raw === \"string\" ? raw.trim() : typeof raw === \"number\" || typeof raw === \"bigint\" ? String(raw) : null;\n"
        "\tif (value === null) {\n"
        "\t\tif (options.invalidType === \"error\") throw invalidTimeout();\n"
        "\t\treturn fallbackMs;\n"
        "\t}\n"
        "\tif (!value) return fallbackMs;\n"
        "\tconst parsed = Number.parseInt(value, 10);\n"
        "\tif (!Number.isFinite(parsed) || parsed <= 0) throw invalidTimeout(value);\n"
        "\treturn parsed;\n"
        "}",
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {}) {\n"
        "\tconst parsed = Number.parseInt(raw, 10);\n"
        "\treturn Number.isFinite(parsed) ? parsed : fallbackMs;\n"
        "}",
    )


def _openclaw_async_lock_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { t as createAsyncLock } from '../third_party/openclaw/selected/async-lock-BcLS4KOc.js';\n\n"
        "function deferred() {\n"
        "  let resolve;\n"
        "  const promise = new Promise((done) => { resolve = done; });\n"
        "  return { promise, resolve };\n"
        "}\n\n"
        "const lock = createAsyncLock();\n"
        "const releaseFirst = deferred();\n"
        "const events = [];\n"
        "let active = 0;\n"
        "let maxActive = 0;\n"
        "const first = lock(async () => {\n"
        "  active += 1;\n"
        "  maxActive = Math.max(maxActive, active);\n"
        "  events.push('first-start');\n"
        "  await releaseFirst.promise;\n"
        "  events.push('first-end');\n"
        "  active -= 1;\n"
        "  return 'first';\n"
        "});\n"
        "let secondStarted = false;\n"
        "const second = lock(async () => {\n"
        "  secondStarted = true;\n"
        "  active += 1;\n"
        "  maxActive = Math.max(maxActive, active);\n"
        "  events.push('second-start');\n"
        "  active -= 1;\n"
        "  return 'second';\n"
        "});\n"
        "await Promise.resolve();\n"
        "await Promise.resolve();\n"
        "assert.equal(secondStarted, false);\n"
        "releaseFirst.resolve();\n"
        "assert.deepEqual(await Promise.all([first, second]), ['first', 'second']);\n"
        "assert.equal(maxActive, 1);\n"
        "assert.deepEqual(events, ['first-start', 'first-end', 'second-start']);\n"
        "await assert.rejects(lock(async () => { throw new Error('boom'); }), /boom/);\n"
        "assert.equal(await lock(async () => 'after'), 'after');\n"
    )


def _mako_js_labels_source() -> str:
    return (
        "function compactLabel(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn normalized.replace(/[^a-z0-9]+/g, \"-\").replace(/^-+|-+$/g, \"\");\n"
        "}\n"
        "function labelKey(value) {\n"
        "\tconst compacted = compactLabel(value);\n"
        "\treturn compacted ? `label:${compacted}` : \"label\";\n"
        "}\n"
        "export { compactLabel, labelKey };\n"
    )


def _broken_mako_js_labels_source() -> str:
    return (
        "function compactLabel(value) {\n"
        "\treturn String(value);\n"
        "}\n"
        "function labelKey(value) {\n"
        "\treturn compactLabel(value);\n"
        "}\n"
        "export { compactLabel, labelKey };\n"
    )


def _mako_js_async_records_source() -> str:
    return (
        "function normalizeUserId(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn /^[a-z0-9_-]+$/.test(normalized) ? normalized : \"\";\n"
        "}\n"
        "function summarizeUser(record) {\n"
        "\tif (!record || typeof record !== \"object\") return null;\n"
        "\tconst id = normalizeUserId(record.id);\n"
        "\tif (!id) return null;\n"
        "\tconst name = String(record.name ?? \"\").trim() || id;\n"
        "\tconst roles = Array.isArray(record.roles) ? record.roles.map((role) => String(role ?? \"\").trim().toLowerCase()).filter(Boolean).sort() : [];\n"
        "\treturn { id, name, roles };\n"
        "}\n"
        "async function loadUserSummaries(client, userIds, options = {}) {\n"
        "\tconst concurrency = Math.max(1, Math.min(Number(options.concurrency ?? 2) || 2, 5));\n"
        "\tconst ids = [...new Set(userIds.map((id) => normalizeUserId(id)).filter(Boolean))];\n"
        "\tconst users = [];\n"
        "\tconst errors = [];\n"
        "\tfor (let index = 0; index < ids.length; index += concurrency) {\n"
        "\t\tconst batch = ids.slice(index, index + concurrency);\n"
        "\t\tconst settled = await Promise.all(batch.map(async (id) => {\n"
        "\t\t\ttry {\n"
        "\t\t\t\treturn { id, record: await client.fetchUser(id) };\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\treturn { id, error };\n"
        "\t\t\t}\n"
        "\t\t}));\n"
        "\t\tfor (const item of settled) {\n"
        "\t\t\tif (item.error) {\n"
        "\t\t\t\terrors.push({ id: item.id, message: String(item.error?.message ?? item.error) });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tconst summary = summarizeUser(item.record);\n"
        "\t\t\tif (summary) users.push(summary);\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { users, errors };\n"
        "}\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser };\n"
    )


def _broken_mako_js_async_records_source() -> str:
    return (
        "function normalizeUserId(value) {\n"
        "\treturn String(value);\n"
        "}\n"
        "function summarizeUser(record) {\n"
        "\treturn record;\n"
        "}\n"
        "async function loadUserSummaries(client, userIds, options = {}) {\n"
        "\treturn { users: [], errors: [] };\n"
        "}\n"
        "export { loadUserSummaries, normalizeUserId, summarizeUser };\n"
    )


def _mako_js_io_boundary_source() -> str:
    return (
        "async function scanWorkspaceManifest(readText, root, candidateFiles) {\n"
        "\tconst normalizeRoot = (value) => {\n"
        "\t\tconst normalized = String(value ?? \"\").trim().replace(/\\\\+/g, \"/\").replace(/\\/+$/g, \"\");\n"
        "\t\treturn normalized || \".\";\n"
        "\t};\n"
        "\tconst cleanCandidate = (value) => {\n"
        "\t\tconst normalized = String(value ?? \"\").trim().replace(/\\\\+/g, \"/\").replace(/^\\/+/, \"\");\n"
        "\t\tconst parts = normalized.split(\"/\").filter(Boolean);\n"
        "\t\tif (!parts.length || parts.some((part) => part === \".\" || part === \"..\" || part.startsWith(\".\"))) return \"\";\n"
        "\t\treturn parts.join(\"/\");\n"
        "\t};\n"
        "\tconst compactName = (value) => String(value ?? \"\").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, \"-\").replace(/^-+|-+$/g, \"\");\n"
        "\tconst summarize = (path, data) => {\n"
        "\t\tif (path.endsWith(\"/package.json\")) {\n"
        "\t\t\treturn { path, kind: \"package\", name: compactName(data?.name), version: String(data?.version ?? \"\"), private: Boolean(data?.private) };\n"
        "\t\t}\n"
        "\t\tif (path.endsWith(\"mako.json\")) {\n"
        "\t\t\treturn { path, kind: \"mako\", owner: compactName(data?.owner), taskCount: Array.isArray(data?.tasks) ? data.tasks.length : 0 };\n"
        "\t\t}\n"
        "\t\treturn { path, kind: \"json\", keyCount: data && typeof data === \"object\" && !Array.isArray(data) ? Object.keys(data).length : 0 };\n"
        "\t};\n"
        "\tconst safeRoot = normalizeRoot(root);\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tfor (const candidate of candidateFiles) {\n"
        "\t\tconst clean = cleanCandidate(candidate);\n"
        "\t\tif (!clean) continue;\n"
        "\t\tconst path = `${safeRoot}/${clean}`;\n"
        "\t\ttry {\n"
        "\t\t\tconst text = await readText(path);\n"
        "\t\t\tlet data;\n"
        "\t\t\ttry {\n"
        "\t\t\t\tdata = JSON.parse(String(text ?? \"\"));\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\tinvalid.push({ path, reason: \"json\" });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tfound.push(summarize(path, data));\n"
        "\t\t} catch (error) {\n"
        "\t\t\tconst code = String(error?.code ?? \"\");\n"
        "\t\t\tif (code === \"ENOENT\") {\n"
        "\t\t\t\tmissing.push(path);\n"
        "\t\t\t} else {\n"
        "\t\t\t\terrors.push({ path, code: code || \"ERROR\" });\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { root: safeRoot, found, missing, invalid, errors };\n"
        "}\n"
        "export { scanWorkspaceManifest };\n"
    )


def _broken_mako_js_io_boundary_source() -> str:
    return (
        "async function scanWorkspaceManifest(readText, root, candidateFiles) {\n"
        "\treturn { root, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { scanWorkspaceManifest };\n"
    )


def _mako_js_fs_manifest_source() -> str:
    return (
        "import { readdir, readFile, stat } from \"node:fs/promises\";\n"
        "import path from \"node:path\";\n\n"
        "async function scanFsPackageManifest(root, options = {}) {\n"
        "\tconst rootPath = path.resolve(String(root ?? \".\"));\n"
        "\tconst maxDepth = Math.max(0, Math.min(Number(options.maxDepth ?? 2) || 2, 5));\n"
        "\tconst required = Array.isArray(options.required) ? options.required : [];\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tconst candidates = new Set(required.map((item) => String(item ?? \"\").replace(/\\\\+/g, \"/\").replace(/^\\/+/, \"\")).filter(Boolean));\n"
        "\tconst visit = async (dir, depth) => {\n"
        "\t\tif (depth > maxDepth) return;\n"
        "\t\tlet entries;\n"
        "\t\ttry {\n"
        "\t\t\tentries = await readdir(dir, { withFileTypes: true });\n"
        "\t\t} catch (error) {\n"
        "\t\t\terrors.push({ path: dir, code: String(error?.code ?? \"ERROR\") });\n"
        "\t\t\treturn;\n"
        "\t\t}\n"
        "\t\tentries.sort((left, right) => left.name.localeCompare(right.name));\n"
        "\t\tfor (const entry of entries) {\n"
        "\t\t\tif (entry.name === \"node_modules\" || entry.name.startsWith(\".\")) continue;\n"
        "\t\t\tconst fullPath = path.join(dir, entry.name);\n"
        "\t\t\tconst relative = path.relative(rootPath, fullPath).replace(/\\\\+/g, \"/\");\n"
        "\t\t\tif (entry.isDirectory()) {\n"
        "\t\t\t\tawait visit(fullPath, depth + 1);\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tif (entry.name === \"package.json\" || entry.name === \"package-lock.json\" || entry.name.endsWith(\".mako.json\")) {\n"
        "\t\t\t\tcandidates.add(relative);\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t};\n"
        "\tconst summarize = (relative, data) => {\n"
        "\t\tif (relative.endsWith(\"package-lock.json\")) {\n"
        "\t\t\tconst packages = data && typeof data === \"object\" && data.packages && typeof data.packages === \"object\" ? Object.keys(data.packages).length : 0;\n"
        "\t\t\treturn { path: relative, kind: \"package-lock\", lockfileVersion: Number(data?.lockfileVersion ?? 0), packageCount: packages };\n"
        "\t\t}\n"
        "\t\tif (relative.endsWith(\"package.json\")) {\n"
        "\t\t\tconst deps = data && typeof data === \"object\" && data.dependencies && typeof data.dependencies === \"object\" ? Object.values(data.dependencies) : [];\n"
        "\t\t\treturn { path: relative, kind: \"package\", name: String(data?.name ?? \"\"), version: String(data?.version ?? \"\"), dependencyCount: deps.length, localDependencyCount: deps.filter((value) => String(value).startsWith(\"file:\")).length };\n"
        "\t\t}\n"
        "\t\tif (relative.endsWith(\".mako.json\")) {\n"
        "\t\t\treturn { path: relative, kind: \"mako\", owner: String(data?.owner ?? \"\").trim().toLowerCase(), taskCount: Array.isArray(data?.tasks) ? data.tasks.length : 0 };\n"
        "\t\t}\n"
        "\t\treturn { path: relative, kind: \"json\" };\n"
        "\t};\n"
        "\tawait visit(rootPath, 0);\n"
        "\tfor (const relative of [...candidates].sort()) {\n"
        "\t\tif (relative.split(\"/\").some((part) => !part || part === \".\" || part === \"..\" || part.startsWith(\".\"))) continue;\n"
        "\t\ttry {\n"
        "\t\t\tconst filePath = path.join(rootPath, relative);\n"
        "\t\t\tconst info = await stat(filePath);\n"
        "\t\t\tif (!info.isFile()) continue;\n"
        "\t\t\tconst text = await readFile(filePath, \"utf8\");\n"
        "\t\t\tlet data;\n"
        "\t\t\ttry {\n"
        "\t\t\t\tdata = JSON.parse(text);\n"
        "\t\t\t} catch (error) {\n"
        "\t\t\t\tinvalid.push({ path: relative, reason: \"json\" });\n"
        "\t\t\t\tcontinue;\n"
        "\t\t\t}\n"
        "\t\t\tfound.push(summarize(relative, data));\n"
        "\t\t} catch (error) {\n"
        "\t\t\tconst code = String(error?.code ?? \"ERROR\");\n"
        "\t\t\tif (code === \"ENOENT\") missing.push(relative);\n"
        "\t\t\telse errors.push({ path: relative, code });\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn { root: rootPath, found, missing, invalid, errors };\n"
        "}\n"
        "export { scanFsPackageManifest };\n"
    )


def _broken_mako_js_fs_manifest_source() -> str:
    return (
        "import { readdir, readFile, stat } from \"node:fs/promises\";\n"
        "import path from \"node:path\";\n\n"
        "async function scanFsPackageManifest(root, options = {}) {\n"
        "\treturn { root, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { scanFsPackageManifest };\n"
    )


def _mako_js_fs_manifest_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { readFile } from 'node:fs/promises';\n"
        "import { fileURLToPath } from 'node:url';\n"
        "import path from 'node:path';\n"
        "import { scanFsPackageManifest } from '../mako_js/index.js';\n\n"
        "const workspaceRoot = fileURLToPath(new URL('../fixtures/workspace', import.meta.url));\n"
        "const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));\n"
        "assert.equal(lock.packages[''].dependencies['@openmako/local-helper'], 'file:fixtures/local-helper');\n"
        "const report = await scanFsPackageManifest(workspaceRoot, { required: ['missing.json', 'broken.json'], maxDepth: 3 });\n"
        "assert.equal(report.root, path.resolve(workspaceRoot));\n"
        "assert.deepEqual(report.found, [\n"
        "  { path: 'package.json', kind: 'package', name: ' Stage Fs ', version: '1.2.3', dependencyCount: 1, localDependencyCount: 1 },\n"
        "  { path: 'packages/core/package.json', kind: 'package', name: '@openmako/core', version: '2.0.0', dependencyCount: 0, localDependencyCount: 0 },\n"
        "  { path: 'team.mako.json', kind: 'mako', owner: 'ops', taskCount: 2 },\n"
        "]);\n"
        "assert.deepEqual(report.missing, ['missing.json']);\n"
        "assert.deepEqual(report.invalid, [{ path: 'broken.json', reason: 'json' }]);\n"
        "assert.deepEqual(report.errors, []);\n"
    )


def _mako_js_http_manifest_source() -> str:
    return (
        "function normalizePackageName(value) {\n"
        "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
        "\treturn /^[a-z0-9@/_-]+$/.test(normalized) ? normalized : \"\";\n"
        "}\n"
        "function packageUrl(baseUrl, name) {\n"
        "\tconst base = String(baseUrl ?? \"\").replace(/\\/+$/, \"\");\n"
        "\treturn `${base}/packages/${encodeURIComponent(name)}.json`;\n"
        "}\n"
        "function summarizePackage(name, data) {\n"
        "\tconst dependencies = data && typeof data === \"object\" && data.dependencies && typeof data.dependencies === \"object\" ? Object.keys(data.dependencies).sort() : [];\n"
        "\tconst tags = Array.isArray(data?.tags) ? data.tags.map((tag) => String(tag ?? \"\").trim().toLowerCase()).filter(Boolean).sort() : [];\n"
        "\treturn { name, version: String(data?.version ?? \"\"), dependencyCount: dependencies.length, tags };\n"
        "}\n"
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {}) {\n"
        "\tconst found = [];\n"
        "\tconst missing = [];\n"
        "\tconst invalid = [];\n"
        "\tconst errors = [];\n"
        "\tconst seen = new Set();\n"
        "\tfor (const rawName of packageNames) {\n"
        "\t\tconst name = normalizePackageName(rawName);\n"
        "\t\tif (!name || seen.has(name)) continue;\n"
        "\t\tseen.add(name);\n"
        "\t\tconst url = packageUrl(baseUrl, name);\n"
        "\t\tlet response;\n"
        "\t\ttry {\n"
        "\t\t\tresponse = await fetch(url, { headers: { \"accept\": \"application/json\", ...(options.headers ?? {}) } });\n"
        "\t\t} catch (error) {\n"
        "\t\t\terrors.push({ name, code: \"NETWORK\", message: String(error?.message ?? error) });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (response.status === 404) {\n"
        "\t\t\tmissing.push(name);\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tif (!response.ok) {\n"
        "\t\t\terrors.push({ name, code: `HTTP_${response.status}` });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tlet data;\n"
        "\t\ttry {\n"
        "\t\t\tdata = await response.json();\n"
        "\t\t} catch (error) {\n"
        "\t\t\tinvalid.push({ name, reason: \"json\" });\n"
        "\t\t\tcontinue;\n"
        "\t\t}\n"
        "\t\tfound.push(summarizePackage(name, data));\n"
        "\t}\n"
        "\treturn { baseUrl: String(baseUrl ?? \"\").replace(/\\/+$/, \"\"), found, missing, invalid, errors };\n"
        "}\n"
        "export { fetchPackageMetadata };\n"
    )


def _broken_mako_js_http_manifest_source() -> str:
    return (
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {}) {\n"
        "\treturn { baseUrl, found: [], missing: [], invalid: [], errors: [] };\n"
        "}\n"
        "export { fetchPackageMetadata };\n"
    )


def _mako_js_http_manifest_stage1_tests() -> str:
    return (
        "import assert from 'node:assert/strict';\n"
        "import { createServer } from 'node:http';\n"
        "import { fetchPackageMetadata } from '../mako_js/index.js';\n\n"
        "async function withServer(routes, fn) {\n"
        "  const server = createServer((request, response) => {\n"
        "    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;\n"
        "    const route = routes.get(pathname);\n"
        "    if (!route) { response.writeHead(404, { 'content-type': 'application/json' }); response.end('{\"error\":\"missing\"}'); return; }\n"
        "    response.writeHead(route.status ?? 200, { 'content-type': route.type ?? 'application/json' });\n"
        "    response.end(route.body);\n"
        "  });\n"
        "  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));\n"
        "  try { return await fn(`http://127.0.0.1:${server.address().port}/`); }\n"
        "  finally { await new Promise((resolve) => server.close(resolve)); }\n"
        "}\n\n"
        "await withServer(new Map([\n"
        "  ['/packages/alpha.json', { body: JSON.stringify({ version: '1.0.0', dependencies: { zed: '^1', beta: '^2' }, tags: ['CLI', 'Tool'] }) }],\n"
        "  ['/packages/%40scope%2Ftool.json', { body: JSON.stringify({ version: '2.5.0', dependencies: {}, tags: ['SDK'] }) }],\n"
        "  ['/packages/broken.json', { body: '{not json' }],\n"
        "  ['/packages/crash.json', { status: 500, body: JSON.stringify({ error: 'boom' }) }],\n"
        "]), async (baseUrl) => {\n"
        "  const report = await fetchPackageMetadata(baseUrl, [' Alpha ', '@scope/tool', 'missing', 'broken', 'crash', 'alpha', '../bad']);\n"
        "  assert.deepEqual(report, {\n"
        "    baseUrl: baseUrl.replace(/\\/+$/, ''),\n"
        "    found: [\n"
        "      { name: 'alpha', version: '1.0.0', dependencyCount: 2, tags: ['cli', 'tool'] },\n"
        "      { name: '@scope/tool', version: '2.5.0', dependencyCount: 0, tags: ['sdk'] },\n"
        "    ],\n"
        "    missing: ['missing'],\n"
        "    invalid: [{ name: 'broken', reason: 'json' }],\n"
        "    errors: [{ name: 'crash', code: 'HTTP_500' }],\n"
        "  });\n"
        "});\n"
    )


if __name__ == "__main__":
    unittest.main()
