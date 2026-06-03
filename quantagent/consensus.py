from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .context_pack import build_context_pack
from .model_client import ModelClient, ModelRequest


APPROVE = "APPROVE"
REJECT = "REJECT"
NEEDS_WORK = "NEEDS_WORK"
REQUIRED_APPROVERS = ("chatgpt_1", "chatgpt_2", "chatgpt_3")


@dataclass(frozen=True)
class Vote:
    agent: str
    decision: str
    source: Path | str
    reason: str = ""


@dataclass(frozen=True)
class ConsensusStatus:
    request_id: str
    task: str
    request_path: Path
    votes: tuple[Vote, ...]

    @property
    def approved_agents(self) -> set[str]:
        return {vote.agent for vote in self.votes if vote.decision == APPROVE}

    @property
    def rejected_votes(self) -> tuple[Vote, ...]:
        return tuple(vote for vote in self.votes if vote.decision == REJECT)

    @property
    def all_approved(self) -> bool:
        return set(REQUIRED_APPROVERS).issubset(self.approved_agents) and not self.rejected_votes


REQUEST_TEMPLATE = """# THREE_CHATGPT_CONSENSUS_REQUEST

- request_id: {request_id}
- created_at: {created_at}
- required_votes: chatgpt_1, chatgpt_2, chatgpt_3
- rule: material strategy/data/result actions require three ChatGPT consistency approvals before execution
- task: {task}

## Gate Rule

Claude is not part of the execution gate.
This is a consistency gate, not a security sandbox: by default all three reviewers use the configured ChatGPT-compatible provider and may share infrastructure/model behavior.

```text
The action can execute only when all three files exist and all say APPROVE:
```

```text
CONSENSUS_REPLY_{request_id}_CHATGPT_1.md
CONSENSUS_REPLY_{request_id}_CHATGPT_2.md
CONSENSUS_REPLY_{request_id}_CHATGPT_3.md
```

Each file must contain one of:

```text
CHATGPT_1_VOTE: APPROVE|REJECT|NEEDS_WORK
CHATGPT_2_VOTE: APPROVE|REJECT|NEEDS_WORK
CHATGPT_3_VOTE: APPROVE|REJECT|NEEDS_WORK
```

## Codex Initial Vote

CODEX_VOTE: APPROVE

Reason: Codex created the request and is routing it through the three-pass ChatGPT consistency gate before any material action.

## Context

{context}
"""


CHATGPT_PROMPT = """You are ChatGPT reviewer #{reviewer_index} in a three-pass ChatGPT quant research gate.

You must decide whether the proposed action is safe to execute now.
Review the evidence from scratch. Do not assume the other two reviewer passes will approve.

Return exactly this structure:

CHATGPT_{reviewer_index}_VOTE: APPROVE|REJECT|NEEDS_WORK

Findings:
- ...

Required verification:
- ...

Blockers:
- ...

Be strict about:
- dedup baseline only
- no 1253 polluted sample conclusions
- no future leakage
- realistic 09:30 execution and slippage/capacity assumptions
- no repeated discarded hard-risk ideas
- no final real-money language before tick validation

Task:
{task}

Context:
{context}
"""


def communication_dir(project: Path) -> Path:
    out_dir = project / "AI_协作交接"
    return out_dir if out_dir.exists() else project


def create_consensus_request(project: Path, task: str, ask_chatgpt: bool = True) -> ConsensusStatus:
    out_dir = communication_dir(project)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    request_id = stamp
    context = build_context_pack(project).text
    request_path = out_dir / f"CONSENSUS_REQUEST_{request_id}.md"
    request_path.write_text(
        REQUEST_TEMPLATE.format(
            request_id=request_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            task=task,
            context=context,
        ),
        encoding="utf-8",
    )
    votes = [Vote("codex", APPROVE, request_path, "routed through three-pass ChatGPT consistency gate")]
    if ask_chatgpt:
        for index in range(1, 4):
            votes.append(ask_chatgpt_for_vote(project, request_id, task, context, index=index))
    return ConsensusStatus(request_id=request_id, task=task, request_path=request_path, votes=tuple(votes))


def ask_chatgpt_for_vote(project: Path, request_id: str, task: str, context: str, index: int) -> Vote:
    out_dir = communication_dir(project)
    agent = f"chatgpt_{index}"
    path = out_dir / f"CONSENSUS_REPLY_{request_id}_CHATGPT_{index}.md"
    client = ModelClient()
    response = client.complete(
        ModelRequest(
            model="gpt-5.5",
            system="You are a strict quant research reviewer. Use high scrutiny.",
            prompt=CHATGPT_PROMPT.format(reviewer_index=index, task=task, context=context),
            project=str(project),
            query_id=f"consensus-{request_id}-{index}",
        )
    )
    if response.ok:
        path.write_text(response.text.strip() + "\n", encoding="utf-8")
        return parse_vote_file(path, agent)
    path.write_text(
        f"CHATGPT_{index}_VOTE: NEEDS_WORK\n\nModel call failed:\n{response.error}\n",
        encoding="utf-8",
    )
    return Vote(agent, NEEDS_WORK, path, response.error)


def latest_request(project: Path) -> Path | None:
    out_dir = communication_dir(project)
    files = sorted(out_dir.glob("CONSENSUS_REQUEST_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def request_id_from_path(path: Path) -> str:
    name = path.stem
    return name.replace("CONSENSUS_REQUEST_", "", 1)


def parse_task(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^- task:\s*(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_vote_file(path: Path, agent: str) -> Vote:
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = rf"{agent.upper()}_VOTE:\s*(APPROVE|REJECT|NEEDS_WORK)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match and agent.startswith("chatgpt_"):
        match = re.search(r"CHATGPT_VOTE:\s*(APPROVE|REJECT|NEEDS_WORK)", text, flags=re.IGNORECASE)
    decision = match.group(1).upper() if match else NEEDS_WORK
    reason = text[:1000]
    return Vote(agent.lower(), decision, path, reason)


def load_consensus_status(project: Path, request_id: str | None = None) -> ConsensusStatus | None:
    out_dir = communication_dir(project)
    if request_id:
        request_path = out_dir / f"CONSENSUS_REQUEST_{request_id}.md"
    else:
        request_path = latest_request(project)
    if not request_path or not request_path.exists():
        return None
    request_id = request_id_from_path(request_path)
    votes: list[Vote] = [Vote("codex", APPROVE, request_path, "request contains CODEX_VOTE: APPROVE")]
    for agent in REQUIRED_APPROVERS:
        suffix = agent.upper()
        files = sorted(
            out_dir.glob(f"CONSENSUS_REPLY_{request_id}_{suffix}.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if files:
            votes.append(parse_vote_file(files[0], agent))
    return ConsensusStatus(
        request_id=request_id,
        task=parse_task(request_path),
        request_path=request_path,
        votes=tuple(votes),
    )


def require_consensus(project: Path, request_id: str | None = None) -> ConsensusStatus:
    status = load_consensus_status(project, request_id=request_id)
    if not status:
        status = create_consensus_request(project, "material action requested without existing consensus")
    return status


def render_status(status: ConsensusStatus | None) -> str:
    if not status:
        return "No consensus request found.\n"
    lines = [
        f"request_id: {status.request_id}",
        f"task: {status.task}",
        f"request: {status.request_path}",
        "votes:",
    ]
    for vote in status.votes:
        lines.append(f"- {vote.agent}: {vote.decision} ({vote.source})")
    missing = set(REQUIRED_APPROVERS) - {vote.agent for vote in status.votes}
    if missing:
        lines.append("missing: " + ", ".join(sorted(missing)))
    lines.append("approved: " + ("true" if status.all_approved else "false"))
    return "\n".join(lines) + "\n"
