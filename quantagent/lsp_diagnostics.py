from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterable
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url


@dataclass(frozen=True)
class LspServerConfig:
    name: str
    command: tuple[str, ...]
    language_id: str
    file_extensions: tuple[str, ...] = field(default_factory=tuple)
    initialization_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LspDiagnostic:
    uri: str
    path: str
    severity: int | None
    message: str
    source: str
    code: str
    line: int | None
    character: int | None
    end_line: int | None = None
    end_character: int | None = None


@dataclass(frozen=True)
class LspServerStatus:
    name: str
    command: tuple[str, ...]
    available: bool
    executable: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class LspSnapshot:
    snapshot_id: str
    generated_at_ms: int
    project: str
    server: str
    status: LspServerStatus
    diagnostics: tuple[LspDiagnostic, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = [asdict(item) for item in self.diagnostics]
        payload["status"] = asdict(self.status)
        return payload


def lsp_cache_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "lsp" / "diagnostics.json"


def path_to_uri(path: str | Path) -> str:
    return "file://" + pathname2url(str(Path(path).expanduser().resolve(strict=False)))


def uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    return unquote(parsed.path)


def default_lsp_server_configs() -> tuple[LspServerConfig, ...]:
    return (
        LspServerConfig(
            name="pyright",
            command=("pyright-langserver", "--stdio"),
            language_id="python",
            file_extensions=(".py", ".pyi"),
        ),
        LspServerConfig(
            name="ruff",
            command=("ruff", "server"),
            language_id="python",
            file_extensions=(".py", ".pyi"),
        ),
        LspServerConfig(
            name="typescript",
            command=("typescript-language-server", "--stdio"),
            language_id="typescript",
            file_extensions=(".ts", ".tsx", ".js", ".jsx"),
        ),
    )


def detect_default_lsp_servers() -> tuple[LspServerStatus, ...]:
    return tuple(lsp_server_status(config) for config in default_lsp_server_configs())


def lsp_server_status(config: LspServerConfig) -> LspServerStatus:
    if not config.command:
        return LspServerStatus(name=config.name, command=(), available=False, reason="empty command")
    executable = shutil.which(config.command[0])
    if executable:
        return LspServerStatus(
            name=config.name,
            command=config.command,
            available=True,
            executable=executable,
            reason="available",
        )
    return LspServerStatus(
        name=config.name,
        command=config.command,
        available=False,
        reason=f"missing executable: {config.command[0]}",
    )


def best_default_lsp_config(project: str | Path, paths: Iterable[str | Path] = ()) -> LspServerConfig | None:
    candidates = default_lsp_server_configs()
    suffixes = {Path(path).suffix for path in paths}
    if suffixes:
        candidates = tuple(
            config for config in candidates if not config.file_extensions or suffixes.intersection(config.file_extensions)
        )
    for config in candidates:
        if lsp_server_status(config).available:
            return config
    return None


class LspJsonRpcClient:
    def __init__(self, command: tuple[str, ...] | list[str], *, cwd: str | Path | None = None) -> None:
        self.command = tuple(command)
        self.cwd = Path(cwd).expanduser().resolve(strict=False) if cwd is not None else None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._next_id = 1

    def __enter__(self) -> "LspJsonRpcClient":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            list(self.command),
            cwd=str(self.cwd) if self.cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self._process.stdout is not None
        self._reader = threading.Thread(target=self._read_loop, args=(self._process.stdout,), daemon=True)
        self._reader.start()

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        for handle in (process.stdin, process.stdout, process.stderr):
            if handle is not None and not handle.closed:
                handle.close()
        self._process = None

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        message_id = self._next_id
        self._next_id += 1
        self.notify_raw({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    message = self._get_message(deadline)
                except queue.Empty:
                    break
                if message.get("id") == message_id:
                    if "error" in message:
                        raise RuntimeError(f"LSP request {method} failed: {message['error']}")
                    return message.get("result")
                deferred.append(message)
            raise TimeoutError(f"timed out waiting for LSP response to {method}")
        finally:
            for item in deferred:
                self._messages.put(item)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.notify_raw({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def notify_raw(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("LSP client is not started")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + body)
        process.stdin.flush()

    def wait_for_diagnostics(
        self,
        wanted_uris: set[str],
        *,
        timeout: float = 5.0,
    ) -> dict[str, list[dict[str, Any]]]:
        diagnostics: dict[str, list[dict[str, Any]]] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self._get_message(deadline)
            except queue.Empty:
                break
            if message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params") or {}
                uri = str(params.get("uri") or "")
                diagnostics[uri] = list(params.get("diagnostics") or [])
                if wanted_uris and wanted_uris.issubset(diagnostics):
                    break
        return diagnostics

    def _get_message(self, deadline: float) -> dict[str, Any]:
        remaining = max(0.0, deadline - time.monotonic())
        return self._messages.get(timeout=remaining)

    def _read_loop(self, stream: BinaryIO) -> None:
        while True:
            try:
                message = _read_lsp_message(stream)
            except Exception as exc:
                audit_suppressed_exception(f"{__name__}:248", exc)
                return
            if message is None:
                return
            self._messages.put(message)


def _read_lsp_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii", errors="replace").partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def run_lsp_diagnostics(
    project: str | Path,
    paths: Iterable[str | Path],
    *,
    config: LspServerConfig | None = None,
    timeout: float = 5.0,
    cache: bool = True,
) -> LspSnapshot:
    project_path = Path(project).expanduser().resolve(strict=False)
    path_list = [Path(path).expanduser().resolve(strict=False) for path in paths]
    chosen = config or best_default_lsp_config(project_path, path_list)
    if chosen is None:
        status = LspServerStatus(name="default", command=(), available=False, reason="no available default LSP server")
        snapshot = _snapshot(project_path, "default", status, ())
        if cache:
            write_lsp_snapshot(snapshot)
        return snapshot

    status = lsp_server_status(chosen)
    if not status.available:
        snapshot = _snapshot(project_path, chosen.name, status, ())
        if cache:
            write_lsp_snapshot(snapshot)
        return snapshot

    uri_text = [(path_to_uri(path), path.read_text(encoding="utf-8")) for path in path_list]
    diagnostics: dict[str, list[dict[str, Any]]] = {}
    with LspJsonRpcClient(chosen.command, cwd=project_path) as client:
        client.request(
            "initialize",
            {
                "processId": None,
                "rootUri": path_to_uri(project_path),
                "capabilities": {},
                "initializationOptions": chosen.initialization_options,
            },
            timeout=timeout,
        )
        client.notify("initialized", {})
        for index, (uri, text) in enumerate(uri_text, start=1):
            text_document = {"uri": uri, "languageId": chosen.language_id, "version": index, "text": text}
            client.notify("textDocument/didOpen", {"textDocument": text_document})
            client.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": index + 100},
                    "contentChanges": [{"text": text}],
                },
            )
        diagnostics = client.wait_for_diagnostics({uri for uri, _ in uri_text}, timeout=timeout)
        try:
            client.request("shutdown", {}, timeout=timeout)
        finally:
            client.notify("exit", {})

    snapshot = _snapshot(project_path, chosen.name, status, _convert_diagnostics(diagnostics))
    if cache:
        write_lsp_snapshot(snapshot)
    return snapshot


def write_lsp_snapshot(snapshot: LspSnapshot) -> Path:
    path = lsp_cache_path(snapshot.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_lsp_json(snapshot), encoding="utf-8")
    return path


def load_lsp_snapshot(project: str | Path) -> LspSnapshot:
    payload = json.loads(lsp_cache_path(project).read_text(encoding="utf-8"))
    status_payload = payload.get("status") or {}
    diagnostics_payload = payload.get("diagnostics") or []
    status = LspServerStatus(
        name=str(status_payload.get("name") or payload.get("server") or ""),
        command=tuple(status_payload.get("command") or ()),
        available=bool(status_payload.get("available")),
        executable=status_payload.get("executable"),
        reason=str(status_payload.get("reason") or ""),
    )
    diagnostics = tuple(_diagnostic_from_payload(item) for item in diagnostics_payload if isinstance(item, dict))
    return LspSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or ""),
        generated_at_ms=int(payload.get("generated_at_ms") or 0),
        project=str(payload.get("project") or project),
        server=str(payload.get("server") or status.name),
        status=status,
        diagnostics=diagnostics,
    )


def render_lsp_json(snapshot: LspSnapshot) -> str:
    return json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_lsp_markdown(snapshot: LspSnapshot) -> str:
    lines = [
        "# LSP Diagnostics",
        "",
        f"- snapshot_id: {snapshot.snapshot_id}",
        f"- project: {snapshot.project}",
        f"- server: {snapshot.server}",
        f"- status: {'available' if snapshot.status.available else 'unavailable'}",
        f"- diagnostics: {len(snapshot.diagnostics)}",
        "",
    ]
    if snapshot.status.reason:
        lines.append(f"Status detail: {snapshot.status.reason}")
        lines.append("")
    if not snapshot.diagnostics:
        lines.append("No diagnostics.")
        return "\n".join(lines) + "\n"
    for item in snapshot.diagnostics:
        location = item.path
        if item.line is not None:
            location += f":{item.line}"
            if item.character is not None:
                location += f":{item.character}"
        code = f" {item.code}" if item.code else ""
        source = item.source or snapshot.server
        lines.append(f"- [{_severity_name(item.severity)}] {source}{code} {location}: {item.message}")
    return "\n".join(lines) + "\n"


def _snapshot(
    project: Path,
    server: str,
    status: LspServerStatus,
    diagnostics: Iterable[LspDiagnostic],
) -> LspSnapshot:
    generated = int(time.time() * 1000)
    return LspSnapshot(
        snapshot_id=f"lsp-{generated}",
        generated_at_ms=generated,
        project=str(project),
        server=server,
        status=status,
        diagnostics=tuple(diagnostics),
    )


def _convert_diagnostics(raw: dict[str, list[dict[str, Any]]]) -> tuple[LspDiagnostic, ...]:
    converted: list[LspDiagnostic] = []
    for uri, diagnostics in sorted(raw.items()):
        for item in diagnostics:
            range_payload = item.get("range") or {}
            start = range_payload.get("start") or {}
            end = range_payload.get("end") or {}
            code = item.get("code")
            converted.append(
                LspDiagnostic(
                    uri=uri,
                    path=uri_to_path(uri),
                    severity=item.get("severity"),
                    message=str(item.get("message") or ""),
                    source=str(item.get("source") or ""),
                    code="" if code is None else str(code),
                    line=_lsp_number_to_one_based(start.get("line")),
                    character=_lsp_number_to_one_based(start.get("character")),
                    end_line=_lsp_number_to_one_based(end.get("line")),
                    end_character=_lsp_number_to_one_based(end.get("character")),
                )
            )
    return tuple(converted)


def _diagnostic_from_payload(payload: dict[str, Any]) -> LspDiagnostic:
    return LspDiagnostic(
        uri=str(payload.get("uri") or ""),
        path=str(payload.get("path") or ""),
        severity=payload.get("severity"),
        message=str(payload.get("message") or ""),
        source=str(payload.get("source") or ""),
        code=str(payload.get("code") or ""),
        line=payload.get("line"),
        character=payload.get("character"),
        end_line=payload.get("end_line"),
        end_character=payload.get("end_character"),
    )


def _lsp_number_to_one_based(value: Any) -> int | None:
    if isinstance(value, int):
        return value + 1
    return None


def _severity_name(severity: int | None) -> str:
    return {1: "error", 2: "warning", 3: "info", 4: "hint"}.get(severity, "unknown")
