# OpenMako Public Progress

This file is a public status boundary, not an internal scoreboard.

Current public proof:

- The public v0.1 proof command is `./scripts/public_review_gate.sh`; `README.md`
  defines the narrower claim and non-proof boundaries.
- Remote focused CI is live GitHub state, not a durable fact in this file.
  A 2026-06-07 GitHub API snapshot showed `.github/workflows/focused.yml`
  run `27096660497` completed with `conclusion=success` on commit
  `665a12912822218f81442598ece268175f30f1c3` before this note was added.
  A 2026-06-08 re-check showed focused workflow run `27098553051`
  completed with `conclusion=success` on commit
  `322b1d8446bad309bfb960f5a3e8c976c3a02772`.
  A 2026-06-08 reset-window re-check showed focused workflow run
  `27116209971` completed with `conclusion=success` on commit
  `a32b5b29dd0fe231d2507a3e229c58c233d15db0`.
  A 2026-06-08 re-check showed focused workflow run `27116813508`
  completed with `conclusion=success` on commit
  `a12389ba48867238218dcb704a42b80f5d7bf507`.
  A 2026-06-08 reset-window re-check showed focused workflow run
  `27116934854` completed with `conclusion=success` on commit
  `e7f1e0d52c858864aed91dc3b67f04fd1016480f`.
  A 2026-06-08 reset-window re-check showed focused workflow run
  `27118350388` completed with `conclusion=success` on commit
  `e53f97374942ea1c3316b04992950b915bd3787b`.
  A 2026-06-08 reset-window re-check showed focused workflow run
  `27120585985` completed with `conclusion=success` on commit
  `d8e32e99cf6cd18d2a56cc83520ef65d832a5868`.
  Re-check the latest `openmako/main` run before claiming current remote CI;
  the snapshot is not external review, endorsement, stars, or reposts.
- `bash scripts/remote_focused_ci_snapshot.sh` is the fail-closed re-check tool
  for the latest focused workflow on current `openmako/main`. It prints
  `not-proof=external review; endorsement; stars; reposts` and returns nonzero
  if the latest focused run is stale, still running, failed, missing, or rate
  limited. It supports `OPENMAKO_GITHUB_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`
  for authenticated GitHub API checks to reduce rate-limit failures; tokens are
  not printed. When API data is unavailable, it still prints the remote main SHA,
  manual Actions URL, local UTC check time, rate-limit reset countdown, and a
  copyable rerun command when available before exiting nonzero. If GitHub
  includes retry/rate-limit reset headers, the script prints those too,
  including a UTC rendering of the reset timestamp when it is parseable.
  Passing this script is current
  focused-CI evidence only, not external review or traction.
- The README evidence-link table now documents the snapshot token fallbacks and
  rate-limit fallback, so users know a nonzero API-unavailable result can still
  include the remote SHA, local UTC check time, manual Actions URL, rate-limit
  reset countdown, and a copyable rerun command when available.
- GitHub workflow artifact upload steps now use `actions/upload-artifact@v7`
  in the manual despair gate, Evidence Court demo workflow, and the documented
  Evidence Court example. This is CI hygiene for Node 24 action compatibility,
  not evidence of external review, endorsement, stars, or reposts.
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
- Wave 1 copyable requests and `docs/openmako-review-card.svg` now describe
  the current public proof as supplied-record/provenance audits plus a supplied
  transcript adapter matrix, instead of the older supplied-record-audit-only
  shorthand. This is outreach text alignment, not proof that outreach or
  external review happened.
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
- Evidence Court now routes successful repair claims with passing validation
  but no source-like edited-file evidence to `SUSPICIOUS` as
  `missing_source_edit_evidence`. This is supplied-record review metadata, not
  proof that the repair is invalid.
- Evidence Court now separates config-like edited-file evidence from generic
  `other_only` patch shape, so supplied config-only repair records can avoid
  `missing_source_edit_evidence` while README-only repair claims remain
  suspicious.
- A public config-only repair fixture is available at
  `examples/evidence_court/config_only_repair.json` and is checked by
  `scripts/public_review_gate.sh`, so reviewers can reproduce that false-positive
  boundary without reading unit tests.
- The README benchmark-thread path and technical review packet now point to the
  config-only repair fixture, so reviewers can find the boundary without reading
  the gate script.
- `docs/REPRODUCE_V0_1.md` now includes the config-only repair fixture in its
  expected public-gate signal, coverage list, and smaller-check command.
- The `artifact-provenance` evidence extension is supported for supplied records:
  Evidence Court preserves supplied eval-rule identifiers, runner identifiers,
  artifact/input/output hashes, and missing-provenance markers as
  `artifact_provenance` in audit JSON and the Markdown report. This adds
  comparability metadata, but it does not mean OpenMako ingests native benchmark
  artifacts or validates benchmark scores.
- The `verifier-tamper-risk` evidence extension is supported for supplied records:
  Evidence Court flags successful repair claims that edit verifier, oracle,
  harness, CI, or test-only paths as `SUSPICIOUS` review items. A public fixture
  checks the verifier/harness path branch; this is supplied-record risk metadata,
  not proof of malicious intent or native benchmark enforcement.
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
  It now also fails closed if the roadmap-style count/rate metrics are missing
  from the dry-run output or if `level_reasons` hides a missing safety rate.
- `desktop-eval` metrics now expose the roadmap-style count fields and explicit
  `misoperation_rate`, `crash_rate`, `total_actions`, and missing-autopsy
  counters so dry-run scoring does not hide missing safety rates. This improves
  local eval auditability only; it is not a live desktop-control benchmark or a
  public L4/L5 claim.
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
- `docs/PUBLIC_SHARE_PACKET.md` now describes the public share scope as
  supplied-record/provenance audits plus supplied transcript adapter checks,
  rather than supplied-record audits only. This keeps short public text aligned
  with the current gate output without claiming external review or traction.
- The v0.1 draft release notes, changelog draft, and release checklist now use
  the same supplied-record/provenance plus supplied transcript fixture boundary.
  They still exclude native Claude/Codex/Cursor/SWE-bench export ingestion and
  are not proof that a new release was tagged.
- The clean-room/source-copy planning docs now point their public-proof
  disclaimer at `./scripts/public_review_gate.sh` instead of the older issue #1
  shorthand. This keeps internal planning boundaries tied to a reproducible
  command, not a claim that those plans are current v0.1 capability.
- `bash scripts/public_share_ready.sh review-request` now runs the public proof
  gate before printing the short public review-request text. It does not post,
  ask for stars or reposts, or record outreach as evidence.
- `docs/openmako-review-card.svg` is an optional visual summary for the public
  gate and issue #2 boundary review. It is not evidence of external review,
  endorsement, stars, or reposts.
- `docs/PUBLIC_SHARE_PACKET.md` also includes a <=280 character technical
  review post and a boundary-clear follow-up that must not be used before a
  named reviewer gives public feedback.
- `scripts/public_proof_card.sh` now prints the full current public gate scope
  in its final screenshot-friendly block: focused learning-effect, metadata
  boundary, supplied Evidence Court audit, artifact provenance, SWTBench patch
  artifact, config-only repair fixture, and supplied transcript adapter matrix.
  This is proof-card wording alignment, not new capability proof or outreach
  evidence.
- `docs/WAVE1_REVIEW_REQUESTS.md` now mirrors the same proof-card scope and
  includes the config-only false-positive fixture in its current-public-proof
  wording. This keeps copyable review requests aligned with the gate output; it
  is not evidence that outreach happened.
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
- The README install/reproduce path now names every current public gate
  subcheck: focused tests, metadata boundary tests, the supplied bad-run audit,
  artifact provenance, SWTBench patch-artifact provenance, and the supplied
  transcript adapter matrix. Metadata tests lock this wording against the gate
  output. This is documentation/proof-surface alignment, not new capability
  proof.
- A supplied Codex transcript regression now covers mixed source+test
  `diff_hunks`: the converted record preserves both hunks, audit JSON reports
  `patch_shape.bucket=mixed_test_source`, and verifier tamper risk remains
  false. A 2026-06-08 local re-check passed the focused transcript tests,
  supplied transcript adapter matrix, `git diff --check`, and
  `bash scripts/public_review_gate.sh`. This is local supplied-record evidence
  only, not native transcript ingestion, remote CI status, external review,
  endorsement, stars, or reposts.
- A supplied OpenHands transcript regression now covers the same mixed
  source+test diff-shape boundary using `diff` and `unified_diff` event
  fields. The local focused tests, supplied transcript adapter matrix,
  `git diff --check`, and `bash scripts/public_review_gate.sh` passed on
  2026-06-08. This is local supplied-record evidence only, not native
  OpenHands export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- A supplied SWE-agent transcript regression now covers the same mixed
  source+test diff-shape boundary using `patch` and `diff_hunks` step fields.
  The local focused tests, supplied transcript adapter matrix,
  `git diff --check`, and `bash scripts/public_review_gate.sh` passed on
  2026-06-08. This is local supplied-record evidence only, not native
  SWE-agent export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- A supplied Claude transcript regression now covers the same mixed source+test
  diff-shape boundary using `diff` and `patch` tool-use input fields. The local
  focused tests, supplied transcript adapter matrix, `git diff --check`, and
  `bash scripts/public_review_gate.sh` passed on 2026-06-08. This completes the
  mixed source+test diff-shape regression set for the repository-defined
  Codex, Claude, OpenHands, and SWE-agent supplied transcript formats. It is
  local supplied-record evidence only, not native export ingestion, remote CI
  status, external review, endorsement, stars, or reposts.
- A supplied Codex transcript duplicate-diff regression now proves repeated
  diff hunks are deduplicated while distinct source and test hunks are retained
  in record output. The local focused tests, supplied transcript adapter
  matrix, `git diff --check`, and `bash scripts/public_review_gate.sh` passed
  on 2026-06-08. This is local supplied-record evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- A supplied OpenHands transcript duplicate-diff regression now proves the same
  dedupe boundary for non-Codex supplied events: repeated source hunks from
  `diff_hunks` and `diff` collapse to one entry while a distinct test hunk is
  retained. The local focused tests, supplied transcript adapter matrix,
  `git diff --check`, and `bash scripts/public_review_gate.sh` passed on
  2026-06-08. This is local supplied-record evidence only, not native
  OpenHands export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Supplied Claude and SWE-agent transcript duplicate-diff regressions now
  cover the same dedupe boundary: repeated source hunks from mixed diff fields
  collapse to one entry while a distinct test hunk is retained and the audit
  remains `mixed_test_source` without verifier-tamper risk. The local focused
  transcript tests, public metadata test, supplied transcript adapter matrix,
  `git diff --check`, and `bash scripts/public_review_gate.sh` passed on
  2026-06-08. This is supplied-record evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- The README and reproduction guide now align the public-proof wording with the
  supplied transcript diff-content boundary: the adapter matrix is described as
  rejecting missing-test-proof, missing edited-file evidence, and missing
  diff-content evidence success claims, while still not proving native export
  ingestion or that supplied patches were applied outside the supplied record.
  The local public metadata test passed on 2026-06-08 before this note was
  added; this is documentation/proof-surface alignment only, not new external
  review, endorsement, stars, or reposts.
- `docs/AGENT_TREND_RADAR.md` now treats supplied diff-content handling,
  mixed source/test diff-shape coverage, and duplicate diff-hunk handling as
  completed `main` work, then points the next build target at adapter evidence
  edge-case hardening. This is planning alignment only, not proof of native
  export ingestion, live harness control, remote CI status, external review,
  endorsement, stars, or reposts.
- A supplied transcript adapter malformed-diff regression now covers Codex,
  Claude, OpenHands, and SWE-agent supplied formats: non-array `diff_hunks` and
  non-string entries are rejected by the CLI instead of being silently treated
  as absent diff evidence. The local focused transcript tests and public
  metadata tests passed on 2026-06-08 before this note was added. This is local
  supplied-record validation evidence only, not native export ingestion, remote
  CI status, external review, endorsement, stars, or reposts.
- A supplied transcript adapter empty-diff regression now covers Codex, Claude,
  OpenHands, and SWE-agent supplied formats: blank `diff_hunks` entries and
  blank `diff`/`patch`/`unified_diff` strings are ignored as empty content, so
  successful source repair claims still audit as `missing_diff_content_evidence`
  instead of treating whitespace as supplied diff proof. The local empty-diff
  focused test, transcript-focused tests, public metadata tests, and
  `git diff --check` passed on 2026-06-08 before this note was finalized. This
  is local supplied-record validation evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- A supplied transcript adapter failed-test regression now covers Codex,
  Claude, OpenHands, and SWE-agent supplied formats: even with source edit and
  diff-content evidence present, a nonzero validation command with failing test
  output audits as `post_edit_validation_failure` at `test_output`, not as a
  successful repair. The local failed-test focused test, transcript-focused
  tests, and public metadata tests passed on 2026-06-08 before this note was
  added. This is local supplied-record validation evidence only, not native
  export ingestion, remote CI status, external review, endorsement, stars, or
  reposts.
- A supplied transcript adapter unsupported-edit regression now covers Codex,
  Claude, OpenHands, and SWE-agent supplied formats: edit-like but unsupported
  `replace` events that carry paths and diff hunks are recorded in
  `adapter_report.unsupported` and do not count as edited-file or diff-content
  evidence. The audit remains `missing_edited_file_evidence` for a successful
  source repair claim. The local unsupported-edit focused test,
  transcript-focused tests, public metadata tests, and `git diff --check`
  passed on 2026-06-08 before this note was added. This is local supplied-record
  validation evidence only, not native export ingestion, remote CI status,
  external review, endorsement, stars, or reposts.
- A supplied transcript adapter missing-final-claim regression now covers Codex,
  Claude, OpenHands, and SWE-agent supplied formats: source edits,
  diff-content evidence, and passing validation without a final success claim
  audit as `missing_final_claim_evidence` at `final_claim`, keeping process
  evidence separate from a completed source repair assertion. The local
  final-claim focused test, transcript-focused tests, public metadata tests,
  supplied transcript adapter matrix, and `git diff --check` passed on
  2026-06-09 before this note was added. This is local supplied-record
  validation evidence only, not native export ingestion, remote CI status,
  external review, endorsement, stars, or reposts.
- A supplied transcript adapter missing-command regression now covers Codex,
  Claude, OpenHands, and SWE-agent supplied formats: command/run/test events
  with exit-code and output but no command text are recorded as unsupported and
  do not count as `commands_run` or `test_output` validation evidence. The
  audit remains `missing_test_evidence` for a final successful source repair
  claim. The local missing-command focused test passed on 2026-06-09 before
  this note was added. This is local supplied-record validation evidence only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court now rejects exit-code-only proof from non-validation commands
  for successful source repair claims: a command such as a status-printing
  script with `exit_code=0` no longer counts as passing test evidence unless
  the command itself looks like a test runner. The focused regression failed as
  `PASS` before the change and passed as `missing_test_evidence` after the
  change on 2026-06-09. This is local audit-boundary evidence only, not proof
  of validation quality, native export ingestion, remote CI status, external
  review, endorsement, stars, or reposts.
- Evidence Court now also rejects source repair success claims where a
  non-validation command emits text that looks like a passing test summary, such
  as `1 passed`. The focused regression failed as `PASS` before the change and
  passed as `missing_test_evidence` after the change on 2026-06-09. This is
  local audit-boundary evidence only, not proof of validation quality, native
  export ingestion, remote CI status, external review, endorsement, stars, or
  reposts.
- Supplied transcript adapter coverage now includes the same validation-command
  identity boundary across Codex, Claude, OpenHands, and SWE-agent formats: a
  non-validation command that emits `1 passed` is preserved in the record, but
  the source repair success claim still audits as `missing_test_evidence`. The
  local validation-command transcript focused test passed on 2026-06-09 before
  this note was added. This is local supplied-record validation evidence only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court direct-record coverage now includes orphan test output for
  source repair claims: a record with `test_output: 1 passed` but no
  `commands_run` validation command remains `missing_test_evidence` instead of
  proving a successful repair. The local orphan-test-output focused test passed
  on 2026-06-09 before this note was added. This is local supplied-record audit
  evidence only, not native export ingestion, remote CI status, external
  review, endorsement, stars, or reposts.
- Evidence Court now gives nonzero validation command exit codes precedence
  over supplied output text that looks passing. The focused regression failed
  as `PASS` before the change and passed as `post_edit_validation_failure`
  after the change on 2026-06-09. This is local audit-boundary evidence only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Supplied transcript adapter coverage now includes the same failed-exit-code
  precedence boundary across Codex, Claude, OpenHands, and SWE-agent supplied
  formats: a validation command with `exit_code=1` audits as
  `post_edit_validation_failure` even when the supplied command output says
  `1 passed`. The local focused transcript test passed on 2026-06-09 before
  this note was added. This is local supplied-record audit evidence only, not
  native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court now gives structured `test_output.exit_code` failure
  precedence over `test_output.status: passed`. The focused regression failed
  as `PASS` before the change and passed as `post_edit_validation_failure`
  after the change on 2026-06-09. This is local audit-boundary evidence only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court now rejects malformed direct-record command exit codes instead
  of silently ignoring them: `commands_run[].exit_code` must be an integer when
  supplied. The focused regression failed before the change and passed with a
  CLI error after the change on 2026-06-09. This is local supplied-record audit
  validation only, not native export ingestion, remote CI status, external
  review, endorsement, stars, or reposts.
- Evidence Court now rejects malformed structured test-output exit codes instead
  of letting `test_output.status: passed` override them:
  `test_output.exit_code` must be an integer when supplied. The focused
  regression failed before the change and passed with a CLI error after the
  change on 2026-06-09. This is local supplied-record audit validation only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court now rejects JSON boolean exit codes in supplied command and
  structured test-output records instead of treating `false` as `0` or `true`
  as `1`. The focused regression failed before the change and passed with CLI
  schema errors after the change on 2026-06-09. This is local supplied-record
  audit validation only, not native export ingestion, remote CI status,
  external review, endorsement, stars, or reposts.
- Evidence Court now lets failure-looking structured `test_output.output` text
  override `test_output.status: passed`. The focused regression failed as
  `PASS` before the change and passed as `post_edit_validation_failure` after
  the change on 2026-06-09. This is local supplied-record audit validation
  only, not native export ingestion, remote CI status, external review,
  endorsement, stars, or reposts.
- Evidence Court now checks both structured `test_output.output` and
  `test_output.summary` for failure-looking text instead of letting a passing
  output hide a failing summary. The focused regression failed as `PASS` before
  the change and passed as `post_edit_validation_failure` after the change on
  2026-06-09. This is local supplied-record audit validation only, not native
  export ingestion, remote CI status, external review, endorsement, stars, or
  reposts.
- Evidence Court now treats nonzero `error` / `errors` counts in supplied
  text test summaries as failed validation evidence. The focused regression
  failed as `PASS` before the change and passed as
  `post_edit_validation_failure` after the change on 2026-06-09. This is local
  supplied-record audit validation only, not native export ingestion, remote CI
  status, external review, endorsement, stars, or reposts.
- Evidence Court now treats natural-language nonzero `failure` / `failures`
  counts in supplied text test summaries as failed validation evidence. The
  focused regression failed as `PASS` before the change and passed as
  `post_edit_validation_failure` after the change on 2026-06-09. This is local
  supplied-record audit validation only, not native export ingestion, remote CI
  status, external review, endorsement, stars, or reposts.
- Evidence Court now rejects malformed structured test-output status fields:
  `test_output.status` must be a string when supplied. The focused regression
  failed before the change and passed with a CLI schema error after the change
  on 2026-06-09. This is local supplied-record audit validation only, not
  native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- Evidence Court now rejects malformed structured test-output text fields:
  `test_output.output` and `test_output.summary` must be strings when supplied.
  The focused regression failed before the change and passed with CLI schema
  errors after the change on 2026-06-09. This is local supplied-record audit
  validation only, not native export ingestion, remote CI status, external
  review, endorsement, stars, or reposts.
- Evidence Court now has a local intensity matrix for supplied test-output
  status parsing: 100 medium, 100 high, and 10 ultra cases covering pass/fail
  counts, conflicting structured fields, malformed structured fields, command
  exit-code precedence, and zero-failure pass summaries. The matrix passed
  `210 passed` locally on 2026-06-09. This is parser-level local evidence only,
  not native export ingestion, remote CI status, external review, endorsement,
  stars, or reposts.
- `scripts/public_review_gate.sh` now runs that 210-case Evidence Court
  intensity matrix as part of the local public proof command, so the matrix is
  not a side-only check. The updated public gate passed locally on 2026-06-09.
  This remains local parser/supplied-record evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject malformed command `exit_code` fields
  before record output instead of emitting or silently dropping boolean/string
  exit codes. The focused transcript-adapter regression, full CLI wrapper test
  file, supplied transcript adapter matrix, and public gate passed locally on
  2026-06-09. This is local supplied-record validation evidence only, not native
  export ingestion, remote CI status, external review, endorsement, stars, or
  reposts.
- Evidence Court now rejects malformed `run_metrics` telemetry before audit or
  transcript-adapter record output: numeric/counter/cost/provider fields must
  match the supplied-record schema instead of preserving strings, booleans, or
  negative counts as comparable telemetry. The focused direct-record and
  transcript-adapter regressions, full CLI wrapper test file, supplied
  transcript adapter matrix, and public gate passed locally on 2026-06-09. This
  is local supplied-record validation evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject malformed command-output text fields
  before record output instead of silently dropping list/object values from
  `output`, `stdout`, `stderr`, `summary`, or `observation`. The focused
  transcript-adapter regression, full CLI wrapper test file, supplied
  transcript adapter matrix, and public gate passed locally on 2026-06-09. This
  is local supplied-record validation evidence only, not native export
  ingestion, remote CI status, external review, endorsement, stars, or reposts.
- Evidence Court now treats pytest `FAILED path::test ...` output lines as
  failed validation evidence even when the same supplied output also contains a
  passing-count line. The focused regression failed as `PASS` before the change
  and passed as `post_edit_validation_failure` after the change on 2026-06-09.
  The Evidence Court intensity matrix, full CLI wrapper test file, supplied
  transcript adapter matrix, and public gate passed locally on 2026-06-09. This
  is local supplied-record parser evidence only, not native export ingestion,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject mixed `session_id` evidence before
  record output instead of flattening edits from one session together with
  validation output from another session. The focused regression failed before
  the change and passed after the change on 2026-06-09; the full CLI wrapper
  test file, supplied transcript adapter matrix, and public gate passed locally
  on 2026-06-09. This is local supplied-record validation evidence only, not
  ACP control, live harness orchestration, native export ingestion, remote CI
  status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now aggregate multi-command `run_metrics`
  telemetry for additive duration, token, cost, and command-count fields instead
  of letting later command events overwrite earlier ones. The focused regression
  failed before the change and passed after the change on 2026-06-09; follow-up
  local coverage now checks the same aggregation boundary for Claude,
  OpenHands, and SWE-agent supplied transcript records. The full CLI wrapper
  test file, supplied transcript adapter matrix, `git diff --check`, and public
  gate passed locally on 2026-06-09 before this note was updated. This is local
  supplied-record telemetry comparability only, not native export ingestion,
  benchmark score validation, live harness orchestration, remote CI status,
  external review, endorsement, stars, or reposts.
- Supplied transcript adapters now deduplicate repeated `files_read` and
  `files_edited` path evidence in output records while preserving first-seen
  order, matching the existing duplicate diff-hunk boundary. The focused
  cross-adapter regression failed before the change and passed after the change
  on 2026-06-10; the full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record normalization only, not native export
  ingestion, live harness orchestration, benchmark score validation, remote CI
  status, external review, endorsement, stars, or reposts.
- Supplied JSONL event records now use the same repeated `files_read` and
  `files_edited` path de-duplication boundary as transcript records. The
  focused JSONL regression failed before the change and passed after the change
  on 2026-06-10; the full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record normalization only, not native export
  ingestion, live harness orchestration, benchmark score validation, remote CI
  status, external review, endorsement, stars, or reposts.
- Supplied JSONL event records now reject malformed command-output text fields
  instead of stringifying list/object values from `output` or `summary`. The
  focused JSONL regression failed before the change and passed after the change
  on 2026-06-10; the full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied JSONL and transcript adapter records now reject malformed command
  text fields instead of stringifying list/object values from `command` or
  `cmd`. The focused JSONL and cross-transcript regressions failed before the
  change and passed after the change on 2026-06-10; the full CLI wrapper test
  file, supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied JSONL event records now reject malformed final-claim text fields
  instead of stringifying list/object values from `final_claim`, `claim`, or
  `text`. The focused JSONL regression failed before the change and passed
  after the change on 2026-06-10; the full CLI wrapper test file, supplied
  transcript adapter matrix, `git diff --check`, and public gate passed locally
  before this note was added. This is local supplied-record schema validation
  only, not native export ingestion, live harness orchestration, benchmark
  score validation, remote CI status, external review, endorsement, stars, or
  reposts.
- Supplied JSONL event records now reject malformed task text fields instead
  of stringifying list/object values from `claimed_task` or `task`. The focused
  JSONL regression failed before the change and passed after the change on
  2026-06-10; the full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject malformed top-level task and final
  claim text instead of stringifying list/object values from `claimed_task`,
  `task`, `issue`, or `final_claim`. The cross-adapter regression failed before
  the change and passed after the change on 2026-06-10; the full CLI wrapper
  test file, supplied transcript adapter matrix, `git diff --check`, and public
  gate passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed `claimed_task` and
  `final_claim` text in both `audit` and `validate` instead of stringifying
  list/object values. The focused audit/validate regression failed before the
  change and passed after the change on 2026-06-10; the full CLI wrapper test
  file, supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed `source_agent`
  metadata in both `audit` and `validate` instead of stringifying list/object
  values. The focused audit/validate regression failed before the change and
  passed after the change on 2026-06-10; the full CLI wrapper test file,
  supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed artifact-provenance
  text fields such as `eval_rule_version`, `eval_rule_commit`,
  `runner_version`, and `runner_commit` instead of preserving list/object
  values in machine-readable provenance metadata. The focused audit/validate
  regression failed before the change and passed after the change on
  2026-06-10; the full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed artifact hash map
  values in `input_hashes`, `output_hashes`, and `artifact_hashes`, and the
  record schema now documents those values as strings. The focused
  audit/validate regression failed before the change and passed after the
  change on 2026-06-10; the public metadata tests, full CLI wrapper test file,
  supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed top-level
  `test_output` values instead of allowing list/object values to fall through
  to validation-command exit-code evidence. The focused audit regression failed
  before the change and passed after the change on 2026-06-10; the public
  metadata tests, full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied raw Evidence Court records now reject malformed `source_format`
  metadata instead of stringifying list/object values and potentially bypassing
  supplied-transcript diff-content boundary checks. The focused audit/validate
  regression failed before the change and passed after the change on
  2026-06-10; the public metadata tests, full CLI wrapper test file, supplied
  transcript adapter matrix, `git diff --check`, and public gate passed locally
  before this note was added. This is local supplied-record schema validation
  only, not native export ingestion, live harness orchestration, benchmark
  score validation, remote CI status, external review, endorsement, stars, or
  reposts.
- Supplied transcript adapters now reject malformed scalar diff-content fields
  (`diff`, `patch`, or `unified_diff`) instead of silently treating list/object
  values as missing diff-content evidence. The focused adapter regression failed
  before the change and passed after the change on 2026-06-10; the public
  metadata tests, full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject malformed single-path fields
  (`file`, `path`, or `file_path`) instead of silently treating list/object
  values as missing file evidence. The focused adapter regression failed before
  the change and passed after the change on 2026-06-10; the public metadata
  tests, full CLI wrapper test file, supplied transcript adapter matrix,
  `git diff --check`, and public gate passed locally before this note was
  added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied OpenHands and SWE-agent transcript adapters now reject malformed
  event-level claim text fields instead of silently treating list/object
  `message`, `content`, `text`, `instruction`, or `final_claim` values as
  missing claim evidence. The focused adapter regression failed before the
  change and passed after the change on 2026-06-10; the public metadata tests,
  full CLI wrapper test file, supplied transcript adapter matrix,
  `git diff --check`, and public gate passed locally before this note was
  added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied Codex and Claude transcript adapters now reject malformed message
  content text blocks instead of silently treating list/object `text` values as
  missing task or final-claim evidence. The focused adapter regression failed
  before the change and passed after the change on 2026-06-10; the public
  metadata tests, full CLI wrapper test file, supplied transcript adapter
  matrix, `git diff --check`, and public gate passed locally before this note
  was added. This is local supplied-record schema validation only, not native
  export ingestion, live harness orchestration, benchmark score validation,
  remote CI status, external review, endorsement, stars, or reposts.
- Supplied transcript adapters now reject malformed event/tool kind fields
  instead of stringifying list/object `type`, `name`, `kind`, `tool`, `action`,
  `operation`, or `role` values into unsupported event labels. The focused
  adapter regression failed before the change and passed after the change on
  2026-06-10; the public metadata tests, full CLI wrapper test file, supplied
  transcript adapter matrix, `git diff --check`, and public gate passed locally
  before this note was added. This is local supplied-record schema validation
  only, not native export ingestion, live harness orchestration, benchmark
  score validation, remote CI status, external review, endorsement, stars, or
  reposts.
- Supplied Codex and Claude transcript adapters now reject malformed nested
  tool payload containers instead of silently ignoring list values, non-object
  JSON strings, or non-JSON strings from `arguments`, `input`, or `params`.
  The focused adapter regression failed before the change and passed after the
  change on 2026-06-10; the public metadata tests, full CLI wrapper test file,
  supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- Supplied JSONL records and Claude transcript content blocks now reject
  malformed classifier fields instead of stringifying list/object values from
  JSONL `kind`/`type`/`event` or Claude content-block `type`. The focused
  regressions failed before the change and passed after the change on
  2026-06-10; the public metadata tests, full CLI wrapper test file, supplied
  transcript adapter matrix, `git diff --check`, and public gate passed locally
  before this note was added. This is local supplied-record schema validation
  only, not native export ingestion, live harness orchestration, benchmark
  score validation, remote CI status, external review, endorsement, stars, or
  reposts.
- Supplied Codex and Claude transcript adapters now reject malformed message
  `role` fields instead of stringifying list/object values and silently treating
  message content as neither a user task nor an assistant final claim. The
  focused adapter regression failed before the change and passed after the
  change on 2026-06-10; the public metadata tests, full CLI wrapper test file,
  supplied transcript adapter matrix, `git diff --check`, and public gate
  passed locally before this note was added. This is local supplied-record
  schema validation only, not native export ingestion, live harness
  orchestration, benchmark score validation, remote CI status, external review,
  endorsement, stars, or reposts.
- `docs/AGENT_TREND_RADAR.md` now treats the recent adapter evidence
  edge-case hardening as completed `main` work and moves the next concrete
  build target to supplied evidence ledger identity. The focused trend-radar
  metadata test failed before the wording change and passed after it; the full
  public metadata test, `git diff --check`, and public gate passed locally
  before this note was added. This is planning/proof-surface alignment only,
  not proof of native export ingestion, live harness control, ACP control,
  broad SWE-bench repair, remote CI status, external review, endorsement,
  stars, or reposts.

Do not use stale internal notes, local-only benchmark counts, old full-suite
logs, or agent-written summaries as public capability claims.

Public launch claims require current code, a reproducible command, and a linked
public result.

Next smallest hygiene task:

- Re-check `docs/AGENT_TREND_RADAR.md` and pick the next code-backed target
  only if it can be reduced to a failing test and public-proof boundary.
- Next concrete candidate: another adapter evidence edge case only if it can
  produce a focused failing regression, or a trend-radar follow-up that stays
  behind the supplied-record proof boundary.
