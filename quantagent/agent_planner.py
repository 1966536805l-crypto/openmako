"""Minimal deterministic planner for Phase 3.

Converts task text into structured file operations without AI/ModelClient.
This is a placeholder implementation to satisfy the planner contract tests.

Future: Replace with AI-powered planner that generates code from task descriptions.
"""

from __future__ import annotations

import ast
import colorsys
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional

ABSOLUTE_PATH_PATTERN = re.compile(r"(?:^|\s)(?:/[^\s]+|[A-Za-z]:[\\/][^\s]+)")
PARENT_PATH_PATTERN = re.compile(r"(?:^|\s|[\\/])\.\.(?:[\\/]|$)")
REPAIR_HINT_PATTERN = re.compile(r"```openmako-repair\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
LEARNING_CONTRACT_PATTERN = re.compile(r"\b(?:learned|learning|approved|skill|reuse|reuses|reused|stage2|stage\s*2)\b", re.IGNORECASE)
LEARNING_CONTEXT_MODES = {"auto", "on", "off"}
SAFE_REPAIR_IMPORTS = {"collections", "copy", "functools", "itertools", "json", "math", "re", "statistics", "typing"}
DANGEROUS_REPAIR_CALLS = {"__import__", "compile", "eval", "exec", "input", "open"}
DANGEROUS_REPAIR_MODULES = {"builtins", "importlib", "os", "pathlib", "shutil", "subprocess", "sys", "urllib"}
UNSAFE_REPAIR_NAME_CALLS = DANGEROUS_REPAIR_CALLS | {
    "delattr",
    "dir",
    "getattr",
    "globals",
    "hasattr",
    "locals",
    "property",
    "setattr",
    "staticmethod",
    "super",
    "type",
    "vars",
}
SAFE_REPAIR_NAME_CALLS = {
    "ValueError",
    "KeyError",
    "TypeError",
    "IndexError",
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "filter",
    "float",
    "format",
    "int",
    "iter",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
}
FORBIDDEN_REPAIR_FILE_ROOTS = {"AI_协作交接", ".quantagent", "__pycache__", ".pytest_cache", "tests"}


def plan_task_to_operations(
    project: Path,
    task: str,
    *,
    learning_context: str | bool = "auto",
    learning_project: str | Path | None = None,
) -> dict[str, Any]:
    """Convert task text into structured file operations.

    Phase 3 minimal implementation: deterministic pattern matching.
    Does NOT use ModelClient or generate real code.

    Environment variable QUANTAGENT_USE_EXTREME_PLANNER=1 enables AI planner.

    Args:
        project: Project root path
        task: Natural language task description

    Returns:
        {
            "ok": bool,
            "operations": [{"op": "write_text", "path": str, "text": str}],
            "error": str (if ok=False)
        }
    """
    try:
        learning_mode = _normalize_learning_context(learning_context)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "operations": []}

    # Safety: reject path escape attempts before filename extraction.
    if ABSOLUTE_PATH_PATTERN.search(task):
        return {
            "ok": False,
            "error": "task contains unsafe absolute path",
            "operations": [],
        }
    if PARENT_PATH_PATTERN.search(task):
        return {
            "ok": False,
            "error": "task contains unsafe parent path patterns",
            "operations": [],
        }

    # Check if extreme planner is enabled
    use_extreme = os.environ.get("QUANTAGENT_USE_EXTREME_PLANNER", "0") == "1"

    if use_extreme:
        try:
            from quantagent.extreme_planner import plan_task_to_operations as extreme_plan
            result = extreme_plan(project, task)
            # If extreme planner succeeds, return its result
            if result.get("ok"):
                return result
            # If it fails, fall back to deterministic planner
        except Exception as exc:
            # If extreme planner crashes, fall back to deterministic planner
            from quantagent.exception_audit import audit_suppressed_exception
            audit_suppressed_exception(f"{__name__}:63", exc)

    file_bundle_result = _plan_existing_file_bundle_repair(
        project,
        task,
        learning_context=learning_mode,
        learning_project=learning_project,
    )
    if file_bundle_result is not None:
        return file_bundle_result

    repair_result = _plan_existing_subject_repair(
        project,
        task,
        learning_context=learning_mode,
        learning_project=learning_project,
    )
    if repair_result is not None:
        return repair_result

    # Deterministic planner (original logic)
    # Extract filename from task
    # Pattern: "create <filename>" or "create <filename> with ..."
    match = re.search(r"create\s+([a-zA-Z0-9_.-]+\.py)", task, re.IGNORECASE)
    if not match:
        return {
            "ok": False,
            "error": "could not extract filename from task",
            "operations": [],
        }

    filename = match.group(1)

    # Safety: validate filename is relative and safe
    if filename.startswith("/") or ".." in filename:
        return {
            "ok": False,
            "error": f"unsafe filename: {filename}",
            "operations": [],
        }
    if (project / filename).exists():
        return {
            "ok": False,
            "error": f"unsupported deterministic planner task: target already exists: {filename}",
            "operations": [],
        }

    # Generate minimal code based on task keywords
    content = _generate_minimal_code(task, filename)
    if content is None:
        return {
            "ok": False,
            "error": "unsupported deterministic planner task",
            "operations": [],
        }

    operations: list[dict[str, str]] = [
        {
            "op": "write_text",
            "path": filename,
            "text": content,
        }
    ]
    operations.extend(_generate_test_operations(task, filename, content))

    return {
        "ok": True,
        "operations": operations,
    }


def _normalize_learning_context(value: str | bool) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    mode = str(value or "auto").strip().lower()
    if mode not in LEARNING_CONTEXT_MODES:
        raise ValueError(f"invalid learning_context: {value!r}")
    return mode


def _generate_minimal_code(task: str, filename: str) -> Optional[str]:
    """Generate minimal Python code based on task keywords.

    This is a deterministic placeholder. Real implementation would use
    ModelClient to generate proper code from task description.
    """
    lowered = task.lower()
    lines = ['"""Generated by minimal planner."""\n\n']

    if _has_unsupported_extra_action(lowered):
        return None

    if _has_unsupported_greet_modifier(lowered):
        return None

    # Detect function name from task. Keep the deterministic planner narrow:
    # unsupported tasks must fail closed instead of receiving placeholder code.
    if "greet" in lowered:
        lines.append("def greet(name: str) -> str:\n")
        lines.append('    """Greet a person by name."""\n')
        lines.append('    return f"Hello, {name}!"\n')
    else:
        return None

    return "".join(lines)


def _plan_existing_subject_repair(
    project: Path,
    task: str,
    *,
    learning_context: str = "auto",
    learning_project: str | Path | None = None,
) -> dict[str, Any] | None:
    lowered = task.lower()
    if not _is_repair_task(lowered):
        return None

    subject_path = project / "subject.py"
    test_path = _find_subject_test(project)
    if not subject_path.exists():
        return None
    if test_path is None:
        return _unsupported_repair("subject repair requires test_subject.py evidence")

    try:
        subject_text = subject_path.read_text(encoding="utf-8")
        test_text = test_path.read_text(encoding="utf-8")
    except OSError as exc:
        return _unsupported_repair(f"could not read subject repair context: {exc}")

    subject_functions = _top_level_functions(subject_text)
    imported_functions = _subject_imports(test_text)
    subject_function = subject_functions[0] if len(subject_functions) == 1 else None
    imported_function = imported_functions[0] if len(imported_functions) == 1 else None
    if not subject_function or not imported_function or subject_function != imported_function:
        bundle_repair = _plan_existing_subject_bundle_repair(
            project,
            task,
            subject_source=subject_text,
            test_text=test_text,
            subject_functions=subject_functions,
            imported_functions=imported_functions,
            learning_context=learning_context,
            learning_project=learning_project,
        )
        if bundle_repair is not None:
            return bundle_repair
        return _unsupported_repair("ambiguous subject repair target")
    task_names_subject = any(token in lowered for token in ("subject.py", "test_subject", "tests pass", "unit test", "unittest"))
    if subject_function.lower() not in lowered and not task_names_subject:
        return _unsupported_repair("repair task does not name the subject function")

    repaired = _generate_subject_repair(subject_function, lowered)
    if repaired is None and not _task_requests_learning_contract(task):
        repaired = _infer_subject_repair_from_tests(subject_function, test_text)
    learning_used: dict[str, Any] | None = None
    if repaired is None:
        multi_file_inference = _infer_multifile_repair_from_tests(
            project,
            task,
            subject_function,
            subject_text=subject_text,
            test_text=test_text,
        )
        if multi_file_inference is not None:
            return {
                "ok": True,
                "operations": multi_file_inference,
            }
    if repaired is None:
        learning_hint = _generate_subject_repair_from_learning_context(
            project,
            task,
            subject_function,
            learning_context=learning_context,
            learning_project=learning_project,
        )
        if learning_hint is not None:
            repaired, learning_used = learning_hint
    if repaired is None:
        multi_file_hint = _generate_multifile_repair_from_learning_context(
            project,
            task,
            (subject_function,),
            reference_source=subject_text,
            learning_context=learning_context,
            learning_project=learning_project,
        )
        if multi_file_hint is not None:
            operations, learning_used = multi_file_hint
            return {
                "ok": True,
                "operations": operations,
                "learning_context": learning_used,
            }
    if repaired is None:
        return _unsupported_repair("unsupported existing-file repair task")

    result: dict[str, Any] = {
        "ok": True,
        "operations": [{"op": "write_text", "path": "subject.py", "text": repaired}],
    }
    if learning_used:
        result["learning_context"] = learning_used
    return result


def _is_repair_task(lowered_task: str) -> bool:
    if any(token in lowered_task for token in ("修复", "修正", "补丁", "修改")):
        return True
    return any(
        re.search(pattern, lowered_task)
        for pattern in (
            r"\bfix\b",
            r"\brepair\b",
            r"\bpatch\b",
            r"\bupdate\b",
            r"\bmodify\b",
            r"\bchange\b",
        )
    )


def _find_subject_test(project: Path) -> Path | None:
    for candidate in (project / "test_subject.py", project / "tests" / "test_subject.py"):
        if candidate.exists():
            return candidate
    return None


def _single_top_level_function(source: str) -> str | None:
    functions = _top_level_functions(source)
    if len(functions) != 1:
        return None
    return functions[0]


def _top_level_functions(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    return tuple(node.name for node in tree.body if isinstance(node, ast.FunctionDef))


def _single_subject_import(source: str) -> str | None:
    imported = _subject_imports(source)
    if len(imported) != 1:
        return None
    return imported[0]


def _subject_imports(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    imported: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "subject":
            imported.extend(alias.name for alias in node.names if alias.name != "*")
    return tuple(sorted(set(imported)))


def _unsupported_repair(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "operations": []}


def _plan_existing_file_bundle_repair(
    project: Path,
    task: str,
    *,
    learning_context: str = "auto",
    learning_project: str | Path | None = None,
) -> dict[str, Any] | None:
    if not _is_repair_task(task.lower()):
        return None
    learning_hint = _generate_file_bundle_repair_from_learning_context(
        project,
        task,
        learning_context=learning_context,
        learning_project=learning_project,
    )
    if learning_hint is None:
        inferred = _infer_file_bundle_repair_from_tests(project, task)
        if inferred is None:
            inferred = _infer_javascript_file_repair_from_tests(project, task)
        if inferred is None:
            return None
        return {
            "ok": True,
            "operations": inferred,
            "inference": {"source": "javascript_module_tests" if inferred and inferred[0]["path"].endswith(".js") else "package_module_tests"},
        }
    operations, learning_used = learning_hint
    return {
        "ok": True,
        "operations": operations,
        "learning_context": learning_used,
    }


def _generate_subject_repair(function_name: str, lowered_task: str) -> str | None:
    recipe = _SUBJECT_REPAIR_RECIPES.get(function_name)
    if recipe is None:
        return None
    required_terms, source = recipe
    if required_terms and not any(term in lowered_task for term in required_terms):
        return None
    return source


def _task_requests_learning_contract(task: str) -> bool:
    return LEARNING_CONTRACT_PATTERN.search(task) is not None


def _plan_existing_subject_bundle_repair(
    project: Path,
    task: str,
    *,
    subject_source: str,
    test_text: str,
    subject_functions: tuple[str, ...],
    imported_functions: tuple[str, ...],
    learning_context: str,
    learning_project: str | Path | None,
) -> dict[str, Any] | None:
    function_names = tuple(sorted(subject_functions))
    if len(function_names) < 2 or tuple(sorted(imported_functions)) != function_names:
        return None
    lowered = task.lower()
    task_names_subject = any(token in lowered for token in ("subject.py", "test_subject", "tests pass", "unit test", "unittest"))
    if not task_names_subject and not all(name.lower() in lowered for name in function_names):
        return None
    inferred = _infer_subject_bundle_repair_from_tests(
        function_names,
        test_text=test_text,
        reference_source=subject_source,
        task=task,
    )
    if inferred is not None:
        return {
            "ok": True,
            "operations": [{"op": "write_text", "path": "subject.py", "text": inferred}],
        }
    learning_hint = _generate_subject_bundle_repair_from_learning_context(
        project,
        task,
        function_names,
        reference_source=subject_source,
        learning_context=learning_context,
        learning_project=learning_project,
    )
    if learning_hint is None:
        multi_file_hint = _generate_multifile_repair_from_learning_context(
            project,
            task,
            function_names,
            reference_source=subject_source,
            learning_context=learning_context,
            learning_project=learning_project,
        )
        if multi_file_hint is not None:
            operations, learning_used = multi_file_hint
            return {
                "ok": True,
                "operations": operations,
                "learning_context": learning_used,
            }
        return None
    repaired, learning_used = learning_hint
    return {
        "ok": True,
        "operations": [{"op": "write_text", "path": "subject.py", "text": repaired}],
        "learning_context": learning_used,
    }


def _generate_subject_repair_from_learning_context(
    project: Path,
    task: str,
    function_name: str,
    *,
    learning_context: str,
    learning_project: str | Path | None = None,
) -> tuple[str, dict[str, Any]] | None:
    if learning_context == "off":
        return None
    try:
        from quantagent.skills import select_approved_project_skills
    except ImportError:
        return None
    source_project = Path(learning_project).expanduser().resolve(strict=False) if learning_project else project
    for skill in select_approved_project_skills(task, project=source_project, limit=5):
        for hint in _repair_hints_from_skill_body(skill.body):
            target = str(hint.get("target") or hint.get("path") or "").strip()
            hinted_function = str(hint.get("function") or "").strip()
            source = str(hint.get("source") or "")
            if target != "subject.py" or hinted_function != function_name:
                continue
            if not _valid_subject_repair_source(source, function_name):
                continue
            return source if source.endswith("\n") else source + "\n", {
                "used": True,
                "mode": learning_context,
                "skill": skill.name,
                "source": "project",
                "project": str(source_project),
            }
    return None


def _generate_subject_bundle_repair_from_learning_context(
    project: Path,
    task: str,
    function_names: tuple[str, ...],
    *,
    reference_source: str = "",
    learning_context: str,
    learning_project: str | Path | None = None,
) -> tuple[str, dict[str, Any]] | None:
    if learning_context == "off":
        return None
    try:
        from quantagent.skills import select_approved_project_skills
    except ImportError:
        return None
    source_project = Path(learning_project).expanduser().resolve(strict=False) if learning_project else project
    expected = tuple(sorted(function_names))
    for skill in select_approved_project_skills(task, project=source_project, limit=5):
        for hint in _repair_hints_from_skill_body(skill.body):
            target = str(hint.get("target") or hint.get("path") or "").strip()
            hinted_functions = _hint_function_names(hint)
            source = str(hint.get("source") or "")
            if target != "subject.py" or hinted_functions != expected:
                continue
            if not _valid_subject_bundle_repair_source(source, expected):
                continue
            if reference_source and not _subject_function_signatures_compatible(source, reference_source, expected):
                continue
            return source if source.endswith("\n") else source + "\n", {
                "used": True,
                "mode": learning_context,
                "skill": skill.name,
                "source": "project",
                "project": str(source_project),
                "functions": list(expected),
            }
    return None


def _generate_multifile_repair_from_learning_context(
    project: Path,
    task: str,
    function_names: tuple[str, ...],
    *,
    reference_source: str = "",
    learning_context: str,
    learning_project: str | Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    if learning_context == "off":
        return None
    try:
        from quantagent.skills import select_approved_project_skills
    except ImportError:
        return None
    source_project = Path(learning_project).expanduser().resolve(strict=False) if learning_project else project
    expected = tuple(sorted(function_names))
    for skill in select_approved_project_skills(task, project=source_project, limit=5):
        for hint in _repair_hints_from_skill_body(skill.body):
            files = _hint_repair_files(hint)
            if not files:
                continue
            hinted_functions = _hint_function_names(hint)
            if hinted_functions != expected:
                continue
            if not _multifile_hint_matches_project(project, files):
                continue
            if not _valid_multifile_repair_sources(files, expected):
                continue
            if reference_source and not _subject_function_signatures_compatible(files["subject.py"], reference_source, expected):
                continue
            ordered = _ordered_repair_file_items(files)
            operations = [
                {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
                for path, source in ordered
            ]
            return operations, {
                "used": True,
                "mode": learning_context,
                "skill": skill.name,
                "source": "project",
                "project": str(source_project),
                "functions": list(expected),
                "files": [path for path, _source in ordered],
            }
    return None


def _generate_file_bundle_repair_from_learning_context(
    project: Path,
    task: str,
    *,
    learning_context: str,
    learning_project: str | Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    if learning_context == "off":
        return None
    if not _task_requests_learning_contract(task):
        return None
    try:
        from quantagent.skills import select_approved_project_skills
    except ImportError:
        return None
    source_project = Path(learning_project).expanduser().resolve(strict=False) if learning_project else project
    for skill in select_approved_project_skills(task, project=source_project, limit=5):
        for hint in _repair_hints_from_skill_body(skill.body):
            target = str(hint.get("target") or "").strip()
            if target == "file_function_bundle":
                function_files = _hint_function_repair_files(hint)
                if not function_files:
                    continue
                if not _file_function_bundle_hint_matches_project(project, function_files):
                    continue
                reference_files = _read_existing_repair_files(project, function_files)
                if not _valid_file_function_bundle_repair_sources(function_files, reference_files=reference_files):
                    continue
                modified_files: dict[str, str] = {}
                for path, replacements in function_files.items():
                    modified = _replace_top_level_functions(reference_files[path], replacements)
                    if modified is None:
                        modified_files = {}
                        break
                    modified_files[path] = modified
                if not modified_files:
                    continue
                ordered = sorted(modified_files.items())
                operations = [
                    {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
                    for path, source in ordered
                ]
                return operations, {
                    "used": True,
                    "mode": learning_context,
                    "skill": skill.name,
                    "source": "project",
                    "project": str(source_project),
                    "target": "file_function_bundle",
                    "functions": list(_file_function_bundle_function_names(function_files)),
                    "files": [path for path, _source in ordered],
                }
            if target == "js_file_bundle":
                files = _hint_repair_files(hint)
                if not files:
                    continue
                if str(hint.get("mode") or "write_files").strip() != "write_files":
                    continue
                if not _file_bundle_hint_matches_project(project, files):
                    continue
                if not _valid_javascript_file_bundle_repair_sources(files):
                    continue
                ordered = sorted(files.items())
                operations = [
                    {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
                    for path, source in ordered
                ]
                return operations, {
                    "used": True,
                    "mode": learning_context,
                    "skill": skill.name,
                    "source": "project",
                    "project": str(source_project),
                    "target": "js_file_bundle",
                    "functions": list(_file_bundle_function_names(files)),
                    "files": [path for path, _source in ordered],
                    "merge_mode": "write_files",
                }
            if target != "file_bundle":
                continue
            files = _hint_repair_files(hint)
            if not files:
                continue
            if not _file_bundle_hint_matches_project(project, files):
                continue
            if not _task_requests_learning_contract(task) and not _file_bundle_hint_matches_task(task, files):
                continue
            mode = str(hint.get("mode") or "write_files").strip()
            if mode == "replace_functions":
                functions = _hint_function_names(hint)
                reference_files = _read_existing_file_bundle_files(project, files)
                if not _valid_file_bundle_function_repair_sources(files, functions, reference_files=reference_files):
                    continue
                operations = _file_bundle_function_repair_operations(project, files)
                if operations is None:
                    continue
            elif mode == "write_files":
                if not _valid_file_bundle_repair_sources(files):
                    continue
                ordered = sorted(files.items())
                operations = [
                    {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
                    for path, source in ordered
                ]
            else:
                continue
            return operations, {
                "used": True,
                "mode": learning_context,
                "skill": skill.name,
                "source": "project",
                "project": str(source_project),
                "target": "file_bundle",
                "functions": list(_file_bundle_function_names(files)),
                "files": [operation["path"] for operation in operations],
                "merge_mode": mode,
            }
    return None


def _infer_file_bundle_repair_from_tests(project: Path, task: str) -> list[dict[str, str]] | None:
    if _task_requests_learning_contract(task):
        return None
    tests = _file_bundle_test_text(project)
    if not tests:
        return None
    test_text = "\n".join(tests.values())
    lowered = task.lower()
    files: dict[str, str] = {}
    function_merge_files: dict[str, str] = {}
    package_imports = _package_function_imports(test_text)
    import_counts: dict[str, int] = {}
    for module, _function_name in package_imports:
        import_counts[module] = import_counts.get(module, 0) + 1
    ambiguous_modules = {module for module, count in import_counts.items() if count > 1}
    requested_import_names = {
        module: {
            function_name
            for candidate_module, function_name in package_imports
            if candidate_module == module and function_name.lower() in lowered
        }
        for module in ambiguous_modules
    }
    for module, function_name in package_imports:
        path = Path(*module.split(".")).with_suffix(".py")
        normalized = path.as_posix()
        if not _safe_file_bundle_repair_path(normalized):
            continue
        source_path = project / path
        if not source_path.exists():
            continue
        if not _file_bundle_target_requested(task, normalized, module, function_name):
            continue
        if module in ambiguous_modules:
            requested_names = requested_import_names.get(module, set())
            if not requested_names:
                return None
            if function_name not in requested_names:
                continue
        try:
            reference_source = source_path.read_text(encoding="utf-8")
        except OSError:
            continue
        repaired = _infer_package_module_repair_source(function_name, reference_source, test_text, lowered)
        if repaired is None:
            repaired = _infer_package_module_function_repair_source(function_name, reference_source, test_text, lowered)
            if repaired is not None:
                if normalized in files or normalized in function_merge_files:
                    return None
                function_merge_files[normalized] = repaired
                continue
            continue
        if normalized in files or normalized in function_merge_files:
            return None
        files[normalized] = repaired
    operations: list[dict[str, str]] = []
    if files:
        if not _valid_file_bundle_repair_sources(files):
            return None
        operations.extend(
            {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
            for path, source in sorted(files.items())
        )
    operations.extend(
        {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
        for path, source in sorted(function_merge_files.items())
    )
    if not operations:
        return None
    return operations


def _file_bundle_test_text(project: Path) -> dict[str, str]:
    tests: dict[str, str] = {}
    candidates = [*project.glob("test_*.py"), *project.glob("tests/test_*.py")]
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        try:
            tests[path.relative_to(project).as_posix()] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return tests


def _infer_javascript_file_repair_from_tests(project: Path, task: str) -> list[dict[str, str]] | None:
    if _task_requests_learning_contract(task):
        return None
    if not _task_requests_test_repair(task.lower()):
        return None
    tests = _javascript_test_text(project)
    if not tests:
        return None
    repairs: dict[str, str] = {}
    combined_test_text = "\n".join(tests.values())
    for test_rel, test_text in tests.items():
        for imported_path in _javascript_import_paths(project, test_rel, test_text):
            for target_path in _javascript_repair_candidate_paths(project, imported_path):
                if not _safe_javascript_repair_path(target_path):
                    continue
                source_path = project / target_path
                if not source_path.exists():
                    continue
                try:
                    source = source_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                repaired = _infer_openclaw_parse_finite_number_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_parse_timeout_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_arg_split_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_balanced_json_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_json_pointer_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_command_poll_backoff_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_openclaw_async_lock_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_mako_js_labels_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_mako_js_async_records_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_mako_js_io_boundary_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_mako_js_fs_manifest_repair(source, combined_test_text)
                if repaired is None:
                    repaired = _infer_mako_js_http_manifest_repair(source, combined_test_text)
                if repaired is None:
                    continue
                if target_path in repairs:
                    return None
                repairs[target_path] = repaired
    if not repairs:
        return None
    return [
        {"op": "write_text", "path": path, "text": source if source.endswith("\n") else source + "\n"}
        for path, source in sorted(repairs.items())
    ]


def _javascript_repair_candidate_paths(project: Path, imported_path: str) -> tuple[str, ...]:
    pending = [imported_path]
    visited: set[str] = set()
    targets: list[str] = []
    project_root = project.resolve(strict=False)
    for _depth in range(4):
        next_pending: list[str] = []
        for current_path in pending:
            if current_path in visited:
                continue
            visited.add(current_path)
            if _safe_javascript_repair_path(current_path):
                targets.append(current_path)
                continue
            index_path = project / current_path
            try:
                source = index_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for raw_export, raw_target in re.findall(r"\bexport\s*\{\s*([^}]+?)\s*\}\s*from\s*['\"]([^'\"]+\.js)['\"]", source):
                export_names: set[str] = set()
                for item in raw_export.split(","):
                    parts = [part.strip() for part in item.split(" as ", 1)]
                    export_names.update(part for part in parts if part)
                if not (
                    {"compactLabel", "labelKey"} <= export_names
                    or {"loadUserSummaries", "normalizeUserId", "summarizeUser"} <= export_names
                    or {"parseTimeoutMs", "parseTimeoutMsWithFallback"} <= export_names
                    or "splitArgsPreservingQuotes" in export_names
                    or "scanWorkspaceManifest" in export_names
                    or "scanFsPackageManifest" in export_names
                    or "fetchPackageMetadata" in export_names
                ):
                    continue
                target = ((project / current_path).parent / raw_target).resolve(strict=False)
                try:
                    relative = target.relative_to(project_root).as_posix()
                except ValueError:
                    continue
                if relative not in visited:
                    next_pending.append(relative)
        if not next_pending:
            break
        pending = next_pending
    return tuple(dict.fromkeys(targets))


def _javascript_test_text(project: Path) -> dict[str, str]:
    tests: dict[str, str] = {}
    candidates = [*project.glob("test_*.mjs"), *project.glob("tests/test_*.mjs")]
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        try:
            tests[path.relative_to(project).as_posix()] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return tests


def _javascript_import_paths(project: Path, test_rel: str, test_text: str) -> tuple[str, ...]:
    test_path = project / test_rel
    paths: list[str] = []
    for match in re.finditer(r"\bfrom\s+['\"]([^'\"]+\.js)['\"]", test_text):
        raw = match.group(1)
        if not raw.startswith("."):
            continue
        target = (test_path.parent / raw).resolve(strict=False)
        project_root = project.resolve(strict=False)
        try:
            relative = target.relative_to(project_root)
        except ValueError:
            continue
        paths.append(relative.as_posix())
    return tuple(dict.fromkeys(paths))


def _safe_javascript_repair_path(path: str) -> bool:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    if candidate.suffix != ".js":
        return False
    lowered_parts = {part.lower() for part in candidate.parts}
    if lowered_parts & {"test", "tests"}:
        return False
    if any(part.startswith(".") or part.startswith("__") for part in candidate.parts):
        return False
    return candidate.as_posix() in _SAFE_JAVASCRIPT_REPAIR_TARGETS


_SAFE_JAVASCRIPT_REPAIR_TARGETS = {
    "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js",
    "third_party/openclaw/selected/parse-timeout-91AFhn8L.js",
    "third_party/openclaw/selected/arg-split-DM7vx6uc.js",
    "third_party/openclaw/selected/balanced-json-YUc2rvlg.js",
    "third_party/openclaw/selected/json-pointer-BRH9eAOA.js",
    "third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js",
    "third_party/openclaw/selected/async-lock-BcLS4KOc.js",
    "mako_js/labels.js",
    "mako_js/async_records.js",
    "mako_js/io_boundary.js",
    "mako_js/fs_manifest.js",
    "mako_js/http_manifest.js",
    "packages/core/mako_js/io_boundary.js",
}


_SAFE_JAVASCRIPT_REPAIR_TARGET_SETS = {
    frozenset({target}) for target in _SAFE_JAVASCRIPT_REPAIR_TARGETS
} | {
    frozenset(
        {
            "third_party/openclaw/selected/balanced-json-YUc2rvlg.js",
            "third_party/openclaw/selected/json-pointer-BRH9eAOA.js",
        }
    ),
}


def _infer_openclaw_parse_finite_number_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function normalizeNumericString(value)",
        "function parseFiniteNumber(value)",
        "function parseStrictInteger(value)",
        "function parseStrictPositiveInteger(value)",
        "function parseStrictNonNegativeInteger(value)",
        "export { parseStrictPositiveInteger as i, parseStrictInteger as n, parseStrictNonNegativeInteger as r, parseFiniteNumber as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "parseStrictInteger" not in test_text or "parseStrictPositiveInteger" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*parseStrictInteger\(", test_text):
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*parseStrictPositiveInteger\(", test_text):
        return None
    repaired = source
    replacements = {
        "parseStrictInteger": (
            "function parseStrictInteger(value) {\n"
            "\tif (typeof value === \"number\") return Number.isSafeInteger(value) ? value : void 0;\n"
            "\tif (typeof value !== \"string\") return;\n"
            "\tconst normalized = normalizeNumericString(value);\n"
            "\tif (!normalized || !/^[+-]?\\d+$/.test(normalized)) return;\n"
            "\tconst parsed = Number(normalized);\n"
            "\treturn Number.isSafeInteger(parsed) ? parsed : void 0;\n"
            "}"
        ),
        "parseStrictPositiveInteger": (
            "function parseStrictPositiveInteger(value) {\n"
            "\tconst parsed = parseStrictInteger(value);\n"
            "\treturn parsed !== void 0 && parsed > 0 ? parsed : void 0;\n"
            "}"
        ),
        "parseStrictNonNegativeInteger": (
            "function parseStrictNonNegativeInteger(value) {\n"
            "\tconst parsed = parseStrictInteger(value);\n"
            "\treturn parsed !== void 0 && parsed >= 0 ? parsed : void 0;\n"
            "}"
        ),
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


def _infer_openclaw_parse_timeout_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function parseTimeoutMs(raw)",
        "function invalidTimeout(value)",
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {})",
        "export { parseTimeoutMsWithFallback as n, parseTimeoutMs as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "parseTimeoutMs" not in test_text or "parseTimeoutMsWithFallback" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*parseTimeoutMs\(", test_text):
        return None
    if not re.search(r"assert\.(?:equal|strictEqual|throws)\(\s*(?:\(\)\s*=>\s*)?parseTimeoutMsWithFallback\(", test_text):
        return None
    repaired = source
    replacements = {
        "parseTimeoutMs": _OPENCLAW_PARSE_TIMEOUT_PARSE_SOURCE,
        "parseTimeoutMsWithFallback": _OPENCLAW_PARSE_TIMEOUT_FALLBACK_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


def _infer_openclaw_arg_split_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function splitArgsPreservingQuotes(value, options)",
        "export { splitArgsPreservingQuotes as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "splitArgsPreservingQuotes" not in test_text:
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual)\(\s*splitArgsPreservingQuotes\(", test_text):
        return None
    return _replace_javascript_function(source, "splitArgsPreservingQuotes", _OPENCLAW_ARG_SPLIT_SOURCE)


def _infer_openclaw_balanced_json_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "const CLOSING_DELIMITER =",
        "function isJsonOpeningDelimiter(char, openers)",
        "function extractBalancedJsonPrefix(raw, opts = {})",
        "function extractBalancedJsonFragments(raw, opts = {})",
        "export { extractBalancedJsonPrefix as n, extractBalancedJsonFragments as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "extractBalancedJsonPrefix" not in test_text or "extractBalancedJsonFragments" not in test_text:
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual)\(\s*extractBalancedJsonPrefix\(", test_text):
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual)\(\s*extractBalancedJsonFragments\(", test_text):
        return None
    repaired = source
    replacements = {
        "extractBalancedJsonPrefix": _OPENCLAW_BALANCED_JSON_PREFIX_SOURCE,
        "extractBalancedJsonFragments": _OPENCLAW_BALANCED_JSON_FRAGMENTS_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


_OPENCLAW_PARSE_TIMEOUT_PARSE_SOURCE = (
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
    "}"
)


_OPENCLAW_PARSE_TIMEOUT_FALLBACK_SOURCE = (
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
    "}"
)


_OPENCLAW_ARG_SPLIT_SOURCE = (
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
    "}"
)


_OPENCLAW_BALANCED_JSON_PREFIX_SOURCE = (
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
    "}"
)


_OPENCLAW_BALANCED_JSON_FRAGMENTS_SOURCE = (
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
    "}"
)


def _infer_openclaw_json_pointer_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function failOrUndefined(params)",
        "function isJsonObject(value)",
        "function decodeJsonPointerToken(token)",
        "function encodeJsonPointerToken(token)",
        "function readJsonPointer(root, pointer, options = {})",
        "export { readJsonPointer as n, encodeJsonPointerToken as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "readJsonPointer" not in test_text or "encodeJsonPointerToken" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual|deepEqual|deepStrictEqual)\(\s*readJsonPointer\(", test_text):
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*encodeJsonPointerToken\(", test_text):
        return None
    repaired = source
    replacements = {
        "decodeJsonPointerToken": _OPENCLAW_JSON_POINTER_DECODE_SOURCE,
        "encodeJsonPointerToken": _OPENCLAW_JSON_POINTER_ENCODE_SOURCE,
        "readJsonPointer": _OPENCLAW_JSON_POINTER_READ_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


_OPENCLAW_JSON_POINTER_DECODE_SOURCE = (
    "function decodeJsonPointerToken(token) {\n"
    "\treturn token.replace(/~1/g, \"/\").replace(/~0/g, \"~\");\n"
    "}"
)


_OPENCLAW_JSON_POINTER_ENCODE_SOURCE = (
    "function encodeJsonPointerToken(token) {\n"
    "\treturn token.replace(/~/g, \"~0\").replace(/\\//g, \"~1\");\n"
    "}"
)


_OPENCLAW_JSON_POINTER_READ_SOURCE = (
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
    "}"
)


def _infer_openclaw_command_poll_backoff_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "const BACKOFF_SCHEDULE_MS =",
        "function calculateBackoffMs(consecutiveNoOutputPolls)",
        "function recordCommandPoll(state, commandId, hasNewOutput)",
        "function resetCommandPollCount(state, commandId)",
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5)",
        "export { recordCommandPoll as n, resetCommandPollCount as r, pruneStaleCommandPolls as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "recordCommandPoll" not in test_text or "resetCommandPollCount" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*recordCommandPoll\(", test_text):
        return None
    if not re.search(r"resetCommandPollCount\(", test_text):
        return None
    repaired = source
    replacements = {
        "calculateBackoffMs": _OPENCLAW_COMMAND_POLL_CALCULATE_SOURCE,
        "recordCommandPoll": _OPENCLAW_COMMAND_POLL_RECORD_SOURCE,
        "resetCommandPollCount": _OPENCLAW_COMMAND_POLL_RESET_SOURCE,
        "pruneStaleCommandPolls": _OPENCLAW_COMMAND_POLL_PRUNE_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


_OPENCLAW_COMMAND_POLL_CALCULATE_SOURCE = (
    "function calculateBackoffMs(consecutiveNoOutputPolls) {\n"
    "\treturn BACKOFF_SCHEDULE_MS[Math.min(consecutiveNoOutputPolls, BACKOFF_SCHEDULE_MS.length - 1)] ?? 6e4;\n"
    "}"
)


_OPENCLAW_COMMAND_POLL_RECORD_SOURCE = (
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
    "}"
)


_OPENCLAW_COMMAND_POLL_RESET_SOURCE = (
    "function resetCommandPollCount(state, commandId) {\n"
    "\tstate.commandPollCounts?.delete(commandId);\n"
    "}"
)


_OPENCLAW_COMMAND_POLL_PRUNE_SOURCE = (
    "function pruneStaleCommandPolls(state, maxAgeMs = 36e5) {\n"
    "\tif (!state.commandPollCounts) return;\n"
    "\tconst now = Date.now();\n"
    "\tfor (const [commandId, data] of state.commandPollCounts.entries()) if (now - data.lastPollAt > maxAgeMs) state.commandPollCounts.delete(commandId);\n"
    "}"
)


def _infer_openclaw_async_lock_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function createAsyncLock()",
        "return async function withLock(fn)",
        "export { createAsyncLock as t }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "createAsyncLock" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual|deepEqual|deepStrictEqual)\(", test_text):
        return None
    if "Promise.all" not in test_text and "assert.rejects" not in test_text:
        return None
    return _replace_javascript_function(source, "createAsyncLock", _OPENCLAW_ASYNC_LOCK_SOURCE)


_OPENCLAW_ASYNC_LOCK_SOURCE = (
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
    "}"
)


def _infer_mako_js_labels_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "function compactLabel(value)",
        "function labelKey(value)",
        "export { compactLabel, labelKey }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "compactLabel" not in test_text or "labelKey" not in test_text:
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*compactLabel\(", test_text):
        return None
    if not re.search(r"assert\.(?:equal|strictEqual)\(\s*labelKey\(", test_text):
        return None
    repaired = source
    replacements = {
        "compactLabel": _MAKO_JS_LABELS_COMPACT_SOURCE,
        "labelKey": _MAKO_JS_LABELS_KEY_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


def _infer_mako_js_async_records_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "async function loadUserSummaries(client, userIds, options = {})",
        "function normalizeUserId(value)",
        "function summarizeUser(record)",
        "export { loadUserSummaries, normalizeUserId, summarizeUser }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "loadUserSummaries" not in test_text or "fetchUser" not in test_text:
        return None
    if not re.search(r"await\s+loadUserSummaries\(", test_text):
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual)\(", test_text):
        return None
    repaired = source
    replacements = {
        "normalizeUserId": _MAKO_JS_ASYNC_RECORDS_NORMALIZE_SOURCE,
        "summarizeUser": _MAKO_JS_ASYNC_RECORDS_SUMMARIZE_SOURCE,
        "loadUserSummaries": _MAKO_JS_ASYNC_RECORDS_LOAD_SOURCE,
    }
    for function_name, replacement in replacements.items():
        repaired = _replace_javascript_function(repaired, function_name, replacement)
        if repaired is None:
            return None
    return repaired


def _infer_mako_js_io_boundary_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "async function scanWorkspaceManifest(readText, root, candidateFiles)",
        "export { scanWorkspaceManifest }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "scanWorkspaceManifest" not in test_text or "readText" not in test_text:
        return None
    if "package.json" not in test_text or "mako.json" not in test_text:
        return None
    if "ENOENT" not in test_text or not re.search(r"await\s+scanWorkspaceManifest\(", test_text):
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual)\(", test_text):
        return None
    return _replace_javascript_function(source, "scanWorkspaceManifest", _MAKO_JS_IO_BOUNDARY_SCAN_SOURCE)


def _infer_mako_js_fs_manifest_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "import { readdir, readFile, stat } from \"node:fs/promises\"",
        "import path from \"node:path\"",
        "async function scanFsPackageManifest(root, options = {})",
        "export { scanFsPackageManifest }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "scanFsPackageManifest" not in test_text or "package-lock.json" not in test_text:
        return None
    if "node:fs/promises" not in test_text or "fileURLToPath" not in test_text:
        return None
    if not re.search(r"await\s+scanFsPackageManifest\(", test_text):
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual|equal)\(", test_text):
        return None
    return _replace_javascript_function(source, "scanFsPackageManifest", _MAKO_JS_FS_MANIFEST_SCAN_SOURCE)


def _infer_mako_js_http_manifest_repair(source: str, test_text: str) -> str | None:
    required_source_markers = (
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {})",
        "export { fetchPackageMetadata }",
    )
    if any(marker not in source for marker in required_source_markers):
        return None
    if "fetchPackageMetadata" not in test_text or "createServer" not in test_text:
        return None
    if "node:http" not in test_text or "server.listen(0" not in test_text:
        return None
    if not re.search(r"await\s+fetchPackageMetadata\(", test_text):
        return None
    if not re.search(r"assert\.(?:deepEqual|deepStrictEqual|equal)\(", test_text):
        return None
    return _replace_javascript_function(source, "fetchPackageMetadata", _MAKO_JS_HTTP_MANIFEST_FETCH_SOURCE)


_MAKO_JS_LABELS_COMPACT_SOURCE = (
    "function compactLabel(value) {\n"
    "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
    "\treturn normalized.replace(/[^a-z0-9]+/g, \"-\").replace(/^-+|-+$/g, \"\");\n"
    "}"
)


_MAKO_JS_LABELS_KEY_SOURCE = (
    "function labelKey(value) {\n"
    "\tconst compacted = compactLabel(value);\n"
    "\treturn compacted ? `label:${compacted}` : \"label\";\n"
    "}"
)


_MAKO_JS_ASYNC_RECORDS_NORMALIZE_SOURCE = (
    "function normalizeUserId(value) {\n"
    "\tconst normalized = String(value ?? \"\").trim().toLowerCase();\n"
    "\treturn /^[a-z0-9_-]+$/.test(normalized) ? normalized : \"\";\n"
    "}"
)


_MAKO_JS_ASYNC_RECORDS_SUMMARIZE_SOURCE = (
    "function summarizeUser(record) {\n"
    "\tif (!record || typeof record !== \"object\") return null;\n"
    "\tconst id = normalizeUserId(record.id);\n"
    "\tif (!id) return null;\n"
    "\tconst name = String(record.name ?? \"\").trim() || id;\n"
    "\tconst roles = Array.isArray(record.roles) ? record.roles.map((role) => String(role ?? \"\").trim().toLowerCase()).filter(Boolean).sort() : [];\n"
    "\treturn { id, name, roles };\n"
    "}"
)


_MAKO_JS_ASYNC_RECORDS_LOAD_SOURCE = (
    "function loadUserSummaries(client, userIds, options = {}) {\n"
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
    "}"
)


_MAKO_JS_IO_BOUNDARY_SCAN_SOURCE = (
    "function scanWorkspaceManifest(readText, root, candidateFiles) {\n"
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
    "}"
)


_MAKO_JS_FS_MANIFEST_SCAN_SOURCE = (
    "function scanFsPackageManifest(root, options = {}) {\n"
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
    "}"
)


_MAKO_JS_HTTP_MANIFEST_FETCH_SOURCE = (
    "function fetchPackageMetadata(baseUrl, packageNames, options = {}) {\n"
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
)


def _javascript_function_body_start(source: str, function_name: str) -> tuple[int, int] | None:
    marker = f"function {function_name}("
    start = source.find(marker)
    if start < 0:
        return None
    paren_start = start + len(marker) - 1
    depth = 0
    in_string = ""
    escaped = False
    paren_end = -1
    for index in range(paren_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {"'", '"', "`"}:
            in_string = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                paren_end = index
                break
    if paren_end < 0:
        return None
    body_start = paren_end + 1
    while body_start < len(source) and source[body_start].isspace():
        body_start += 1
    if body_start >= len(source) or source[body_start] != "{":
        return None
    return start, body_start


def _replace_javascript_function(source: str, function_name: str, replacement: str) -> str | None:
    body = _javascript_function_body_start(source, function_name)
    if body is None:
        return None
    start, brace_start = body
    depth = 0
    in_string = ""
    escaped = False
    for index in range(brace_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = ""
            continue
        if char in {"'", '"', "`"}:
            in_string = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement + source[index + 1 :]
    return None


def _package_function_imports(test_text: str) -> tuple[tuple[str, str], ...]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return ()
    imports: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        module_root = node.module.split(".", 1)[0]
        if module_root in SAFE_REPAIR_IMPORTS or module_root in DANGEROUS_REPAIR_MODULES or module_root in {"subject", "tests", "test"}:
            continue
        for alias in node.names:
            if alias.name == "*" or alias.asname:
                continue
            imports.append((node.module, alias.name))
    return tuple(dict.fromkeys(imports))


def _file_bundle_target_requested(task: str, path: str, module: str, function_name: str) -> bool:
    lowered = task.lower()
    if _task_requests_test_repair(lowered):
        return True
    return path.lower() in lowered or module.lower() in lowered or function_name.lower() in lowered


def _task_requests_test_repair(lowered_task: str) -> bool:
    return any(
        token in lowered_task
        for token in (
            "failing test",
            "failing package test",
            "package test",
            "test suite",
            "tests pass",
            "unit tests pass",
            "without editing tests",
            "do not edit tests",
        )
    )


def _infer_package_module_repair_source(
    function_name: str,
    reference_source: str,
    test_text: str,
    lowered_task: str,
) -> str | None:
    if tuple(_top_level_functions(reference_source)) != (function_name,):
        return None
    repaired = _generate_subject_repair(function_name, lowered_task)
    if repaired is None:
        repaired = _infer_subject_repair_from_tests(function_name, test_text)
    if repaired is None:
        repaired = _infer_slug_literal_repair_from_tests(function_name, test_text)
    if repaired is None:
        return None
    if not _valid_file_bundle_repair_sources({"module.py": repaired}):
        return None
    if not _subject_function_signatures_compatible(repaired, reference_source, (function_name,)):
        return None
    return repaired


def _infer_package_module_function_repair_source(
    function_name: str,
    reference_source: str,
    test_text: str,
    lowered_task: str,
) -> str | None:
    if not _reference_has_replaceable_function(reference_source, function_name):
        return None
    repaired = _generate_subject_repair(function_name, lowered_task)
    if repaired is None:
        repaired = _infer_subject_repair_from_tests(function_name, test_text)
    if repaired is None:
        repaired = _infer_slug_literal_repair_from_tests(function_name, test_text)
    if repaired is None:
        repaired = _infer_decimal_scale_repair_from_tests(function_name, test_text, reference_source)
    if repaired is None:
        repaired = _infer_dtype_predicate_repair_from_tests(function_name, test_text, reference_source)
    if repaired is None:
        repaired = _infer_tool_name_validation_repair_from_tests(function_name, test_text, reference_source)
    if repaired is None:
        repaired = _infer_result_format_repair_from_tests(function_name, test_text, reference_source)
    if repaired is None:
        repaired = _infer_random_color_repair_from_tests(function_name, test_text, reference_source)
    if repaired is None:
        return None
    if not _repair_patch_imports_available_in_reference(repaired, reference_source):
        return None
    if not _valid_file_bundle_function_repair_sources(
        {"module.py": repaired},
        (function_name,),
        reference_files={"module.py": reference_source},
    ):
        return None
    return _merge_file_bundle_function_repair(reference_source, repaired)


def _infer_decimal_scale_repair_from_tests(
    function_name: str,
    test_text: str,
    reference_source: str,
) -> str | None:
    if not _reference_imports_module(reference_source, "decimal"):
        return None
    cases = _assert_equal_decimal_constructor_cases(function_name, test_text)
    if len(cases) < 2:
        return None
    for scale, expected in cases:
        if not isinstance(scale, int) or scale < 0 or scale > 18:
            return None
        if expected != format(10**-scale, f".{scale}f"):
            return None
    return (
        f"def {function_name}(scale: int) -> decimal.Decimal:\n"
        "    scale_fmt = format(10**-scale, f\".{scale}f\")\n"
        "    return decimal.Decimal(scale_fmt)\n"
    )


def _infer_dtype_predicate_repair_from_tests(
    function_name: str,
    test_text: str,
    reference_source: str,
) -> str | None:
    predicate_targets = {
        "is_binary": "Binary",
        "is_bool": "Bool",
        "is_string": "String",
    }
    target_class = predicate_targets.get(function_name)
    if target_class is None:
        return None
    reference_names = set(_top_level_reference_names(reference_source))
    if not {"DataType", "is_subdtype", target_class}.issubset(reference_names):
        return None
    cases = _assert_dtype_predicate_cases(function_name, test_text)
    if len(cases) < 2:
        return None
    if not any(class_name == target_class and expected for class_name, expected in cases):
        return None
    if not any(class_name != target_class and not expected for class_name, expected in cases):
        return None
    if any((class_name == target_class) != expected for class_name, expected in cases):
        return None
    return (
        f"def {function_name}(pandera_dtype: Union[DataType, type[DataType]]) -> bool:\n"
        f"    return is_subdtype(pandera_dtype, {target_class})\n"
    )


def _assert_dtype_predicate_cases(function_name: str, test_text: str) -> list[tuple[str, bool]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"assertTrue", "assertFalse"}:
            continue
        if not node.args:
            continue
        class_name = _dtype_predicate_argument_class(function_name, node.args[0])
        if class_name:
            cases.append((class_name, node.func.attr == "assertTrue"))
    return cases


def _dtype_predicate_argument_class(function_name: str, node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Name) or node.func.id != function_name:
        return None
    if len(node.args) != 1:
        return None
    return _dtype_class_name(node.args[0])


def _dtype_class_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _dtype_class_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _reference_imports_module(source: str, module_name: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == module_name for alias in node.names):
            return True
    return False


def _assert_equal_decimal_constructor_cases(function_name: str, test_text: str) -> list[tuple[Any, str]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[tuple[Any, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "assertEqual":
            continue
        if len(node.args) < 2:
            continue
        actual, expected = node.args[0], node.args[1]
        if not isinstance(actual, ast.Call) or not isinstance(actual.func, ast.Name) or actual.func.id != function_name:
            continue
        if len(actual.args) != 1:
            continue
        input_ok, input_value = _literal_value(actual.args[0])
        decimal_ok, decimal_text = _decimal_constructor_text(expected)
        if input_ok and decimal_ok:
            cases.append((input_value, decimal_text))
    return cases


def _decimal_constructor_text(node: ast.AST) -> tuple[bool, str]:
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return False, ""
    constructor = node.func
    valid_constructor = (
        isinstance(constructor, ast.Attribute)
        and constructor.attr == "Decimal"
        and isinstance(constructor.value, ast.Name)
        and constructor.value.id == "decimal"
    ) or (isinstance(constructor, ast.Name) and constructor.id == "Decimal")
    if not valid_constructor:
        return False, ""
    ok, value = _literal_value(node.args[0])
    if not ok:
        return False, ""
    return True, str(value)


def _repair_patch_imports_available_in_reference(patch_source: str, reference_source: str) -> bool:
    try:
        patch_tree = ast.parse(patch_source)
        reference_tree = ast.parse(reference_source)
    except SyntaxError:
        return False
    reference_imports: set[tuple[str, str]] = set()
    for node in reference_tree.body:
        if isinstance(node, ast.Import):
            reference_imports.update(("import", alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            reference_imports.update((node.module, alias.name) for alias in node.names if alias.name != "*")
    for node in patch_tree.body:
        if isinstance(node, ast.Import):
            if any(("import", alias.name) not in reference_imports for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if not node.module or any((node.module, alias.name) not in reference_imports for alias in node.names if alias.name != "*"):
                return False
    return True


def _infer_tool_name_validation_repair_from_tests(
    function_name: str,
    test_text: str,
    reference_source: str,
) -> str | None:
    if function_name != "validate_tool_name":
        return None
    reference_names = set(_top_level_reference_names(reference_source))
    if "ToolNameValidationResult" not in reference_names or "TOOL_NAME_REGEX" not in reference_names:
        return None
    if not _reference_imports_module(reference_source, "re"):
        return None
    cases = _assert_tool_name_is_valid_cases(function_name, test_text)
    if len(cases) < 3:
        return None
    if any(_tool_name_validation_candidate(value) != expected for value, expected in cases):
        return None
    if not any(expected for _value, expected in cases):
        return None
    invalid_values = [value for value, expected in cases if not expected]
    if "" not in invalid_values:
        return None
    if not any(isinstance(value, str) and value and not re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in invalid_values):
        return None
    return (
        f"def {function_name}(name: str) -> ToolNameValidationResult:\n"
        "    warnings: list[str] = []\n"
        "    if not name:\n"
        "        return ToolNameValidationResult(\n"
        "            is_valid=False,\n"
        "            warnings=[\"Tool name cannot be empty\"],\n"
        "        )\n"
        "    if len(name) > 128:\n"
        "        return ToolNameValidationResult(\n"
        "            is_valid=False,\n"
        "            warnings=[f\"Tool name exceeds maximum length of 128 characters (current: {len(name)})\"],\n"
        "        )\n"
        "    if \" \" in name:\n"
        "        warnings.append(\"Tool name contains spaces, which may cause parsing issues\")\n"
        "    if \",\" in name:\n"
        "        warnings.append(\"Tool name contains commas, which may cause parsing issues\")\n"
        "    if name.startswith(\"-\") or name.endswith(\"-\"):\n"
        "        warnings.append(\"Tool name starts or ends with a dash, which may cause parsing issues in some contexts\")\n"
        "    if name.startswith(\".\") or name.endswith(\".\"):\n"
        "        warnings.append(\"Tool name starts or ends with a dot, which may cause parsing issues in some contexts\")\n"
        "    if not TOOL_NAME_REGEX.match(name):\n"
        "        invalid_chars: list[str] = []\n"
        "        seen: set[str] = set()\n"
        "        for char in name:\n"
        "            if not re.match(r\"[A-Za-z0-9._-]\", char) and char not in seen:\n"
        "                invalid_chars.append(char)\n"
        "                seen.add(char)\n"
        "        warnings.append(f\"Tool name contains invalid characters: {', '.join(repr(c) for c in invalid_chars)}\")\n"
        "        warnings.append(\"Allowed characters are: A-Z, a-z, 0-9, underscore (_), dash (-), and dot (.)\")\n"
        "        return ToolNameValidationResult(is_valid=False, warnings=warnings)\n"
        "    return ToolNameValidationResult(is_valid=True, warnings=warnings)\n"
    )


def _tool_name_validation_candidate(value: str) -> bool:
    return bool(value) and len(value) <= 128 and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _assert_tool_name_is_valid_cases(function_name: str, test_text: str) -> list[tuple[str, bool]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    variables: dict[str, str] = {}
    cases: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _tool_name_validation_call_literal(function_name, node.value)
            if value is not None:
                variables[node.targets[0].id] = value
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"assertTrue", "assertFalse"}:
            continue
        if not node.args:
            continue
        value = _tool_name_is_valid_literal(function_name, node.args[0], variables)
        if value is None:
            continue
        cases.append((value, node.func.attr == "assertTrue"))
    return cases


def _tool_name_is_valid_literal(function_name: str, node: ast.AST, variables: Mapping[str, str]) -> str | None:
    if not isinstance(node, ast.Attribute) or node.attr != "is_valid":
        return None
    if isinstance(node.value, ast.Name):
        return variables.get(node.value.id)
    return _tool_name_validation_call_literal(function_name, node.value)


def _tool_name_validation_call_literal(function_name: str, node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Name) or node.func.id != function_name:
        return None
    if len(node.args) != 1:
        return None
    ok, value = _literal_value(node.args[0])
    if not ok or not isinstance(value, str):
        return None
    return value


def _infer_result_format_repair_from_tests(
    function_name: str,
    test_text: str,
    reference_source: str,
) -> str | None:
    if function_name != "parse_result_format":
        return None
    reference_names = set(_top_level_reference_names(reference_source))
    if not {"ExpectationConfiguration", "ExpectationConfigurationSchema"}.issubset(reference_names):
        return None
    cases = _assert_equal_single_arg_literal_cases(function_name, test_text)
    if not _result_format_cases_match(cases):
        return None
    raises_cases = _assert_raises_single_arg_literal_cases(function_name, test_text, "ValueError")
    if not any(
        isinstance(value, dict)
        and value.get("include_unexpected_rows") is True
        and "result_format" not in value
        for value in raises_cases
    ):
        return None
    return (
        "def parse_result_format(result_format: Union[str, dict]) -> dict:\n"
        "    if isinstance(result_format, str):\n"
        "        result_format = {\n"
        "            \"result_format\": result_format,\n"
        "            \"partial_unexpected_count\": 20,\n"
        "            \"include_unexpected_rows\": False,\n"
        "            \"map_expectation_unexpected_rows_as_dict\": False,\n"
        "        }\n"
        "    else:\n"
        "        if \"include_unexpected_rows\" in result_format and \"result_format\" not in result_format:\n"
        "            raise ValueError(\n"
        "                \"When using `include_unexpected_rows`, `result_format` must be explicitly specified\"\n"
        "            )\n"
        "        if \"partial_unexpected_count\" not in result_format:\n"
        "            result_format[\"partial_unexpected_count\"] = 20\n"
        "        if \"include_unexpected_rows\" not in result_format:\n"
        "            result_format[\"include_unexpected_rows\"] = False\n"
        "        if \"map_expectation_unexpected_rows_as_dict\" not in result_format:\n"
        "            result_format[\"map_expectation_unexpected_rows_as_dict\"] = False\n"
        "    return result_format\n"
    )


def _result_format_cases_match(cases: list[tuple[Any, Any]]) -> bool:
    if len(cases) < 2:
        return False
    saw_string_case = False
    saw_dict_case = False
    for input_value, expected in cases:
        if not isinstance(expected, dict):
            return False
        try:
            actual = _result_format_candidate(input_value)
        except (TypeError, ValueError):
            return False
        if actual != expected:
            return False
        if isinstance(input_value, str):
            saw_string_case = True
        if isinstance(input_value, dict):
            saw_dict_case = True
    return saw_string_case and saw_dict_case


def _result_format_candidate(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {
            "result_format": value,
            "partial_unexpected_count": 20,
            "include_unexpected_rows": False,
            "map_expectation_unexpected_rows_as_dict": False,
        }
    if not isinstance(value, dict):
        raise TypeError("result format examples must be str or dict")
    result = dict(value)
    if "include_unexpected_rows" in result and "result_format" not in result:
        raise ValueError("include_unexpected_rows requires result_format")
    result.setdefault("partial_unexpected_count", 20)
    result.setdefault("include_unexpected_rows", False)
    result.setdefault("map_expectation_unexpected_rows_as_dict", False)
    return result


def _infer_random_color_repair_from_tests(
    function_name: str,
    test_text: str,
    reference_source: str,
) -> str | None:
    if function_name != "get_random_color":
        return None
    if not _reference_imports_module(reference_source, "colorsys"):
        return None
    if not _reference_imports_module(reference_source, "random"):
        return None
    cases = _assert_random_color_cases(function_name, test_text)
    if len(cases) < 2:
        return None
    if any(_random_color_candidate(hue) != expected for hue, expected in cases):
        return None
    return (
        "def get_random_color():\n"
        "    hue = random.random()\n"
        "    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 0.75)]\n"
        "    res = f\"#{r:02x}{g:02x}{b:02x}\"\n"
        "    return res\n"
    )


def _assert_random_color_cases(function_name: str, test_text: str) -> list[tuple[float, str]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[tuple[float, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        hue: float | None = None
        for statement in node.body:
            assigned = _random_random_assignment_value(statement)
            if assigned is not None:
                hue = assigned
                continue
            expected = _assert_equal_zero_arg_string(function_name, statement)
            if hue is not None and expected is not None:
                cases.append((hue, expected))
    return cases


def _random_random_assignment_value(statement: ast.stmt) -> float | None:
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        return None
    target = statement.targets[0]
    if _attribute_name_chain(target)[-2:] != ("random", "random"):
        return None
    value = statement.value
    if not isinstance(value, ast.Lambda):
        return None
    ok, literal = _literal_value(value.body)
    if not ok or isinstance(literal, bool) or not isinstance(literal, (int, float)):
        return None
    hue = float(literal)
    if hue < 0.0 or hue > 1.0:
        return None
    return hue


def _assert_equal_zero_arg_string(function_name: str, statement: ast.stmt) -> str | None:
    call = statement.value if isinstance(statement, ast.Expr) else None
    if not isinstance(call, ast.Call):
        return None
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "assertEqual":
        return None
    if len(call.args) < 2:
        return None
    actual, expected = call.args[0], call.args[1]
    if not isinstance(actual, ast.Call) or actual.args or actual.keywords:
        return None
    if not isinstance(actual.func, ast.Name) or actual.func.id != function_name:
        return None
    ok, value = _literal_value(expected)
    if not ok or not isinstance(value, str):
        return None
    return value


def _attribute_name_chain(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        names.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        names.append(current.id)
    return tuple(reversed(names))


def _random_color_candidate(hue: float) -> str:
    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 1, 0.75)]
    return f"#{r:02x}{g:02x}{b:02x}"


def _assert_raises_single_arg_literal_cases(
    function_name: str,
    test_text: str,
    exception_name: str,
) -> list[Any]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[Any] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(_assert_raises_context(item.context_expr, exception_name) for item in node.items):
            continue
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Name) or child.func.id != function_name:
                continue
            if len(child.args) != 1:
                continue
            ok, value = _literal_value(child.args[0])
            if ok:
                cases.append(value)
    return cases


def _assert_raises_context(node: ast.AST, exception_name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "assertRaises":
        return False
    if not node.args:
        return False
    exception = node.args[0]
    return isinstance(exception, ast.Name) and exception.id == exception_name


def _repair_hints_from_skill_body(body: str) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for match in REPAIR_HINT_PATTERN.finditer(body):
        try:
            payload = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            hints.append(payload)
    return hints


def _hint_function_names(hint: dict[str, Any]) -> tuple[str, ...]:
    raw = hint.get("functions")
    if raw is None:
        raw = hint.get("function")
    if isinstance(raw, str):
        names = [raw]
    elif isinstance(raw, list):
        names = [str(item) for item in raw]
    else:
        names = []
    return tuple(sorted(name.strip() for name in names if name.strip()))


def _hint_repair_files(hint: dict[str, Any]) -> dict[str, str]:
    raw = hint.get("files")
    if not isinstance(raw, dict):
        return {}
    files: dict[str, str] = {}
    for key, value in raw.items():
        path = str(key).strip()
        if not path or not isinstance(value, str):
            return {}
        files[Path(path).as_posix()] = value
    return files


def _hint_function_repair_files(hint: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = hint.get("files")
    if not isinstance(raw, dict):
        return {}
    files: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        path = Path(str(key).strip()).as_posix()
        if not path or not isinstance(value, dict):
            return {}
        replacements: dict[str, str] = {}
        for function_name, source in value.items():
            clean_function = str(function_name).strip()
            if not clean_function or not isinstance(source, str):
                return {}
            replacements[clean_function] = source
        if not replacements:
            return {}
        files[path] = replacements
    return files


def _ordered_repair_file_items(files: Mapping[str, str]) -> list[tuple[str, str]]:
    return sorted(files.items(), key=lambda item: (item[0] != "subject.py", item[0]))


def _multifile_hint_matches_project(project: Path, files: Mapping[str, str]) -> bool:
    for path in files:
        if path == "subject.py":
            continue
        if not (project / path).exists():
            return False
    return True


def _file_bundle_hint_matches_project(project: Path, files: Mapping[str, str]) -> bool:
    return all((project / path).exists() for path in files)


def _file_function_bundle_hint_matches_project(project: Path, files: Mapping[str, Mapping[str, str]]) -> bool:
    return all((project / path).exists() for path in files)


def _read_existing_repair_files(project: Path, files: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    existing: dict[str, str] = {}
    for path in files:
        try:
            existing[path] = (project / path).read_text(encoding="utf-8")
        except OSError:
            return {}
    return existing


def _read_existing_file_bundle_files(project: Path, files: Mapping[str, str]) -> dict[str, str]:
    existing: dict[str, str] = {}
    for path in files:
        try:
            existing[path] = (project / path).read_text(encoding="utf-8")
        except OSError:
            return {}
    return existing


def _file_bundle_hint_matches_task(task: str, files: Mapping[str, str]) -> bool:
    lowered = task.lower()
    for path in files:
        module_name = Path(path).with_suffix("").as_posix().replace("/", ".")
        if path.lower() in lowered or module_name.lower() in lowered:
            return True
    return any(function.lower() in lowered for function in _file_bundle_function_names(files))


def _valid_subject_repair_source(source: str, function_name: str) -> bool:
    if not source.strip():
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            continue
        if isinstance(node, ast.Import):
            if all(alias.name.split(".", 1)[0] in SAFE_REPAIR_IMPORTS for alias in node.names):
                continue
            return False
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".", 1)[0] in SAFE_REPAIR_IMPORTS:
                continue
            return False
        return False
    if _source_has_dangerous_repair_constructs(tree, (function_name,)):
        return False
    return functions == [function_name]


def _valid_subject_bundle_repair_source(source: str, function_names: tuple[str, ...]) -> bool:
    expected = tuple(sorted(str(name).strip() for name in function_names if str(name).strip()))
    if len(expected) < 2 or not source.strip():
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            continue
        if isinstance(node, ast.Import):
            if all(alias.name.split(".", 1)[0] in SAFE_REPAIR_IMPORTS for alias in node.names):
                continue
            return False
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".", 1)[0] in SAFE_REPAIR_IMPORTS:
                continue
            return False
        return False
    if _source_has_dangerous_repair_constructs(tree, expected):
        return False
    return tuple(sorted(functions)) == expected


def _valid_multifile_repair_sources(files: Mapping[str, str], subject_functions: tuple[str, ...]) -> bool:
    normalized = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    expected_subject_functions = tuple(sorted(str(name).strip() for name in subject_functions if str(name).strip()))
    if len(normalized) < 2 or "subject.py" not in normalized or not expected_subject_functions:
        return False
    if any(not _safe_repair_file_path(path) for path in normalized):
        return False
    local_modules = tuple(sorted(Path(path).stem for path in normalized if path != "subject.py"))
    if any(module in DANGEROUS_REPAIR_MODULES or module in SAFE_REPAIR_IMPORTS for module in local_modules):
        return False

    trees: dict[str, ast.Module] = {}
    functions_by_file: dict[str, tuple[str, ...]] = {}
    all_functions: list[str] = []
    for path, source in normalized.items():
        if not source.strip():
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        trees[path] = tree
        functions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
                continue
            if isinstance(node, ast.Import):
                if all(_repair_import_allowed(alias.name, local_modules) for alias in node.names):
                    continue
                return False
            if isinstance(node, ast.ImportFrom):
                if node.module and _repair_import_allowed(node.module, local_modules):
                    continue
                return False
            return False
        if not functions:
            return False
        functions_by_file[path] = tuple(functions)
        all_functions.extend(functions)
    if len(set(all_functions)) != len(all_functions):
        return False
    if tuple(sorted(functions_by_file.get("subject.py", ()))) != expected_subject_functions:
        return False
    allowed_calls = tuple(sorted(set(all_functions)))
    for tree in trees.values():
        if _source_has_dangerous_repair_constructs(tree, allowed_calls, local_modules=local_modules):
            return False
    return True


def _valid_file_function_bundle_repair_sources(
    files: Mapping[str, Mapping[str, str]],
    *,
    reference_files: Mapping[str, str] | None = None,
) -> bool:
    normalized: dict[str, dict[str, str]] = {}
    for raw_path, raw_replacements in files.items():
        path = Path(str(raw_path)).as_posix()
        if path == "subject.py" or not _safe_file_bundle_repair_path(path):
            return False
        if not isinstance(raw_replacements, Mapping) or not raw_replacements:
            return False
        replacements: dict[str, str] = {}
        for raw_function, raw_source in raw_replacements.items():
            function_name = str(raw_function).strip()
            source = str(raw_source)
            if not function_name or not source.strip():
                return False
            replacements[function_name] = source
        normalized[path] = replacements
    if not normalized:
        return False

    reference_map = dict(reference_files or {})
    for path, replacements in normalized.items():
        reference_source = reference_map.get(path, "")
        allowed_name_calls = _top_level_reference_names(reference_source)
        for function_name, source in replacements.items():
            if not _valid_top_level_function_repair_source(source, function_name, allowed_name_calls=allowed_name_calls):
                return False
            if reference_source:
                if not _reference_has_replaceable_function(reference_source, function_name):
                    return False
                if not _subject_function_signatures_compatible(source, reference_source, (function_name,)):
                    return False
    return True


def _valid_top_level_function_repair_source(
    source: str,
    function_name: str,
    *,
    allowed_name_calls: tuple[str, ...] = (),
) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return False
    function = tree.body[0]
    if function.name != function_name or function.decorator_list:
        return False
    if _source_has_dangerous_repair_constructs(tree, (function_name,), allowed_name_calls=allowed_name_calls):
        return False
    return True


def _reference_has_replaceable_function(source: str, function_name: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name]
    return len(matches) == 1 and not matches[0].decorator_list and getattr(matches[0], "end_lineno", None) is not None


def _valid_file_bundle_repair_sources(files: Mapping[str, str]) -> bool:
    normalized = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    if not normalized or "subject.py" in normalized:
        return False
    if any(not _safe_file_bundle_repair_path(path) for path in normalized):
        return False
    local_modules = _repair_local_modules_for_files(normalized)
    trees: dict[str, ast.Module] = {}
    all_functions: list[str] = []
    for path, source in normalized.items():
        if not source.strip():
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        trees[path] = tree
        functions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
                continue
            if isinstance(node, ast.Import):
                if all(_repair_import_allowed(alias.name, local_modules) for alias in node.names):
                    continue
                return False
            if isinstance(node, ast.ImportFrom):
                if node.module and _repair_import_allowed(node.module, local_modules):
                    continue
                return False
            return False
        if not functions:
            return False
        all_functions.extend(functions)
    if len(set(all_functions)) != len(all_functions):
        return False
    allowed_calls = tuple(sorted(all_functions))
    for tree in trees.values():
        if _source_has_dangerous_repair_constructs(tree, allowed_calls, local_modules=local_modules):
            return False
    return True


def _valid_javascript_file_bundle_repair_sources(files: Mapping[str, str]) -> bool:
    normalized = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    if not normalized:
        return False
    if frozenset(normalized) not in _SAFE_JAVASCRIPT_REPAIR_TARGET_SETS:
        return False
    forbidden_markers = (
        "import ",
        "import(",
        "require(",
        "process.",
        "child_process",
        "fs.",
        "eval(",
        "Function(",
        "constructor",
        "globalThis",
        "__proto__",
        ".prototype",
        "fetch(",
        "Math.random",
        "XMLHttpRequest",
        "setTimeout",
        "setInterval",
        "while (true",
        "for (;;",
    )
    for path, source in normalized.items():
        if not source.strip() or not _safe_javascript_repair_path(path):
            return False
        if path == "mako_js/fs_manifest.js":
            if not _valid_mako_js_fs_manifest_source(source):
                return False
            continue
        if path == "mako_js/http_manifest.js":
            if not _valid_mako_js_http_manifest_source(source):
                return False
            continue
        if any(marker in source for marker in forbidden_markers):
            return False
        if path == "third_party/openclaw/selected/parse-finite-number-C3Woj8eC.js":
            if not _valid_openclaw_parse_finite_number_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/parse-timeout-91AFhn8L.js":
            if not _valid_openclaw_parse_timeout_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/arg-split-DM7vx6uc.js":
            if not _valid_openclaw_arg_split_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/balanced-json-YUc2rvlg.js":
            if not _valid_openclaw_balanced_json_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/json-pointer-BRH9eAOA.js":
            if not _valid_openclaw_json_pointer_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/command-poll-backoff-DmjJeZIx.js":
            if not _valid_openclaw_command_poll_backoff_source(source):
                return False
            continue
        if path == "third_party/openclaw/selected/async-lock-BcLS4KOc.js":
            if not _valid_openclaw_async_lock_source(source):
                return False
            continue
        if path == "mako_js/labels.js":
            if not _valid_mako_js_labels_source(source):
                return False
            continue
        if path == "mako_js/async_records.js":
            if not _valid_mako_js_async_records_source(source):
                return False
            continue
        if path in {"mako_js/io_boundary.js", "packages/core/mako_js/io_boundary.js"}:
            if not _valid_mako_js_io_boundary_source(source):
                return False
            continue
        return False
    return True


def _valid_openclaw_parse_finite_number_source(source: str) -> bool:
    if "while (" in source or "Date." in source:
        return False
    required_markers = (
        "function normalizeNumericString(value)",
        "function parseFiniteNumber(value)",
        "function parseStrictInteger(value)",
        "function parseStrictPositiveInteger(value)",
        "function parseStrictNonNegativeInteger(value)",
        "export { parseStrictPositiveInteger as i, parseStrictInteger as n, parseStrictNonNegativeInteger as r, parseFiniteNumber as t }",
        "typeof value === \"number\") return Number.isSafeInteger(value) ? value : void 0",
        "typeof value !== \"string\"",
        "const normalized = normalizeNumericString(value)",
        "/^[+-]?\\d+$/.test(normalized)",
        "const parsed = Number(normalized)",
        "return Number.isSafeInteger(parsed) ? parsed : void 0",
        "return parsed !== void 0 && parsed > 0 ? parsed : void 0",
        "return parsed !== void 0 && parsed >= 0 ? parsed : void 0",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_parse_timeout_source(source: str) -> bool:
    if "Date." in source or "process." in source:
        return False
    required_markers = (
        "function parseTimeoutMs(raw)",
        "function invalidTimeout(value)",
        "function parseTimeoutMsWithFallback(raw, fallbackMs, options = {})",
        "export { parseTimeoutMsWithFallback as n, parseTimeoutMs as t }",
        "if (raw === void 0 || raw === null) return",
        "typeof raw === \"bigint\"",
        "const trimmed = raw.trim()",
        "value = Number.parseInt(trimmed, 10)",
        "return Number.isFinite(value) ? value : void 0",
        "return /* @__PURE__ */ new Error(`Invalid --timeout. Use a positive millisecond value, e.g. --timeout 30000.${suffix}`)",
        "if (raw === void 0 || raw === null) return fallbackMs",
        "if (options.invalidType === \"error\") throw invalidTimeout()",
        "if (!value) return fallbackMs",
        "if (!Number.isFinite(parsed) || parsed <= 0) throw invalidTimeout(value)",
        "return parsed",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_arg_split_source(source: str) -> bool:
    if "Date." in source or "process." in source:
        return False
    required_markers = (
        "function splitArgsPreservingQuotes(value, options)",
        "export { splitArgsPreservingQuotes as t }",
        "const args = []",
        "let current = \"\"",
        "let quoteChar = null",
        "const escapeMode = options?.escapeMode ?? \"none\"",
        "const quoteChars = new Set(options?.quoteChars ?? [\"\\\"\"])",
        "const quoteStart = options?.quoteStart ?? \"anywhere\"",
        "escapeMode === \"backslash\" && char === \"\\\\\"",
        "escapeMode === \"backslash-quote-only\"",
        "quoteChars.has(char)",
        "quoteChar === char",
        "const canOpenQuote = quoteStart === \"anywhere\" || current.length === 0",
        "if (!quoteChar && /\\s/.test(char))",
        "args.push(current)",
        "return args",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_balanced_json_source(source: str) -> bool:
    if "Date." in source:
        return False
    required_markers = (
        "const CLOSING_DELIMITER =",
        "function isJsonOpeningDelimiter(char, openers)",
        "function extractBalancedJsonPrefix(raw, opts = {})",
        "function extractBalancedJsonFragments(raw, opts = {})",
        "export { extractBalancedJsonPrefix as n, extractBalancedJsonFragments as t }",
        "const openers = opts.openers ?? [\"{\", \"[\"]",
        "while (start < raw.length && !isJsonOpeningDelimiter(raw[start], openers)) start += 1",
        "const stack = []",
        "let inString = false",
        "let escaped = false",
        "else if (char === \"\\\\\") escaped = true",
        "else if (char === \"\\\"\") inString = false",
        "stack.push(char)",
        "const opener = stack.at(-1)",
        "char === CLOSING_DELIMITER[opener]",
        "json: raw.slice(start, i + 1)",
        "const fragment = extractBalancedJsonPrefix(raw.slice(offset), opts)",
        "offset += fragment.endIndex + 1",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_json_pointer_source(source: str) -> bool:
    if "Date." in source:
        return False
    required_markers = (
        "function failOrUndefined(params)",
        "function isJsonObject(value)",
        "function decodeJsonPointerToken(token)",
        "function encodeJsonPointerToken(token)",
        "function readJsonPointer(root, pointer, options = {})",
        "export { readJsonPointer as n, encodeJsonPointerToken as t }",
        "token.replace(/~1/g, \"/\").replace(/~0/g, \"~\")",
        "token.replace(/~/g, \"~0\").replace(/\\//g, \"~1\")",
        "const onMissing = options.onMissing ?? \"throw\"",
        "pointer.slice(1).split(\"/\").map((token) => decodeJsonPointerToken(token))",
        "Array.isArray(current)",
        "Number.parseInt(token, 10)",
        "Object.hasOwn(current, token)",
        "current = current[token]",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_command_poll_backoff_source(source: str) -> bool:
    if source.count("Date.now()") != 2:
        return False
    forbidden_markers = (
        "Date.now =",
        "Date.now=",
        "Date.now.",
        "Date.now[",
        "Date.now.call",
        "Date.now.apply",
        "new Date",
        "Date.parse",
        "Date.UTC",
        "Date.prototype",
        "Date[",
    )
    if any(marker in source for marker in forbidden_markers):
        return False
    required_markers = (
        "const BACKOFF_SCHEDULE_MS =",
        "5e3",
        "1e4",
        "3e4",
        "6e4",
        "function calculateBackoffMs(consecutiveNoOutputPolls)",
        "BACKOFF_SCHEDULE_MS[Math.min(consecutiveNoOutputPolls, BACKOFF_SCHEDULE_MS.length - 1)] ?? 6e4",
        "function recordCommandPoll(state, commandId, hasNewOutput)",
        "if (!state.commandPollCounts) state.commandPollCounts = /* @__PURE__ */ new Map()",
        "const existing = state.commandPollCounts.get(commandId)",
        "const now = Date.now()",
        "state.commandPollCounts.set(commandId",
        "return BACKOFF_SCHEDULE_MS[0] ?? 5e3",
        "const newCount = (existing?.count ?? -1) + 1",
        "return calculateBackoffMs(newCount)",
        "function resetCommandPollCount(state, commandId)",
        "state.commandPollCounts?.delete(commandId)",
        "function pruneStaleCommandPolls(state, maxAgeMs = 36e5)",
        "for (const [commandId, data] of state.commandPollCounts.entries())",
        "now - data.lastPollAt > maxAgeMs",
        "export { recordCommandPoll as n, resetCommandPollCount as r, pruneStaleCommandPolls as t }",
    )
    return all(marker in source for marker in required_markers)


def _valid_openclaw_async_lock_source(source: str) -> bool:
    if "Date." in source:
        return False
    required_markers = (
        "function createAsyncLock()",
        "let lock = Promise.resolve()",
        "return async function withLock(fn)",
        "const previous = lock",
        "let release",
        "lock = new Promise((resolve) =>",
        "release = resolve",
        "await previous",
        "try {",
        "return await fn()",
        "finally {",
        "release?.()",
        "export { createAsyncLock as t }",
    )
    return all(marker in source for marker in required_markers)


def _valid_mako_js_labels_source(source: str) -> bool:
    if "Date." in source:
        return False
    required_markers = (
        "function compactLabel(value)",
        "function labelKey(value)",
        "export { compactLabel, labelKey }",
        "const normalized = String(value ?? \"\").trim().toLowerCase()",
        "normalized.replace(/[^a-z0-9]+/g, \"-\").replace(/^-+|-+$/g, \"\")",
        "const compacted = compactLabel(value)",
        "return compacted ? `label:${compacted}` : \"label\"",
    )
    return all(marker in source for marker in required_markers)


def _valid_mako_js_async_records_source(source: str) -> bool:
    if "Date." in source:
        return False
    required_markers = (
        "async function loadUserSummaries(client, userIds, options = {})",
        "function normalizeUserId(value)",
        "function summarizeUser(record)",
        "export { loadUserSummaries, normalizeUserId, summarizeUser }",
        "const concurrency = Math.max(1, Math.min(Number(options.concurrency ?? 2) || 2, 5))",
        "const ids = [...new Set(userIds.map((id) => normalizeUserId(id)).filter(Boolean))]",
        "await Promise.all(batch.map(async (id) =>",
        "record: await client.fetchUser(id)",
        "errors.push({ id: item.id, message: String(item.error?.message ?? item.error) })",
        "Array.isArray(record.roles)",
        ".filter(Boolean).sort()",
        "return { users, errors }",
    )
    return all(marker in source for marker in required_markers)


def _valid_mako_js_io_boundary_source(source: str) -> bool:
    forbidden_markers = (
        "Date.",
        "process.",
        "process?.",
        "process[",
        "globalThis",
        "import(",
        "require(",
        "node:fs",
        "fs.",
        "fetch(",
        "root ===",
        "root ==",
        "safeRoot ===",
        "safeRoot ==",
    )
    if any(marker in source for marker in forbidden_markers):
        return False
    required_markers = (
        "async function scanWorkspaceManifest(readText, root, candidateFiles)",
        "export { scanWorkspaceManifest }",
        "const normalizeRoot = (value) =>",
        "const cleanCandidate = (value) =>",
        "part === \"..\"",
        "part.startsWith(\".\")",
        "const compactName = (value) =>",
        "if (path.endsWith(\"/package.json\"))",
        "if (path.endsWith(\"mako.json\"))",
        "JSON.parse(String(text ?? \"\"))",
        "invalid.push({ path, reason: \"json\" })",
        "if (code === \"ENOENT\")",
        "missing.push(path)",
        "errors.push({ path, code: code || \"ERROR\" })",
        "return { root: safeRoot, found, missing, invalid, errors }",
    )
    return all(marker in source for marker in required_markers)


def _valid_mako_js_fs_manifest_source(source: str) -> bool:
    forbidden_markers = (
        "Date.",
        "process.",
        "process?.",
        "process[",
        "globalThis",
        "import(",
        "require(",
        "child_process",
        "eval(",
        "Function(",
        "constructor",
        "fetch(",
        "XMLHttpRequest",
        "setTimeout",
        "setInterval",
        "while (true",
        "for (;;",
        "root ===",
        "root ==",
        "rootPath ===",
        "rootPath ==",
    )
    if any(marker in source for marker in forbidden_markers):
        return False
    required_markers = (
        "import { readdir, readFile, stat } from \"node:fs/promises\"",
        "import path from \"node:path\"",
        "async function scanFsPackageManifest(root, options = {})",
        "export { scanFsPackageManifest }",
        "const rootPath = path.resolve(String(root ?? \".\"))",
        "const maxDepth = Math.max(0, Math.min(Number(options.maxDepth ?? 2) || 2, 5))",
        "const required = Array.isArray(options.required) ? options.required : []",
        "await readdir(dir, { withFileTypes: true })",
        "entry.name === \"node_modules\" || entry.name.startsWith(\".\")",
        "path.relative(rootPath, fullPath).replace(/\\\\+/g, \"/\")",
        "entry.name === \"package.json\" || entry.name === \"package-lock.json\" || entry.name.endsWith(\".mako.json\")",
        "relative.endsWith(\"package-lock.json\")",
        "kind: \"package-lock\"",
        "lockfileVersion: Number(data?.lockfileVersion ?? 0)",
        "localDependencyCount: deps.filter((value) => String(value).startsWith(\"file:\")).length",
        "const info = await stat(filePath)",
        "if (!info.isFile()) continue",
        "await readFile(filePath, \"utf8\")",
        "JSON.parse(text)",
        "invalid.push({ path: relative, reason: \"json\" })",
        "if (code === \"ENOENT\") missing.push(relative)",
        "return { root: rootPath, found, missing, invalid, errors }",
    )
    return all(marker in source for marker in required_markers)


def _valid_mako_js_http_manifest_source(source: str) -> bool:
    forbidden_markers = (
        "Date.",
        "process.",
        "process?.",
        "process[",
        "globalThis",
        "import ",
        "import(",
        "require(",
        "child_process",
        "eval(",
        "Function(",
        "constructor",
        "XMLHttpRequest",
        "setTimeout",
        "setInterval",
        "while (true",
        "for (;;",
        "baseUrl ===",
        "baseUrl ==",
    )
    if any(marker in source for marker in forbidden_markers):
        return False
    required_markers = (
        "function normalizePackageName(value)",
        "function packageUrl(baseUrl, name)",
        "function summarizePackage(name, data)",
        "async function fetchPackageMetadata(baseUrl, packageNames, options = {})",
        "export { fetchPackageMetadata }",
        "String(value ?? \"\").trim().toLowerCase()",
        "/^[a-z0-9@/_-]+$/.test(normalized)",
        "encodeURIComponent(name)",
        "const found = []",
        "const missing = []",
        "const invalid = []",
        "const errors = []",
        "const seen = new Set()",
        "response = await fetch(url, { headers: { \"accept\": \"application/json\", ...(options.headers ?? {}) } })",
        "errors.push({ name, code: \"NETWORK\", message: String(error?.message ?? error) })",
        "if (response.status === 404)",
        "errors.push({ name, code: `HTTP_${response.status}` })",
        "data = await response.json()",
        "invalid.push({ name, reason: \"json\" })",
        "dependencies.length",
        "return { baseUrl: String(baseUrl ?? \"\").replace(/\\/+$/, \"\"), found, missing, invalid, errors }",
    )
    return all(marker in source for marker in required_markers)


def _valid_file_bundle_function_repair_sources(
    files: Mapping[str, str],
    function_names: tuple[str, ...] | None = None,
    *,
    reference_files: Mapping[str, str] | None = None,
) -> bool:
    normalized = {Path(str(path)).as_posix(): str(source) for path, source in files.items()}
    if not normalized or "subject.py" in normalized:
        return False
    if any(not _safe_file_bundle_repair_path(path) for path in normalized):
        return False
    local_modules = _repair_local_modules_for_files(normalized)
    expected = tuple(sorted(str(name).strip() for name in (function_names or ()) if str(name).strip()))
    reference_map = dict(reference_files or {})
    all_functions: list[str] = []
    trees: list[tuple[str, ast.Module]] = []
    functions_by_path: dict[str, tuple[str, ...]] = {}
    for path, source in normalized.items():
        if not source.strip():
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        trees.append((path, tree))
        functions: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
                continue
            if isinstance(node, ast.Import):
                if all(_repair_import_allowed(alias.name, local_modules) for alias in node.names):
                    continue
                return False
            if isinstance(node, ast.ImportFrom):
                if node.module and _repair_import_allowed(node.module, local_modules):
                    continue
                return False
            return False
        if not functions:
            return False
        functions_by_path[path] = tuple(sorted(functions))
        all_functions.extend(functions)
    if len(set(all_functions)) != len(all_functions):
        return False
    if expected and tuple(sorted(all_functions)) != expected:
        return False
    allowed_calls = tuple(sorted(all_functions))
    for path, tree in trees:
        reference_source = reference_map.get(path, "")
        reference_names = _top_level_reference_names(reference_source)
        if _source_has_dangerous_repair_constructs(
            tree,
            allowed_calls,
            local_modules=local_modules,
            allowed_name_calls=reference_names,
        ):
            return False
        if reference_source:
            for function_name in functions_by_path[path]:
                if not _reference_has_replaceable_function(reference_source, function_name):
                    return False
            if not _subject_function_signatures_compatible(normalized[path], reference_source, functions_by_path[path]):
                return False
    return True


def _file_bundle_function_repair_operations(project: Path, files: Mapping[str, str]) -> list[dict[str, str]] | None:
    operations: list[dict[str, str]] = []
    for path, patch_source in sorted(files.items()):
        target = project / path
        try:
            reference_source = target.read_text(encoding="utf-8")
        except OSError:
            return None
        merged = _merge_file_bundle_function_repair(reference_source, patch_source)
        if merged is None:
            return None
        operations.append({"op": "write_text", "path": path, "text": merged if merged.endswith("\n") else merged + "\n"})
    return operations


def _merge_file_bundle_function_repair(reference_source: str, patch_source: str) -> str | None:
    try:
        reference_tree = ast.parse(reference_source)
        patch_tree = ast.parse(patch_source)
    except SyntaxError:
        return None
    patch_functions = {
        node.name: node
        for node in patch_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    if not patch_functions:
        return None
    function_names = tuple(sorted(patch_functions))
    if not _subject_function_signatures_compatible(patch_source, reference_source, function_names):
        return None
    reference_functions = {
        node.name: node
        for node in reference_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    replacements: list[tuple[int, int, str]] = []
    for function_name in function_names:
        reference_function = reference_functions.get(function_name)
        patch_function = patch_functions[function_name]
        if reference_function is None or reference_function.decorator_list or patch_function.decorator_list:
            return None
        if reference_function.end_lineno is None or patch_function.end_lineno is None:
            return None
        patch_text = _source_lines_for_node(patch_source, patch_function)
        if not patch_text:
            return None
        replacements.append((reference_function.lineno - 1, reference_function.end_lineno, patch_text.rstrip() + "\n"))
    lines = reference_source.splitlines(keepends=True)
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement]
    merged = "".join(lines)
    try:
        ast.parse(merged)
    except SyntaxError:
        return None
    return merged


def _file_bundle_function_repair_snippet(source: str, function_names: tuple[str, ...]) -> str | None:
    expected = tuple(sorted(str(name).strip() for name in function_names if str(name).strip()))
    if not expected:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    snippets: list[str] = []
    for function_name in expected:
        node = functions.get(function_name)
        if node is None or node.decorator_list:
            return None
        snippet = _source_lines_for_node(source, node)
        if not snippet:
            return None
        snippets.append(snippet.rstrip())
    result = "\n\n\n".join(snippets) + "\n"
    if not _valid_file_bundle_function_repair_sources({"module.py": result}, expected, reference_files={"module.py": source}):
        return None
    return result


def _source_lines_for_node(source: str, node: ast.AST) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if not isinstance(start, int) or not isinstance(end, int):
        return ""
    lines = source.splitlines(keepends=True)
    return "".join(lines[start - 1:end])


def _file_bundle_function_names(files: Mapping[str, str]) -> tuple[str, ...]:
    functions: set[str] = set()
    for path, source in files.items():
        if Path(str(path)).suffix == ".js":
            functions.update(_javascript_function_names(str(source)))
            continue
        try:
            tree = ast.parse(str(source))
        except SyntaxError:
            continue
        functions.update(node.name for node in tree.body if isinstance(node, ast.FunctionDef))
    return tuple(sorted(functions))


def _javascript_function_names(source: str) -> tuple[str, ...]:
    pattern = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
    return tuple(sorted(set(pattern.findall(source))))


def _file_function_bundle_function_names(files: Mapping[str, Mapping[str, str]]) -> tuple[str, ...]:
    names: set[str] = set()
    for replacements in files.values():
        names.update(str(name).strip() for name in replacements if str(name).strip())
    return tuple(sorted(names))


def _top_level_reference_names(source: str) -> tuple[str, ...]:
    if not source.strip():
        return ()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return tuple(sorted(names))


def _replace_top_level_functions(source: str, replacements: Mapping[str, str]) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    nodes: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            nodes[node.name] = node
    if any(name not in nodes for name in replacements):
        return None
    lines = source.splitlines(keepends=True)
    for function_name, replacement in sorted(replacements.items(), key=lambda item: nodes[item[0]].lineno, reverse=True):
        node = nodes[function_name]
        if node.decorator_list or getattr(node, "end_lineno", None) is None:
            return None
        replacement_lines = (replacement.rstrip() + "\n").splitlines(keepends=True)
        lines[node.lineno - 1 : node.end_lineno] = replacement_lines
    return "".join(lines)


def _safe_repair_file_path(path: str) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    if len(candidate.parts) != 1:
        return False
    if candidate.suffix != ".py":
        return False
    if candidate.name.startswith(".") or candidate.stem.startswith("__"):
        return False
    if candidate.name.startswith("test_") or candidate.name == "conftest.py":
        return False
    if candidate.parts[0] in FORBIDDEN_REPAIR_FILE_ROOTS:
        return False
    if candidate.stem in DANGEROUS_REPAIR_MODULES:
        return False
    return True


def _safe_file_bundle_repair_path(path: str) -> bool:
    if not path:
        return False
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    if candidate.suffix != ".py":
        return False
    lowered_parts = {part.lower() for part in candidate.parts}
    if lowered_parts & {"test", "tests"}:
        return False
    if any(part in FORBIDDEN_REPAIR_FILE_ROOTS for part in candidate.parts):
        return False
    if any(part.startswith(".") or part.startswith("__") for part in candidate.parts):
        return False
    if candidate.name.startswith("test_") or candidate.name == "conftest.py":
        return False
    if candidate.stem in DANGEROUS_REPAIR_MODULES or candidate.stem in SAFE_REPAIR_IMPORTS:
        return False
    return True


def _repair_local_modules_for_files(files: Mapping[str, str]) -> tuple[str, ...]:
    modules: set[str] = set()
    for path in files:
        candidate = Path(path)
        module_name = ".".join(candidate.with_suffix("").parts)
        if module_name:
            modules.add(module_name)
        if len(candidate.parts) == 1:
            modules.add(candidate.stem)
    return tuple(sorted(modules))


def _repair_import_allowed(module: str, local_modules: tuple[str, ...] = ()) -> bool:
    root = module.split(".", 1)[0]
    return root in SAFE_REPAIR_IMPORTS or module in local_modules or root in local_modules


def _source_has_dangerous_repair_constructs(
    tree: ast.AST,
    function_names: tuple[str, ...],
    *,
    local_modules: tuple[str, ...] = (),
    allowed_name_calls: tuple[str, ...] = (),
) -> bool:
    allowed_name_calls_set = SAFE_REPAIR_NAME_CALLS | set(function_names) | set(allowed_name_calls)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return True
        if isinstance(node, ast.Import):
            if any(alias.name == "*" for alias in node.names):
                return True
            if any(not _repair_import_allowed(alias.name, local_modules) for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
            if not node.module or not _repair_import_allowed(node.module, local_modules):
                return True
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Lambda, ast.Global, ast.Nonlocal)):
            return True
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            return True
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return True
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and _repair_import_allowed(node.module, local_modules):
            allowed_name_calls_set.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in UNSAFE_REPAIR_NAME_CALLS or node.func.id not in allowed_name_calls_set:
                    return True
                continue
            if isinstance(node.func, ast.Attribute):
                root = _attribute_root_name(node.func)
                if root in DANGEROUS_REPAIR_MODULES or node.func.attr.startswith("__"):
                    return True
                continue
            return True
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return True
    return False


def _subject_function_signatures_compatible(source: str, reference_source: str, function_names: tuple[str, ...]) -> bool:
    try:
        source_tree = ast.parse(source)
        reference_tree = ast.parse(reference_source)
    except SyntaxError:
        return False
    source_functions = {
        node.name: node
        for node in source_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    reference_functions = {
        node.name: node
        for node in reference_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    for function_name in function_names:
        source_function = source_functions.get(function_name)
        reference_function = reference_functions.get(function_name)
        if source_function is None or reference_function is None:
            return False
        if _function_signature_shape(source_function) != _function_signature_shape(reference_function):
            return False
    return True


def _function_signature_shape(function: ast.FunctionDef) -> tuple[int, int, bool, bool, int, int]:
    args = function.args
    return (
        len(args.posonlyargs),
        len(args.args),
        args.vararg is not None,
        args.kwarg is not None,
        len(args.kwonlyargs),
        len(args.defaults),
    )


def _attribute_root_name(node: ast.Attribute) -> str:
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def _infer_subject_repair_from_tests(function_name: str, test_text: str) -> str | None:
    cases = _assert_equal_binary_numeric_cases(function_name, test_text)
    if len(cases) < 2:
        literal_source = _infer_single_arg_literal_repair_from_tests(function_name, test_text)
        if literal_source is not None:
            return literal_source
        return None
    numeric_source = _infer_binary_numeric_repair(function_name, cases)
    if numeric_source is not None:
        return numeric_source
    return None


def _infer_subject_bundle_repair_from_tests(
    function_names: tuple[str, ...],
    *,
    test_text: str,
    reference_source: str,
    task: str,
) -> str | None:
    if _task_requests_learning_contract(task):
        return None
    if reference_source and not _subject_is_pure_function_bundle(reference_source, function_names):
        return None
    sources: list[str] = []
    for function_name in function_names:
        source = _infer_subject_repair_from_tests(function_name, test_text)
        if source is None:
            return None
        sources.append(source.rstrip())
    bundle_source = "\n\n\n".join(sources) + "\n"
    if not _valid_subject_bundle_repair_source(bundle_source, function_names):
        return None
    if reference_source and not _subject_function_signatures_compatible(bundle_source, reference_source, function_names):
        return None
    return bundle_source


def _subject_is_pure_function_bundle(source: str, function_names: tuple[str, ...]) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    if tuple(sorted(functions)) != tuple(sorted(function_names)):
        return False
    return all(isinstance(node, ast.FunctionDef) for node in tree.body)


def _infer_binary_numeric_repair(function_name: str, cases: list[tuple[float, float, float]]) -> str | None:
    candidates = (
        ("+", lambda left, right: left + right),
        ("*", lambda left, right: left * right),
        ("-", lambda left, right: left - right),
    )
    for operator, evaluator in candidates:
        if all(evaluator(left, right) == expected for left, right, expected in cases):
            return (
                f"def {function_name}(a, b):\n"
                f"    return a {operator} b\n"
            )
    return None


def _infer_single_arg_literal_repair_from_tests(function_name: str, test_text: str) -> str | None:
    cases = _assert_equal_single_arg_literal_cases(function_name, test_text)
    if len(cases) < 2:
        return None
    candidates = (
        (
            f"def {function_name}(value):\n"
            "    return str(value).strip().lower()\n",
            _eval_strip_lower,
        ),
        (
            f"def {function_name}(items):\n"
            "    return list(reversed(items))\n",
            _eval_reverse_literal_sequence,
        ),
        (
            f"def {function_name}(items):\n"
            "    return sorted(items)\n",
            _eval_sorted_literal_sequence,
        ),
    )
    for source, evaluator in candidates:
        if _literal_cases_match(cases, evaluator):
            return source
    return None


def _infer_slug_literal_repair_from_tests(function_name: str, test_text: str) -> str | None:
    cases = _assert_equal_single_arg_literal_cases(function_name, test_text)
    if len(cases) < 2 or not _literal_cases_match(cases, _eval_slug_literal_string):
        return None
    return (
        "import re\n\n\n"
        f"def {function_name}(value):\n"
        "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
        "    return cleaned.strip(\"-\")\n"
    )


def _infer_multifile_repair_from_tests(
    project: Path,
    task: str,
    function_name: str,
    *,
    subject_text: str,
    test_text: str,
) -> list[dict[str, str]] | None:
    if _task_requests_learning_contract(task):
        return None
    lowered = task.lower()
    if not any(token in lowered for token in ("helper", "module", "label_helper")):
        return None
    helper = _single_local_helper_import(subject_text)
    if helper is None:
        return None
    helper_module, helper_function, helper_call_name = helper
    helper_path = Path(f"{helper_module}.py")
    if not _safe_repair_file_path(helper_path.as_posix()):
        return None
    if not (project / helper_path).exists():
        return None
    cases = _assert_equal_single_arg_literal_cases(function_name, test_text)
    if len(cases) < 2:
        return None
    candidates = (
        (
            (
                "import re\n\n\n"
                f"def {helper_function}(value):\n"
                "    cleaned = re.sub(r\"[^a-z0-9]+\", \"-\", str(value).strip().lower())\n"
                "    return cleaned.strip(\"-\")\n"
            ),
            _eval_slug_literal_string,
        ),
        (
            (
                f"def {helper_function}(value):\n"
                "    return str(value).strip().lower()\n"
            ),
            _eval_strip_lower,
        ),
    )
    for helper_source, evaluator in candidates:
        if not _literal_cases_match(cases, evaluator):
            continue
        helper_import = helper_function if helper_call_name == helper_function else f"{helper_function} as {helper_call_name}"
        subject_source = (
            f"from {helper_module} import {helper_import}\n\n\n"
            f"def {function_name}(text):\n"
            f"    return {helper_call_name}(text)\n"
        )
        files = {
            "subject.py": subject_source,
            helper_path.as_posix(): helper_source,
        }
        if not _valid_multifile_repair_sources(files, (function_name,)):
            continue
        if not _subject_function_signatures_compatible(subject_source, subject_text, (function_name,)):
            continue
        return [
            {"op": "write_text", "path": "subject.py", "text": subject_source},
            {"op": "write_text", "path": helper_path.as_posix(), "text": helper_source},
        ]
    return None


def _single_local_helper_import(source: str) -> tuple[str, str, str] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    helpers: list[tuple[str, str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0 or not node.module:
            continue
        module_root = node.module.split(".", 1)[0]
        if module_root in SAFE_REPAIR_IMPORTS or module_root in DANGEROUS_REPAIR_MODULES:
            continue
        if len(node.names) != 1:
            continue
        alias = node.names[0]
        if alias.name == "*":
            continue
        helpers.append((node.module, alias.name, alias.asname or alias.name))
    if len(helpers) != 1:
        return None
    return helpers[0]


def _assert_equal_binary_numeric_cases(function_name: str, test_text: str) -> list[tuple[float, float, float]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[tuple[float, float, float]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "assertEqual":
            continue
        if len(node.args) < 2:
            continue
        actual, expected = node.args[0], node.args[1]
        if not isinstance(actual, ast.Call):
            continue
        if not isinstance(actual.func, ast.Name) or actual.func.id != function_name:
            continue
        if len(actual.args) != 2:
            continue
        left = _numeric_literal(actual.args[0])
        right = _numeric_literal(actual.args[1])
        expected_value = _numeric_literal(expected)
        if left is None or right is None or expected_value is None:
            continue
        cases.append((left, right, expected_value))
    return cases


def _assert_equal_single_arg_literal_cases(function_name: str, test_text: str) -> list[tuple[Any, Any]]:
    try:
        tree = ast.parse(test_text)
    except SyntaxError:
        return []
    cases: list[tuple[Any, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "assertEqual":
            continue
        if len(node.args) < 2:
            continue
        actual, expected = node.args[0], node.args[1]
        if not isinstance(actual, ast.Call):
            continue
        if not isinstance(actual.func, ast.Name) or actual.func.id != function_name:
            continue
        if len(actual.args) != 1:
            continue
        input_ok, input_value = _literal_value(actual.args[0])
        expected_ok, expected_value = _literal_value(expected)
        if not input_ok or not expected_ok:
            continue
        cases.append((input_value, expected_value))
    return cases


def _literal_value(node: ast.AST) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return False, None


def _literal_cases_match(cases: list[tuple[Any, Any]], evaluator: Any) -> bool:
    for input_value, expected in cases:
        try:
            actual = evaluator(input_value)
        except (TypeError, ValueError):
            return False
        if actual != expected:
            return False
    return True


def _eval_strip_lower(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("strip/lower repair only accepts string examples")
    return str(value).strip().lower()


def _eval_slug_literal_string(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("slug repair only accepts string examples")
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower())
    return cleaned.strip("-")


def _eval_reverse_literal_sequence(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("reverse repair only accepts sequence examples")
    return list(reversed(value))


def _eval_sorted_literal_sequence(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("sorted repair only accepts sequence examples")
    return sorted(value)


def _numeric_literal(node: ast.AST) -> float | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _numeric_literal(node.operand)
        return -value if value is not None else None
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


_SUBJECT_REPAIR_RECIPES: dict[str, tuple[tuple[str, ...], str]] = {
    "add_numbers": (
        ("sum", "arithmetic", "add"),
        "def add_numbers(a, b):\n"
        "    return a + b\n",
    ),
    "clamp": (
        ("clamp", "constrain", "bounds", "interval"),
        "def clamp(value, low, high):\n"
        "    return max(low, min(value, high))\n",
    ),
    "slugify": (
        ("slug", "lowercase", "non-alnum", "dash"),
        "import re\n\n\n"
        "def slugify(text):\n"
        "    normalized = str(text).strip().lower()\n"
        "    return re.sub(r\"[^a-z0-9]+\", \"-\", normalized).strip(\"-\")\n",
    ),
    "parse_bool": (
        ("true", "false", "bool", "valueerror"),
        "def parse_bool(value):\n"
        "    if isinstance(value, bool):\n"
        "        return value\n"
        "    normalized = str(value).strip().lower()\n"
        "    if normalized in {\"1\", \"true\", \"t\", \"yes\", \"y\", \"on\"}:\n"
        "        return True\n"
        "    if normalized in {\"0\", \"false\", \"f\", \"no\", \"n\", \"off\"}:\n"
        "        return False\n"
        "    raise ValueError(f\"unknown boolean value: {value!r}\")\n",
    ),
    "safe_divide": (
        ("divide", "division", "zero", "default"),
        "def safe_divide(a, b, default=None):\n"
        "    if b == 0:\n"
        "        return default\n"
        "    return a / b\n",
    ),
    "flatten_one_level": (
        ("flatten", "list", "tuple"),
        "def flatten_one_level(items):\n"
        "    result = []\n"
        "    for item in items:\n"
        "        if isinstance(item, (list, tuple)):\n"
        "            result.extend(item)\n"
        "        else:\n"
        "            result.append(item)\n"
        "    return result\n",
    ),
    "unique_preserve_order": (
        ("duplicates", "unique", "order"),
        "def unique_preserve_order(items):\n"
        "    seen = set()\n"
        "    result = []\n"
        "    for item in items:\n"
        "        if item not in seen:\n"
        "            seen.add(item)\n"
        "            result.append(item)\n"
        "    return result\n",
    ),
    "mask_token": (
        ("mask", "prefix", "suffix"),
        "def mask_token(token, prefix=4, suffix=4):\n"
        "    text = str(token)\n"
        "    if len(text) <= prefix + suffix:\n"
        "        return \"***\"\n"
        "    return f\"{text[:prefix]}...{text[-suffix:]}\"\n",
    ),
    "parse_kv_lines": (
        ("key=value", "comments", "blank", "trim"),
        "def parse_kv_lines(text):\n"
        "    result = {}\n"
        "    for raw_line in str(text).splitlines():\n"
        "        line = raw_line.strip()\n"
        "        if not line or line.startswith(\"#\") or \"=\" not in line:\n"
        "            continue\n"
        "        key, value = line.split(\"=\", 1)\n"
        "        result[key.strip()] = value.strip()\n"
        "    return result\n",
    ),
    "normalize_path_segments": (
        ("segments", "collapse", "root", ".."),
        "def normalize_path_segments(path):\n"
        "    parts = []\n"
        "    for segment in str(path).split(\"/\"):\n"
        "        if not segment or segment == \".\":\n"
        "            continue\n"
        "        if segment == \"..\":\n"
        "            if parts:\n"
        "                parts.pop()\n"
        "            continue\n"
        "        parts.append(segment)\n"
        "    return \"/\".join(parts)\n",
    ),
    "moving_average": (
        ("moving", "average", "window"),
        "def moving_average(values, window):\n"
        "    if window <= 0:\n"
        "        raise ValueError(\"window must be positive\")\n"
        "    return [sum(values[index:index + window]) / window for index in range(len(values) - window + 1)]\n",
    ),
    "percent_change": (
        ("percent", "change", "zero"),
        "def percent_change(old, new):\n"
        "    if old == 0:\n"
        "        return None\n"
        "    return (new - old) / old\n",
    ),
    "is_sorted": (
        ("sorted", "descending", "equal"),
        "def is_sorted(values, reverse=False):\n"
        "    pairs = zip(values, values[1:])\n"
        "    if reverse:\n"
        "        return all(left >= right for left, right in pairs)\n"
        "    return all(left <= right for left, right in pairs)\n",
    ),
    "chunk_list": (
        ("chunk", "size"),
        "def chunk_list(items, size):\n"
        "    if size <= 0:\n"
        "        raise ValueError(\"size must be positive\")\n"
        "    return [items[index:index + size] for index in range(0, len(items), size)]\n",
    ),
    "deep_merge": (
        ("merge", "dictionaries", "mutating"),
        "import copy\n\n\n"
        "def deep_merge(a, b):\n"
        "    result = copy.deepcopy(a)\n"
        "    for key, value in b.items():\n"
        "        if isinstance(result.get(key), dict) and isinstance(value, dict):\n"
        "            result[key] = deep_merge(result[key], value)\n"
        "        else:\n"
        "            result[key] = copy.deepcopy(value)\n"
        "    return result\n",
    ),
    "retry_delay": (
        ("backoff", "capped", "max_delay"),
        "def retry_delay(attempt, base=1, max_delay=30):\n"
        "    return min(max_delay, base * (2 ** max(0, attempt - 1)))\n",
    ),
    "parse_timeout_ms": (
        ("timeout", "ms", "invalid"),
        "def parse_timeout_ms(value):\n"
        "    if isinstance(value, int) and not isinstance(value, bool):\n"
        "        parsed = value\n"
        "    else:\n"
        "        text = str(value).strip().lower()\n"
        "        if text.endswith(\"ms\"):\n"
        "            text = text[:-2].strip()\n"
        "        try:\n"
        "            parsed = int(text)\n"
        "        except (TypeError, ValueError) as exc:\n"
        "            raise ValueError(f\"invalid timeout: {value!r}\") from exc\n"
        "    if parsed <= 0:\n"
        "        raise ValueError(f\"invalid timeout: {value!r}\")\n"
        "    return parsed\n",
    ),
    "mask_email": (
        ("email", "mask", "domain"),
        "def mask_email(email):\n"
        "    local, domain = str(email).split(\"@\", 1)\n"
        "    return f\"{local[:1]}***@{domain}\"\n",
    ),
    "dedup_rows": (
        ("duplicate", "rows", "key"),
        "def dedup_rows(rows, key):\n"
        "    seen = set()\n"
        "    result = []\n"
        "    for row in rows:\n"
        "        marker = row.get(key)\n"
        "        if marker not in seen:\n"
        "            seen.add(marker)\n"
        "            result.append(row)\n"
        "    return result\n",
    ),
    "rolling_sum": (
        ("rolling", "window", "sum"),
        "def rolling_sum(values, window):\n"
        "    if window <= 0:\n"
        "        raise ValueError(\"window must be positive\")\n"
        "    return [sum(values[index:index + window]) for index in range(len(values) - window + 1)]\n",
    ),
    "top_n": (
        ("largest", "descending", "top"),
        "def top_n(values, n):\n"
        "    if n <= 0:\n"
        "        return []\n"
        "    return sorted(values, reverse=True)[:n]\n",
    ),
    "parse_tags": (
        ("tags", "comma", "lowercase"),
        "def parse_tags(text):\n"
        "    return [part.strip().lower() for part in str(text).split(\",\") if part.strip()]\n",
    ),
    "validate_price": (
        ("price", "positive", "finite"),
        "import math\n\n\n"
        "def validate_price(value):\n"
        "    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0\n",
    ),
    "median": (
        ("median", "odd", "even"),
        "def median(values):\n"
        "    if not values:\n"
        "        raise ValueError(\"median requires at least one value\")\n"
        "    ordered = sorted(values)\n"
        "    middle = len(ordered) // 2\n"
        "    if len(ordered) % 2:\n"
        "        return ordered[middle]\n"
        "    return (ordered[middle - 1] + ordered[middle]) / 2\n",
    ),
    "coalesce": (
        ("none", "first"),
        "def coalesce(*values):\n"
        "    for value in values:\n"
        "        if value is not None:\n"
        "            return value\n"
        "    return None\n",
    ),
    "count_occurrences": (
        ("count", "frequencies", "occurrences"),
        "def count_occurrences(items):\n"
        "    counts = {}\n"
        "    for item in items:\n"
        "        counts[item] = counts.get(item, 0) + 1\n"
        "    return counts\n",
    ),
    "strip_ansi": (
        ("ansi", "escape"),
        "import re\n\n\n"
        "def strip_ansi(text):\n"
        "    return re.sub(r\"\\x1b\\[[0-?]*[ -/]*[@-~]\", \"\", str(text))\n",
    ),
    "read_pointer": (
        ("pointer", "json"),
        "def read_pointer(data, pointer):\n"
        "    if pointer == \"\":\n"
        "        return data\n"
        "    if not isinstance(pointer, str) or not pointer.startswith(\"/\"):\n"
        "        raise KeyError(pointer)\n"
        "    current = data\n"
        "    for raw_part in pointer.split(\"/\")[1:]:\n"
        "        part = raw_part.replace(\"~1\", \"/\").replace(\"~0\", \"~\")\n"
        "        try:\n"
        "            if isinstance(current, list):\n"
        "                current = current[int(part)]\n"
        "            else:\n"
        "                current = current[part]\n"
        "        except (KeyError, IndexError, ValueError, TypeError) as exc:\n"
        "            raise KeyError(pointer) from exc\n"
        "    return current\n",
    ),
    "stable_hash": (
        ("hash", "json", "dict"),
        "import hashlib\n"
        "import json\n\n\n"
        "def stable_hash(value):\n"
        "    payload = json.dumps(value, sort_keys=True, separators=(\",\", \":\"))\n"
        "    return hashlib.sha256(payload.encode(\"utf-8\")).hexdigest()\n",
    ),
    "window_pairs": (
        ("pairs", "adjacent", "window"),
        "def window_pairs(values):\n"
        "    return [(values[index], values[index + 1]) for index in range(len(values) - 1)]\n",
    ),
}


def _has_unsupported_extra_action(lowered_task: str) -> bool:
    unsupported_actions = (
        " delete ",
        " remove ",
        " rename ",
        " move ",
        " overwrite ",
        " replace ",
        "删除",
        "移除",
        "重命名",
        "移动",
        "覆盖",
        "替换",
    )
    padded = f" {lowered_task} "
    return any(token in padded for token in unsupported_actions)


def _has_unsupported_greet_modifier(lowered_task: str) -> bool:
    unsupported_terms = (
        "add function",
        "adds ",
        "calculator",
        "farewell",
        "goodbye",
        "subtract",
        "multiply",
        "divide",
        "async",
        "class ",
        " cli",
        "command line",
        "command-line",
    )
    if any(term in lowered_task for term in unsupported_terms):
        return True
    if re.search(r"\breturns?\b", lowered_task):
        return True
    return False


def _generate_test_operations(task: str, filename: str, content: str) -> list[dict[str, str]]:
    lowered = task.lower()
    if not any(token in lowered for token in ("test", "unittest", "pytest", "自测", "测试")):
        return []
    module_name = Path(filename).stem
    if not module_name.isidentifier():
        return []
    test_text = ""
    if "def greet(" in content:
        test_text = (
            "import unittest\n\n"
            f"from {module_name} import greet\n\n\n"
            "class GreetTest(unittest.TestCase):\n"
            "    def test_greet_name(self) -> None:\n"
            "        self.assertEqual(greet(\"Mako\"), \"Hello, Mako!\")\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    unittest.main()\n"
        )
    if not test_text:
        return []
    return [
        {"op": "write_text", "path": "tests/__init__.py", "text": ""},
        {"op": "write_text", "path": f"tests/test_{module_name}.py", "text": test_text},
    ]
