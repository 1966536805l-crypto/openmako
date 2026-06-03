"""Deterministic-first code fixer with AI fallback.

80% of code errors can be fixed deterministically:
- Auto-format (black, ruff format)
- Add missing imports (autoflake, isort)
- Fix simple type errors (remove unused, add obvious types)
- Fix syntax errors (missing colons, unmatched brackets)

Only invoke AI when deterministic fixes fail or are insufficient.
Record cost of every fix attempt for budget tracking.
"""

from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .exception_audit import audit_suppressed_exception
from .model_client import ModelClient, ModelRequest
from .model_errors import classify_model_error


@dataclass(frozen=True)
class FixAttempt:
    """Single fix attempt record."""
    method: Literal["format", "import", "type", "syntax", "ai"]
    success: bool
    duration_ms: int
    cost_usd: float
    error_before: str
    error_after: str
    diff_lines: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FixResult:
    """Result of fix operation."""
    ok: bool
    file_path: str
    original_error: str
    final_error: str
    attempts: list[FixAttempt]
    total_cost_usd: float
    total_duration_ms: int
    deterministic_success: bool
    ai_invoked: bool

    @property
    def fix_count(self) -> int:
        return sum(1 for a in self.attempts if a.success)

    @property
    def deterministic_ratio(self) -> float:
        """Ratio of deterministic fixes to total attempts."""
        if not self.attempts:
            return 0.0
        det = sum(1 for a in self.attempts if a.method != "ai")
        return det / len(self.attempts)


class SmartFixer:
    """Deterministic-first code fixer with AI fallback.

    Fix priority:
    1. Auto-format (black/ruff) - free, fast, safe
    2. Add missing imports - deterministic via AST analysis
    3. Fix simple type errors - pattern-based
    4. Fix syntax errors - bracket/colon matching
    5. AI fix - only when above fail

    Tracks cost and success rate of each method.
    """

    def __init__(
        self,
        *,
        model_client: ModelClient | None = None,
        enable_ai: bool = True,
        max_ai_cost_usd: float = 0.50,
        timeout_sec: int = 30,
    ):
        self.model_client = model_client
        self.enable_ai = enable_ai
        self.max_ai_cost_usd = max_ai_cost_usd
        self.timeout_sec = timeout_sec
        self._total_cost = 0.0

    def fix_file(
        self,
        file_path: str | Path,
        error_output: str,
        *,
        verify_command: list[str] | None = None,
        verify_cwd: str | Path | None = None,
        verify_env: dict[str, str] | None = None,
    ) -> FixResult:
        """Fix a file with deterministic methods first, AI as fallback.

        Args:
            file_path: Path to file to fix
            error_output: Error message from linter/compiler/test
            verify_command: Command to verify fix (e.g. ["python3", "-m", "py_compile", "file.py"])

        Returns:
            FixResult with all attempts and final status
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return FixResult(
                ok=False,
                file_path=str(path),
                original_error=error_output,
                final_error=f"File not found: {path}",
                attempts=[],
                total_cost_usd=0.0,
                total_duration_ms=0,
                deterministic_success=False,
                ai_invoked=False,
            )

        attempts: list[FixAttempt] = []
        current_error = error_output
        original_content = path.read_text(encoding="utf-8")

        # 1. Try auto-format
        attempt = self._try_format(path, current_error)
        attempts.append(attempt)
        if attempt.success:
            current_error = self._verify_fix(
                path,
                verify_command,
                verify_cwd=verify_cwd,
                verify_env=verify_env,
            )
            if not current_error:
                return self._make_result(path, error_output, "", attempts, deterministic=True)

        # 2. Try import fixes
        attempt = self._try_import_fix(path, current_error)
        attempts.append(attempt)
        if attempt.success:
            current_error = self._verify_fix(
                path,
                verify_command,
                verify_cwd=verify_cwd,
                verify_env=verify_env,
            )
            if not current_error:
                return self._make_result(path, error_output, "", attempts, deterministic=True)

        # 3. Try simple type fixes
        attempt = self._try_type_fix(path, current_error)
        attempts.append(attempt)
        if attempt.success:
            current_error = self._verify_fix(
                path,
                verify_command,
                verify_cwd=verify_cwd,
                verify_env=verify_env,
            )
            if not current_error:
                return self._make_result(path, error_output, "", attempts, deterministic=True)

        # 4. Try syntax fixes
        attempt = self._try_syntax_fix(path, current_error)
        attempts.append(attempt)
        if attempt.success:
            current_error = self._verify_fix(
                path,
                verify_command,
                verify_cwd=verify_cwd,
                verify_env=verify_env,
            )
            if not current_error:
                return self._make_result(path, error_output, "", attempts, deterministic=True)

        # 5. AI fallback (only if enabled and budget available)
        if self.enable_ai and self._total_cost < self.max_ai_cost_usd:
            attempt = self._try_ai_fix(path, current_error, original_content)
            attempts.append(attempt)
            if attempt.success:
                current_error = self._verify_fix(
                    path,
                    verify_command,
                    verify_cwd=verify_cwd,
                    verify_env=verify_env,
                )
                if not current_error:
                    return self._make_result(path, error_output, "", attempts, deterministic=False, ai_invoked=True)

        # All fixes failed
        return self._make_result(path, error_output, current_error, attempts, deterministic=False, ai_invoked=any(a.method == "ai" for a in attempts))

    def _try_format(self, path: Path, error: str) -> FixAttempt:
        """Try auto-formatting with black or ruff."""
        start = time.perf_counter()

        # Try ruff format first (faster)
        try:
            result = subprocess.run(
                ["ruff", "format", str(path)],
                capture_output=True,
                timeout=self.timeout_sec,
            )
            if result.returncode == 0:
                duration_ms = int((time.perf_counter() - start) * 1000)
                return FixAttempt(
                    method="format",
                    success=True,
                    duration_ms=duration_ms,
                    cost_usd=0.0,
                    error_before=error,
                    error_after="",
                    diff_lines=0,
                    details={"tool": "ruff"},
                )
        except FileNotFoundError:
            pass

        # Fallback to black
        try:
            result = subprocess.run(
                ["black", "--quiet", str(path)],
                capture_output=True,
                timeout=self.timeout_sec,
            )
            if result.returncode == 0:
                duration_ms = int((time.perf_counter() - start) * 1000)
                return FixAttempt(
                    method="format",
                    success=True,
                    duration_ms=duration_ms,
                    cost_usd=0.0,
                    error_before=error,
                    error_after="",
                    diff_lines=0,
                    details={"tool": "black"},
                )
        except FileNotFoundError:
            pass

        # No formatter available
        duration_ms = int((time.perf_counter() - start) * 1000)
        return FixAttempt(
            method="format",
            success=False,
            duration_ms=duration_ms,
            cost_usd=0.0,
            error_before=error,
            error_after=error,
            diff_lines=0,
            details={"tool": "none", "reason": "no formatter available"},
        )

    def _try_import_fix(self, path: Path, error: str) -> FixAttempt:
        """Add missing imports via AST analysis."""
        start = time.perf_counter()

        # Extract missing import from error
        missing = self._extract_missing_import(error)
        if not missing:
            return FixAttempt(
                method="import",
                success=False,
                duration_ms=0,
                cost_usd=0.0,
                error_before=error,
                error_after=error,
                diff_lines=0,
                details={"reason": "no missing import detected"},
            )

        # Add import at top of file
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        # Find insertion point (after docstring/comments, before code)
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                insert_idx = i
                break

        import_line = f"import {missing}\n"
        lines.insert(insert_idx, import_line)
        path.write_text("".join(lines), encoding="utf-8")

        duration_ms = int((time.perf_counter() - start) * 1000)

        return FixAttempt(
            method="import",
            success=True,
            duration_ms=duration_ms,
            cost_usd=0.0,
            error_before=error,
            error_after="",
            diff_lines=1,
            details={"added": missing},
        )

    def _try_type_fix(self, path: Path, error: str) -> FixAttempt:
        """Fix simple type errors via pattern matching."""
        start = time.perf_counter()

        content = path.read_text(encoding="utf-8")
        original = content
        fix_pattern = "no_match"

        # Pattern: unused variable
        if "unused variable" in error.lower() or "is assigned to but never used" in error.lower():
            # Extract variable name and line number
            match = re.search(r"'(\w+)'.*line (\d+)", error)
            if match:
                var_name = match.group(1)
                # Prefix with underscore to mark as intentionally unused
                content = re.sub(rf"\b{var_name}\b", f"_{var_name}", content, count=1)
                fix_pattern = "unused_var"

        # Pattern: missing type annotation (simple cases)
        elif "missing type annotation" in error.lower() or "need type annotation" in error.lower():
            var_match = re.search(r"(?:Need|Missing) type annotation for [\"'](\w+)[\"']", error, re.IGNORECASE)
            if var_match:
                content = self._annotate_empty_collection(content, var_match.group(1))
                fix_pattern = "type_annotation"
            else:
                # Add : Any for now (deterministic, safe)
                match = re.search(r"line (\d+)", error)
                if match:
                    line_num = int(match.group(1)) - 1
                    lines = content.splitlines(keepends=True)
                    if line_num < len(lines):
                        line = lines[line_num]
                        # Simple pattern: def func(param) -> add : Any
                        if "def " in line and "(" in line:
                            lines[line_num] = line.replace("(", "(", 1)  # No-op for now
                            content = "".join(lines)
                            fix_pattern = "type_annotation"

        changed = content != original
        if changed:
            path.write_text(content, encoding="utf-8")

        duration_ms = int((time.perf_counter() - start) * 1000)

        return FixAttempt(
            method="type",
            success=changed,
            duration_ms=duration_ms,
            cost_usd=0.0,
            error_before=error,
            error_after="" if changed else error,
            diff_lines=1 if changed else 0,
            details={"pattern": fix_pattern if changed else "no_match"},
        )

    def _annotate_empty_collection(self, content: str, var_name: str) -> str:
        lines = content.splitlines(keepends=True)
        assignment = re.compile(
            rf"^(\s*){re.escape(var_name)}\s*=\s*(\{{\}}|\[\]|set\(\))(\s*(?:#.*)?\n?)$"
        )
        annotations = {
            "{}": "dict[Any, Any]",
            "[]": "list[Any]",
            "set()": "set[Any]",
        }

        for idx, line in enumerate(lines):
            match = assignment.match(line)
            if not match:
                continue
            indent, literal, suffix = match.groups()
            lines[idx] = f"{indent}{var_name}: {annotations[literal]} = {literal}{suffix}"
            return self._ensure_typing_any_import("".join(lines))

        return content

    def _ensure_typing_any_import(self, content: str) -> str:
        if re.search(r"^from typing import .*\bAny\b", content, re.MULTILINE):
            return content

        lines = content.splitlines(keepends=True)
        for idx, line in enumerate(lines):
            if line.startswith("from typing import "):
                lines[idx] = line.rstrip("\n") + ", Any\n"
                return "".join(lines)

        insert_idx = self._typing_import_insert_index(lines)
        lines.insert(insert_idx, "from typing import Any\n")
        return "".join(lines)

    def _typing_import_insert_index(self, lines: list[str]) -> int:
        idx = 0
        while idx < len(lines) and (
            lines[idx].startswith("#!")
            or "coding" in lines[idx][:40]
            or not lines[idx].strip()
        ):
            idx += 1

        if idx < len(lines) and lines[idx].lstrip().startswith(("'''", '"""')):
            quote = "'''" if lines[idx].lstrip().startswith("'''") else '"""'
            if lines[idx].count(quote) >= 2 and lines[idx].lstrip().find(quote, 3) != -1:
                idx += 1
            else:
                idx += 1
                while idx < len(lines):
                    if quote in lines[idx]:
                        idx += 1
                        break
                    idx += 1

        while idx < len(lines) and lines[idx].startswith("from __future__ import "):
            idx += 1

        return idx

    def _try_syntax_fix(self, path: Path, error: str) -> FixAttempt:
        """Fix syntax errors (missing colons, brackets)."""
        start = time.perf_counter()

        content = path.read_text(encoding="utf-8")
        original = content

        # Pattern: missing colon
        if "expected ':'" in error.lower() or "syntaxerror: invalid syntax" in error.lower():
            match = re.search(r"line (\d+)", error)
            lines = content.splitlines(keepends=True)

            if match:
                # Fix specific line
                line_num = int(match.group(1)) - 1
                if line_num < len(lines):
                    line = lines[line_num]
                    # Add colon at end if missing
                    if line.strip() and not line.rstrip().endswith(":"):
                        if any(kw in line for kw in ["def ", "class ", "if ", "elif ", "else", "for ", "while ", "try", "except", "finally", "with "]):
                            lines[line_num] = line.rstrip() + ":\n"
                            content = "".join(lines)
            else:
                # No line number - scan all lines for missing colons
                for i, line in enumerate(lines):
                    if line.strip() and not line.rstrip().endswith(":"):
                        if any(kw in line for kw in ["def ", "class ", "if ", "elif ", "else", "for ", "while ", "try", "except", "finally", "with "]):
                            lines[i] = line.rstrip() + ":\n"
                content = "".join(lines)

        # Pattern: unmatched brackets
        elif "unmatched" in error.lower() or "unexpected eof" in error.lower():
            # Count brackets
            open_paren = content.count("(")
            close_paren = content.count(")")
            if open_paren > close_paren:
                content += ")" * (open_paren - close_paren)

            open_bracket = content.count("[")
            close_bracket = content.count("]")
            if open_bracket > close_bracket:
                content += "]" * (open_bracket - close_bracket)

            open_brace = content.count("{")
            close_brace = content.count("}")
            if open_brace > close_brace:
                content += "}" * (open_brace - close_brace)

        changed = content != original
        if changed:
            path.write_text(content, encoding="utf-8")

        duration_ms = int((time.perf_counter() - start) * 1000)

        return FixAttempt(
            method="syntax",
            success=changed,
            duration_ms=duration_ms,
            cost_usd=0.0,
            error_before=error,
            error_after="" if changed else error,
            diff_lines=1 if changed else 0,
            details={"pattern": "colon_or_bracket" if changed else "no_match"},
        )

    def _try_ai_fix(self, path: Path, error: str, original_content: str) -> FixAttempt:
        """AI-powered fix as last resort."""
        if not self.model_client:
            return FixAttempt(
                method="ai",
                success=False,
                duration_ms=0,
                cost_usd=0.0,
                error_before=error,
                error_after=error,
                diff_lines=0,
                details={"reason": "no model client"},
            )

        start = time.perf_counter()

        # Precise prompt for code fixing
        prompt = f"""Fix this Python code error. Return ONLY the corrected code, no explanation.

File: {path.name}
Error: {error[:500]}

Current code:
```python
{original_content}
```

Return the complete fixed code:"""

        try:
            request = ModelRequest(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4000,
            )
            response = self.model_client.complete(request)

            # Extract code from response
            fixed_code = self._extract_code_block(response.content)
            if not fixed_code:
                fixed_code = response.content

            # Validate it's valid Python
            try:
                ast.parse(fixed_code)
            except SyntaxError:
                duration_ms = int((time.perf_counter() - start) * 1000)
                return FixAttempt(
                    method="ai",
                    success=False,
                    duration_ms=duration_ms,
                    cost_usd=response.cost_usd,
                    error_before=error,
                    error_after="AI returned invalid Python",
                    diff_lines=0,
                    details={"reason": "invalid_syntax"},
                )

            # Write fixed code
            path.write_text(fixed_code, encoding="utf-8")

            duration_ms = int((time.perf_counter() - start) * 1000)
            cost = response.cost_usd
            self._total_cost += cost

            return FixAttempt(
                method="ai",
                success=True,
                duration_ms=duration_ms,
                cost_usd=cost,
                error_before=error,
                error_after="",
                diff_lines=len(fixed_code.splitlines()) - len(original_content.splitlines()),
                details={"model": response.model, "tokens": response.usage.total_tokens if response.usage else 0},
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            classified = classify_model_error(e)
            return FixAttempt(
                method="ai",
                success=False,
                duration_ms=duration_ms,
                cost_usd=0.0,
                error_before=error,
                error_after=str(e)[:200],
                diff_lines=0,
                details={"error": classified.reason.value},
            )

    def _verify_fix(
        self,
        path: Path,
        verify_command: list[str] | None,
        *,
        verify_cwd: str | Path | None = None,
        verify_env: dict[str, str] | None = None,
    ) -> str:
        """Verify fix by running verification command.

        Returns:
            Empty string if verification passed, error message otherwise
        """
        if not verify_command:
            # Default: try to compile
            try:
                ast.parse(path.read_text(encoding="utf-8"))
                return ""
            except SyntaxError as e:
                return str(e)

        try:
            result = subprocess.run(
                verify_command,
                capture_output=True,
                timeout=self.timeout_sec,
                text=True,
                cwd=str(verify_cwd) if verify_cwd else None,
                env=verify_env,
            )
            if result.returncode == 0:
                return ""
            return result.stderr or result.stdout or f"exit {result.returncode}"
        except subprocess.TimeoutExpired:
            return "verification timeout"
        except Exception as e:
            audit_suppressed_exception(f"{__name__}:508", e)
            return str(e)

    def _extract_missing_import(self, error: str) -> str | None:
        """Extract missing import name from error message."""
        # Pattern: NameError: name 'X' is not defined
        match = re.search(r"name '(\w+)' is not defined", error)
        if match:
            return match.group(1)

        # Pattern: ImportError: cannot import name 'X'
        match = re.search(r"cannot import name '(\w+)'", error)
        if match:
            return match.group(1)

        # Pattern: ModuleNotFoundError: No module named 'X'
        match = re.search(r"no module named '(\w+)'", error, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    def _extract_code_block(self, text: str) -> str:
        """Extract code from markdown code block."""
        match = re.search(r"```(?:python)?\n(.*?)\n```", text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    def _make_result(
        self,
        path: Path,
        original_error: str,
        final_error: str,
        attempts: list[FixAttempt],
        deterministic: bool,
        ai_invoked: bool = False,
    ) -> FixResult:
        """Build final result."""
        total_cost = sum(a.cost_usd for a in attempts)
        total_duration = sum(a.duration_ms for a in attempts)

        return FixResult(
            ok=not final_error,
            file_path=str(path),
            original_error=original_error,
            final_error=final_error,
            attempts=attempts,
            total_cost_usd=total_cost,
            total_duration_ms=total_duration,
            deterministic_success=deterministic,
            ai_invoked=ai_invoked,
        )


def fix_code_file(
    file_path: str | Path,
    error_output: str,
    *,
    model_client: ModelClient | None = None,
    enable_ai: bool = True,
    verify_command: list[str] | None = None,
) -> FixResult:
    """Convenience function to fix a single file.

    Args:
        file_path: Path to file to fix
        error_output: Error message from linter/compiler/test
        model_client: Optional model client for AI fixes
        enable_ai: Whether to enable AI fallback
        verify_command: Command to verify fix

    Returns:
        FixResult with all attempts and final status
    """
    fixer = SmartFixer(
        model_client=model_client,
        enable_ai=enable_ai,
    )
    return fixer.fix_file(file_path, error_output, verify_command=verify_command)
