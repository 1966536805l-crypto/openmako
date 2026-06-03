"""Extreme context builder for AI planner.

Builds rich context using only free/local tools:
- Semantic search (local embeddings)
- Dependency analysis (static analysis)
- Convention extraction (from codebase)
- Similar code retrieval (local search)
- Type information (LSP)

Zero AI calls, maximum context quality.
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from quantagent.code_index import dependency_graph
from quantagent.embedding_provider import embed_batch, EmbeddingJob
from quantagent.exception_audit import audit_suppressed_exception
from quantagent.repo_map import search_repo_map, RepoMapHit
from quantagent.retrieval_daemon import search_retrieval_index, RetrievalHit


@dataclass
class ProjectConventions:
    """Extracted project conventions (learned from codebase)."""

    naming_style: str = "snake_case"  # snake_case, camelCase, PascalCase
    docstring_style: str = "google"   # google, numpy, sphinx
    type_hints_used: bool = True
    error_handling_pattern: str = ""  # raise, return None, Result type
    test_framework: str = "pytest"    # pytest, unittest
    import_style: str = ""            # absolute, relative
    line_length: int = 88
    quote_style: str = "double"       # single, double

    def to_dict(self) -> dict[str, Any]:
        return {
            "naming": self.naming_style,
            "docstrings": self.docstring_style,
            "type_hints": self.type_hints_used,
            "error_handling": self.error_handling_pattern,
            "tests": self.test_framework,
            "imports": self.import_style,
            "line_length": self.line_length,
            "quotes": self.quote_style,
        }


@dataclass
class CodeExample:
    """Similar code example for reference."""

    path: str
    code: str
    reason: str
    score: float = 0.0


@dataclass
class TaskContext:
    """Rich context for a coding task (built without AI calls)."""

    task: str
    project_root: Path

    # Relevant files (from semantic search)
    relevant_files: list[RepoMapHit] = field(default_factory=list)

    # Dependencies (static analysis)
    dependencies: dict[str, list[str]] = field(default_factory=dict)

    # Type information (from LSP if available)
    type_info: dict[str, str] = field(default_factory=dict)

    # Existing tests
    existing_tests: list[Path] = field(default_factory=list)

    # Project conventions (learned from code)
    conventions: ProjectConventions = field(default_factory=ProjectConventions)

    # Similar code examples
    similar_code: list[CodeExample] = field(default_factory=list)

    # Common mistakes to avoid (from local failure DB)
    common_mistakes: list[str] = field(default_factory=list)

    # Project metadata
    python_version: str = "3.10+"
    framework: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "relevant_files": [hit.to_dict() for hit in self.relevant_files],
            "dependencies": self.dependencies,
            "type_info": self.type_info,
            "existing_tests": [str(p) for p in self.existing_tests],
            "conventions": self.conventions.to_dict(),
            "similar_code": [
                {"path": ex.path, "reason": ex.reason, "score": ex.score}
                for ex in self.similar_code
            ],
            "common_mistakes": self.common_mistakes,
            "python_version": self.python_version,
            "framework": self.framework,
        }


class ExtremeContextBuilder:
    """Build extreme context using only free/local tools."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self._conventions_cache: ProjectConventions | None = None
        self._dependency_cache: dict[str, list[str]] | None = None
        self._framework_cache: str | None = None

    def build_context(self, task: str) -> TaskContext:
        """Build rich context for a task (0 AI calls)."""

        context = TaskContext(
            task=task,
            project_root=self.project_root,
        )

        # Step 1: Find relevant files (semantic search, local embeddings)
        context.relevant_files = self._find_relevant_files(task)

        # Step 2: Analyze dependencies (static analysis)
        context.dependencies = self._analyze_dependencies(context.relevant_files)

        # Step 3: Extract project conventions (from codebase)
        context.conventions = self._extract_conventions()

        # Step 4: Find existing tests
        context.existing_tests = self._find_existing_tests(task)

        # Step 5: Find similar code (retrieval)
        context.similar_code = self._find_similar_code(task)

        # Step 6: Get common mistakes (from local DB)
        context.common_mistakes = self._get_common_mistakes(task)

        # Step 7: Get type information (from LSP if available)
        context.type_info = self._get_type_info(context.relevant_files)

        # Step 8: Detect framework
        context.framework = self._detect_framework()

        return context

    def _find_relevant_files(self, task: str, limit: int = 10) -> list[RepoMapHit]:
        """Find relevant files using semantic search (local embeddings)."""

        try:
            # Use existing repo_map search (BM25 + PageRank)
            hits = search_repo_map(self.project_root, task, limit=limit)
            return hits
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:164", exc)
            return []

    def _analyze_dependencies(self, relevant_files: list[RepoMapHit]) -> dict[str, list[str]]:
        """Analyze dependencies between files (static analysis)."""

        # Use cache if available
        if self._dependency_cache is not None:
            deps = {}
            for hit in relevant_files:
                file_path = hit.path
                if file_path in self._dependency_cache:
                    deps[file_path] = self._dependency_cache[file_path]
            return deps

        deps: dict[str, list[str]] = {}

        try:
            # Get dependency graph (already implemented in code_index)
            self._dependency_cache = dependency_graph(self.project_root)

            # Extract dependencies for relevant files
            for hit in relevant_files:
                file_path = hit.path
                if file_path in self._dependency_cache:
                    deps[file_path] = self._dependency_cache[file_path]

        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:191", exc)

        return deps

    def _extract_conventions(self) -> ProjectConventions:
        """Extract project conventions by analyzing existing code."""

        if self._conventions_cache:
            return self._conventions_cache

        conventions = ProjectConventions()

        # Sample Python files from project
        py_files = list(self.project_root.glob("**/*.py"))
        if not py_files:
            return conventions

        # Limit sampling to avoid slowdown
        sample_files = py_files[:min(20, len(py_files))]

        # Analyze conventions
        naming_styles = []
        has_type_hints = []
        docstring_styles = []
        test_frameworks = []
        quote_styles = []

        for file_path in sample_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content)

                # Naming style
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if "_" in node.name:
                            naming_styles.append("snake_case")
                        elif node.name[0].islower():
                            naming_styles.append("camelCase")

                        # Type hints
                        if node.returns or any(arg.annotation for arg in node.args.args):
                            has_type_hints.append(True)

                        # Docstring style
                        docstring = ast.get_docstring(node)
                        if docstring:
                            if "Args:" in docstring or "Returns:" in docstring:
                                docstring_styles.append("google")
                            elif "Parameters" in docstring:
                                docstring_styles.append("numpy")

                # Test framework
                if "pytest" in content or "import pytest" in content:
                    test_frameworks.append("pytest")
                elif "unittest" in content or "import unittest" in content:
                    test_frameworks.append("unittest")

                # Quote style
                single_quotes = content.count("'")
                double_quotes = content.count('"')
                if double_quotes > single_quotes * 1.5:
                    quote_styles.append("double")
                elif single_quotes > double_quotes * 1.5:
                    quote_styles.append("single")

            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:258", exc)
                continue

        # Aggregate results
        if naming_styles:
            conventions.naming_style = Counter(naming_styles).most_common(1)[0][0]

        if has_type_hints:
            conventions.type_hints_used = len(has_type_hints) > len(sample_files) * 0.3

        if docstring_styles:
            conventions.docstring_style = Counter(docstring_styles).most_common(1)[0][0]

        if test_frameworks:
            conventions.test_framework = Counter(test_frameworks).most_common(1)[0][0]

        if quote_styles:
            conventions.quote_style = Counter(quote_styles).most_common(1)[0][0]

        self._conventions_cache = conventions
        return conventions

    def _find_existing_tests(self, task: str) -> list[Path]:
        """Find existing test files related to the task."""

        tests = []
        test_dirs = [
            self.project_root / "tests",
            self.project_root / "test",
        ]

        for test_dir in test_dirs:
            if test_dir.exists():
                tests.extend(test_dir.glob("test_*.py"))
                tests.extend(test_dir.glob("*_test.py"))

        return tests[:10]  # Limit to avoid too much context

    def _find_similar_code(self, task: str, limit: int = 3) -> list[CodeExample]:
        """Find similar code implementations (retrieval)."""

        examples = []

        try:
            # Use retrieval daemon if available
            hits = search_retrieval_index(
                self.project_root,
                query=task,
                limit=limit
            )

            for hit in hits:
                # Read code snippet
                try:
                    file_path = self.project_root / hit.path
                    if file_path.exists():
                        content = file_path.read_text(encoding="utf-8")

                        # Extract relevant snippet (around line number if available)
                        lines = content.split("\n")
                        snippet = "\n".join(lines[:50])  # First 50 lines

                        examples.append(CodeExample(
                            path=hit.path,
                            code=snippet,
                            reason=hit.reason,
                            score=hit.score
                        ))
                except Exception as exc:
                    audit_suppressed_exception(f"{__name__}:326", exc)
                    continue

        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:329", exc)

        return examples

    def _get_common_mistakes(self, task: str) -> list[str]:
        """Get common mistakes from local failure database."""

        # TODO: Implement failure database
        # For now, return general Python mistakes

        mistakes = []

        # Task-specific mistakes
        if "test" in task.lower():
            mistakes.append("Don't forget to import the module being tested")
            mistakes.append("Use descriptive test names (test_<what>_<condition>_<expected>)")

        if "api" in task.lower() or "endpoint" in task.lower():
            mistakes.append("Validate input parameters")
            mistakes.append("Handle errors with proper HTTP status codes")

        if "async" in task.lower():
            mistakes.append("Don't forget 'await' for async functions")
            mistakes.append("Use 'async with' for async context managers")

        # General mistakes
        mistakes.extend([
            "Handle edge cases (None, empty list, invalid input)",
            "Add type hints for better IDE support",
            "Write docstrings for public functions",
        ])

        return mistakes

    def _get_type_info(self, relevant_files: list[RepoMapHit]) -> dict[str, str]:
        """Get type information from files (using AST, LSP would be better but requires setup)."""

        type_info: dict[str, str] = {}

        try:
            for hit in relevant_files:
                file_path = self.project_root / hit.path
                if not file_path.exists() or file_path.suffix != ".py":
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")
                    tree = ast.parse(content)

                    # Extract function signatures with type hints
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            # Build function signature
                            args_list = []
                            for arg in node.args.args:
                                arg_str = arg.arg
                                if arg.annotation:
                                    arg_str += f": {ast.unparse(arg.annotation)}"
                                args_list.append(arg_str)

                            return_type = ""
                            if node.returns:
                                return_type = f" -> {ast.unparse(node.returns)}"

                            signature = f"def {node.name}({', '.join(args_list)}){return_type}"
                            key = f"{hit.path}::{node.name}"
                            type_info[key] = signature

                        elif isinstance(node, ast.ClassDef):
                            # Record class definition
                            key = f"{hit.path}::{node.name}"
                            type_info[key] = f"class {node.name}"

                except Exception as exc:
                    audit_suppressed_exception(f"{__name__}:403", exc)
                    continue

        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:406", exc)

        return type_info

    def _detect_framework(self) -> str:
        """Detect framework used in project."""

        # Use cache if available
        if self._framework_cache is not None:
            return self._framework_cache

        framework = ""

        try:
            # Check common framework files
            if (self.project_root / "manage.py").exists():
                framework = "Django"
            elif (self.project_root / "app.py").exists() or (self.project_root / "application.py").exists():
                # Check for Flask
                app_file = self.project_root / "app.py"
                if app_file.exists():
                    content = app_file.read_text()
                    if "from flask import" in content or "import flask" in content:
                        framework = "Flask"
                    elif "from fastapi import" in content or "import fastapi" in content:
                        framework = "FastAPI"

            # Check requirements.txt or pyproject.toml
            if not framework:
                req_file = self.project_root / "requirements.txt"
                if req_file.exists():
                    content = req_file.read_text()
                    if "django" in content.lower():
                        framework = "Django"
                    elif "flask" in content.lower():
                        framework = "Flask"
                    elif "fastapi" in content.lower():
                        framework = "FastAPI"

        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:446", exc)

        self._framework_cache = framework
        return framework


def build_extreme_context(project_root: str | Path, task: str) -> TaskContext:
    """Build extreme context for a task (convenience function)."""
    builder = ExtremeContextBuilder(project_root)
    return builder.build_context(task)
