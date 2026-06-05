# OpenMako Public Progress

This file is a public status boundary, not an internal scoreboard.

Current public proof:

- The public v0.1 claim is the focused learning-effect gate in `README.md`.
- Latest local send-ready check on 2026-06-05 passed:
  `./scripts/public_review_gate.sh` ended with `public-review-gate: PASS`;
  `bash scripts/wave1_send_ready.sh swe-agent` re-ran the gate and printed a
  non-promotional technical-boundary message with
  `Proof command: bash scripts/public_proof_card.sh`.
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
- `bash scripts/wave1_thread_reply_ready.sh` runs the public review gate before
  printing one thread-specific reply draft for selected public discussions. It
  still does not send messages, create issues, or record outreach as evidence.
- The README exposes issue #2, the technical review packet, and focused CI as
  technical review entry points before the v0.1 scope section.
- The README now exposes a `60-Second Proof` section before the review links so
  visitors can run the public gate before reading longer docs.
- The README now includes an `If You Came From A Benchmark Thread` path that
  tells external benchmark/eval readers to run the gate, compare README claims
  against that command, and leave concrete mismatches on issue #2. It is a
  review path, not outreach evidence, endorsement, stars, or reposts.
- The technical review packet includes a minimal issue-comment template for
  boundary-clear, overclaim, or unclear findings.
- The technical review packet also links the supplied Codex/OpenHands/SWE-agent
  transcript adapter checks through `docs/evidence_court_schema.md`. This is a
  reviewer lookup path for repository-defined supplied formats only, not native
  exports, live control, benchmark ingestion, or endorsement.
- `scripts/public_review_gate.sh` wraps the local reviewer proof command:
  focused public tests, metadata boundary checks, and supplied-record
  Evidence Court bad-run audit.
- The `run-metrics` evidence extension is on `main`: Evidence Court preserves
  optional duration, token, cost, command-count, and missing-telemetry fields
  as `run_metrics` in supplied records and audit JSON. Provider/model fields
  are also preserved when supplied. The fields are preserved in Evidence Court audit JSON.
  They improve comparability, but they are not treated as proof that validation
  ran.
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
- `scripts/public_proof_card.sh` wraps the same gate and prints a
  screenshot-friendly proof card with commit, scope, non-proof boundaries,
  review issue, and external-review record form.
- `docs/PUBLIC_SHARE_PACKET.md` provides boundary-preserving public wording for
  reviewers who independently choose to discuss the project.
- `docs/PUBLIC_SHARE_PACKET.md` also includes a <=280 character technical
  review post and a boundary-clear follow-up that must not be used before a
  named reviewer gives public feedback.
- `docs/REVIEWER_OUTREACH_DRAFT.md` defines who to contact first and blocks
  general-influencer outreach until at least one public technical boundary
  review exists.
- GitHub Actions runs the focused gate through `.github/workflows/focused.yml`.
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
