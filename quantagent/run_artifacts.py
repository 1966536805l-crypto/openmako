from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    name: str
    created_at: str
    spec_hash: str
    spec: dict[str, Any]
    run_dir: str
    code_version: str = ""
    library_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SpecLockCheck:
    run_id: str
    ok: bool
    stored_hash: str
    current_hash: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def runs_root(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quantagent_runs"


def stable_run_id(spec: dict[str, Any], *, name: str = "") -> str:
    payload = {"name": name, "spec": spec}
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return "run-" + digest[:16]


def spec_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(spec).encode("utf-8")).hexdigest()


def create_run_spec(
    project: str | Path,
    name: str,
    spec: dict[str, Any],
    *,
    code_version: str = "",
    library_versions: dict[str, str] | None = None,
) -> RunSpec:
    project_path = Path(project).expanduser().resolve(strict=False)
    normalized_spec = _normalize_spec(spec)
    versions = library_versions or _default_library_versions()
    enriched = {
        **normalized_spec,
        "code_version": code_version,
        "library_versions": versions,
    }
    run_id = stable_run_id(enriched, name=name)
    run_dir = runs_root(project_path) / run_id
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    run_spec = RunSpec(
        run_id=run_id,
        name=name,
        created_at=datetime.now().isoformat(timespec="seconds"),
        spec_hash=spec_hash(enriched),
        spec=enriched,
        run_dir=str(run_dir),
        code_version=code_version,
        library_versions=versions,
    )
    _write_json(run_dir / "spec.json", run_spec.to_dict())
    _write_text(run_dir / "README.md", render_run_spec(run_spec))
    return run_spec


def load_run_spec(project: str | Path, run_id: str) -> RunSpec:
    path = runs_root(project) / run_id / "spec.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RunSpec(
        run_id=str(payload["run_id"]),
        name=str(payload.get("name") or ""),
        created_at=str(payload.get("created_at") or ""),
        spec_hash=str(payload.get("spec_hash") or ""),
        spec=dict(payload.get("spec") or {}),
        run_dir=str(payload.get("run_dir") or path.parent),
        code_version=str(payload.get("code_version") or ""),
        library_versions={str(key): str(value) for key, value in dict(payload.get("library_versions") or {}).items()},
    )


def check_spec_lock(project: str | Path, run_id: str, current_spec: dict[str, Any] | None = None) -> SpecLockCheck:
    stored = load_run_spec(project, run_id)
    current = _normalize_spec(current_spec) if current_spec is not None else stored.spec
    if current_spec is not None:
        current = {
            **current,
            "code_version": stored.code_version,
            "library_versions": stored.library_versions,
        }
    current_hash = spec_hash(current)
    ok = current_hash == stored.spec_hash
    return SpecLockCheck(
        run_id=run_id,
        ok=ok,
        stored_hash=stored.spec_hash,
        current_hash=current_hash,
        reason="spec lock intact" if ok else "spec changed after lock; invalidate this run",
    )


def write_run_result(
    project: str | Path,
    run_id: str,
    *,
    result: dict[str, Any] | None = None,
    report: str = "",
    audit: dict[str, Any] | None = None,
    current_spec: dict[str, Any] | None = None,
) -> SpecLockCheck:
    lock = check_spec_lock(project, run_id, current_spec=current_spec)
    if not lock.ok:
        _write_json(runs_root(project) / run_id / "stale.json", lock.to_dict())
        return lock
    run_dir = runs_root(project) / run_id
    if result is not None:
        _write_json(run_dir / "result.json", result)
    if audit is not None:
        _write_json(run_dir / "audit.json", audit)
    if report:
        _write_text(run_dir / "report.md", report.rstrip() + "\n")
    return lock


def render_run_spec(run_spec: RunSpec) -> str:
    return "\n".join(
        [
            f"# Run {run_spec.run_id}",
            "",
            f"- name: {run_spec.name}",
            f"- created_at: {run_spec.created_at}",
            f"- spec_hash: {run_spec.spec_hash}",
            f"- code_version: {run_spec.code_version or '-'}",
            f"- run_dir: {run_spec.run_dir}",
            "",
            "## Spec",
            "",
            "```json",
            json.dumps(run_spec.spec, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    ) + "\n"


def _normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("run spec must be an object")
    return json.loads(_stable_json(spec))


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _default_library_versions() -> dict[str, str]:
    return {"python": platform.python_version()}
