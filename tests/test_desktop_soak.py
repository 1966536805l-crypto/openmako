from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from quantagent.desktop_soak import (
    latest_desktop_soak_run,
    list_desktop_soak_runs,
    load_desktop_soak_run,
    render_desktop_soak_result,
    run_desktop_soak,
)


class DesktopSoakTest(unittest.TestCase):
    def test_watchdog_times_out_and_kills_hung_eval_cycle(self) -> None:
        def run_eval(_project, **_kwargs):
            time.sleep(5)
            return {"ok": True, "status": "success", "summary": "too late", "run_id": "hung"}

        with tempfile.TemporaryDirectory(prefix="desktop soak watchdog timeout ") as tmp:
            started = time.monotonic()
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                run_eval=run_eval,
                watchdog=True,
                cycle_timeout_seconds=0.15,
                watchdog_interval_seconds=0.02,
            )
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.metrics["watchdog_kills"], 1)
        self.assertEqual(result.metrics["watchdog_timeouts"], 1)
        self.assertGreaterEqual(result.metrics["watchdog_checks"], 1)

    def test_watchdog_stop_file_kills_running_eval_cycle(self) -> None:
        def run_eval(_project, **kwargs):
            Path(kwargs["stop_file"]).write_text("operator stop\n", encoding="utf-8")
            time.sleep(5)
            return {"ok": True, "status": "success", "summary": "too late", "run_id": "stop-hung"}

        with tempfile.TemporaryDirectory(prefix="desktop soak watchdog stop ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                run_eval=run_eval,
                watchdog=True,
                cycle_timeout_seconds=5.0,
                watchdog_interval_seconds=0.02,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.metrics["watchdog_kills"], 1)
        self.assertIn("STOP file present", result.summary)

    def test_watchdog_guardian_failure_kills_running_eval_cycle(self) -> None:
        def run_eval(_project, **_kwargs):
            time.sleep(5)
            return {"ok": True, "status": "success", "summary": "too late", "run_id": "guardian-hung"}

        def inspect_guardian(_project, **_kwargs):
            return {"ok": False, "status": "stopped", "summary": "permission failure while eval running"}

        with tempfile.TemporaryDirectory(prefix="desktop soak watchdog guardian ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=True,
                run_eval=run_eval,
                inspect_guardian=inspect_guardian,
                watchdog=True,
                cycle_timeout_seconds=5.0,
                watchdog_interval_seconds=0.02,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.metrics["watchdog_kills"], 1)
        self.assertEqual(result.cycles[0].watchdog_status, "stopped")

    def test_default_watchdog_guardian_ignores_stale_global_daemon_state(self) -> None:
        def run_eval(_project, **_kwargs):
            time.sleep(0.08)
            return {"ok": True, "status": "success", "summary": "eval ok", "run_id": "eval-ok", "metrics": {"total": 1, "success": 1, "steps": 1}}

        with tempfile.TemporaryDirectory(prefix="desktop soak stale global guardian ") as tmp:
            project = Path(tmp)
            daemon_dir = project / "AI_协作交接" / "desktop" / "intelligence" / "daemon"
            daemon_dir.mkdir(parents=True)
            (daemon_dir / "latest_state.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "goal": "buy 100 shares",
                        "summary": "high-risk goal term: buy",
                        "stop_file": str(project / "AI_协作交接" / "desktop" / "agent" / "STOP"),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_desktop_soak(
                project,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=True,
                require_evidence=False,
                run_eval=run_eval,
                watchdog=True,
                cycle_timeout_seconds=2.0,
                watchdog_interval_seconds=0.02,
            )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "success")
        self.assertEqual(result.metrics["watchdog_kills"], 0)
        self.assertEqual(result.cycles[0].guardian_status, "idle")

    def test_require_evidence_blocks_missing_eval_json(self) -> None:
        def run_eval(_project, **_kwargs):
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok without persisted json",
                "run_id": "eval-missing-json",
                "json_path": "",
                "metrics": {"total": 1, "success": 1, "steps": 1},
            }

        with tempfile.TemporaryDirectory(prefix="desktop soak evidence json ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                require_evidence=True,
                run_eval=run_eval,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.metrics["runs"], 1)
        self.assertIn("eval json", result.summary)
        self.assertIn("eval-missing-json", result.summary)

    def test_require_evidence_blocks_missing_trajectory_and_query_events(self) -> None:
        def run_eval(project, **_kwargs):
            eval_json = Path(project) / "eval-without-ledgers.json"
            eval_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "success",
                        "run_id": "eval-without-ledgers",
                        "query_events_path": str(Path(project) / "missing-query-events.jsonl"),
                        "trajectory_path": str(Path(project) / "missing-trajectory.jsonl"),
                        "metrics": {"total": 1, "success": 1, "steps": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok without ledgers",
                "run_id": "eval-without-ledgers",
                "json_path": str(eval_json),
                "metrics": {"total": 1, "success": 1, "steps": 1},
            }

        with tempfile.TemporaryDirectory(prefix="desktop soak evidence ledgers ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                require_evidence=True,
                run_eval=run_eval,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("query_events", result.summary)
        self.assertIn("trajectory", result.summary)

    def test_require_evidence_blocks_duplicate_eval_run_id(self) -> None:
        clock = [0.0]

        def now() -> float:
            return clock[0]

        def run_eval(project, **_kwargs):
            cycle = len(list((Path(project) / ".quantagent" / "desktop" / "soak").glob("*.json"))) + 1
            query_events = Path(project) / f"query-events-{cycle}.jsonl"
            trajectory = Path(project) / f"trajectory-{cycle}.jsonl"
            eval_json = Path(project) / f"eval-{cycle}.json"
            query_events.write_text('{"kind":"query_start","query_id":"q","summary":"started"}\n', encoding="utf-8")
            trajectory.write_text('{"kind":"observation","summary":"observed","ok":true}\n', encoding="utf-8")
            eval_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "success",
                        "run_id": "eval-duplicate",
                        "query_events_path": str(query_events),
                        "trajectory_path": str(trajectory),
                        "metrics": {"total": 1, "success": 1, "steps": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            clock[0] += 1
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok",
                "run_id": "eval-duplicate",
                "json_path": str(eval_json),
                "metrics": {"total": 1, "success": 1, "steps": 1},
            }

        with tempfile.TemporaryDirectory(prefix="desktop soak evidence duplicate ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=2,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                require_evidence=True,
                run_eval=run_eval,
                now=now,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.metrics["runs"], 2)
        self.assertIn("duplicate eval_run_id", result.summary)
        self.assertIn("eval-duplicate", result.summary)

    def test_require_evidence_binds_guardian_to_each_cycle_artifact_paths(self) -> None:
        clock = [0.0]
        guardian_calls: list[dict[str, str]] = []

        def now() -> float:
            return clock[0]

        def run_eval(project, **_kwargs):
            cycle = len(guardian_calls) + 1
            query_events = Path(project) / f"cycle-{cycle}-query-events.jsonl"
            trajectory = Path(project) / f"cycle-{cycle}-trajectory.jsonl"
            eval_json = Path(project) / f"cycle-{cycle}-eval.json"
            query_events.write_text('{"kind":"query_start","query_id":"q","summary":"started"}\n', encoding="utf-8")
            trajectory.write_text('{"kind":"observation","summary":"observed","ok":true}\n', encoding="utf-8")
            eval_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "status": "success",
                        "run_id": f"eval-{cycle}",
                        "query_events_path": str(query_events),
                        "trajectory_path": str(trajectory),
                        "metrics": {"total": 1, "success": 1, "steps": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            clock[0] += 1
            return {
                "ok": True,
                "status": "success",
                "summary": f"eval {cycle} ok",
                "run_id": f"eval-{cycle}",
                "json_path": str(eval_json),
                "metrics": {"total": 1, "success": 1, "steps": 1},
            }

        def inspect_guardian(_project, **kwargs):
            guardian_calls.append(
                {
                    "query_events_path": str(kwargs.get("query_events_path") or ""),
                    "trajectory_path": str(kwargs.get("trajectory_path") or ""),
                }
            )
            return {"ok": True, "status": "ok", "summary": "guardian checks passed"}

        with tempfile.TemporaryDirectory(prefix="desktop soak evidence guardian ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=2,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=True,
                require_evidence=True,
                run_eval=run_eval,
                inspect_guardian=inspect_guardian,
                now=now,
            )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(
            guardian_calls,
            [
                {
                    "query_events_path": str(Path(tmp) / "cycle-1-query-events.jsonl"),
                    "trajectory_path": str(Path(tmp) / "cycle-1-trajectory.jsonl"),
                },
                {
                    "query_events_path": str(Path(tmp) / "cycle-2-query-events.jsonl"),
                    "trajectory_path": str(Path(tmp) / "cycle-2-trajectory.jsonl"),
                },
            ],
        )

    def test_soak_requires_explicit_execution_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop soak blocked ") as tmp:
            result = run_desktop_soak(tmp, max_cycles=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.metrics["runs"], 0)
        self.assertIn("--execute", result.summary)

    def test_soak_aggregates_cycles_and_scores_l4_after_four_hours(self) -> None:
        clock = [0.0]

        def now() -> float:
            return clock[0]

        def run_eval(_project, **_kwargs):
            clock[0] += 4 * 3600
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok",
                "run_id": "eval-1",
                "json_path": "/tmp/eval-1.json",
                "report_path": "/tmp/eval-1.md",
                "metrics": {
                    "total": 7,
                    "success": 7,
                    "failure": 0,
                    "blocked": 0,
                    "stopped": 0,
                    "timeout": 0,
                    "steps": 7,
                    "misoperations": 0,
                    "crashes": 0,
                    "autopsies": 0,
                    "recovery_attempts": 0,
                    "recovery_successes": 0,
                    "manual_interventions": 0,
                },
            }

        def inspect_guardian(_project):
            return {"ok": True, "status": "ok", "summary": "guardian checks passed"}

        with tempfile.TemporaryDirectory(prefix="desktop soak l4 ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=4,
                interval_seconds=0,
                max_cycles=1,
                execute=True,
                reviewed=True,
                allow_actions=True,
                run_eval=run_eval,
                inspect_guardian=inspect_guardian,
                now=now,
            )
            payload = json.loads(Path(result.json_path).read_text(encoding="utf-8"))
            report = Path(result.report_path).read_text(encoding="utf-8")

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "success")
        self.assertEqual(result.metrics["runs"], 1)
        self.assertEqual(result.metrics["total_tasks"], 7)
        self.assertEqual(result.metrics["level"], "L4")
        self.assertGreaterEqual(result.metrics["long_run_hours"], 4.0)
        self.assertEqual(payload["metrics"]["level"], "L4")
        self.assertIn("# Desktop Soak Run", report)

    def test_soak_skips_short_tail_cycle_after_successful_cycle(self) -> None:
        clock = [0.0]
        durations: list[float] = []
        sleeps: list[float] = []

        def now() -> float:
            return clock[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        def run_eval(_project, **kwargs):
            durations.append(float(kwargs["duration_minutes"]))
            clock[0] = 3595.0
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok",
                "run_id": "eval-1",
                "metrics": {"total": 1, "success": 1, "steps": 1, "misoperations": 0, "crashes": 0},
            }

        with tempfile.TemporaryDirectory(prefix="desktop soak short tail ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=1,
                interval_seconds=0,
                max_cycles=2,
                execute=True,
                reviewed=True,
                allow_actions=True,
                guardian=False,
                watchdog=False,
                run_eval=run_eval,
                now=now,
                sleep=sleep,
            )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, "success")
        self.assertEqual(durations, [60.0])
        self.assertEqual(result.metrics["runs"], 1)
        self.assertGreaterEqual(result.metrics["long_run_hours"], 1.0)
        self.assertEqual(sleeps, [5.0])

    def test_soak_stops_when_guardian_fails(self) -> None:
        clock = [0.0]

        def now() -> float:
            return clock[0]

        def run_eval(_project, **_kwargs):
            clock[0] += 5
            return {
                "ok": True,
                "status": "success",
                "summary": "eval ok",
                "run_id": "eval-1",
                "metrics": {"total": 1, "success": 1, "steps": 1},
            }

        def inspect_guardian(_project):
            return {"ok": False, "status": "stopped", "summary": "same_action_repeat"}

        with tempfile.TemporaryDirectory(prefix="desktop soak guard ") as tmp:
            result = run_desktop_soak(
                tmp,
                hours=4,
                interval_seconds=0,
                max_cycles=3,
                execute=True,
                reviewed=True,
                allow_actions=True,
                run_eval=run_eval,
                inspect_guardian=inspect_guardian,
                now=now,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.metrics["runs"], 1)
        self.assertEqual(result.metrics["guardian_stops"], 1)
        self.assertIn("guardian", result.summary)

    def test_latest_soak_returns_running_state_before_final_json_exists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop soak latest ") as tmp:
            project = Path(tmp)
            state = project / ".quantagent" / "desktop" / "soak" / "latest_state.json"
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "run_id": "soak_running",
                        "suite": "suite_live",
                        "cycles": 3,
                        "last_eval_run_id": "eval-3",
                        "stop_file": str(state.parent / "STOP"),
                        "heartbeat_at": "2026-05-26T21:00:00",
                    }
                ),
                encoding="utf-8",
            )
            result = latest_desktop_soak_run(project)

        self.assertEqual(result.status, "running")
        self.assertEqual(result.metrics["runs"], 3)
        self.assertEqual(result.metrics["last_eval_run_id"], "eval-3")
        self.assertIn("soak_running", render_desktop_soak_result(result))

    def test_load_list_and_render_completed_soak_with_failed_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop soak load ") as tmp:
            result = run_desktop_soak(tmp, max_cycles=1)
            loaded = load_desktop_soak_run(result.json_path)
            listed = list_desktop_soak_runs(tmp)
            rendered = render_desktop_soak_result(loaded)

        self.assertEqual(loaded.run_id, result.run_id)
        self.assertEqual([item.run_id for item in listed], [result.run_id])
        self.assertIn("failed_gates:", rendered)
        self.assertIn("L4 long_run_hours", rendered)


if __name__ == "__main__":
    unittest.main()
