# OpenMako Public Progress

This file is a public status boundary, not an internal scoreboard.

Current public proof:

- The public v0.1 claim is the focused learning-effect gate in `README.md`.
- Latest local send-ready check on 2026-06-05 passed:
  `./scripts/public_review_gate.sh` ended with `public-review-gate: PASS`;
  `bash scripts/wave1_send_ready.sh swe-agent` re-ran the gate and printed a
  non-promotional technical-boundary message with
  `Proof command: bash scripts/public_proof_card.sh`.
- Latest local learning/desktop regression check on 2026-06-07 passed:
  `python3 -m pytest -p no:cacheprovider tests/test_learning_effect.py
  tests/test_learning_effect_cli.py tests/test_learning_effect_e2e.py
  tests/test_extreme_learner.py tests/test_hermes_learning.py
  tests/test_skill_learning.py tests/test_skill_learning_effect_gate.py
  tests/test_agent_loop_core.py tests/test_agent_planner_contract.py
  tests/test_desktop_intelligence.py tests/test_desktop_learning.py
  tests/test_desktop_daemon_policy.py tests/test_coding_bench.py -q`
  ended with `259 passed, 1 warning`. The warning is a deprecated
  `run_agent_v2` call in a test. This is local regression evidence only, not
  external review, benchmark ranking, stars, or endorsement.
- Latest local high-intensity verification on 2026-06-07 passed after fixing
  full-suite regressions exposed by the run: the built-in CodingBench pack
  solved `30/30` tasks with the real OpenMako CLI agent, the external
  multimodule hidden regression file ended with `17 passed`, the full
  repository pytest command `python3 -m pytest -p no:cacheprovider -q` ended
  with `1680 passed, 1 skipped, 32 warnings`, `bash scripts/public_review_gate.sh`
  ended with `public-review-gate: PASS`, and
  `bash scripts/desktop_control_local_gate.sh` ended with
  `desktop-control-local-gate: PASS`. The desktop gate still reports
  `status=dry_run`, `scenarios=8`, and `level=L2`, so this is local
  regression evidence only, not live desktop-control proof, external review,
  benchmark ranking, stars, or endorsement.
- `bash scripts/despair_gate.sh` now wraps that high-intensity local loop into
  a repeatable gate. By default it runs the real-CLI CodingBench pack, the
  external multimodule regression file, full repository pytest, the public
  review gate, and the desktop local gate. Its skip and limit flags are for
  script smoke testing only; they do not create public proof.
- `.github/workflows/despair-gate.yml` exposes that gate as a manual
  `workflow_dispatch` check. It is intentionally not attached to default push
  or pull-request CI because it is slow and local-regression oriented, not a
  public endorsement signal. The workflow uploads CodingBench artifacts for
  debugging failed manual runs; those artifacts are not external review or
  endorsement evidence. The gate also writes
  `.quantagent/despair_gate/last_summary.json` as a local machine-readable
  run summary with the same non-proof boundary. Failed segments are also
  recorded in that summary with the failed segment and exit code so interrupted
  local gates do not look like successful or still-pending proof. Smoke-test
  calls can write to a separate summary path so full pytest does not overwrite
  the outer gate summary. The summary also records the invoking commit, argv,
  CodingBench elapsed seconds, and per-segment elapsed seconds for local
  debugging. The gate validates the summary before printing `PASS` so stale,
  pending, failed, or internally inconsistent summaries fail closed.
  CodingBench solved, total, success rate, artifact directory, and elapsed
  fields are also type-checked so missing upstream fields cannot pass as
  equality by accident. A corrupt-summary smoke path deletes those fields
  before validation and must fail closed. Failed summaries are validated after
  failure metadata is written for the same local artifact boundary.
- v0.1.0 is published at:
  `https://github.com/1966536805l-crypto/openmako/releases/tag/v0.1.0`.
- Public evidence is tracked in issue #1:
  `https://github.com/1966536805l-crypto/openmako/issues/1`.
- External technical boundary criticism is requested in issue #2:
  `https://github.com/1966536805l-crypto/openmako/issues/2`.
  This is a review request, not evidence of endorsement or promotion.
- Issue #2 was updated on 2026-06-05 after PR #4 merged into `main` at
  `f2659e1aa17a18b8ab015e1f6c1245425bb6d2ca`. The update keeps the same
  ask: point out README, release, or docs wording that sounds broader than the
  code and tests prove.
- A structured technical boundary issue form is available at:
  `.github/ISSUE_TEMPLATE/technical-boundary-check.yml`.
- A structured external review record form is available at:
  `.github/ISSUE_TEMPLATE/external-review-record.yml`. It is for already-public
  external technical reviews only, not private messages or self-written
  summaries.
- A technical reviewer packet is available at:
  `docs/TECHNICAL_REVIEW_PACKET.md`.
- A reproduction guide with exact local commands and expected public gate
  signals is available at: `docs/REPRODUCE_V0_1.md`.
- A non-promotional reviewer outreach draft is available at:
  `docs/REVIEWER_OUTREACH_DRAFT.md`.
- A public-source reviewer target map is available at:
  `docs/REVIEWER_TARGETS.md`. It separates technical-review targets from
  broader writer/community targets and forbids star, repost, promotion, or
  endorsement asks.
- A source-linked agent trend radar refreshed on 2026-06-05 is available at:
  `docs/AGENT_TREND_RADAR.md`. It maps Hermes/OpenClaw/OpenHands/eval trends to
  future OpenMako build bets, marks them as non-claims until code, fixtures,
  and CI exist, and points the next build target at an external run-record
  adapter matrix for supplied transcripts rather than the completed
  `run-metrics` extension.
- Wave 1 copyable review requests are available at:
  `docs/WAVE1_REVIEW_REQUESTS.md`. They target technical reviewers only and are
  not proof that outreach, review, endorsement, stars, or reposts happened.
- `docs/WAVE1_PUBLIC_TARGET_QUEUE.md` lists reachable public surfaces for the
  first technical-boundary review pass. It is a queue, not proof that messages
  were sent or that anyone reviewed the project.
- `docs/WAVE1_PUBLIC_TARGET_QUEUE.md` also lists existing public threads to
  inspect before posting. Those threads are reading candidates, not approved
  posting targets, outreach evidence, endorsement, stars, or reposts.
- `bash scripts/wave1_review_request.sh` prints the same Wave 1 short messages
  by target ecosystem without sending messages or recording outreach as evidence.
- `bash scripts/wave1_send_ready.sh` runs the public review gate before printing
  a target-specific Wave 1 short message. It still does not send messages or
  record outreach as evidence.
- `bash scripts/wave1_send_ready.sh --linkless TARGET` runs the same proof gate
  before printing a public-thread cold-start question without repo,
  proof-command, or review-issue links. This is for avoiding promotional-looking
  first comments in existing technical threads. It now prints a required
  `THREAD_HOOK` placeholder so the draft must be tied to a concrete thread point
  before posting. It is still send-ready text, not proof that outreach, review,
  endorsement, stars, or reposts happened.
- `agent-runtime` is now a send-ready Wave 1 target for reviewers already
  discussing skills, memory, ACP-style sessions, desktop control, or external
  harness orchestration. The message asks whether runtime-adjacent docs
  overread the current proof; it is not a launch note and not outreach evidence.
- `bash scripts/wave1_thread_reply_ready.sh` runs the public review gate before
  printing one thread-specific reply draft, target URL, and final-confirmation
  guard for selected public discussions. It now re-fetches the target page and
  checks expected topic markers before the proof gate, so stale or off-topic
  pages fail closed. It still does not send messages, create issues, or record
  outreach as evidence.
- The `openhands-benchmarks-718` thread draft was refreshed after re-checking
  the public issue page on 2026-06-05. It now discusses `output.jsonl` to
  `output.swtbench.jsonl` artifact identity and links only the concrete
  `swtbench_patch_artifact` fixture, not a homepage, star ask, or promotion
  request. This is send-ready text only, not proof of posting.
- The `openhands-benchmarks-718` draft was rechecked again with the live topic
  guard before sending: the page matched the expected artifact-identity markers
  and the public review gate passed. The printed reply is now a shorter
  artifact-identity question about eval rule version, runner commit/version,
  input/output hashes, and patch-shape metadata. It still requires final user
  confirmation before any public comment is submitted.
- The `openhands-benchmarks-708` thread draft was refreshed after re-checking
  the public issue page on 2026-06-05. It now discusses the `332 / 424` mixed
  test+source patch bucket, patch-shape metadata, and the concrete
  `swtbench_patch_artifact` fixture. This is send-ready text only, not proof
  of posting.
- The README exposes issue #2, the technical review packet, and focused CI as
  technical review entry points before the v0.1 scope section.
- The README now exposes a `60-Second Proof` section before the review links so
  visitors can run the public gate before reading longer docs.
- The README now includes a short `Why It Is Worth Checking` hook before the
  proof commands. It frames OpenMako as an inspectable-evidence harness and
  asks for concrete claim/proof mismatches, not promotion.
- The README now includes an `If You Came From A Benchmark Thread` path that
  tells external benchmark/eval readers to run the gate, inspect the
  `artifact_provenance` fixture for artifact-identity questions, compare README
  claims against the proof commands, and leave concrete mismatches on issue #2.
  It is a review path, not outreach evidence, endorsement, stars, or reposts.
- The technical review packet includes a minimal issue-comment template for
  boundary-clear, overclaim, or unclear findings.
- The technical review packet also links the supplied Codex/OpenHands/SWE-agent
  transcript adapter checks through `docs/evidence_court_schema.md`. This is a
  reviewer lookup path for repository-defined supplied formats only, not native
  exports, live control, benchmark ingestion, or endorsement.
- `scripts/public_review_gate.sh` wraps the local reviewer proof command:
  focused public tests, metadata boundary checks, and supplied-record
  Evidence Court bad-run audit. It parses Evidence Court audit JSON fields for
  `failure_class`, `failed_at`, `patch_shape.bucket`, and
  `artifact_provenance.eval_rule_version` instead of grepping raw output.
- The `run-metrics` evidence extension is on `main`: Evidence Court preserves
  optional duration, token, cost, command-count, and missing-telemetry fields
  as `run_metrics` in supplied records and audit JSON. Provider/model fields
  are also preserved when supplied. The fields are preserved in Evidence Court audit JSON.
  They improve comparability, but they are not treated as proof that validation
  ran.
- The `patch-shape` evidence extension is on `main`: Evidence Court derives a
  machine-readable `patch_shape` bucket from supplied `files_edited` evidence,
  including `mixed_test_source` for runs that edit both test-like and
  source-like files. This improves artifact comparability, but it does not
  prove a benchmark score should be higher or lower by itself.
- The `artifact-provenance` evidence extension is supported for supplied records:
  Evidence Court preserves supplied eval-rule identifiers, runner identifiers,
  artifact/input/output hashes, and missing-provenance markers as
  `artifact_provenance` in audit JSON and the Markdown report. This adds
  comparability metadata, but it does not mean OpenMako ingests native benchmark
  artifacts or validates benchmark scores.
- A public `artifact_provenance` fixture is available at
  `examples/evidence_court/artifact_provenance.json` and is now checked by
  `scripts/public_review_gate.sh`, so reviewers can reproduce the supplied
  artifact-identity boundary without relying on prose.
- A supplied SWTBench-style patch artifact fixture is available at
  `examples/evidence_court/swtbench_patch_artifact.json` and is checked by
  `scripts/public_review_gate.sh`. It combines `mixed_test_source` patch-shape
  metadata with `output.jsonl` to `output.swtbench.jsonl` artifact identity
  metadata for OpenHands/SWTBench-style comparability questions. It is still a
  supplied-record audit, not native benchmark ingestion or score validation.
- `openmako evidence-court record from-swtbench-artifacts` now builds the same
  supplied artifact-identity record from real `output.jsonl` and
  `output.swtbench.jsonl` paths, computing input/output SHA-256 hashes and
  preserving supplied rule/runner metadata plus patch-shape files. This is a
  reviewer-facing artifact comparability entrypoint; its machine JSON also
  records `benchmark_score_validated=false` and `runner_verified=false`. It is
  not native OpenHands or SWTBench ingestion, benchmark scoring, or external
  review evidence.
- A supplied Codex-style transcript adapter is available through
  `openmako evidence-court record from-codex-transcript`. It converts a
  repository-defined JSON transcript shape into an Evidence Court audit record
  with `source_format=codex-transcript/v0.1` and unsupported tool-call markers.
  It is not native Codex product log ingestion or live Codex control.
- A supplied Claude-style transcript adapter is available through
  `openmako evidence-court record from-claude-transcript`. It converts a
  repository-defined JSON transcript shape into an Evidence Court audit record
  with `source_format=claude-transcript/v0.1` and unsupported tool-call
  markers. It is not native Claude or Claude Code export parsing or live Claude
  control.
- A supplied OpenHands-style transcript adapter is available through
  `openmako evidence-court record from-openhands-transcript`. It converts a
  repository-defined JSON transcript shape into an Evidence Court audit record
  with `source_format=openhands-transcript/v0.1` and unsupported event markers.
  It is not native OpenHands export parsing or live OpenHands control.
- A supplied SWE-agent-style transcript adapter is available through
  `openmako evidence-court record from-swe-agent-transcript`. It converts a
  repository-defined JSON transcript shape into an Evidence Court audit record
  with `source_format=swe-agent-transcript/v0.1` and unsupported step markers.
  It is not native SWE-agent export parsing or live SWE-agent control.
- `scripts/supplied_transcript_adapter_matrix.sh` generates temporary
  repository-defined Codex, Claude, OpenHands, and SWE-agent style transcripts,
  converts each one into an Evidence Court record, audits each generated
  record, and now verifies that each adapter rejects a success claim when
  command/test proof is missing or when validation exists but edited-file
  evidence is missing. The script parses audit JSON fields instead of grepping
  raw output, so verdict and `failure_class` checks are tied to
  machine-readable fields. It is a supplied-format smoke test, not native
  product export parsing, live agent control, benchmark ingestion,
  diff-content proof, or endorsement.
- `scripts/public_proof_card.sh` wraps the same gate and prints a
  screenshot-friendly proof card with commit, scope, non-proof boundaries,
  review issue, and external-review record form.
- Internal desktop-control preflight now refreshes only the target source needed
  for fenced side-effect validation when possible, such as AX-only refresh for
  AX click targets. This reduces redundant perception work before reviewed
  control actions, but it is still an internal local hardening step, not a
  public live-control claim.
- Initial desktop-control decision observation now tries an AX-only no-screenshot
  path for deterministic click/type/hotkey intents, then falls back to the full
  screenshot/OCR/SoM observation when AX cannot resolve a click target. Focused
  tests assert both the fast hit path and the fallback path. This is local
  call-path evidence, not a live latency benchmark or public L4/L5 claim.
- Desktop L4 soak live preflight now refreshes fenced targets before
  click/type-style actions. AX targets use the AX-only fast path, and stale
  target hashes block execution. Scope: local safety guard only, with no public
  live-control, L4, or L5 claim.
- Internal desktop-control verification now uses the same source-scoped refresh
  path where safe: AX targets verify with AX-only evidence, typed text verifies
  with AX+OCR, and global hotkeys can use screenshot capture without rebuilding
  SoM. The regression test now asserts the AX click verification path skips
  OCR/SoM; this is narrower local work, not a benchmarked live-control speed
  claim.
- Text actions that pass the local review gates now bind to the focused AX
  text/search target when that target is visible, carrying `target_id`,
  `target_hash`, and `observation_id` into the action. This lets the daemon
  execute focused input through AX-only preflight instead of producing an
  unfenced type action that is blocked before execution. It remains local
  bounded control hardening, not live desktop-control proof.
- AX-only target preflight can now skip the screenshot step when no visual
  sources are requested. This makes the stale-target check for AX click/type
  fences lighter while leaving typed-text verification on its normal
  AX+OCR capture/source path. The focused regression test asserts that the fast AX-only
  tokenization path does not call screenshot capture. This is local hardening,
  not a live speed benchmark or public L4/L5 desktop-control proof.
- AX click/move post-action verification now uses the same AX-only no-screenshot
  refresh when the original target was an AX token, reducing one redundant
  screenshot capture in the focused daemon path. Verification now also fails if
  the fresh AX check uses cached AX fallback tokens, so the fast path does
  not treat stale accessibility state as proof. This is local call-count
  evidence, not a live latency benchmark or external desktop-control claim.
- Focused AX text input verification now checks the original AX target first,
  without taking another screenshot. If that target's fresh AX state shows the
  typed text, verification passes on the fast path. If not, it falls back to OCR
  and keeps the stricter check. Regression tests cover the no-OCR fast path, OCR
  fallback, and the case where matching text appears only on a different AX
  token. This is local call-path evidence, not a live latency benchmark or public
  L4/L5 desktop-control proof.
- Focused AX text input fallback now avoids a second AX snapshot after the
  AX-only fast check already failed to show the typed text. The fallback goes
  straight to OCR verification and keeps the original target-scoped AX result
  in `fast_type_verify`, so the daemon does less repeated AX work without
  treating unrelated AX text as target proof. This is local call-path evidence,
  not a live speed benchmark or public L4/L5 desktop-control proof.
- Focused AX text-field hotkeys now carry the same `target_id`, `target_hash`,
  and `observation_id` fence for single-key `return`, `enter`, and `tab`
  actions. The daemon can verify AX-visible focus/value changes without a
  screenshot first, then fall back to the normal verification path if AX does
  not show progress. This is local call-path hardening, not a live speed
  benchmark or public L4/L5 desktop-control proof.
- Screenshot failure diagnostics now support the
  `OPENMAKO_DESKTOP_FAST_DIAGNOSTICS=1` local fast path, which skips the slower
  display probe while still returning front-app/window/console context and a
  conservative permission hint. This speeds local diagnosis only; it is not
  live desktop-control proof or a public L4/L5 claim.
- `scripts/desktop_control_local_gate.sh` provides a bounded local desktop
  control gate: it runs focused desktop intelligence/policy tests and a
  `suite_l4` dry-run eval, then checks that the result remains conservative
  rather than claiming live L4/L5 desktop control. The gate also verifies that
  every scenario remains in `suite_l4` dry-run mode with execution disabled.
- `scripts/desktop_control_proof_card.sh` wraps the same bounded local desktop
  control gate into a screenshot-friendly proof card. It prints the commit,
  proof command, local scope, recent fast-path evidence, and explicit
  `not-proof` boundary for live control, L4/L5, endorsement, stars, or reposts.
- The README and technical review packet now expose that desktop-control local
  gate only under optional non-v0.1 inspection paths. They keep the expected
  `status=dry_run`, `scenarios=8`, and `level=L2` boundary visible so reviewers
  do not confuse it with live L4/L5 autonomy proof.
- `docs/PUBLIC_SHARE_PACKET.md` provides boundary-preserving public wording for
  reviewers who independently choose to discuss the project.
- `bash scripts/public_share_ready.sh review-request` now runs the public proof
  gate before printing the short public review-request text. It does not post,
  ask for stars or reposts, or record outreach as evidence.
- `docs/openmako-review-card.svg` is an optional visual summary for the public
  gate and issue #2 boundary review. It is not evidence of external review,
  endorsement, stars, or reposts.
- `docs/PUBLIC_SHARE_PACKET.md` also includes a <=280 character technical
  review post and a boundary-clear follow-up that must not be used before a
  named reviewer gives public feedback.
- `docs/LARGE_REPOST_PACKET.md` defines the second-stage broader share packet
  for writer/community surfaces, and `bash scripts/large_repost_ready.sh
  REVIEW_RECORD_ISSUE_URL --confirm-external-review` refuses to print it unless
  a public external-review record issue URL is supplied, a human confirms the
  linked public review was written by a named external reviewer, the issue page
  contains structured review record fields plus the required boundary checkbox
  text, and the public proof gate passes.
  This is a readiness check after external review, not proof of reposts, stars,
  or endorsement.
- `docs/REVIEWER_OUTREACH_DRAFT.md` defines who to contact first and blocks
  general-influencer outreach until at least one public technical boundary
  review exists.
- GitHub Actions runs the same `scripts/public_review_gate.sh` command through
  `.github/workflows/focused.yml`, so the focused badge covers the README's
  public proof command instead of a separate pytest-only subset.
- GitHub Actions also runs the supplied-record Evidence Court demo through
  `.github/workflows/evidence-court-demo.yml`.

Do not use stale internal notes, local-only benchmark counts, old full-suite
logs, or agent-written summaries as public capability claims.

Public launch claims require current code, a reproducible command, and a linked
public result.

Next smallest hygiene task:

- Pick one relevant public benchmark/eval thread from
  `docs/WAVE1_PUBLIC_TARGET_QUEUE.md`, re-check that the thread is still
  on-topic, and prepare a short technical-boundary reply only after a 5-agent
  AI-like/promotional-risk review.
