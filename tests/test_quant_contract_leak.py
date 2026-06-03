from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.evidence_ledger import load_evidence
from quantagent.experiment_runner import ExperimentSpec, run_experiment
from quantagent.quant_data_contract import validate_quant_data_contract
from quantagent.quant_leak_check import run_quant_leak_check, check_survivorship_bias_data


class QuantContractLeakTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant contract ")

    def test_data_contract_blocks_invalid_required_values(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "bad_dedup.csv"
            path.write_text("entry_date,net_return\nnot-a-date,abc\n", encoding="utf-8")

            result = validate_quant_data_contract(path)

            self.assertFalse(result.ok)
            codes = {issue.code for issue in result.issues if issue.level == "error"}
            self.assertIn("invalid_date", codes)
            self.assertIn("no_valid_numeric_values", codes)

    def test_data_contract_can_enforce_dedup_name(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text("entry_date,net_return\n2025-01-01,0.01\n", encoding="utf-8")

            loose = validate_quant_data_contract(path)
            strict = validate_quant_data_contract(path, strict_dedup=True)

            self.assertTrue(loose.ok)
            self.assertFalse(strict.ok)
            self.assertIn("not_dedup_marked", {issue.code for issue in strict.issues})

    def test_leak_check_flags_future_shift_and_future_column(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            py_path = project / "strategy.py"
            csv_path = project / "features.csv"
            py_path.write_text("df['x'] = df['close'].shift(-1)\n", encoding="utf-8")
            csv_path.write_text("entry_date,net_return,future_return\n2025-01-01,0.01,0.02\n", encoding="utf-8")

            result = run_quant_leak_check(project)

            self.assertFalse(result.ok)
            codes = {finding.code for finding in result.findings}
            self.assertIn("negative_shift", codes)
            self.assertIn("suspicious_future_or_target_column", codes)

    def test_leak_check_flags_shift_periods_keyword(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "strategy.py"
            path.write_text("df['x'] = df['close'].shift(periods=-1)\n", encoding="utf-8")

            result = run_quant_leak_check(path)

            self.assertFalse(result.ok)
            self.assertIn("negative_shift", {finding.code for finding in result.findings})

    def test_leak_check_flags_merge_asof_forward_direction_variable(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "strategy.py"
            path.write_text(
                "join_dir = 'forward'\n"
                "df = pd.merge_asof(df, events, on='ts', direction=join_dir)\n",
                encoding="utf-8",
            )

            result = run_quant_leak_check(path)

            self.assertFalse(result.ok)
            self.assertIn("forward_merge_asof", {finding.code for finding in result.findings})

    def test_leak_check_flags_dynamic_merge_asof_direction(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "strategy.py"
            path.write_text("df = pd.merge_asof(df, events, on='ts', direction=mydir)\n", encoding="utf-8")

            result = run_quant_leak_check(path)

            self.assertFalse(result.ok)
            self.assertIn("dynamic_merge_asof_direction", {finding.code for finding in result.findings})

    def test_leak_check_flags_concatenated_target_feature_column(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "strategy.py"
            path.write_text("features = ['open', 'tar' + 'get_return']\n", encoding="utf-8")

            result = run_quant_leak_check(path)

            self.assertFalse(result.ok)
            self.assertIn("target_column_in_feature_list", {finding.code for finding in result.findings})

    def test_leak_check_flags_concatenated_target_column_reference(self) -> None:
        with self.make_project() as tmp:
            path = Path(tmp) / "strategy.py"
            path.write_text("df['feature'] = df['tar' + 'get_return']\n", encoding="utf-8")

            result = run_quant_leak_check(path)

            self.assertFalse(result.ok)
            self.assertIn("target_like_column_reference", {finding.code for finding in result.findings})

    def test_experiment_records_run_artifacts_and_evidence(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            comm = project / "AI_协作交接"
            comm.mkdir()
            path = comm / "sample_position_dedup.csv"
            path.write_text(
                "entry_date,net_return,t1_auction_return\n"
                "2025-01-01,0.01,-10\n"
                "2026-01-02,0.02,-11\n",
                encoding="utf-8",
            )

            payload = run_experiment(
                project,
                ExperimentSpec(
                    name="evidence run",
                    input_path=path,
                    threshold_col="t1_auction_return",
                    threshold_lte=-9,
                ),
            )
            evidence = load_evidence(project)

            self.assertTrue(payload["run_id"].startswith("run-"))
            self.assertTrue((Path(payload["run_dir"]) / "spec.json").exists())
            self.assertTrue((Path(payload["run_dir"]) / "result.json").exists())
            self.assertTrue(payload["data_contract"]["ok"])
            self.assertTrue(payload["leak_check"]["ok"])
            self.assertTrue(any(record.claim == "dedup baseline" for record in evidence))
            self.assertTrue(any(record.claim == "artifact hashes and row count" for record in evidence))
            self.assertTrue(any(record.claim == "yearly OOS split" for record in evidence))

    def test_quant_cli_data_contract_and_leak_check(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            csv_path = project / "sample_dedup.csv"
            py_path = project / "strategy.py"
            csv_path.write_text("entry_date,net_return\n2025-01-01,0.01\n", encoding="utf-8")
            py_path.write_text("df = df.merge_asof(other, direction='forward')\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                contract_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "data-contract", str(csv_path)])
            contract_output = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                leak_rc = main(["--no-trust-prompt", "quant", "--project", tmp, "leak-check", str(py_path)])
            leak_output = stdout.getvalue()

            self.assertEqual(contract_rc, 0)
            self.assertIn("# Quant Data Contract", contract_output)
            self.assertEqual(leak_rc, 1)
            self.assertIn("forward_merge_asof", leak_output)

    def test_survivorship_bias_data_no_delisted_stocks(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            # Create strategy CSV with many stocks
            strategy_path = project / "strategy_data.csv"
            strategy_lines = ["code,entry_date,net_return"]
            for i in range(150):
                strategy_lines.append(f"STOCK{i:03d},2025-01-01,0.01")
            strategy_path.write_text("\n".join(strategy_lines) + "\n", encoding="utf-8")

            # Create universe with all stocks marked as active (no delisted)
            universe_path = project / "universe.csv"
            universe_lines = ["code,delisted"]
            for i in range(200):
                universe_lines.append(f"STOCK{i:03d},false")
            universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")

            finding = check_survivorship_bias_data(strategy_path, universe_path)

            self.assertIsNotNone(finding)
            self.assertEqual(finding.code, "survivorship_bias_no_delisted")
            self.assertEqual(finding.level, "error")
            self.assertIn("zero delisted stocks", finding.message)

    def test_survivorship_bias_data_low_coverage(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            # Create strategy CSV with 100 stocks
            strategy_path = project / "strategy_data.csv"
            strategy_lines = ["code,entry_date,net_return"]
            for i in range(100):
                strategy_lines.append(f"STOCK{i:03d},2025-01-01,0.01")
            strategy_path.write_text("\n".join(strategy_lines) + "\n", encoding="utf-8")

            # Create universe with only 3% delisted (3 out of 100)
            universe_path = project / "universe.csv"
            universe_lines = ["code,delisted"]
            for i in range(100):
                is_delisted = "true" if i < 3 else "false"
                universe_lines.append(f"STOCK{i:03d},{is_delisted}")
            universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")

            finding = check_survivorship_bias_data(strategy_path, universe_path)

            self.assertIsNotNone(finding)
            self.assertEqual(finding.code, "survivorship_bias_low_coverage")
            self.assertEqual(finding.level, "warn")
            self.assertIn("3.0%", finding.message)
            self.assertIn("3/100", finding.message)

    def test_survivorship_bias_data_acceptable_coverage(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            # Create strategy CSV with 100 stocks
            strategy_path = project / "strategy_data.csv"
            strategy_lines = ["code,entry_date,net_return"]
            for i in range(100):
                strategy_lines.append(f"STOCK{i:03d},2025-01-01,0.01")
            strategy_path.write_text("\n".join(strategy_lines) + "\n", encoding="utf-8")

            # Create universe with 10% delisted (acceptable coverage)
            universe_path = project / "universe.csv"
            universe_lines = ["code,delisted"]
            for i in range(100):
                is_delisted = "true" if i < 10 else "false"
                universe_lines.append(f"STOCK{i:03d},{is_delisted}")
            universe_path.write_text("\n".join(universe_lines) + "\n", encoding="utf-8")

            finding = check_survivorship_bias_data(strategy_path, universe_path)

            self.assertIsNone(finding)

    def test_survivorship_bias_data_no_universe_provided(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            strategy_path = project / "strategy_data.csv"
            strategy_path.write_text("code,entry_date,net_return\nSTOCK001,2025-01-01,0.01\n", encoding="utf-8")

            # No universe path provided - should return None
            finding = check_survivorship_bias_data(strategy_path, None)

            self.assertIsNone(finding)

    def test_survivorship_bias_data_small_sample(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            # Create strategy CSV with only 5 stocks (too small for assessment)
            strategy_path = project / "strategy_data.csv"
            strategy_lines = ["code,entry_date,net_return"]
            for i in range(5):
                strategy_lines.append(f"STOCK{i:03d},2025-01-01,0.01")
            strategy_path.write_text("\n".join(strategy_lines) + "\n", encoding="utf-8")

            universe_path = project / "universe.csv"
            universe_path.write_text("code,delisted\nSTOCK001,false\n", encoding="utf-8")

            finding = check_survivorship_bias_data(strategy_path, universe_path)

            # Too few stocks to assess - should return None
            self.assertIsNone(finding)


if __name__ == "__main__":
    unittest.main()
