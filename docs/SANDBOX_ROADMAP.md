# QuantAgent Sandbox Roadmap

Internal legacy QuantAgent roadmap. This is not the current public v0.1 capability claim; the current public proof is the focused learning-effect gate linked from README.md and issue #1.

This roadmap adapts sandbox and tool-policy separation concepts from OpenClaw
under its MIT license. QuantAgent keeps the implementation project-native; this
file is an architectural plan, not copied runtime code.

## Current State

QuantAgent already has useful policy guardrails:

- `quantagent/safety.py` classifies shell commands, write targets, raw/tick data
  mutation, account/funds language, and quant claim hazards.
- `quantagent/sandbox_policy.py` defines `off`, `project`, and `strict`
  allow/ask/deny profiles.
- `quantagent/file_ops.py` resolves paths inside the project before read,
  search, write, diff, or exact replace.
- `quantagent/tool_loop.py` treats model output as planning text and grounds
  answers in tool observations.
- `quantagent/desktop_control.py` exposes local screenshot/window/input tools.

The gap is that these are policy checks, not a hard sandbox. A shell command
that is allowed still runs on the host. Desktop input still acts through the
operator's real UI. File writes still use the host filesystem.

## Design Split

QuantAgent should keep these controls independent:

1. Sandbox runtime: controls where execution happens.
   Examples: host, subprocess with restricted cwd/env, macOS sandbox-exec,
   container, VM.
2. Tool policy: controls which tools exist and whether they are allow, ask, or
   deny for a profile.
   Examples: `file_read`, `file_edit`, `shell`, `desktop.click`, `memory.add`.
3. Elevated execution: controls explicit host escape for commands that cannot
   run inside the sandbox.
   Examples: package installation, system probe, GUI automation helper compile.

This split prevents confusing statements such as "deny file_edit makes shell
read-only." It does not. If `shell` is available on the host, it can still write
unless a separate runtime or command guard prevents it.

## Phase 0: Documented Policy Baseline

Status: mostly done.

Actions:

- Keep `docs/SAFETY_POLICY.md` explicit that QuantAgent has policy guardrails,
  not an OS sandbox.
- Keep `docs/OPERATOR_TRUST_MODEL.md` as the source of truth for trusted
  operator assumptions.
- Ensure `docs/UPSTREAM_ATTRIBUTION.md` records OpenClaw MIT attribution.
- Keep `qagent sandbox --profile strict|project|off` useful for explaining
  allow/ask/deny.
- Add doctor checks that warn when no hard sandbox backend is configured.

## Phase 1: Tool Policy Enforcement Everywhere

Goal: every callable tool passes through one policy gate.

Actions:

- Give every tool a stable name, risk class, side-effect class, input schema,
  output schema, and observation summary.
- Apply profile checks before `agent`, `chat /agent`, task workers, file tools,
  desktop tools, and future plugin tools.
- Make `deny` always win.
- If a profile has an allowlist, hide unavailable tools from the model prompt.
- Add explicit `owner_only` metadata for desktop input, shell, experiment, P4,
  memory mutation, and broker-adjacent tools.
- Record policy decisions in agent observations and session artifacts.

Acceptance checks:

- `strict` mode cannot write files, run shell, type, click, or add memory.
- Unknown tools are ask or deny, never silently allowed.
- Model output cannot select a broader profile.

## Phase 2: Structured Tools Before Shell

Goal: reduce the amount of authority hidden inside shell strings.

Actions:

- Prefer `file_read`, `file_search`, `file_diff`, `file_replace`,
  `file_apply_patch`, `py_compile`, `pytest`, and `rg` structured tools.
- Treat user-facing shell as a last resort.
- For shell, require exact command text in the approval summary.
- Normalize command args and avoid `shell=True` for internal tools.
- Persist stdout/stderr summaries and large outputs to artifacts.

Acceptance checks:

- The agent can edit-test-retry common code paths without direct shell writes.
- Shell approvals show command, cwd, profile, sandbox backend, and expected side
  effects.
- Read-only shell commands remain allowed only when statically classified.

## Phase 3: Local Subprocess Sandbox

Goal: make command execution less coupled to the operator shell.

Actions:

- Run commands in a clean environment with a controlled cwd.
- Strip secrets and unrelated environment variables by default.
- Set timeout, output limit, and process group cleanup.
- Add read/write path policy before command launch.
- On macOS, investigate `sandbox-exec` profiles for read-only and
  project-write modes where available.
- On Linux, support namespace/seccomp/bubblewrap-style isolation when present.

Acceptance checks:

- A strict-profile command cannot write outside the allowed temp/output roots.
- Environment dumps do not expose unrelated secrets by default.
- Timeouts clean child processes.

## Phase 4: Container or VM Backend

Goal: provide a real isolation backend for risky code and unknown repos.

Actions:

- Add backend enum: `host`, `subprocess`, `macos_sandbox`, `container`, `vm`.
- Mount project read-only by default in strict mode.
- Mount `.quantagent` and selected output directories read-write only when
  profile permits.
- Mount raw/tick data read-only, even in project mode.
- Disable network by default for unknown code.
- Add an explicit network allowlist for data/vendor endpoints if needed.
- Do not mount Docker socket, browser profiles, password stores, SSH agents, or
  broker credentials into the sandbox by default.

Acceptance checks:

- `qagent sandbox explain --json` can show backend, profile, mounts, network,
  env exposure, and elevated gates.
- Container mode blocks writes outside mounted writable roots.
- Raw/tick mutation attempts fail at filesystem level, not only policy level.

## Phase 5: Elevated Execution

Goal: support necessary host actions without making host execution the default.

Actions:

- Add `elevated` as an exec-only escape hatch.
- Require owner approval for every elevated action unless a temporary
  break-glass window is active.
- Log reason, command, cwd, profile, duration, and artifacts.
- Never let model output enable elevated mode.
- Never let elevated override tool allow/deny policy.

Acceptance checks:

- A denied tool remains denied even in elevated mode.
- Elevated applies only to exec/shell, not arbitrary plugin or desktop tools.
- Break-glass mode expires automatically.

## Phase 6: Desktop Sandbox and UI Safety

Goal: make desktop automation fast while keeping visible control.

Actions:

- Split desktop tools into observation, planning, input, and sensitive input.
- Add app/window allowlists and deny broker/payment/password/cloud-console apps
  by default.
- Require a visible action summary before clicks, typing, hotkeys, or drags.
- Add OCR/accessibility-tree tools as observation-only in strict mode.
- Store screenshots and click plans as artifacts.
- Add coordinate-grid confirmation for high-impact actions.

Acceptance checks:

- `strict` can screenshot/OCR but cannot click/type/hotkey.
- `project` can plan clicks but asks before input.
- Sensitive apps require owner confirmation even in operator mode.

## Phase 7: Quant Evidence Sandbox

Goal: protect research credibility as a first-class safety surface.

Actions:

- Treat PF, slippage, capacity, and P4 conclusions as publish-gated claims.
- Store claim evidence references with report outputs.
- Require raw/tick provenance and hash records for derived data.
- Separate exploratory notebooks from publishable validation artifacts.
- Add a read-only evidence mode for final audit.

Acceptance checks:

- The agent cannot publish a PF/slippage/capacity claim without evidence
  context.
- Derived tick artifacts include source, hash, script/tool, and timestamp.
- Final reports can be regenerated from recorded artifacts.

## Doctor Scoring Targets

Suggested readiness scoring:

- 0-20: policy documents only
- 20-40: tool policy gates wired into CLI/chat/agent
- 40-60: structured file/edit/test tools reduce shell dependency
- 60-75: subprocess sandbox with env/time/output limits
- 75-90: container or OS sandbox with read-only project/raw-data mounts
- 90-100: elevated gates, desktop safety, network policy, evidence provenance,
  and reproducible audit logs

QuantAgent should not claim hard sandbox readiness above 60 until at least one
runtime backend enforces filesystem and environment isolation outside Python
policy code.
