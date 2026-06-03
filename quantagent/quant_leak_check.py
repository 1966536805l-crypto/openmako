from __future__ import annotations

import ast
import csv
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


ERROR = "error"
WARN = "warn"
INFO = "info"

EXCLUDED_DIRS = {".git", ".quantagent", "__pycache__", ".venv", "venv", "node_modules", "quantagent_runs"}
CSV_SUSPICIOUS_COLUMN_RE = re.compile(
    r"(future|forward|next[_-]?return|tomorrow|lookahead|leak|target|label|y_true|未来|次日|明日|标签)",
    re.IGNORECASE,
)
PY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\.shift\s*\(\s*-\s*\d+"), ERROR, "negative_shift"),
    (re.compile(r"direction\s*=\s*['\"]forward['\"]"), ERROR, "forward_merge_asof"),
    (re.compile(r"rolling\s*\([^)]*center\s*=\s*True"), WARN, "centered_rolling_window"),
    (re.compile(r"(future|forward|lookahead|target|label)[a-z0-9_]*\s*=\s*.*(feature|x_|train)"), WARN, "target_like_feature"),
    (re.compile(r"\.iloc\s*\[[^\]]+\+\s*1[^\]]*\]"), WARN, "forward_iloc_access"),
    (re.compile(r"(current_universe|survived|still_listed|active_stocks|existing_stocks)", re.IGNORECASE), WARN, "survivorship_bias"),
)


@dataclass(frozen=True)
class LeakFinding:
    level: str
    code: str
    message: str
    path: str
    line: int = 0
    column: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantLeakCheckResult:
    target: str
    ok: bool
    checked_files: int
    findings: tuple[LeakFinding, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "ok": self.ok,
            "checked_files": self.checked_files,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def run_quant_leak_check(target: str | Path, *, max_files: int = 500) -> QuantLeakCheckResult:
    path = Path(target).expanduser().resolve(strict=False)
    findings: list[LeakFinding] = []
    checked = 0
    for item in _iter_targets(path, max_files=max_files):
        checked += 1
        if item.suffix.lower() == ".csv":
            findings.extend(_check_csv(item))
        elif item.suffix.lower() == ".py":
            findings.extend(_check_python(item))
    ok = not any(finding.level == ERROR for finding in findings)
    return QuantLeakCheckResult(str(path), ok, checked, tuple(findings))


def render_quant_leak_check(result: QuantLeakCheckResult) -> str:
    lines = [
        "# Quant Leak Check",
        "",
        f"- target: {result.target}",
        f"- ok: {str(result.ok).lower()}",
        f"- checked_files: {result.checked_files}",
        f"- findings: {len(result.findings)}",
        "",
        "## Findings",
        "",
    ]
    if not result.findings:
        lines.append("- none")
    for finding in result.findings:
        loc = f":{finding.line}" if finding.line else ""
        column = f" column={finding.column}" if finding.column else ""
        snippet = f" snippet={finding.snippet}" if finding.snippet else ""
        lines.append(f"- [{finding.level}] {finding.code} {finding.path}{loc}{column}: {finding.message}{snippet}")
    return "\n".join(lines).rstrip() + "\n"


def _iter_targets(path: Path, *, max_files: int) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in {".csv", ".py"}:
            yield path
        return
    if not path.exists():
        return
    count = 0
    for item in path.rglob("*"):
        if count >= max_files:
            break
        if any(part in EXCLUDED_DIRS for part in item.parts):
            continue
        if item.is_file() and item.suffix.lower() in {".csv", ".py"}:
            count += 1
            yield item


def _check_csv(path: Path) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = [name for name in (reader.fieldnames or []) if name]
    except OSError as exc:
        return [LeakFinding(ERROR, "csv_read_failed", str(exc), str(path))]
    for column in fieldnames:
        if CSV_SUSPICIOUS_COLUMN_RE.search(column):
            findings.append(
                LeakFinding(
                    WARN,
                    "suspicious_future_or_target_column",
                    "Column name looks like future/target/label data; ensure it is never used as a feature.",
                    str(path),
                    column=column,
                )
            )
    return findings


def _check_python(path: Path) -> list[LeakFinding]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [LeakFinding(ERROR, "python_read_failed", str(exc), str(path))]
    findings: list[LeakFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern, level, code in PY_PATTERNS:
            if pattern.search(stripped):
                findings.append(
                    LeakFinding(
                        level,
                        code,
                        _message_for_code(code),
                        str(path),
                        line=line_number,
                        snippet=stripped[:180],
                    )
                )
    findings.extend(_check_python_ast(path, text))
    return _dedupe_findings(findings)


def _dedupe_findings(findings: list[LeakFinding]) -> list[LeakFinding]:
    selected: dict[tuple[str, str, int], LeakFinding] = {}
    for finding in findings:
        key = (finding.path, finding.code, finding.line)
        selected.setdefault(key, finding)
    return list(selected.values())


def _check_python_ast(path: Path, text: str) -> list[LeakFinding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    findings: list[LeakFinding] = []
    seen: set[tuple[str, int, str]] = set()
    string_bindings = _literal_string_bindings(tree)

    def add(level: str, code: str, node: ast.AST, snippet: str = "") -> None:
        line = int(getattr(node, "lineno", 0) or 0)
        key = (code, line, snippet)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            LeakFinding(
                level,
                code,
                _message_for_code(code),
                str(path),
                line=line,
                snippet=snippet or _source_segment(text, node),
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name == "shift":
                periods = _call_arg(node, 0, "periods")
                if _is_negative_int(periods):
                    add(ERROR, "negative_shift", node)
            elif call_name == "merge_asof":
                direction = _keyword_value(node, "direction")
                if _string_value(direction, string_bindings) == "forward":
                    add(ERROR, "forward_merge_asof", node)
                elif direction is not None and _string_value(direction, string_bindings) is None:
                    add(ERROR, "dynamic_merge_asof_direction", node)
        if isinstance(node, ast.Subscript) and _target_like_string_expr(node.slice, string_bindings):
            add(ERROR, "target_like_column_reference", node)
        if isinstance(node, ast.Assign) and _assigns_feature_list(node) and _contains_target_like_string(node.value, string_bindings):
            add(ERROR, "target_column_in_feature_list", node)
    return findings


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _call_arg(node: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(node.args) > position:
        return node.args[position]
    return _keyword_value(node, keyword)


def _keyword_value(node: ast.Call, keyword: str) -> ast.AST | None:
    for item in node.keywords:
        if item.arg == keyword:
            return item.value
    return None


def _is_negative_int(node: ast.AST | None) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return isinstance(node.operand.value, int) and node.operand.value > 0
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int) and node.value < 0
    return False


def _literal_string_bindings(tree: ast.AST) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = _string_value(node.value, bindings)
        if value is not None:
            bindings[node.targets[0].id] = value
    return bindings


def _string_value(node: ast.AST | None, bindings: dict[str, str] | None = None) -> str | None:
    bindings = bindings or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.lower()
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_value(node.left, bindings)
        right = _string_value(node.right, bindings)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        static_parts = [part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)]
        return "".join(static_parts).lower() if static_parts else None
    return None


def _target_like_string_expr(node: ast.AST, bindings: dict[str, str] | None = None) -> bool:
    value = _string_value(node, bindings)
    if value is None or len(value) > 80:
        return False
    return bool(CSV_SUSPICIOUS_COLUMN_RE.search(value))


def _assigns_feature_list(node: ast.Assign) -> bool:
    return any(isinstance(target, ast.Name) and re.search(r"(^|_)(features?|feature_cols|x_cols|x|train_cols)(_|$)", target.id, re.IGNORECASE) for target in node.targets)


def _contains_target_like_string(node: ast.AST, bindings: dict[str, str]) -> bool:
    if _target_like_string_expr(node, bindings):
        return True
    return any(_target_like_string_expr(child, bindings) for child in ast.walk(node))


def _source_segment(text: str, node: ast.AST) -> str:
    return (ast.get_source_segment(text, node) or "").strip()[:180]


def check_survivorship_bias_data(csv_path: str | Path, universe_path: str | Path | None = None) -> LeakFinding | None:
    """
    Check for survivorship bias in strategy data by analyzing stock coverage.

    Args:
        csv_path: Path to strategy CSV with 'code' column containing stock symbols
        universe_path: Optional path to historical universe CSV with 'code' and 'delisted' columns

    Returns:
        LeakFinding if survivorship bias detected, None otherwise
    """
    csv_path = Path(csv_path)

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = [name for name in (reader.fieldnames or []) if name]

            if "code" not in fieldnames:
                return None

            # Read all stock codes from strategy data
            handle.seek(0)
            reader = csv.DictReader(handle)
            strategy_codes = {row.get("code", "").strip() for row in reader if row.get("code", "").strip()}

    except (OSError, csv.Error):
        return None

    if not strategy_codes or len(strategy_codes) < 10:
        # Too few stocks to make meaningful assessment
        return None

    # If universe_path provided, check against historical delisted stocks
    if universe_path:
        universe_path = Path(universe_path)
        if not universe_path.exists():
            return None

        try:
            with universe_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = [name for name in (reader.fieldnames or []) if name]

                if "code" not in fieldnames:
                    return None

                # Identify delisted stocks
                delisted_codes = set()
                all_universe_codes = set()

                for row in reader:
                    code = row.get("code", "").strip()
                    if not code:
                        continue
                    all_universe_codes.add(code)

                    # Check if marked as delisted (various possible column names)
                    is_delisted = (
                        row.get("delisted", "").lower() in ("true", "1", "yes") or
                        row.get("is_delisted", "").lower() in ("true", "1", "yes") or
                        row.get("status", "").lower() in ("delisted", "退市")
                    )
                    if is_delisted:
                        delisted_codes.add(code)

        except (OSError, csv.Error):
            return None

        if not all_universe_codes:
            return None

        # Calculate coverage
        strategy_delisted = strategy_codes & delisted_codes
        total_strategy_stocks = len(strategy_codes)
        delisted_count = len(strategy_delisted)
        coverage_pct = (delisted_count / total_strategy_stocks * 100) if total_strategy_stocks > 0 else 0

        # Check for survivorship bias
        if total_strategy_stocks > 100 and delisted_count == 0:
            return LeakFinding(
                ERROR,
                "survivorship_bias_no_delisted",
                f"Strategy has {total_strategy_stocks} stocks but zero delisted stocks; likely survivorship bias.",
                str(csv_path),
            )
        elif coverage_pct < 5.0 and total_strategy_stocks > 50:
            return LeakFinding(
                WARN,
                "survivorship_bias_low_coverage",
                f"Strategy may have survivorship bias: only {coverage_pct:.1f}% delisted stocks ({delisted_count}/{total_strategy_stocks}).",
                str(csv_path),
            )

    return None


def _message_for_code(code: str) -> str:
    return {
        "negative_shift": "Negative shift can pull future values into current-row features.",
        "forward_merge_asof": "Forward asof merge can join future data into past rows.",
        "dynamic_merge_asof_direction": "Dynamic asof merge direction is not auditable; use a literal non-forward direction before live gating.",
        "centered_rolling_window": "Centered rolling windows can include future observations.",
        "target_like_feature": "Target/label-like variable appears near feature/train construction.",
        "target_like_column_reference": "Target/label-like column reference appears in Python code; ensure it is never used as a feature.",
        "target_column_in_feature_list": "Target/label-like column is listed as a feature input.",
        "forward_iloc_access": "Forward positional access can leak next-row data.",
        "survivorship_bias": "Survivorship bias detected: filtering by current/surviving stocks excludes delisted stocks and inflates backtest results.",
        "survivorship_bias_no_delisted": "Strategy has no delisted stocks; likely survivorship bias.",
        "survivorship_bias_low_coverage": "Strategy may have survivorship bias due to low delisted stock coverage.",
    }.get(code, "Potential leakage pattern")
