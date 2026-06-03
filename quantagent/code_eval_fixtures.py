from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .edit_loop import create_patch_plan, run_isolated_repair_loop
from .model_client import ModelClient


PASS = "pass"
FAIL = "fail"
ERROR = "error"
DEFAULT_TEST_COMMAND = ("python3", "-m", "unittest", "discover", "-s", "tests")
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PREVIEW_CHARS = 2400


@dataclass(frozen=True)
class CodeEvalFile:
    path: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeEvalEdit:
    path: str
    old: str
    new: str
    expected_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeEvalFixture:
    id: str
    title: str
    issue: str
    files: tuple[CodeEvalFile, ...]
    oracle_edits: tuple[CodeEvalEdit, ...]
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND
    expected_initial_status: str = FAIL
    expected_failure: str = ""
    tags: tuple[str, ...] = ("code", "issue-to-patch")
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["test_command"] = list(self.test_command)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class CodeEvalCommandResult:
    status: str
    returncode: int | None
    command: list[str]
    duration_ms: int
    stdout_preview: str = ""
    stderr_preview: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeEvalFixtureRun:
    fixture_id: str
    title: str
    workspace: str
    issue_path: str
    initial: CodeEvalCommandResult
    oracle: CodeEvalCommandResult | None = None
    ok: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "title": self.title,
            "workspace": self.workspace,
            "issue_path": self.issue_path,
            "initial": self.initial.to_dict(),
            "oracle": self.oracle.to_dict() if self.oracle else None,
            "ok": self.ok,
            "message": self.message,
        }


@dataclass(frozen=True)
class CodeEvalSolveRun:
    fixture_id: str
    title: str
    workspace: str
    issue_path: str
    initial: CodeEvalCommandResult
    solver_ok: bool = False
    solver_summary: str = ""
    review_id: str = ""
    changed_paths: tuple[str, ...] = ()
    rounds: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_paths"] = list(self.changed_paths)
        return payload


@dataclass(frozen=True)
class CodeEvalRun:
    run_id: str
    project: str
    started_at: str
    finished_at: str
    results: tuple[CodeEvalFixtureRun, ...]
    duration_ms: int = 0

    @property
    def summary(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for item in self.results if item.ok)
        failed = total - passed
        coverage = _fixture_coverage(tuple(item.fixture_id for item in self.results))
        level = _code_engineering_level(total=total, passed=passed, coverage=coverage)
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "score": passed,
            "max_score": total,
            "percent": round(passed / total * 100) if total else 0,
            "engineering_level": level["level"],
            "level_reasons": level["reasons"],
            "multi_file_fixtures": coverage["multi_file_fixtures"],
            "multi_edit_fixtures": coverage["multi_edit_fixtures"],
            "coverage_tags": coverage["coverage_tags"],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
        }


@dataclass(frozen=True)
class CodeEvalSolvePackRun:
    run_id: str
    project: str
    started_at: str
    finished_at: str
    model: str
    results: tuple[CodeEvalSolveRun, ...]
    duration_ms: int = 0

    @property
    def summary(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for item in self.results if item.solver_ok)
        failed = total - passed
        coverage = _fixture_coverage(tuple(item.fixture_id for item in self.results))
        level = _code_engineering_level(total=total, passed=passed, coverage=coverage)
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "score": passed,
            "max_score": total,
            "percent": round(passed / total * 100) if total else 0,
            "engineering_level": level["level"],
            "level_reasons": level["reasons"],
            "multi_file_fixtures": coverage["multi_file_fixtures"],
            "multi_edit_fixtures": coverage["multi_edit_fixtures"],
            "coverage_tags": coverage["coverage_tags"],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "summary": self.summary,
            "results": [item.to_dict() for item in self.results],
        }


def code_eval_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "code_eval_fixtures"


def builtin_code_eval_fixtures() -> tuple[CodeEvalFixture, ...]:
    return (
        _fixture(
            "add-regression",
            "Addition returns subtraction",
            "Fix add(a, b). The failing test shows add(2, 3) should return 5.",
            "calc.py",
            "def add(a, b):\n    return a - b\n",
            "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py",
            "import unittest\nfrom calc import add\n\n\nclass CalcTest(unittest.TestCase):\n    def test_adds_numbers(self):\n        self.assertEqual(add(2, 3), 5)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "unit", "simple"),
        ),
        _fixture(
            "email-normalization",
            "Email normalizer preserves spaces and case",
            "Normalize user emails by trimming outer whitespace and lowercasing the address.",
            "users.py",
            "def normalize_email(value):\n    return value\n",
            "def normalize_email(value):\n    return value.strip().lower()\n",
            "tests/test_users.py",
            "import unittest\nfrom users import normalize_email\n\n\nclass UsersTest(unittest.TestCase):\n    def test_normalizes_email(self):\n        self.assertEqual(normalize_email('  Alice@Example.COM '), 'alice@example.com')\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "string"),
        ),
        _fixture(
            "comma-int-parser",
            "Integer parser rejects comma separated values",
            "parse_int should accept simple thousands separators such as '1,200'.",
            "numparse.py",
            "def parse_int(value):\n    return int(value)\n",
            "def parse_int(value):\n    return int(str(value).replace(',', ''))\n",
            "tests/test_numparse.py",
            "import unittest\nfrom numparse import parse_int\n\n\nclass NumParseTest(unittest.TestCase):\n    def test_parses_commas(self):\n        self.assertEqual(parse_int('1,200'), 1200)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="ValueError",
            tags=("code", "issue-to-patch", "parsing"),
        ),
        _fixture(
            "palindrome-normalization",
            "Palindrome check treats punctuation as characters",
            "is_palindrome should ignore case and non-alphanumeric separators.",
            "textcheck.py",
            "def is_palindrome(value):\n    return value == value[::-1]\n",
            "def is_palindrome(value):\n    cleaned = ''.join(ch.lower() for ch in value if ch.isalnum())\n    return cleaned == cleaned[::-1]\n",
            "tests/test_textcheck.py",
            "import unittest\nfrom textcheck import is_palindrome\n\n\nclass TextCheckTest(unittest.TestCase):\n    def test_sentence_palindrome(self):\n        self.assertTrue(is_palindrome('A man, a plan, a canal: Panama'))\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "string"),
        ),
        _fixture(
            "chunk-tail-loss",
            "Chunking drops the final partial chunk",
            "chunk_list should keep the final partial chunk instead of truncating it.",
            "chunks.py",
            "def chunk_list(values, size):\n    return [values[i:i + size] for i in range(0, len(values) - len(values) % size, size)]\n",
            "def chunk_list(values, size):\n    return [values[i:i + size] for i in range(0, len(values), size)]\n",
            "tests/test_chunks.py",
            "import unittest\nfrom chunks import chunk_list\n\n\nclass ChunksTest(unittest.TestCase):\n    def test_keeps_tail_chunk(self):\n        self.assertEqual(chunk_list([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "list"),
        ),
        _fixture(
            "slugify-punctuation",
            "Slugify leaves punctuation in URLs",
            "slugify should produce lowercase hyphenated slugs with punctuation removed.",
            "slug.py",
            "def slugify(value):\n    return value.lower().replace(' ', '-')\n",
            "import re\n\n\ndef slugify(value):\n    slug = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')\n    return slug\n",
            "tests/test_slug.py",
            "import unittest\nfrom slug import slugify\n\n\nclass SlugTest(unittest.TestCase):\n    def test_removes_punctuation(self):\n        self.assertEqual(slugify('Hello, Mako Agent!'), 'hello-mako-agent')\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "regex"),
        ),
        _fixture(
            "moving-average-denominator",
            "Average divides by one too few values",
            "mean should divide by the full number of values.",
            "stats.py",
            "def mean(values):\n    return sum(values) / (len(values) - 1)\n",
            "def mean(values):\n    return sum(values) / len(values)\n",
            "tests/test_stats.py",
            "import unittest\nfrom stats import mean\n\n\nclass StatsTest(unittest.TestCase):\n    def test_mean(self):\n        self.assertEqual(mean([2, 4, 6]), 4)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "math"),
        ),
        _fixture(
            "unique-order",
            "Unique helper sorts values instead of preserving input order",
            "unique should remove duplicates while preserving first-seen order.",
            "dedupe.py",
            "def unique(values):\n    return sorted(set(values))\n",
            "def unique(values):\n    out = []\n    for value in values:\n        if value not in out:\n            out.append(value)\n    return out\n",
            "tests/test_dedupe.py",
            "import unittest\nfrom dedupe import unique\n\n\nclass DedupeTest(unittest.TestCase):\n    def test_preserves_order(self):\n        self.assertEqual(unique(['b', 'a', 'b', 'c']), ['b', 'a', 'c'])\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "list"),
        ),
        _fixture(
            "retry-count",
            "Retry helper performs one attempt too few",
            "retry should call the function exactly attempts times before re-raising.",
            "retrying.py",
            "def retry(fn, attempts):\n    last = None\n    for _ in range(attempts - 1):\n        try:\n            return fn()\n        except Exception as exc:\n            last = exc\n    raise last\n",
            "def retry(fn, attempts):\n    last = None\n    for _ in range(attempts):\n        try:\n            return fn()\n        except Exception as exc:\n            last = exc\n    raise last\n",
            "tests/test_retrying.py",
            "import unittest\nfrom retrying import retry\n\n\nclass RetryTest(unittest.TestCase):\n    def test_uses_all_attempts(self):\n        calls = {'count': 0}\n        def flaky():\n            calls['count'] += 1\n            if calls['count'] < 3:\n                raise RuntimeError('not yet')\n            return 'ok'\n        self.assertEqual(retry(flaky, 3), 'ok')\n        self.assertEqual(calls['count'], 3)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="RuntimeError",
            tags=("code", "issue-to-patch", "control-flow"),
        ),
        _fixture(
            "merge-mutates-input",
            "Merge helper mutates its input dictionary",
            "merge should return a new dictionary and leave the base object unchanged.",
            "merge.py",
            "def merge(base, override):\n    base.update(override)\n    return base\n",
            "def merge(base, override):\n    merged = dict(base)\n    merged.update(override)\n    return merged\n",
            "tests/test_merge.py",
            "import unittest\nfrom merge import merge\n\n\nclass MergeTest(unittest.TestCase):\n    def test_does_not_mutate_base(self):\n        base = {'a': 1}\n        self.assertEqual(merge(base, {'b': 2}), {'a': 1, 'b': 2})\n        self.assertEqual(base, {'a': 1})\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "mutation"),
        ),
        _multi_file_fixture(
            "parser-service-contract",
            "Parser returns fields the service does not consume",
            "parse_user should return the name/email keys expected by user_label and trim input whitespace.",
            files=(
                CodeEvalFile(
                    "service.py",
                    "from parser import parse_user\n\n\ndef user_label(raw):\n    user = parse_user(raw)\n    return f\"{user['name']}<{user['email']}>\"\n",
                ),
                CodeEvalFile(
                    "parser.py",
                    "def parse_user(raw):\n    name, email = raw.split(',')\n    return {'full_name': name, 'mail': email}\n",
                ),
                CodeEvalFile(
                    "tests/test_service.py",
                    "import unittest\nfrom service import user_label\n\n\nclass ServiceTest(unittest.TestCase):\n    def test_user_label_uses_parser_contract(self):\n        self.assertEqual(user_label(' Alice , Alice@Example.COM '), 'Alice<Alice@Example.COM>')\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
                ),
            ),
            edits=(
                CodeEvalEdit(
                    "parser.py",
                    "def parse_user(raw):\n    name, email = raw.split(',')\n    return {'full_name': name, 'mail': email}\n",
                    "def parse_user(raw):\n    name, email = raw.split(',', 1)\n    return {'name': name.strip(), 'email': email.strip()}\n",
                ),
            ),
            expected_failure="KeyError",
            tags=("code", "issue-to-patch", "multi-file", "contract", "integration"),
        ),
        _multi_file_fixture(
            "none-default-contract",
            "Configuration helper erases explicit None and zero",
            "Preserve explicit timeout values, including None and 0, while still defaulting missing timeout.",
            files=(
                CodeEvalFile(
                    "config.py",
                    "def resolve_timeout(value, default=30):\n    return value or default\n",
                ),
                CodeEvalFile(
                    "service.py",
                    "from config import resolve_timeout\n\n\ndef build_options(raw):\n    return {'timeout': resolve_timeout(raw.get('timeout'))}\n",
                ),
                CodeEvalFile(
                    "tests/test_service.py",
                    "import unittest\nfrom service import build_options\n\n\nclass ServiceTest(unittest.TestCase):\n    def test_preserves_explicit_timeout_values(self):\n        self.assertEqual(build_options({'timeout': None}), {'timeout': None})\n        self.assertEqual(build_options({'timeout': 0}), {'timeout': 0})\n        self.assertEqual(build_options({}), {'timeout': 30})\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
                ),
            ),
            edits=(
                CodeEvalEdit(
                    "config.py",
                    "def resolve_timeout(value, default=30):\n    return value or default\n",
                    "_MISSING = object()\n\n\ndef resolve_timeout(value=_MISSING, default=30):\n    return default if value is _MISSING else value\n",
                ),
                CodeEvalEdit(
                    "service.py",
                    "from config import resolve_timeout\n\n\ndef build_options(raw):\n    return {'timeout': resolve_timeout(raw.get('timeout'))}\n",
                    "from config import _MISSING, resolve_timeout\n\n\ndef build_options(raw):\n    value = raw['timeout'] if 'timeout' in raw else _MISSING\n    return {'timeout': resolve_timeout(value)}\n",
                ),
            ),
            expected_failure="AssertionError",
            tags=("code", "issue-to-patch", "multi-file", "multi-edit", "config", "contract"),
        ),
        _multi_file_fixture(
            "cli-json-contract",
            "CLI prints Python repr instead of JSON",
            "The CLI should emit valid JSON so downstream tools can parse status output.",
            files=(
                CodeEvalFile(
                    "collector.py",
                    "def collect_status():\n    return {'ok': True, 'count': 2}\n",
                ),
                CodeEvalFile(
                    "cli_app.py",
                    "from collector import collect_status\n\n\ndef main():\n    print(collect_status())\n\n\nif __name__ == '__main__':\n    main()\n",
                ),
                CodeEvalFile(
                    "tests/test_cli_app.py",
                    "import contextlib\nimport io\nimport json\nimport unittest\nfrom cli_app import main\n\n\nclass CliAppTest(unittest.TestCase):\n    def test_main_prints_json(self):\n        stdout = io.StringIO()\n        with contextlib.redirect_stdout(stdout):\n            main()\n        self.assertEqual(json.loads(stdout.getvalue()), {'ok': True, 'count': 2})\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
                ),
            ),
            edits=(
                CodeEvalEdit(
                    "cli_app.py",
                    "from collector import collect_status\n\n\ndef main():\n    print(collect_status())\n\n\nif __name__ == '__main__':\n    main()\n",
                    "import json\nfrom collector import collect_status\n\n\ndef main():\n    print(json.dumps(collect_status(), sort_keys=True))\n\n\nif __name__ == '__main__':\n    main()\n",
                ),
            ),
            expected_failure="JSONDecodeError",
            tags=("code", "issue-to-patch", "multi-file", "cli", "json", "contract"),
        ),
    )


def list_code_eval_fixtures() -> tuple[CodeEvalFixture, ...]:
    return builtin_code_eval_fixtures()


def select_code_eval_fixtures(ids: Sequence[str] = ()) -> tuple[CodeEvalFixture, ...]:
    fixtures = list_code_eval_fixtures()
    if not ids:
        return fixtures
    wanted = set(ids)
    selected = tuple(item for item in fixtures if item.id in wanted)
    missing = sorted(wanted - {item.id for item in selected})
    if missing:
        all_ids = [f.id for f in fixtures]
        available = ', '.join(all_ids[:5])
        hint = f" (available: {available}{'...' if len(all_ids) > 5 else ''}; run list_code_eval_fixtures() for full list)"
        raise KeyError(f"unknown code eval fixture(s): {', '.join(missing)}{hint}")
    return selected


def run_code_eval_pack(
    project: str | Path,
    *,
    fixture_ids: Sequence[str] = (),
    apply_oracle: bool = True,
    keep_workspaces: bool = True,
) -> CodeEvalRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    run_id = "codeeval-" + uuid.uuid4().hex[:12]
    root = code_eval_root(project_path) / "runs" / run_id
    root.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    start = time.monotonic()
    results = tuple(
        run_code_eval_fixture(project_path, fixture, run_root=root, apply_oracle=apply_oracle)
        for fixture in select_code_eval_fixtures(fixture_ids)
    )
    finished = datetime.now().isoformat(timespec="seconds")
    run = CodeEvalRun(
        run_id=run_id,
        project=str(project_path),
        started_at=started,
        finished_at=finished,
        results=results,
        duration_ms=round((time.monotonic() - start) * 1000),
    )
    _write_run_artifacts(project_path, run)
    if not keep_workspaces:
        shutil.rmtree(root, ignore_errors=True)
    return run


def run_code_eval_solve_pack(
    project: str | Path,
    *,
    fixture_ids: Sequence[str] = (),
    model: str = "",
    base_url: str | None = None,
    max_rounds: int = 2,
    client_factory: Any | None = None,
    keep_workspaces: bool = True,
) -> CodeEvalSolvePackRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    selected_model = model or "gpt-5.5"
    if client_factory is None and not ModelClient(base_url=base_url).configured:
        raise ValueError(
            "model API key is not configured; set QUANTAGENT_OPENAI_API_KEY "
            "or OPENAI_API_KEY before running code-eval solve"
        )
    run_id = "codesolve-" + uuid.uuid4().hex[:12]
    root = code_eval_root(project_path) / "runs" / run_id
    root.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    start = time.monotonic()
    results: list[CodeEvalSolveRun] = []
    for fixture in select_code_eval_fixtures(fixture_ids):
        client = client_factory(fixture) if client_factory is not None else None
        results.append(
            run_code_eval_solve_fixture(
                project_path,
                fixture,
                run_root=root,
                model=selected_model,
                base_url=base_url,
                max_rounds=max_rounds,
                client=client,
            )
        )
    finished = datetime.now().isoformat(timespec="seconds")
    run = CodeEvalSolvePackRun(
        run_id=run_id,
        project=str(project_path),
        started_at=started,
        finished_at=finished,
        model=selected_model,
        results=tuple(results),
        duration_ms=round((time.monotonic() - start) * 1000),
    )
    _write_solve_artifacts(project_path, run)
    if not keep_workspaces:
        shutil.rmtree(root, ignore_errors=True)
    return run


def run_code_eval_solve_fixture(
    project: str | Path,
    fixture: CodeEvalFixture,
    *,
    run_root: str | Path | None = None,
    model: str = "",
    base_url: str | None = None,
    max_rounds: int = 2,
    client: Any | None = None,
) -> CodeEvalSolveRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    root = Path(run_root).expanduser().resolve(strict=False) if run_root else code_eval_root(project_path) / "runs" / ("codesolve-" + uuid.uuid4().hex[:12])
    workspace = materialize_code_eval_fixture(fixture, root / fixture.id)
    issue_path = workspace / "ISSUE.md"
    initial = _run_fixture_command(workspace, fixture)
    if initial.status != fixture.expected_initial_status:
        return CodeEvalSolveRun(
            fixture_id=fixture.id,
            title=fixture.title,
            workspace=str(workspace),
            issue_path=str(issue_path),
            initial=initial,
            solver_ok=False,
            message=f"initial test status {initial.status} did not match expected {fixture.expected_initial_status}",
        )
    if fixture.expected_failure and fixture.expected_failure not in (initial.stdout_preview + initial.stderr_preview + initial.message):
        return CodeEvalSolveRun(
            fixture_id=fixture.id,
            title=fixture.title,
            workspace=str(workspace),
            issue_path=str(issue_path),
            initial=initial,
            solver_ok=False,
            message=f"initial failure did not contain {fixture.expected_failure!r}",
        )
    source_paths = tuple(edit.path for edit in fixture.oracle_edits)
    plan = create_patch_plan(
        workspace,
        _solver_task(fixture),
        paths=source_paths,
        test_command=fixture.test_command,
        max_attempts=max(1, max_rounds),
        allow_risky_tests=True,
    )
    failure_output = "\n".join(item for item in (initial.stderr_preview, initial.stdout_preview, initial.message) if item)
    repair = run_isolated_repair_loop(
        workspace,
        plan,
        failure_output,
        max_rounds=max_rounds,
        model=model,
        base_url=base_url,
        client=client,
        timeout=round(fixture.timeout_seconds),
    )
    changed_paths = tuple(repair.review.changed_paths if repair.review else ())
    return CodeEvalSolveRun(
        fixture_id=fixture.id,
        title=fixture.title,
        workspace=str(workspace),
        issue_path=str(issue_path),
        initial=initial,
        solver_ok=repair.ok,
        solver_summary=repair.summary,
        review_id=repair.review.review_id if repair.review else "",
        changed_paths=changed_paths,
        rounds=len(repair.rounds),
        message="solver passed" if repair.ok else repair.summary,
    )


def run_code_eval_fixture(
    project: str | Path,
    fixture: CodeEvalFixture,
    *,
    run_root: str | Path | None = None,
    apply_oracle: bool = True,
) -> CodeEvalFixtureRun:
    project_path = Path(project).expanduser().resolve(strict=False)
    root = Path(run_root).expanduser().resolve(strict=False) if run_root else code_eval_root(project_path) / "runs" / ("codeeval-" + uuid.uuid4().hex[:12])
    workspace = materialize_code_eval_fixture(fixture, root / fixture.id)
    issue_path = workspace / "ISSUE.md"
    initial = _run_fixture_command(workspace, fixture)
    if initial.status != fixture.expected_initial_status:
        return CodeEvalFixtureRun(
            fixture_id=fixture.id,
            title=fixture.title,
            workspace=str(workspace),
            issue_path=str(issue_path),
            initial=initial,
            ok=False,
            message=f"initial test status {initial.status} did not match expected {fixture.expected_initial_status}",
        )
    if fixture.expected_failure and fixture.expected_failure not in (initial.stdout_preview + initial.stderr_preview + initial.message):
        return CodeEvalFixtureRun(
            fixture_id=fixture.id,
            title=fixture.title,
            workspace=str(workspace),
            issue_path=str(issue_path),
            initial=initial,
            ok=False,
            message=f"initial failure did not contain {fixture.expected_failure!r}",
        )
    if not apply_oracle:
        return CodeEvalFixtureRun(
            fixture_id=fixture.id,
            title=fixture.title,
            workspace=str(workspace),
            issue_path=str(issue_path),
            initial=initial,
            ok=True,
            message="initial failure reproduced",
        )
    oracle_error = apply_oracle_edits(workspace, fixture)
    if oracle_error:
        oracle = CodeEvalCommandResult(
            status=ERROR,
            returncode=None,
            command=list(fixture.test_command),
            duration_ms=0,
            message=oracle_error,
        )
    else:
        oracle = _run_fixture_command(workspace, fixture)
    ok = oracle.status == PASS
    return CodeEvalFixtureRun(
        fixture_id=fixture.id,
        title=fixture.title,
        workspace=str(workspace),
        issue_path=str(issue_path),
        initial=initial,
        oracle=oracle,
        ok=ok,
        message="initial failed and oracle passed" if ok else "oracle did not pass",
    )


def materialize_code_eval_fixture(fixture: CodeEvalFixture, workspace: str | Path) -> Path:
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)
    for item in fixture.files:
        target = _safe_child(workspace_path, item.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8")
    (workspace_path / "ISSUE.md").write_text(_render_issue(fixture), encoding="utf-8")
    return workspace_path


def apply_oracle_edits(workspace: str | Path, fixture: CodeEvalFixture) -> str:
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    for edit in fixture.oracle_edits:
        target = _safe_child(workspace_path, edit.path)
        if not target.exists():
            return f"oracle target missing: {edit.path}"
        text = target.read_text(encoding="utf-8")
        count = text.count(edit.old)
        if count != edit.expected_count:
            return f"oracle edit {edit.path} expected {edit.expected_count} match(es), found {count}"
        target.write_text(text.replace(edit.old, edit.new, edit.expected_count), encoding="utf-8")
    return ""


def render_code_eval_json(run: CodeEvalRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def render_code_eval_solve_json(run: CodeEvalSolvePackRun) -> str:
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def render_code_eval_markdown(run: CodeEvalRun) -> str:
    summary = run.summary
    lines = [
        "# Mako Code Eval Fixtures",
        "",
        f"- project: {run.project}",
        f"- run_id: {run.run_id}",
        f"- score: {summary['score']}/{summary['max_score']} ({summary['percent']}/100)",
        f"- engineering_level: {summary['engineering_level']}",
        f"- multi_file_fixtures: {summary['multi_file_fixtures']}",
        f"- multi_edit_fixtures: {summary['multi_edit_fixtures']}",
        f"- fixtures: {summary['total']} total, {summary['passed']} passed, {summary['failed']} failed",
        f"- duration_ms: {run.duration_ms}",
        "",
        "## Results",
        "",
    ]
    for result in run.results:
        status = "pass" if result.ok else "fail"
        oracle = result.oracle.status if result.oracle else "skipped"
        lines.append(f"- [{status}] {result.fixture_id}: initial={result.initial.status}, oracle={oracle}; {result.message}")
        lines.append(f"  workspace: {result.workspace}")
    return "\n".join(lines) + "\n"


def render_code_eval_solve_markdown(run: CodeEvalSolvePackRun) -> str:
    summary = run.summary
    lines = [
        "# Mako Code Eval Solve",
        "",
        f"- project: {run.project}",
        f"- run_id: {run.run_id}",
        f"- model: {run.model}",
        f"- score: {summary['score']}/{summary['max_score']} ({summary['percent']}/100)",
        f"- engineering_level: {summary['engineering_level']}",
        f"- multi_file_fixtures: {summary['multi_file_fixtures']}",
        f"- multi_edit_fixtures: {summary['multi_edit_fixtures']}",
        f"- fixtures: {summary['total']} total, {summary['passed']} passed, {summary['failed']} failed",
        f"- duration_ms: {run.duration_ms}",
        "",
        "## Results",
        "",
    ]
    for result in run.results:
        status = "pass" if result.solver_ok else "fail"
        changed = ",".join(result.changed_paths) if result.changed_paths else "-"
        lines.append(f"- [{status}] {result.fixture_id}: rounds={result.rounds}, changed={changed}; {result.message}")
        lines.append(f"  workspace: {result.workspace}")
    return "\n".join(lines) + "\n"


def render_code_eval_fixture_list(fixtures: Sequence[CodeEvalFixture]) -> str:
    lines = ["# Mako Code Eval Fixture Pack", ""]
    for fixture in fixtures:
        lines.append(f"- {fixture.id}: {fixture.title} tags={','.join(fixture.tags)}")
    return "\n".join(lines) + "\n"


def _fixture(
    fixture_id: str,
    title: str,
    issue: str,
    source_path: str,
    broken_source: str,
    fixed_source: str,
    test_path: str,
    test_source: str,
    *,
    expected_failure: str,
    tags: tuple[str, ...],
) -> CodeEvalFixture:
    return CodeEvalFixture(
        id=fixture_id,
        title=title,
        issue=issue,
        files=(
            CodeEvalFile(source_path, broken_source),
            CodeEvalFile(test_path, test_source),
        ),
        oracle_edits=(CodeEvalEdit(source_path, broken_source, fixed_source),),
        expected_failure=expected_failure,
        tags=tags,
    )


def _multi_file_fixture(
    fixture_id: str,
    title: str,
    issue: str,
    *,
    files: tuple[CodeEvalFile, ...],
    edits: tuple[CodeEvalEdit, ...],
    expected_failure: str,
    tags: tuple[str, ...],
) -> CodeEvalFixture:
    return CodeEvalFixture(
        id=fixture_id,
        title=title,
        issue=issue,
        files=files,
        oracle_edits=edits,
        expected_failure=expected_failure,
        tags=tags,
    )


def _fixture_coverage(fixture_ids: Sequence[str]) -> dict[str, Any]:
    lookup = {fixture.id: fixture for fixture in list_code_eval_fixtures()}
    fixtures = [lookup[item] for item in fixture_ids if item in lookup]
    tags = sorted({tag for fixture in fixtures for tag in fixture.tags})
    return {
        "multi_file_fixtures": sum(1 for fixture in fixtures if len(fixture.files) >= 3 or "multi-file" in fixture.tags),
        "multi_edit_fixtures": sum(1 for fixture in fixtures if len(fixture.oracle_edits) >= 2 or "multi-edit" in fixture.tags),
        "coverage_tags": tags,
    }


def _code_engineering_level(*, total: int, passed: int, coverage: Mapping[str, Any]) -> dict[str, Any]:
    percent = passed / total if total else 0.0
    multi_file = int(coverage.get("multi_file_fixtures", 0) or 0)
    multi_edit = int(coverage.get("multi_edit_fixtures", 0) or 0)
    tags = set(coverage.get("coverage_tags", ()) or ())
    l45_ready = (
        total >= 13
        and passed == total
        and multi_file >= 3
        and multi_edit >= 1
        and {"contract", "cli", "config", "mutation", "control-flow"}.issubset(tags)
    )
    if l45_ready:
        return {"level": "L4.5", "reasons": ["full fixture pack passed", "multi-file contracts covered", "multi-edit repair covered"]}
    if total >= 10 and passed == total:
        return {"level": "L4", "reasons": ["single-pack issue-to-patch fixtures passed", "L4.5 breadth gates not all met"]}
    if percent >= 0.8:
        return {"level": "L3", "reasons": ["most fixtures passed", "not enough for L4"]}
    if total and passed:
        return {"level": "L2", "reasons": ["some fixtures passed"]}
    return {"level": "L1", "reasons": ["no passing code engineering fixture pack"]}


def _run_fixture_command(workspace: Path, fixture: CodeEvalFixture) -> CodeEvalCommandResult:
    start = time.monotonic()
    command = list(fixture.test_command)
    _purge_pycache(workspace)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=fixture.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CodeEvalCommandResult(
            status=ERROR,
            returncode=None,
            command=command,
            duration_ms=round((time.monotonic() - start) * 1000),
            stdout_preview=_preview(exc.stdout),
            stderr_preview=_preview(exc.stderr),
            message=f"timeout after {fixture.timeout_seconds:g}s",
        )
    except OSError as exc:
        return CodeEvalCommandResult(
            status=ERROR,
            returncode=None,
            command=command,
            duration_ms=round((time.monotonic() - start) * 1000),
            message=f"{type(exc).__name__}: {exc}",
        )
    return CodeEvalCommandResult(
        status=PASS if completed.returncode == 0 else FAIL,
        returncode=completed.returncode,
        command=command,
        duration_ms=round((time.monotonic() - start) * 1000),
        stdout_preview=_preview(completed.stdout),
        stderr_preview=_preview(completed.stderr),
        message="ok" if completed.returncode == 0 else f"returncode {completed.returncode}",
    )


def _write_run_artifacts(project: Path, run: CodeEvalRun) -> None:
    root = code_eval_root(project)
    root.mkdir(parents=True, exist_ok=True)
    (root / "latest.json").write_text(render_code_eval_json(run) + "\n", encoding="utf-8")
    (root / f"{run.run_id}.json").write_text(render_code_eval_json(run) + "\n", encoding="utf-8")
    (root / f"{run.run_id}.md").write_text(render_code_eval_markdown(run), encoding="utf-8")


def _write_solve_artifacts(project: Path, run: CodeEvalSolvePackRun) -> None:
    root = code_eval_root(project)
    root.mkdir(parents=True, exist_ok=True)
    (root / "latest_solve.json").write_text(render_code_eval_solve_json(run) + "\n", encoding="utf-8")
    (root / f"{run.run_id}.json").write_text(render_code_eval_solve_json(run) + "\n", encoding="utf-8")
    (root / f"{run.run_id}.md").write_text(render_code_eval_solve_markdown(run), encoding="utf-8")


def _render_issue(fixture: CodeEvalFixture) -> str:
    return "\n".join(
        [
            f"# {fixture.title}",
            "",
            fixture.issue,
            "",
            "## Validation",
            "",
            "Run:",
            "",
            "```bash",
            " ".join(fixture.test_command),
            "```",
            "",
            "The starting workspace is expected to fail this command. A correct patch should make it pass without editing tests.",
            "",
        ]
    )


def _solver_task(fixture: CodeEvalFixture) -> str:
    return "\n".join(
        [
            fixture.title,
            "",
            fixture.issue,
            "",
            "Constraints:",
            "- Fix the source code only.",
            "- Do not edit tests.",
            "- Keep the patch minimal.",
        ]
    )


def _safe_child(root: Path, relative: str) -> Path:
    target = (root / relative).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"path escapes fixture workspace: {relative}")
    return target


def _preview(value: str | bytes | None, limit: int = DEFAULT_PREVIEW_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value if len(value) <= limit else value[:limit] + "\n...<truncated>"


def _purge_pycache(root: Path) -> None:
    for path in root.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
