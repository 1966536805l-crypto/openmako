from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from quantagent.desktop_eval import (
    BLOCKED,
    DRY_RUN,
    FAILURE,
    STOPPED,
    SUCCESS,
    TIMEOUT,
    list_desktop_eval_runs,
    load_desktop_eval_run,
    render_desktop_eval_result,
    run_desktop_eval,
)


def hanging_desktop_eval_runner(**_kwargs):
    time.sleep(5)
    return {"status": "success", "summary": "too late"}


def stop_then_hanging_desktop_eval_runner(**kwargs):
    Path(kwargs["context"]["stop_file"]).write_text("operator stop\n", encoding="utf-8")
    time.sleep(5)
    return {"status": "success", "summary": "too late"}


class DesktopEvalTest(unittest.TestCase):
    def test_default_dry_run_writes_json_and_markdown_without_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval dry ") as tmp:
            result = run_desktop_eval(tmp)
            json_payload = json.loads(Path(result.json_path).read_text(encoding="utf-8"))
            report = Path(result.report_path).read_text(encoding="utf-8")
            query_events = Path(result.query_events_path).read_text(encoding="utf-8")
            trajectory = Path(result.trajectory_path).read_text(encoding="utf-8")

        self.assertTrue(result.ok)
        self.assertEqual(result.status, DRY_RUN)
        self.assertEqual(result.metrics["total"], 8)
        self.assertEqual(result.metrics["dry_run"], 8)
        self.assertEqual(result.metrics[SUCCESS], 0)
        self.assertEqual(result.metrics[FAILURE], 0)
        self.assertTrue(result.json_path.endswith(".json"))
        self.assertTrue(result.report_path.endswith(".md"))
        self.assertEqual(json_payload["status"], DRY_RUN)
        self.assertEqual(json_payload["query_events_path"], result.query_events_path)
        self.assertEqual(json_payload["trajectory_path"], result.trajectory_path)
        self.assertIn('"kind": "query_start"', query_events)
        self.assertIn('"kind": "desktop_eval_scenario"', trajectory)
        self.assertIn("# Desktop Eval Run", report)
        self.assertIn("[dry_run] desktop-l4-screenshot-permission", report)
        self.assertEqual(result.metrics["level"], "L2")
        self.assertEqual(result.metrics["scenario_count"], 8)
        self.assertEqual(result.metrics["success_count"], 0)
        self.assertEqual(result.metrics["failure_count"], 0)
        self.assertEqual(result.metrics["blocked_count"], 0)
        self.assertEqual(result.metrics["stopped_count"], 0)
        self.assertEqual(result.metrics["timeout_count"], 0)
        self.assertEqual(result.metrics["crash_count"], 0)
        self.assertEqual(result.metrics["side_effect_count"], 0)
        self.assertEqual(result.metrics["manual_intervention_count"], 0)
        self.assertEqual(result.metrics["recovery_attempt_count"], 0)
        self.assertEqual(result.metrics["recovery_success_count"], 0)
        self.assertEqual(result.metrics["autopsy_count"], 0)
        self.assertEqual(result.metrics["missing_autopsy_count"], 0)
        self.assertEqual(result.metrics["total_actions"], 0)
        self.assertEqual(result.metrics["action_count"], 0)
        self.assertEqual(result.metrics["misoperation_rate"], 0.0)
        self.assertEqual(result.metrics["crash_rate"], 0.0)
        self.assertFalse(any("misoperation_rate" in reason for reason in result.metrics["level_reasons"]))

    def test_injected_runner_records_mixed_outcomes_and_counters(self) -> None:
        calls: list[str] = []

        def runner(scenario, context):
            calls.append(scenario["id"])
            self.assertTrue(context["execute"])
            if scenario["id"] == "ok":
                return {
                    "status": "completed",
                    "summary": "ok",
                    "steps": 4,
                    "recovery_attempts": 2,
                    "manual_interventions": 1,
                    "data": {"proof": "seen"},
                }
            return {"status": "failed", "summary": "bad", "steps": 3}

        scenarios = [
            {"id": "ok", "name": "ok scenario", "goal": "safe goal"},
            {"id": "bad", "name": "bad scenario", "goal": "safe failure"},
        ]
        with tempfile.TemporaryDirectory(prefix="desktop eval runner ") as tmp:
            result = run_desktop_eval(
                tmp,
                scenario=scenarios,
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=runner,
            )
            loaded = load_desktop_eval_run(result.json_path)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, FAILURE)
        self.assertEqual(calls, ["ok", "bad"])
        self.assertEqual(result.metrics[SUCCESS], 1)
        self.assertEqual(result.metrics[FAILURE], 1)
        self.assertEqual(result.metrics["steps"], 7)
        self.assertEqual(result.metrics["recovery_attempts"], 2)
        self.assertEqual(result.metrics["manual_interventions"], 1)
        self.assertEqual(result.metrics["scenario_count"], 2)
        self.assertEqual(result.metrics["success_count"], 1)
        self.assertEqual(result.metrics["failure_count"], 1)
        self.assertEqual(result.metrics["total_actions"], 7)
        self.assertEqual(result.metrics["action_count"], 7)
        self.assertEqual(result.metrics["missing_autopsy_count"], 1)
        self.assertEqual(result.metrics["crash_rate"], 0.0)
        self.assertEqual(result.metrics["misoperation_rate"], 0.0)
        self.assertEqual(result.scenarios[0].data["proof"], "seen")
        self.assertEqual(loaded.run_id, result.run_id)
        self.assertEqual(loaded.scenarios[0].status, SUCCESS)

    def test_execute_requires_review_allow_actions_and_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval blocked ") as tmp:
            guarded = run_desktop_eval(tmp, scenario="one,two", execute=True, reviewed=False, allow_actions=False)
            no_runner = run_desktop_eval(tmp, scenario="one", execute=True, reviewed=True, allow_actions=True)

        self.assertFalse(guarded.ok)
        self.assertEqual(guarded.status, BLOCKED)
        self.assertEqual(guarded.metrics[BLOCKED], 2)
        self.assertIn("--reviewed", guarded.summary)
        self.assertFalse(no_runner.ok)
        self.assertEqual(no_runner.status, BLOCKED)
        self.assertIn("requires an injected runner", no_runner.scenarios[0].summary)

    def test_named_builtin_scenario_keeps_suite_payload(self) -> None:
        seen: list[dict[str, object]] = []

        def runner(scenario, context):
            del context
            seen.append(scenario)
            return {"status": "success", "summary": "ok", "steps": 1}

        with tempfile.TemporaryDirectory(prefix="desktop eval named ") as tmp:
            result = run_desktop_eval(
                tmp,
                suite="suite_live",
                scenario="desktop-live-tokenization-fluctuation",
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=runner,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.metrics["total"], 1)
        self.assertEqual(result.scenarios[0].id, "desktop-live-tokenization-fluctuation")
        self.assertIn("ocr", result.scenarios[0].tags)
        self.assertEqual(seen[0]["data"]["setup"]["kind"], "live_tokenization_fluctuation_probe")

    def test_stop_file_prevents_runner(self) -> None:
        calls: list[str] = []

        def runner(**_kwargs):
            calls.append("runner")
            return {"status": "success"}

        with tempfile.TemporaryDirectory(prefix="desktop eval stop ") as tmp:
            project = Path(tmp)
            stop = project / "STOP"
            stop.write_text("stop\n", encoding="utf-8")
            result = run_desktop_eval(
                project,
                scenario="one,two",
                execute=True,
                reviewed=True,
                allow_actions=True,
                stop_file=stop,
                runner=runner,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, STOPPED)
        self.assertEqual(result.metrics[STOPPED], 2)
        self.assertEqual(calls, [])

    def test_step_budget_exhaustion_counts_timeout_for_remaining_scenarios(self) -> None:
        calls: list[str] = []

        def runner(scenario, context):
            calls.append(scenario["id"])
            return {"status": "success", "summary": "spent", "steps": context["remaining_steps"]}

        with tempfile.TemporaryDirectory(prefix="desktop eval timeout ") as tmp:
            result = run_desktop_eval(
                tmp,
                scenario="one,two",
                max_steps=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=runner,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, TIMEOUT)
        self.assertEqual(calls, ["one"])
        self.assertEqual(result.metrics[SUCCESS], 1)
        self.assertEqual(result.metrics[TIMEOUT], 1)
        self.assertEqual(result.scenarios[1].status, TIMEOUT)

    def test_scenario_watchdog_times_out_and_kills_hung_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval watchdog timeout ") as tmp:
            project = Path(tmp)
            started = time.monotonic()
            result = run_desktop_eval(
                project,
                scenario="hang,next",
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=hanging_desktop_eval_runner,
                scenario_timeout_seconds=0.15,
            )
            elapsed = time.monotonic() - started
            stop_written = (project / ".quantagent" / "desktop" / "STOP").exists()

        self.assertLess(elapsed, 2.0)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, TIMEOUT)
        self.assertEqual(result.scenarios[0].status, TIMEOUT)
        self.assertEqual(result.scenarios[1].status, TIMEOUT)
        self.assertTrue(result.scenarios[0].data["watchdog_killed"])
        self.assertEqual(result.metrics["watchdog_kills"], 1)
        self.assertEqual(result.metrics["watchdog_timeouts"], 1)
        self.assertGreaterEqual(result.metrics["watchdog_checks"], 1)
        self.assertTrue(stop_written)

    def test_scenario_watchdog_stop_file_kills_running_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval watchdog stop ") as tmp:
            started = time.monotonic()
            result = run_desktop_eval(
                tmp,
                scenario="hang",
                execute=True,
                reviewed=True,
                allow_actions=True,
                runner=stop_then_hanging_desktop_eval_runner,
                scenario_timeout_seconds=5.0,
            )
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, STOPPED)
        self.assertEqual(result.scenarios[0].status, STOPPED)
        self.assertTrue(result.scenarios[0].data["watchdog_killed"])
        self.assertEqual(result.metrics["watchdog_kills"], 1)

    def test_list_runs_sorts_and_returns_loaded_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop eval list ") as tmp:
            first = run_desktop_eval(tmp, scenario="a")
            second = run_desktop_eval(tmp, scenario="b")
            runs = list_desktop_eval_runs(tmp)
            rendered = render_desktop_eval_result(second)

        self.assertEqual([run.run_id for run in runs], sorted([first.run_id, second.run_id]))
        self.assertIn(second.run_id, rendered)
        self.assertEqual(runs[0].scenarios[0].status, DRY_RUN)


if __name__ == "__main__":
    unittest.main()
