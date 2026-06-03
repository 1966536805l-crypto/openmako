from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.agent_v2 import AgentStep, run_agent_v2
from quantagent.hermes_learning import learn_from_query_events, render_hermes_learning_report
from quantagent.memory_sidecar import load_memory_proposals
from quantagent.query_runtime import QueryRuntime


class HermesLearningTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent hermes learning ")

    def test_learn_from_query_events_queues_memory_proposals(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            runtime = QueryRuntime(project, query_id="qa-hermes")
            runtime.start("P4 strategy evidence must include broker hash", mode="agent_v3")
            runtime.post_tool(
                "execution_gate",
                step=1,
                ok=True,
                summary="Evidence requirement: P4 evidence must include script hash and broker execution provenance.",
            )
            runtime.stop("P4 evidence gate passed", ok=True)

            report = learn_from_query_events(project, query_id="qa-hermes")
            proposals = load_memory_proposals(project)

            self.assertGreaterEqual(report.candidate_count, 1)
            self.assertGreaterEqual(report.proposal_count, 1)
            self.assertIn("Hermes Learning", render_hermes_learning_report(report))
            self.assertTrue(any(proposal.source.startswith("hermes_learning:qa-hermes") for proposal in proposals))

    def test_agent_v2_auto_learning_sidecar_proposes_quant_lesson(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            result = run_agent_v2(
                project,
                "P4逐笔验证要检查滑点容量和证据hash",
                plan=[AgentStep("status", "tool", {"tool": "status", "args": {}})],
            )
            proposals = load_memory_proposals(project)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(any(proposal.source.startswith("hermes_learning:") for proposal in proposals))
            self.assertTrue(any("P4" in proposal.text or "逐笔" in proposal.text for proposal in proposals))


if __name__ == "__main__":
    unittest.main()
