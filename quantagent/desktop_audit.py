from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .desktop_control import desktop_dir
from .mcp_runtime import redact_mcp_error, redact_mcp_payload
from .trajectory import read_events, record_action, record_observation, record_step


PHASE4_ITEMS = (26, 27, 28, 29, 30, 36, 37, 38, 39, 40)


@dataclass(frozen=True)
class DesktopEvidenceObject:
    evidence_id: str
    kind: str
    summary: str
    path: str = ""
    sha256: str = ""
    verified: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DesktopClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["text"] = _redact_text(self.text)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True)
class DesktopAuditStep:
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    app: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkProvenance:
    phase: str
    benchmark_items: tuple[int, ...]
    task_digest: str
    run_id: str
    project: str
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["benchmark_items"] = list(self.benchmark_items)
        return payload


@dataclass(frozen=True)
class DiffManifestAttribution:
    manifest_hash: str
    files: dict[str, tuple[int, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_hash": self.manifest_hash,
            "files": {path: list(items) for path, items in sorted(self.files.items())},
        }


@dataclass(frozen=True)
class DesktopAuditReport:
    ok: bool
    status: str
    summary: str
    run_id: str
    task: str
    trajectory_path: str
    report_path: str
    evidence: tuple[DesktopEvidenceObject, ...]
    claims: tuple[DesktopClaim, ...]
    rejected_claim_ids: tuple[str, ...]
    provenance: BenchmarkProvenance
    attribution: DiffManifestAttribution

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "run_id": self.run_id,
            "task": self.task,
            "trajectory_path": self.trajectory_path,
            "report_path": self.report_path,
            "evidence": [item.to_dict() for item in self.evidence],
            "claims": [item.to_dict() for item in self.claims],
            "rejected_claim_ids": list(self.rejected_claim_ids),
            "provenance": self.provenance.to_dict(),
            "attribution": self.attribution.to_dict(),
        }


class DesktopAuditAdapter(Protocol):
    def screenshot(self, project: Path, *, name: str = "") -> DesktopEvidenceObject:
        ...

    def ax_snapshot(self, project: Path, *, name: str = "") -> DesktopEvidenceObject:
        ...

    def ocr_snapshot(self, project: Path, image_path: str, *, name: str = "") -> DesktopEvidenceObject:
        ...

    def open_app(self, project: Path, app: str) -> DesktopEvidenceObject:
        ...

    def click(self, project: Path, x: int, y: int) -> DesktopEvidenceObject:
        ...

    def command(self, project: Path, command: str) -> DesktopEvidenceObject:
        ...


class FakeDesktopAuditAdapter:
    """Deterministic desktop adapter for tests and non-desktop environments."""

    def __init__(self, *, permission_fail_actions: Iterable[str] = ()) -> None:
        self.permission_fail_actions = {str(item) for item in permission_fail_actions}
        self.calls: list[str] = []
        self.counter = 0
        self.active_app = "Finder"

    def screenshot(self, project: Path, *, name: str = "") -> DesktopEvidenceObject:
        self.calls.append("screenshot")
        self.counter += 1
        path = _audit_dir(project) / (name or f"fake_screenshot_{self.counter:03d}.png")
        path.write_bytes(f"fake screenshot {self.counter} app={self.active_app}\n".encode("utf-8"))
        return _evidence("screenshot", f"screenshot captured for {self.active_app}", path=path, data={"app": self.active_app})

    def ax_snapshot(self, project: Path, *, name: str = "") -> DesktopEvidenceObject:
        self.calls.append("ax")
        path = _audit_dir(project) / (name or f"fake_ax_{self.counter:03d}.json")
        payload = {"app": self.active_app, "elements": [{"role": "AXButton", "title": "Search", "bounds": [10, 20, 110, 60]}]}
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return _evidence("ax", f"AX snapshot captured for {self.active_app}", path=path, data=payload)

    def ocr_snapshot(self, project: Path, image_path: str, *, name: str = "") -> DesktopEvidenceObject:
        self.calls.append("ocr")
        path = _audit_dir(project) / (name or f"fake_ocr_{self.counter:03d}.json")
        payload = {"image_path": image_path, "blocks": [{"text": "Search", "confidence": 0.95, "bounds": [10, 20, 110, 60]}]}
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return _evidence("ocr", "OCR snapshot captured", path=path, data=payload)

    def open_app(self, project: Path, app: str) -> DesktopEvidenceObject:
        self.calls.append(f"open:{app}")
        if "open_app" in self.permission_fail_actions:
            return _evidence("permission_failure", f"permission denied opening {app}", verified=False, data={"permission_kind": "automation", "app": app})
        self.active_app = app
        return _evidence("desktop_action", f"opened {app}", data={"action": "open_app", "app": app})

    def click(self, project: Path, x: int, y: int) -> DesktopEvidenceObject:
        self.calls.append("click")
        if "click" in self.permission_fail_actions:
            return _evidence("permission_failure", "permission denied clicking desktop", verified=False, data={"permission_kind": "accessibility", "x": x, "y": y})
        return _evidence("desktop_action", f"clicked {x},{y}", data={"action": "click", "x": x, "y": y, "app": self.active_app})

    def command(self, project: Path, command: str) -> DesktopEvidenceObject:
        self.calls.append("command")
        return _evidence(
            "command_output",
            f"command output captured: {command}",
            data={"command": command, "returncode": 0, "stdout": f"fake output for {command}", "stderr": ""},
        )


@dataclass(frozen=True)
class MixedSoakConfig:
    target_hours: float = 8.0
    interval_seconds: float = 60.0
    max_cycles: int = 0


@dataclass(frozen=True)
class MixedSoakResult:
    ok: bool
    status: str
    target_hours: float
    cycles: tuple[DesktopAuditReport, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "target_hours": self.target_hours,
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "summary": self.summary,
        }


def capture_desktop_observation(project: str | Path, adapter: DesktopAuditAdapter, *, name: str = "") -> tuple[DesktopEvidenceObject, ...]:
    project_path = Path(project).expanduser().resolve(strict=False)
    shot = adapter.screenshot(project_path, name=f"{name}_screenshot.png" if name else "")
    ax = adapter.ax_snapshot(project_path, name=f"{name}_ax.json" if name else "")
    ocr = adapter.ocr_snapshot(project_path, shot.path, name=f"{name}_ocr.json" if name else "")
    unified = _evidence(
        "desktop_observation",
        "unified screenshot/AX/OCR desktop observation",
        data={"screenshot": shot.to_dict(), "ax": ax.to_dict(), "ocr": ocr.to_dict()},
        verified=shot.verified and ax.verified and ocr.verified,
    )
    return shot, ax, ocr, unified


def run_desktop_audit_workflow(
    project: str | Path,
    task: str,
    steps: Iterable[DesktopAuditStep],
    *,
    adapter: DesktopAuditAdapter | None = None,
    changed_files: Mapping[str, Iterable[int]] | None = None,
    benchmark_items: Iterable[int] = PHASE4_ITEMS,
) -> DesktopAuditReport:
    project_path = Path(project).expanduser().resolve(strict=False)
    selected_adapter = adapter or FakeDesktopAuditAdapter()
    run_id = "desktop-audit-" + uuid.uuid4().hex[:10]
    run_dir = _audit_dir(project_path) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = run_dir / "trajectory.jsonl"
    evidence: list[DesktopEvidenceObject] = []
    claims: list[DesktopClaim] = []
    rejected: list[str] = []
    status = "success"
    ok = True
    summary = "desktop audit workflow completed"
    step_number = 0

    record_step(trajectory_path, f"task: {task}", step=step_number, ok=True, phase="task", task=task)
    observation = capture_desktop_observation(project_path, selected_adapter, name=f"{run_id}_initial")
    evidence.extend(observation)
    record_observation(trajectory_path, "initial screenshot/AX/OCR observation", step=step_number, ok=observation[-1].verified, phase="screenshot", evidence_id=observation[-1].evidence_id)
    if not observation[-1].verified:
        ok = False
        status = "paused"
        summary = "initial desktop observation failed"

    for step in (() if not ok else steps):
        step_number += 1
        action = step.action
        record_action(trajectory_path, f"desktop action: {action}", step=step_number, ok=None, phase="action", action=action, app=step.app, args=step.args)
        if action == "open_app":
            result = selected_adapter.open_app(project_path, str(step.args.get("app") or step.app))
        elif action == "click":
            result = selected_adapter.click(project_path, int(step.args.get("x") or 0), int(step.args.get("y") or 0))
        elif action == "command":
            result = selected_adapter.command(project_path, str(step.args.get("command") or ""))
        elif action == "claim":
            claim = DesktopClaim("claim-" + uuid.uuid4().hex[:10], str(step.args.get("text") or ""), tuple(str(item) for item in step.args.get("evidence_ids", ()) if str(item)))
            claims.append(claim)
            record_observation(trajectory_path, "claim proposed", step=step_number, ok=True, phase="claim", claim_id=claim.claim_id, evidence_ids=list(claim.evidence_ids))
            continue
        else:
            result = _evidence("workflow_error", f"unsupported audit step: {action}", verified=False, data={"action": action})
        evidence.append(result)
        result_phase = "command_output" if result.kind == "command_output" else "action_result"
        record_observation(trajectory_path, result.summary, step=step_number, ok=result.verified, phase=result_phase, evidence_id=result.evidence_id, kind=result.kind)
        if result.kind == "permission_failure":
            ok = False
            status = "paused"
            summary = result.summary
            break
        if not result.verified:
            ok = False
            status = "failed"
            summary = result.summary
            break
        if action == "click":
            verify = selected_adapter.screenshot(project_path, name=f"{run_id}_verify_click_{step_number:02d}.png")
            evidence.append(verify)
            record_observation(trajectory_path, "post-click screenshot verification", step=step_number, ok=verify.verified, phase="screenshot", evidence_id=verify.evidence_id)
            if not verify.verified:
                ok = False
                status = "verify_failed"
                summary = verify.summary
                break

    allowed_claims, rejected_claims = guard_claims_with_evidence(claims, evidence)
    rejected.extend(claim.claim_id for claim in rejected_claims)
    attribution = build_diff_manifest_attribution(changed_files or {"quantagent/desktop_audit.py": tuple(benchmark_items)})
    provenance = build_benchmark_provenance(project_path, task=task, run_id=run_id, benchmark_items=benchmark_items)
    report_path = run_dir / "report.md"
    report = DesktopAuditReport(ok, status, summary, run_id, task, str(trajectory_path), str(report_path), tuple(evidence), tuple(allowed_claims), tuple(rejected), provenance, attribution)
    record_step(trajectory_path, "final report generated", step=step_number + 1, ok=report.ok, phase="report", report_path=str(report_path))
    report_path.write_text(render_desktop_audit_report(report), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def guard_claims_with_evidence(
    claims: Iterable[DesktopClaim],
    evidence: Iterable[DesktopEvidenceObject],
) -> tuple[tuple[DesktopClaim, ...], tuple[DesktopClaim, ...]]:
    verified = {item.evidence_id: item for item in evidence if item.verified}
    allowed: list[DesktopClaim] = []
    rejected: list[DesktopClaim] = []
    for claim in claims:
        referenced = [verified[evidence_id] for evidence_id in claim.evidence_ids if evidence_id in verified]
        if (
            claim.evidence_ids
            and len(referenced) == len(claim.evidence_ids)
            and any(_evidence_supports_claim(item, claim) for item in referenced)
        ):
            allowed.append(claim)
        else:
            rejected.append(claim)
    return tuple(allowed), tuple(rejected)


def validate_trajectory_chain(path: str | Path) -> dict[str, Any]:
    events = read_events(path)
    phases = tuple(str(event.meta.get("phase") or "") for event in events if event.meta.get("phase"))
    required = ("task", "action", "screenshot", "command_output", "claim", "report")
    missing = tuple(phase for phase in required if phase not in phases)
    order_errors: list[str] = []
    if not missing:
        cursor = -1
        for phase in required:
            try:
                cursor = phases.index(phase, cursor + 1)
            except ValueError:
                order_errors.append(f"{phase} is out of order")
                break
    failed = tuple(str(event.meta.get("phase") or event.kind) for event in events if event.ok is False)
    return {"ok": not missing and not order_errors and not failed, "missing": missing, "order_errors": tuple(order_errors), "failed": failed, "phases": phases}


def build_benchmark_provenance(
    project: str | Path,
    *,
    task: str,
    run_id: str,
    benchmark_items: Iterable[int] = PHASE4_ITEMS,
) -> BenchmarkProvenance:
    project_path = Path(project).expanduser().resolve(strict=False)
    items = tuple(sorted({int(item) for item in benchmark_items}))
    digest = _sha256_json({"task": task, "items": items})[:16]
    return BenchmarkProvenance("phase4", items, digest, run_id, str(project_path), _now_ms())


def build_diff_manifest_attribution(changed_files: Mapping[str, Iterable[int]]) -> DiffManifestAttribution:
    allowed_items = set(PHASE4_ITEMS)
    files: dict[str, tuple[int, ...]] = {}
    for path, items in sorted(changed_files.items()):
        item_tuple = tuple(sorted({int(item) for item in items}))
        if not path.strip() or not item_tuple:
            raise ValueError("every changed file must map to at least one benchmark item")
        invalid = tuple(item for item in item_tuple if item not in allowed_items)
        if invalid:
            raise ValueError(f"unknown phase4 benchmark item(s): {', '.join(str(item) for item in invalid)}")
        files[str(path)] = item_tuple
    if not files:
        raise ValueError("diff/manifest attribution requires at least one changed file")
    manifest_hash = _sha256_json({path: list(items) for path, items in files.items()})
    return DiffManifestAttribution(manifest_hash, files)


def run_mixed_soak(
    project: str | Path,
    workflows: Iterable[tuple[str, Iterable[DesktopAuditStep]]],
    *,
    adapter: DesktopAuditAdapter | None = None,
    config: MixedSoakConfig = MixedSoakConfig(),
    sleep: Any = time.sleep,
    now: Any = time.monotonic,
) -> MixedSoakResult:
    workflow_items = [(task, tuple(steps)) for task, steps in workflows]
    if not workflow_items:
        return MixedSoakResult(False, "blocked", config.target_hours, (), "mixed soak requires at least one workflow")
    if config.target_hours <= 0 and config.max_cycles <= 0:
        return MixedSoakResult(False, "blocked", config.target_hours, (), "mixed soak requires target_hours or max_cycles")
    max_cycles = max(0, int(config.max_cycles))
    target_seconds = max(0.0, float(config.target_hours)) * 3600.0
    interval_seconds = max(0.0, float(config.interval_seconds))
    started = float(now())
    deadline = started + target_seconds if target_seconds > 0 else started
    cycles: list[DesktopAuditReport] = []
    selected_adapter = adapter or FakeDesktopAuditAdapter()
    index = 0
    while True:
        current = float(now())
        if max_cycles and index >= max_cycles:
            break
        if not max_cycles and target_seconds > 0 and current >= deadline:
            break
        task, steps = workflow_items[index % len(workflow_items)]
        report = run_desktop_audit_workflow(project, task, steps, adapter=selected_adapter)
        cycles.append(report)
        if not report.ok:
            return MixedSoakResult(False, report.status, config.target_hours, tuple(cycles), report.summary)
        index += 1
        if max_cycles and index >= max_cycles:
            break
        if not max_cycles and target_seconds > 0 and float(now()) >= deadline:
            break
        if interval_seconds > 0:
            sleep(interval_seconds)
    return MixedSoakResult(True, "success", config.target_hours, tuple(cycles), f"mixed soak completed {len(cycles)} cycle(s) toward {config.target_hours:g}h target")


def render_desktop_audit_report(report: DesktopAuditReport) -> str:
    lines = [
        "# Desktop Audit Report",
        "",
        f"- status: {report.status}",
        f"- ok: {str(report.ok).lower()}",
        f"- run_id: {report.run_id}",
        f"- trajectory: {report.trajectory_path}",
        f"- benchmark_items: {', '.join(str(item) for item in report.provenance.benchmark_items)}",
        f"- attribution_manifest: {report.attribution.manifest_hash}",
        "",
        "## Evidence",
    ]
    for item in report.evidence:
        source = item.path or item.kind
        lines.append(f"- {item.evidence_id} [{item.kind}] {item.summary} source={source}")
    lines.extend(["", "## Claims"])
    if not report.claims:
        lines.append("- none")
    for claim in report.claims:
        lines.append(f"- {claim.claim_id}: {_redact_text(claim.text)} evidence={','.join(claim.evidence_ids)}")
    lines.extend(["", f"Rejected claims: {len(report.rejected_claim_ids)}"])
    return "\n".join(lines).rstrip() + "\n"


def _audit_dir(project: Path) -> Path:
    path = desktop_dir(project) / "audit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _evidence(
    kind: str,
    summary: str,
    *,
    path: str | Path = "",
    verified: bool = True,
    data: Mapping[str, Any] | None = None,
) -> DesktopEvidenceObject:
    raw_path_text = str(path or "")
    safe_summary = _redact_text(summary)
    safe_data = _redact_payload(data or {})
    safe_path_text = _redact_text(raw_path_text)
    sha = _sha256_file(Path(raw_path_text)) if raw_path_text and Path(raw_path_text).exists() else _sha256_json({"kind": kind, "summary": safe_summary, "data": safe_data})
    evidence_id = "desk-ev-" + _sha256_json({"kind": kind, "summary": safe_summary, "path": safe_path_text, "sha256": sha})[:14]
    return DesktopEvidenceObject(evidence_id, kind, safe_summary, safe_path_text, sha, verified, safe_data)


def _evidence_supports_claim(evidence: DesktopEvidenceObject, claim: DesktopClaim) -> bool:
    supports = evidence.data.get("supports_claims")
    if isinstance(supports, (list, tuple, set)) and claim.claim_id in {str(item) for item in supports}:
        return True
    if str(evidence.data.get("claim_id") or "") == claim.claim_id:
        return True
    return str(evidence.data.get("claim_text_sha256") or "") == _claim_digest(claim.text)


def _claim_digest(text: str) -> str:
    return _sha256_json({"claim": text})


def _redact_text(text: str) -> str:
    return redact_mcp_error(str(text))


def _redact_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted = redact_mcp_payload(dict(value))
    return redacted if isinstance(redacted, dict) else {}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)
