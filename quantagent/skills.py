from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    source: str = "builtin"
    path: str = ""
    license: str = ""


@dataclass(frozen=True)
class SkillManifest:
    name: str
    source: str
    body_hash: str
    approved: bool
    path: str = ""
    source_path: str = ""
    license: str = ""
    proposal_id: str = ""
    proposal_body_hash: str = ""
    eval_evidence_hash: str = ""
    eval_command_hash: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "body_hash": self.body_hash,
            "approved": self.approved,
            "path": self.path,
            "source_path": self.source_path,
            "license": self.license,
            "proposal_id": self.proposal_id,
            "proposal_body_hash": self.proposal_body_hash,
            "eval_evidence_hash": self.eval_evidence_hash,
            "eval_command_hash": self.eval_command_hash,
            "version": self.version,
        }


@dataclass(frozen=True)
class SkillSnapshot:
    snapshot_id: str
    prompt: str
    skills: tuple[dict[str, Any], ...]
    skill_filter: tuple[str, ...] = ()
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "prompt": self.prompt,
            "skills": list(self.skills),
            "skill_filter": list(self.skill_filter),
            "version": self.version,
        }


@dataclass(frozen=True)
class SkillRegistryRecord:
    name: str
    description: str
    source: str
    approved: bool
    body_hash: str
    triggers: tuple[str, ...]
    path: str = ""
    license: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "approved": self.approved,
            "body_hash": self.body_hash,
            "triggers": list(self.triggers),
            "path": self.path,
            "license": self.license,
        }


BUILTIN_SKILLS: tuple[Skill, ...] = (
    Skill(
        name="p4-tick-validation",
        description="逐笔 / tick 到货后的 P4 真实成交验证流程。",
        triggers=("p4", "逐笔", "tick", "真实成交", "09:30", "成交", "滑点", "容量"),
        body=(
            "Use this when the task touches tick data or real execution. First inspect schema, row counts, date "
            "range, symbol format, price/volume units, and file hashes. Keep 09:25 signal formation separated "
            "from 09:30 entry. Do not upgrade any backtest result into an execution conclusion before P4 evidence "
            "exists. Prefer scenario A and D deduplicated baselines as comparison anchors."
        ),
    ),
    Skill(
        name="evidence-lock",
        description="所有量化结论必须绑定证据、hash、命令和样本口径。",
        triggers=("证据", "hash", "复现", "结论", "pf", "报告", "验证", "结果"),
        body=(
            "For every quantitative claim, include dataset path, row count, dedup status, command or script, key "
            "parameters, output path, and hashes when available. Treat PF jumps as suspicious until duplicate "
            "pollution, leakage, fill assumptions, and unit errors are ruled out."
        ),
    ),
    Skill(
        name="quant-audit",
        description="量化专用审计：未来函数、重复样本、理想成交、单位错误。",
        triggers=("审计", "漏洞", "错误", "未来函数", "重复", "污染", "单位", "过滤", "风控"),
        body=(
            "Audit for lookahead, duplicate trades, reused exit prices, wrong volume/amount units, exact fills, "
            "overfit thresholds, and filters already proven harmful. Never use the old 1253-trade polluted sample "
            "as clean evidence. Time hard limits, cooldowns, volume, big-order, and sector filters are discarded "
            "unless new evidence explicitly overturns them."
        ),
    ),
    Skill(
        name="report-writer",
        description="把输出写成短、稳、能交接的研究记录。",
        triggers=("写文件", "交接", "总结", "复盘", "报告", "记录", "同步", "留言"),
        body=(
            "Write conclusion first, then evidence, limits, and next action. Separate model judgment from verified "
            "facts. Keep reports concise enough for the next AI to resume without rereading everything. Use "
            "NEEDS_WORK for unknowns instead of inventing numbers."
        ),
    ),
    Skill(
        name="context-router",
        description="控制 token 成本：短问轻上下文，复盘才深上下文。",
        triggers=("token", "上下文", "烧", "成本", "卡", "慢", "长一点", "276"),
        body=(
            "Use light context for short operational questions, standard context for analysis/code/quant tasks, "
            "and deep context only for full reconstruction or final reports. Prefer writing durable reports to "
            "files instead of repeatedly sending huge context."
        ),
    ),
    Skill(
        name="handoff-brief",
        description="给另一个 AI / 新会话的启动检查清单。",
        triggers=("claude", "另一个ai", "新ai", "交接", "通信", "回复", "协作"),
        body=(
            "When coordinating another AI, state the current phase, clean baselines, forbidden polluted sample, "
            "latest files to read, open questions, and what requires user approval. If communication files change, "
            "read them before continuing and do not treat pending diagnosis as final strategy."
        ),
    ),
    Skill(
        name="systematic-debugging",
        description="测试失败和运行异常的系统化调试流程。",
        triggers=("失败", "报错", "debug", "debugging", "测试失败", "traceback", "修复", "回归"),
        body=(
            "Use this when tests, commands, or agent steps fail. Reproduce the failure first, capture the exact "
            "command and output, classify it as syntax/import/assertion/path/env/policy/timeout/unknown, compare "
            "with recent similar failures or trajectory entries, state one root-cause hypothesis, make the smallest "
            "patch that can test the hypothesis, then rerun the narrow test before the full suite. Do not randomly "
            "edit unrelated files after seeing a failure."
        ),
    ),
    Skill(
        name="tdd-code-change",
        description="代码任务的 TDD 约束：先测试，再实现，再回归。",
        triggers=("代码", "实现", "改代码", "修bug", "patch", "diff", "测试", "tdd"),
        body=(
            "For code changes, inspect the existing failing behavior or add a focused failing test before editing "
            "production code. Apply the smallest diff that should make the test pass, rerun the narrow test, then "
            "run the full configured suite. If tests fail, switch to systematic-debugging and classify the failure "
            "before making another patch."
        ),
    ),
)


PACKAGED_HERMES_SKILLS_ROOT = Path(__file__).resolve().parent / "vendor" / "hermes" / "skills"
REPO_HERMES_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "third_party" / "hermes" / "skills"

HERMES_TRIGGER_ALIASES: dict[str, tuple[str, ...]] = {
    "a-stock-market-analysis": ("a股", "A股", "股票", "个股", "行情", "大盘", "市场分析", "market"),
    "news-sentiment-analysis": ("新闻", "公告", "情绪", "舆情", "催化", "sentiment", "catalyst"),
    "quant-backtesting": ("策略", "回测", "backtest", "backtesting", "strategy", "收益", "夏普", "回撤", "未来函数", "过拟合"),
    "risk-position-sizing": ("仓位", "风控", "风险", "止损", "头寸", "position", "sizing", "risk"),
    "stock-screening-sector-rotation": ("选股", "筛选", "板块", "轮动", "sector", "screening", "watchlist"),
    "technical-trading-analysis": ("技术分析", "k线", "K线", "均线", "突破", "macd", "rsi", "trend"),
    "trade-plan-review": ("交易计划", "买入", "卖出", "止盈", "止损", "trade plan", "entry", "exit"),
    "jupyter-live-kernel": ("jupyter", "notebook", "kernel", "数据科学", "可视化"),
    "codebase-inspection": ("读代码", "看源码", "源码", "codebase", "inspect", "inspection"),
    "native-mcp": ("mcp", "工具", "tool", "server", "stdio"),
    "requesting-code-review": ("代码审查", "review", "pr", "pull request", "diff"),
    "spike": ("spike", "原型", "探索", "调研", "prototype"),
    "subagent-driven-development": ("子agent", "subagent", "delegate", "并行", "两阶段", "代理", "review"),
    "systematic-debugging": ("debug", "debugging", "调试", "报错", "失败", "traceback", "复现"),
    "test-driven-development": ("tdd", "测试先行", "先写测试", "red", "green", "refactor"),
    "writing-plans": ("计划", "方案", "拆解", "planning", "plan"),
}


def skill_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "skills"


def skill_manifest_path(project: str | Path, skill_name: str) -> Path:
    return skill_root(project) / _clean_name(skill_name) / "skill.json"


def list_skills(project: str | Path | None = None) -> list[Skill]:
    skills = list(BUILTIN_SKILLS)
    if project is not None:
        skills.extend(load_project_skills(project))
    skills.extend(load_vendored_hermes_skills())
    return skills


def list_skill_registry(project: str | Path | None = None) -> list[SkillRegistryRecord]:
    return [_skill_registry_record(skill, project=project) for skill in list_skills(project)]


def load_vendored_hermes_skills(root: str | Path | None = None) -> list[Skill]:
    skill_root_path = Path(root).expanduser().resolve(strict=False) if root else _vendored_hermes_skills_root()
    if not skill_root_path.exists():
        return []
    skills: list[Skill] = []
    for path in sorted(skill_root_path.glob("**/SKILL.md")):
        try:
            skills.append(load_skill_file(path, source="hermes"))
        except ValueError:
            continue
    return skills


def _vendored_hermes_skills_root() -> Path:
    if PACKAGED_HERMES_SKILLS_ROOT.exists():
        return PACKAGED_HERMES_SKILLS_ROOT
    return REPO_HERMES_SKILLS_ROOT


def load_project_skills(project: str | Path) -> list[Skill]:
    root = skill_root(project)
    if not root.exists():
        return []
    skills: list[Skill] = []
    for path in sorted(root.glob("*/SKILL.md")):
        try:
            skills.append(load_skill_file(path, source="project"))
        except ValueError:
            continue
    return skills


def load_skill_file(path: str | Path, *, source: str = "file") -> Skill:
    skill_path = Path(path).expanduser().resolve(strict=False)
    if skill_path.name != "SKILL.md":
        raise ValueError("skill file must be named SKILL.md")
    text = skill_path.read_text(encoding="utf-8", errors="replace")[:12000]
    meta, body = _parse_frontmatter(text)
    name = meta.get("name") or _first_heading(body) or skill_path.parent.name
    description = meta.get("description") or _first_paragraph(body) or "Local Mako skill."
    triggers = _skill_triggers(name, description, body, meta)
    return Skill(
        name=_clean_name(name),
        description=description.strip(),
        triggers=triggers,
        body=body.strip() or text.strip(),
        source=source,
        path=str(skill_path),
        license=meta.get("license", "").strip(),
    )


def install_skill(project: str | Path, source: str | Path, *, name: str | None = None, force: bool = False) -> Skill:
    project_path = Path(project).expanduser().resolve(strict=False)
    source_path = Path(source).expanduser().resolve(strict=False)
    skill_file = source_path / "SKILL.md" if source_path.is_dir() else source_path
    skill = load_skill_file(skill_file, source="project")
    install_name = _clean_name(name or skill.name)
    destination_dir = skill_root(project_path) / install_name
    destination = destination_dir / "SKILL.md"
    if destination.exists() and not force:
        raise FileExistsError(f"skill already installed: {install_name}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(skill_file, destination)
    installed = load_skill_file(destination, source="project")
    write_skill_manifest(
        project_path,
        installed,
        approved=True,
        source_path=str(skill_file),
    )
    return installed


def load_skill_manifest(path: str | Path) -> SkillManifest:
    manifest_path = Path(path).expanduser().resolve(strict=False)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid skill manifest: {manifest_path}")
    return SkillManifest(
        name=str(payload.get("name") or ""),
        source=str(payload.get("source") or ""),
        body_hash=str(payload.get("body_hash") or ""),
        approved=bool(payload.get("approved", False)),
        path=str(payload.get("path") or ""),
        source_path=str(payload.get("source_path") or ""),
        license=str(payload.get("license") or ""),
        proposal_id=str(payload.get("proposal_id") or ""),
        proposal_body_hash=str(payload.get("proposal_body_hash") or ""),
        eval_evidence_hash=str(payload.get("eval_evidence_hash") or ""),
        eval_command_hash=str(payload.get("eval_command_hash") or ""),
        version=int(payload.get("version") or 1),
    )


def write_skill_manifest(
    project: str | Path,
    skill: Skill,
    *,
    approved: bool,
    source_path: str = "",
    proposal_id: str = "",
    proposal_body_hash: str = "",
    eval_evidence_hash: str = "",
    eval_command_hash: str = "",
) -> Path:
    path = skill_manifest_path(project, skill.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = SkillManifest(
        name=skill.name,
        source=skill.source,
        body_hash=_skill_body_hash(skill),
        approved=bool(approved),
        path=skill.path,
        source_path=source_path,
        license=skill.license,
        proposal_id=proposal_id,
        proposal_body_hash=proposal_body_hash,
        eval_evidence_hash=eval_evidence_hash,
        eval_command_hash=eval_command_hash,
    )
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def select_skills(task: str | None, limit: int = 3, project: str | Path | None = None) -> list[Skill]:
    if not task:
        return []
    lowered = task.lower()
    scored: list[tuple[int, int, Skill]] = []
    for index, skill in enumerate(list_skills(project)):
        score = 0
        for trigger in skill.triggers:
            if trigger.lower() in lowered:
                score += 1
        if score:
            scored.append((score, -index, skill))
    scored.sort(reverse=True)
    return [skill for _, _, skill in scored[:limit]]


def select_approved_project_skills(task: str | None, *, project: str | Path, limit: int = 3) -> list[Skill]:
    if not task:
        return []
    lowered = task.lower()
    scored: list[tuple[int, int, Skill]] = []
    for index, skill in enumerate(load_project_skills(project)):
        manifest_path = skill_manifest_path(project, skill.name)
        if not manifest_path.exists():
            continue
        try:
            manifest = load_skill_manifest(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not manifest.approved or manifest.body_hash != _skill_body_hash(skill):
            continue
        if not _approved_manifest_provenance_ok(project, manifest):
            continue
        score = 0
        for trigger in skill.triggers:
            if trigger.lower() in lowered:
                score += 1
        if score:
            scored.append((score, -index, skill))
    scored.sort(reverse=True)
    return [skill for _, _, skill in scored[:limit]]


def _approved_manifest_provenance_ok(project: str | Path, manifest: SkillManifest) -> bool:
    if not manifest.source_path.startswith("skill_proposal:"):
        return True
    proposal_id = manifest.source_path.split(":", 1)[1].strip()
    if not proposal_id or manifest.proposal_id != proposal_id:
        return False
    if len(manifest.proposal_body_hash) != 64 or len(manifest.eval_evidence_hash) != 64 or len(manifest.eval_command_hash) != 64:
        return False
    proposal_path = Path(project).expanduser().resolve(strict=False) / ".quantagent" / "skill_proposals" / f"{proposal_id}.json"
    try:
        payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("status") or "") != "approved":
        return False
    if str(payload.get("name") or "") != manifest.name:
        return False
    body = str(payload.get("body") or "")
    eval_evidence = str(payload.get("eval_evidence") or "")
    if _sha256_text(body) != manifest.proposal_body_hash:
        return False
    if _sha256_text(eval_evidence) != manifest.eval_evidence_hash:
        return False
    try:
        eval_payload = json.loads(eval_evidence)
    except json.JSONDecodeError:
        return False
    if not isinstance(eval_payload, dict):
        return False
    return _sha256_text(str(eval_payload.get("command") or "")) == manifest.eval_command_hash


def render_skill_context(skills: list[Skill]) -> str:
    if not skills:
        return "(none)"
    blocks = []
    for skill in skills:
        source = f" source={skill.source}" if skill.source != "builtin" else ""
        blocks.append(f"[{skill.name}{source}] {skill.description}\n{skill.body}")
    return "\n\n".join(blocks)


def build_skill_snapshot(task: str | None, *, project: str | Path | None = None, limit: int = 3) -> SkillSnapshot:
    selected = select_skills(task, limit=limit, project=project)
    prompt = render_skill_context(selected)
    records = tuple(_skill_record(skill) for skill in selected)
    version = max((int(record.get("mtime_ns") or 1) for record in records), default=1)
    payload = {
        "prompt": prompt,
        "skills": records,
        "skill_filter": [skill.name for skill in selected],
        "version": version,
    }
    snapshot_id = "skills-" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return SkillSnapshot(
        snapshot_id=snapshot_id,
        prompt=prompt,
        skills=records,
        skill_filter=tuple(skill.name for skill in selected),
        version=version,
    )


def persist_skill_snapshot(
    project: str | Path,
    snapshot: SkillSnapshot,
    *,
    session_id: str | None = None,
    run_id: str | None = None,
) -> str:
    from .runtime_store import save_skill_snapshot

    return save_skill_snapshot(
        project,
        snapshot_id=snapshot.snapshot_id,
        prompt=snapshot.prompt,
        skills=snapshot.skills,
        session_id=session_id,
        run_id=run_id,
        skill_filter=snapshot.skill_filter,
        version=snapshot.version,
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + 4 :].lstrip()
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, body


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _first_paragraph(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.lower().startswith("triggers:"):
            if lines:
                break
            continue
        lines.append(stripped)
    return " ".join(lines)


def _inline_triggers(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("triggers:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_triggers(value: str) -> tuple[str, ...]:
    cleaned = value.strip().strip("[]")
    items = [item.strip().strip("'\"") for item in re.split(r"[,，]", cleaned)]
    return tuple(item for item in items if item)


def _skill_triggers(name: str, description: str, body: str, meta: dict[str, str]) -> tuple[str, ...]:
    explicit = meta.get("triggers") or _inline_triggers(body)
    if explicit:
        return _parse_triggers(explicit)
    cleaned_name = _clean_name(name)
    triggers: list[str] = [cleaned_name]
    triggers.extend(part for part in re.split(r"[-_.\s]+", cleaned_name) if len(part) >= 2)
    for key in ("tags", "related_skills"):
        value = meta.get(key)
        if value:
            triggers.extend(_parse_triggers(value))
    triggers.extend(HERMES_TRIGGER_ALIASES.get(cleaned_name, ()))
    if not triggers:
        triggers.append(description)
    return _ordered_unique_triggers(triggers)


def _ordered_unique_triggers(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value).strip().strip("'\"")
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _clean_name(value: str) -> str:
    lowered = value.strip().lower().replace("_", "-")
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff.-]+", "-", lowered).strip(".-")
    if not cleaned:
        raise ValueError("skill name is empty")
    return cleaned[:80]


def _skill_record(skill: Skill) -> dict[str, Any]:
    path = Path(skill.path) if skill.path else None
    mtime_ns = path.stat().st_mtime_ns if path and path.exists() else 1
    body_hash = _skill_body_hash(skill)
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "path": skill.path,
        "license": skill.license,
        "triggers": list(skill.triggers),
        "body_hash": body_hash,
        "mtime_ns": mtime_ns,
        "requiredEnv": [],
    }


def _skill_body_hash(skill: Skill) -> str:
    return hashlib.sha256(skill.body.encode("utf-8")).hexdigest()[:16]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _skill_registry_record(skill: Skill, *, project: str | Path | None) -> SkillRegistryRecord:
    approved = skill.source in {"builtin", "hermes"}
    if project is not None and skill.source == "project":
        manifest_path = skill_manifest_path(project, skill.name)
        if manifest_path.exists():
            try:
                approved = load_skill_manifest(manifest_path).approved
            except (OSError, ValueError, json.JSONDecodeError):
                approved = False
    return SkillRegistryRecord(
        name=skill.name,
        description=skill.description,
        source=skill.source,
        approved=approved,
        body_hash=_skill_body_hash(skill),
        triggers=skill.triggers,
        path=skill.path,
        license=skill.license,
    )
