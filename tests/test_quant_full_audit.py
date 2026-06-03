from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.quant_full_audit import (
    QuantFullAuditSpec,
    render_quant_full_audit,
    render_quant_full_audit_json,
    run_quant_full_audit,
)


class QuantFullAuditTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quant full audit ")

    def write_scenario_a(self, project: Path) -> Path:
        comm = project / "AI_协作交接"
        comm.mkdir()
        path = comm / "agent2_scenario_A_0p2_0p2_position_dedup.csv"
        path.write_text(
            "code,entry_date,exit_date,entry_price,exit_price,net_return,t1_auction_return\n"
            "000001,2025-01-03,2025-01-04,10.0,10.2,0.020,-10\n"
            "000001,2026-04-24,2026-04-25,11.0,10.89,-0.010,-11\n",
            encoding="utf-8",
        )
        return path

    def test_full_audit_without_auto_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=False,
            )

            result = run_quant_full_audit(project, spec)

            self.assertEqual(result.scenario, "A")
            self.assertTrue(result.audit_id.startswith("audit-"))
            self.assertTrue(result.research_ready)
            self.assertFalse(result.live_ready)
            self.assertEqual(result.action, "pass")
            self.assertTrue(result.ok)
            self.assertEqual(result.data_discovery, {})
            self.assertEqual(result.sample_manifest, [])
            self.assertTrue(Path(result.output_json).exists())
            self.assertTrue(Path(result.output_markdown).exists())

    def test_full_audit_with_auto_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=True,
            )

            result = run_quant_full_audit(project, spec)

            self.assertEqual(result.scenario, "A")
            self.assertTrue(result.research_ready)
            self.assertFalse(result.live_ready)
            self.assertTrue(result.ok)
            # Auto evidence should have run
            self.assertIsInstance(result.auto_evidence_result, dict)
            self.assertTrue(Path(result.output_json).exists())
            self.assertTrue(Path(result.output_markdown).exists())

    def test_full_audit_renders_markdown(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=False,
            )

            result = run_quant_full_audit(project, spec)
            markdown = render_quant_full_audit(result)

            self.assertIn("# Quant Full Audit Report", markdown)
            self.assertIn("audit_id:", markdown)
            self.assertIn("scenario: A", markdown)
            self.assertIn("research_ready: true", markdown)
            self.assertIn("live_ready: false", markdown)
            self.assertIn("## Executive Summary", markdown)
            self.assertIn("## Data Discovery", markdown)
            self.assertIn("## Leakage Check", markdown)
            self.assertIn("## Walk-Forward Split", markdown)
            self.assertIn("## Broker Evidence", markdown)

    def test_full_audit_renders_json(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=False,
            )

            result = run_quant_full_audit(project, spec)
            json_output = render_quant_full_audit_json(result)
            payload = json.loads(json_output)

            self.assertEqual(payload["scenario"], "A")
            self.assertTrue(payload["research_ready"])
            self.assertFalse(payload["live_ready"])
            self.assertTrue(payload["ok"])
            self.assertIn("audit_id", payload)
            self.assertIn("data_discovery", payload)
            self.assertIn("sample_manifest", payload)
            self.assertIn("leakage_check", payload)
            self.assertIn("walk_forward_split", payload)
            self.assertIn("broker_evidence", payload)

    def test_full_audit_blocked_on_single_year(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            comm = project / "AI_协作交接"
            comm.mkdir()
            path = comm / "single_year.csv"
            path.write_text(
                "code,entry_date,exit_date,entry_price,exit_price,net_return,t1_auction_return\n"
                "000001,2025-01-03,2025-01-04,10.0,10.2,0.020,-10\n"
                "000001,2025-04-24,2025-04-25,11.0,10.89,-0.010,-11\n",
                encoding="utf-8",
            )

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=False,
            )

            result = run_quant_full_audit(project, spec)

            self.assertFalse(result.ok)
            self.assertFalse(result.research_ready)
            self.assertEqual(result.action, "block")
            self.assertTrue(result.failure_reason)

    def test_full_audit_with_execution_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            # Create mock execution evidence files
            comm = project / "AI_协作交接"
            tick_path = comm / "tick.csv"
            tick_path.write_text(
                "time,price,volume\n"
                "2025-01-03 09:30:00,10.0,1000\n"
                "2025-01-03 09:31:00,10.1,2000\n",
                encoding="utf-8",
            )

            fill_path = comm / "fill.csv"
            fill_path.write_text(
                "time,code,price,qty\n"
                "2025-01-03 09:30:00,000001,10.0,100\n",
                encoding="utf-8",
            )

            broker_path = comm / "broker.json"
            broker_path.write_text('{"broker": "test_broker", "account": "123456"}', encoding="utf-8")

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                threshold_col="t1_auction_return",
                threshold_lte=-9.0,
                auto_evidence=False,
                execution_source="test broker",
                tick_path=str(tick_path),
                fill_path=str(fill_path),
                broker_path=str(broker_path),
            )

            result = run_quant_full_audit(project, spec)

            self.assertTrue(result.research_ready)
            # Note: live_ready requires more complete execution evidence
            self.assertIsInstance(result.broker_evidence, dict)

    def test_full_audit_spec_to_dict(self) -> None:
        spec = QuantFullAuditSpec(
            scenario="B",
            input_path="/path/to/input.csv",
            threshold_lte=-5.0,
            assumptions=("assumption1", "assumption2"),
            strategy_roots=("/root1", "/root2"),
        )

        payload = spec.to_dict()

        self.assertEqual(payload["scenario"], "B")
        self.assertEqual(payload["input_path"], "/path/to/input.csv")
        self.assertEqual(payload["threshold_lte"], -5.0)
        self.assertEqual(payload["assumptions"], ["assumption1", "assumption2"])
        self.assertEqual(payload["strategy_roots"], ["/root1", "/root2"])

    def test_full_audit_result_to_dict(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            input_path = self.write_scenario_a(project)

            spec = QuantFullAuditSpec(
                scenario="A",
                input_path=str(input_path),
                auto_evidence=False,
            )

            result = run_quant_full_audit(project, spec)
            payload = result.to_dict()

            self.assertIn("audit_id", payload)
            self.assertIn("scenario", payload)
            self.assertIn("ok", payload)
            self.assertIn("research_ready", payload)
            self.assertIn("live_ready", payload)
            self.assertIn("data_discovery", payload)
            self.assertIn("sample_manifest", payload)
            self.assertIn("leakage_check", payload)
            self.assertIn("walk_forward_split", payload)
            self.assertIn("broker_evidence", payload)
            self.assertIn("warnings", payload)
            self.assertIsInstance(payload["warnings"], list)


if __name__ == "__main__":
    unittest.main()
