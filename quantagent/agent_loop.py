from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent_loop_core import (
    AgentLoopObservation,
    AgentLoopResult,
    AgentLoopStep,
    build_agent_plan,
    classify_agent_failure,
    render_agent_result,
    render_agent_summary,
    run_agent_loop,
)
from .guards import quant_text_risk
from .model_client import ModelClient, ModelRequest, ModelResponse
from .context_pack import build_context_pack
from .result_schema import AgentRunResult


AgentV3Step = AgentLoopStep
AgentV3Observation = AgentLoopObservation
AgentV3Result = AgentLoopResult
build_agent_v3_plan = build_agent_plan
run_agent_loop_v3 = run_agent_loop
classify_agent_v3_failure = classify_agent_failure
render_agent_v3_summary = render_agent_summary
render_agent_v3_result = render_agent_result


@dataclass
class AgentStep:
    kind: str
    content: str


class QuantAgent:
    def __init__(self, project: Path, model: str = "gpt-5.5", base_url: str | None = None) -> None:
        self.project = project
        self.model = model
        self.client = ModelClient(base_url=base_url)

    def build_context(self, *, token_budget: int | None = None) -> str:
        return build_context_pack(self.project, token_budget=token_budget).text

    def plan(self, task: str) -> list[AgentStep]:
        issues = quant_text_risk(task)
        steps = [AgentStep("context", self.build_context())]
        if issues:
            steps.append(AgentStep("risk", "\n".join(issues)))
        steps.append(AgentStep("task", task))
        return steps

    def ask_model(self, task: str, *, token_budget: int | None = None) -> ModelResponse:
        context = build_context_pack(self.project, task=task, token_budget=token_budget).text
        return self.client.complete(
            ModelRequest(
                model=self.model,
                system="You are a quant research agent. Prefer reproducible tests.",
                prompt=f"{context}\n\nTask:\n{task}",
                project=str(self.project),
            )
        )

    def run_once(self, task: str) -> AgentRunResult:
        """Compatibility entrypoint for the canonical mode-aware agent loop."""
        return run_agent_loop(
            self.project,
            task,
            explicit_mode="build",
            input_provenance="quantagent.run_once",
        ).to_agent_result()


__all__ = [
    "AgentLoopObservation",
    "AgentLoopResult",
    "AgentLoopStep",
    "AgentStep",
    "AgentV3Observation",
    "AgentV3Result",
    "AgentV3Step",
    "QuantAgent",
    "build_agent_plan",
    "build_agent_v3_plan",
    "classify_agent_failure",
    "classify_agent_v3_failure",
    "render_agent_result",
    "render_agent_summary",
    "render_agent_v3_result",
    "render_agent_v3_summary",
    "run_agent_loop",
    "run_agent_loop_v3",
]
