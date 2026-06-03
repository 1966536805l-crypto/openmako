"""Extreme AI planner with rich context and prompt caching.

Replaces the deterministic planner with AI-powered code generation.
Uses extreme context building + prompt engineering for one-shot success.

Cost: ~$0.03-0.04 per task (with caching)
Success rate target: 80%+ on first try
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quantagent.exception_audit import audit_suppressed_exception
from quantagent.extreme_context import build_extreme_context, TaskContext
from quantagent.model_client import ModelClient, ModelRequest


def plan_task_to_operations(project: Path, task: str) -> dict[str, Any]:
    """Convert task to operations using AI + extreme context.

    This is the new entry point that replaces the old deterministic planner.

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
        planner = ExtremePlanner(project)
        return planner.plan(task)
    except Exception as e:
        audit_suppressed_exception(f"{__name__}:41", e)
        return {
            "ok": False,
            "error": f"planner exception: {e}",
            "operations": [],
        }


class ExtremePlanner:
    """AI planner with extreme context and prompt engineering."""

    def __init__(self, project_root: Path, model_client: ModelClient | None = None):
        self.project_root = Path(project_root)
        self.model_client = model_client or ModelClient()

    def plan(self, task: str, max_retries: int = 2) -> dict[str, Any]:
        """Plan task using AI with extreme context.

        Args:
            task: Natural language task description
            max_retries: Maximum retry attempts if parsing fails

        Returns:
            {
                "ok": bool,
                "operations": [{"op": "write_text", "path": str, "text": str}],
                "error": str (if ok=False)
            }
        """

        # Step 1: Build extreme context (0 AI calls, all local)
        context = build_extreme_context(self.project_root, task)

        # Step 2: Build extreme prompt
        prompt = self._build_extreme_prompt(task, context)

        # Step 3: Call AI with retries
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = self._generate_with_caching(prompt, context)
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    continue
                return {
                    "ok": False,
                    "error": f"model call failed after {max_retries + 1} attempts: {last_error}",
                    "operations": [],
                }

            # Step 4: Parse response into operations
            operations = self._parse_response(response)

            if operations:
                return {
                    "ok": True,
                    "operations": operations,
                }

            # If parsing failed, retry with more explicit instructions
            if attempt < max_retries:
                prompt = self._build_retry_prompt(task, context, response)
                continue

        return {
            "ok": False,
            "error": "no valid operations extracted from model response after retries",
            "operations": [],
        }

    def _build_extreme_prompt(self, task: str, context: TaskContext) -> str:
        """Build extreme prompt with all context."""

        # Build relevant code snippets
        relevant_code = self._format_relevant_code(context)

        # Build similar examples
        similar_examples = self._format_similar_code(context)

        # Build conventions
        conventions = self._format_conventions(context)

        prompt = f"""You are an expert Python developer working on a production codebase.

# Task
{task}

# Project Context
- Python version: {context.python_version}
- Framework: {context.framework or "None"}
- Test framework: {context.conventions.test_framework}
- Project root: {context.project_root}

# Relevant Existing Code
{relevant_code}

# Project Conventions (learned from codebase)
{conventions}

# Similar Implementations (for reference)
{similar_examples}

# Common Mistakes to Avoid
{self._format_mistakes(context.common_mistakes)}

# Requirements
1. Follow existing project conventions EXACTLY
2. Include comprehensive type hints (project uses type hints: {context.conventions.type_hints_used})
3. Write defensive code (handle edge cases: None, empty, invalid input)
4. Include docstrings ({context.conventions.docstring_style} style)
5. Write corresponding tests in tests/test_*.py using {context.conventions.test_framework}
6. Use {context.conventions.quote_style} quotes
7. Keep lines under {context.conventions.line_length} characters
8. Ensure code is production-ready and complete

# Output Format
Provide complete, production-ready code for ALL files that need to be created or modified.

For each file, use this EXACT format:
```
FILE: path/to/file.py
<complete file content>
```

Think step by step:
1. What files need to be created or modified?
2. What are the edge cases to handle?
3. What imports are needed?
4. What tests are needed?

Now implement the task. Output ONLY the file blocks, no explanation before or after."""

        return prompt

    def _format_relevant_code(self, context: TaskContext) -> str:
        """Format relevant code snippets."""

        if not context.relevant_files:
            return "(No directly relevant files found)"

        lines = []
        for hit in context.relevant_files[:5]:  # Top 5 files
            lines.append(f"- {hit.path} (score: {hit.score:.2f})")
            if hit.symbols:
                lines.append(f"  Symbols: {', '.join(hit.symbols[:5])}")
            if hit.preview:
                lines.append(f"  Preview: {hit.preview[:200]}")

        return "\n".join(lines)

    def _format_similar_code(self, context: TaskContext) -> str:
        """Format similar code examples."""

        if not context.similar_code:
            return "(No similar implementations found)"

        lines = []
        for example in context.similar_code:
            lines.append(f"\n## Example from {example.path}")
            lines.append(f"Reason: {example.reason}")
            lines.append("```python")
            lines.append(example.code[:500])  # First 500 chars
            lines.append("```")

        return "\n".join(lines)

    def _format_conventions(self, context: TaskContext) -> str:
        """Format project conventions."""

        conv = context.conventions
        return f"""- Naming: {conv.naming_style}
- Docstrings: {conv.docstring_style} style
- Type hints: {"Required" if conv.type_hints_used else "Optional"}
- Test framework: {conv.test_framework}
- Quote style: {conv.quote_style} quotes
- Line length: {conv.line_length} characters"""

    def _format_mistakes(self, mistakes: list[str]) -> str:
        """Format common mistakes."""

        if not mistakes:
            return "(None specific to this task)"

        return "\n".join(f"- {mistake}" for mistake in mistakes)

    def _generate_with_caching(self, prompt: str, context: TaskContext) -> str:
        """Generate code with prompt caching to reduce cost.

        Uses ModelClient's system/prompt separation for caching.
        System prompt (project context) is cacheable across tasks.
        User prompt (specific task) varies per request.
        """

        lines = prompt.split("\n")

        # Find where task-specific content starts
        task_start = 0
        for i, line in enumerate(lines):
            if line.startswith("# Task"):
                task_start = i
                break

        # System prompt (cacheable): everything about the project
        system_lines = [
            "You are an expert Python developer working on a production codebase.",
            "",
            f"# Project Context",
            f"- Python version: {context.python_version}",
            f"- Framework: {context.framework or 'None'}",
            f"- Test framework: {context.conventions.test_framework}",
            "",
            "# Project Conventions",
            self._format_conventions(context),
        ]

        system_prompt = "\n".join(system_lines)

        # User prompt (variable): the specific task
        user_prompt = "\n".join(lines[task_start:])

        # Call model with system/prompt separation for caching
        # ModelClient uses complete() with ModelRequest
        request = ModelRequest(
            model="claude-opus-4-7",
            prompt=user_prompt,
            system=system_prompt,
            project=str(self.project_root),
        )

        response = self.model_client.complete(request)

        if not response.ok:
            raise RuntimeError(f"Model call failed: {response.error}")

        return response.text

    def _parse_response(self, response: str) -> list[dict[str, str]]:
        """Parse model response into operations.

        Supports multiple formats:
        1. FILE: path/to/file.py
        2. ```python path/to/file.py
        3. # File: path/to/file.py
        """

        operations = []

        # Try multiple parsing strategies
        strategies = [
            self._parse_file_marker,
            self._parse_code_blocks_with_path,
            self._parse_markdown_headers,
        ]

        for strategy in strategies:
            ops = strategy(response)
            if ops:
                operations.extend(ops)

        # Deduplicate by path (keep last occurrence)
        seen = {}
        for op in operations:
            seen[op["path"]] = op

        return list(seen.values())

    def _parse_file_marker(self, response: str) -> list[dict[str, str]]:
        """Parse FILE: marker format."""
        operations = []

        # Pattern: FILE: path/to/file.py followed by code
        pattern = r'FILE:\s*([^\n]+)\n(.*?)(?=FILE:|$)'
        matches = re.findall(pattern, response, re.DOTALL)

        for file_path, code in matches:
            file_path = file_path.strip()
            code = code.strip()

            # Remove markdown code fences if present
            code = re.sub(r'^```(?:python)?\n', '', code)
            code = re.sub(r'\n```$', '', code)
            code = code.strip()

            if not code:
                continue

            # Validate path is relative and safe
            if file_path.startswith("/") or ".." in file_path:
                continue

            operations.append({
                "op": "write_text",
                "path": file_path,
                "text": code,
            })

        return operations

    def _parse_code_blocks_with_path(self, response: str) -> list[dict[str, str]]:
        """Parse code blocks with path in the fence."""
        operations = []

        # Pattern: ```python path/to/file.py
        pattern = r'```(?:python)?\s+([^\n]+)\n(.*?)```'
        matches = re.findall(pattern, response, re.DOTALL)

        for file_path, code in matches:
            file_path = file_path.strip()
            code = code.strip()

            if not code:
                continue

            # Skip if path looks like a language identifier
            if file_path in ("python", "py", "bash", "sh", "json", "yaml"):
                continue

            # Validate path
            if file_path.startswith("/") or ".." in file_path:
                continue

            # Must look like a file path
            if not ("/" in file_path or file_path.endswith(".py")):
                continue

            operations.append({
                "op": "write_text",
                "path": file_path,
                "text": code,
            })

        return operations

    def _parse_markdown_headers(self, response: str) -> list[dict[str, str]]:
        """Parse markdown headers with file paths."""
        operations = []

        # Pattern: # File: path/to/file.py or ## path/to/file.py
        lines = response.split("\n")
        current_path = None
        current_code = []

        for line in lines:
            # Check for file header
            if line.startswith("# File:") or line.startswith("## File:"):
                # Save previous file
                if current_path and current_code:
                    code = "\n".join(current_code).strip()
                    # Remove code fences
                    code = re.sub(r'^```(?:python)?\n', '', code)
                    code = re.sub(r'\n```$', '', code)
                    code = code.strip()

                    if code and not current_path.startswith("/") and ".." not in current_path:
                        operations.append({
                            "op": "write_text",
                            "path": current_path,
                            "text": code,
                        })

                # Start new file
                current_path = line.split(":", 1)[1].strip()
                current_code = []
            elif line.startswith("#") and "/" in line and line.endswith(".py"):
                # Alternative: ## path/to/file.py
                if current_path and current_code:
                    code = "\n".join(current_code).strip()
                    code = re.sub(r'^```(?:python)?\n', '', code)
                    code = re.sub(r'\n```$', '', code)
                    code = code.strip()

                    if code and not current_path.startswith("/") and ".." not in current_path:
                        operations.append({
                            "op": "write_text",
                            "path": current_path,
                            "text": code,
                        })

                current_path = line.lstrip("#").strip()
                current_code = []
            elif current_path:
                current_code.append(line)

        # Save last file
        if current_path and current_code:
            code = "\n".join(current_code).strip()
            code = re.sub(r'^```(?:python)?\n', '', code)
            code = re.sub(r'\n```$', '', code)
            code = code.strip()

            if code and not current_path.startswith("/") and ".." not in current_path:
                operations.append({
                    "op": "write_text",
                    "path": current_path,
                    "text": code,
                })

        return operations

    def _build_retry_prompt(self, task: str, context: TaskContext, previous_response: str) -> str:
        """Build retry prompt with more explicit format instructions."""

        return f"""You are an expert Python developer working on a production codebase.

# Task
{task}

# Previous Response Issue
Your previous response could not be parsed. Please follow the EXACT format below.

# Required Output Format
You MUST use this exact format for each file:

FILE: path/to/file.py
```python
<complete file content here>
```

Example:
FILE: quantagent/example.py
```python
def hello():
    return "world"
```

FILE: tests/test_example.py
```python
def test_hello():
    assert hello() == "world"
```

# Project Context
- Python version: {context.python_version}
- Framework: {context.framework or "None"}
- Test framework: {context.conventions.test_framework}

# Requirements
1. Use the FILE: marker before each file
2. Include complete, production-ready code
3. Follow project conventions
4. Include tests

Now implement the task using the exact format above."""
