import ast
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DESCRIPTION = (
    "Evidence harness for coding agents: learning-effect, patch-scope, and test-proof checks."
)
FORBIDDEN_DESCRIPTION_TERMS = (
    "agent runtime",
    "coding and data work",
    "general autonomy",
)
FORBIDDEN_README_CLAIMS = (
    "Today, OpenMako proves",
    "## What It Proves Today",
    "| Green public CI |",
    "OpenMako does not copy Claude/closed-source code",
    "docs/COMPARISON.md",
    "docs/LAUNCH_PLAYBOOK.md",
    "docs/MARKET_TOOL_COPY_SCAN.md",
)
FORBIDDEN_PUBLIC_PROGRESS_CLAIMS = (
    "112/112",
    "60/60",
    "full pytest passed",
    "level=L5",
    "SWE-style repository reasoning",
    "broad unknown NPM repo repair",
)
FORBIDDEN_ROOT_AGENT_NOTES = (
    "QuantAgent Project Memory",
    "local quant-focused coding agent starter",
    "quant-focused coding agent starter",
    "Claude Code-like local workflow",
    "PF, slippage, capacity, tick, broker",
    "python3 -m unittest discover -s tests",
    "desktop actions",
    "Claude Code source",
    "OpenClaw, Hermes Agent",
    "desktop_plan.py",
)
ARCHIVED_ROOT_QUANT_FILES = (
    "TICK_CAPACITY_VALIDATOR_GUIDE.md",
    "capacity_validation_report.json",
    "tick_price_validation.json",
    "tick_price_validation.md",
)
EXAMPLE_ROOT_QUANT_FILES = (
    "demo_capacity_comprehensive.py",
    "demo_capacity_validation.py",
    "example_tick_price_validator.py",
    "realistic_t1_trades.csv",
)
LEGACY_ROOT_QUANT_TEST_FILES = (
    "test_tick_price_validator.py",
    "test_realistic_t1_trades.csv",
    "test_slippage_calculator.py",
    "test_tick_extraction_real.py",
    "test_tick_extraction.py",
    "tick_data_request_test.csv",
)
INTERNAL_PLANNING_DOCS = (
    "docs/LAUNCH_PLAYBOOK.md",
    "docs/COMPARISON.md",
    "docs/MARKET_TOOL_COPY_SCAN.md",
    "docs/CLAUDE_SRC_ABSORPTION_PLAN.md",
    "docs/DESKTOP_L5_ROADMAP.md",
    "docs/OPENCLAW_LEVEL_TARGET.md",
    "docs/OPENCLAW_HERMES_FULL_PORT_PLAN.md",
    "docs/AGENT_PORTING_SWARM.md",
    "docs/DESKTOP_DAEMON_L4.md",
    "docs/HERMES_OPENCLAW_SOURCE_SCAN.md",
    "docs/OPENCLAW_HERMES_COPY_WHITELIST.md",
    "docs/SOURCE_COPY_BORROW_MATRIX.md",
    "docs/SAFETY_POLICY.md",
    "docs/SANDBOX_ROADMAP.md",
    "docs/TICK_VALIDATION.md",
    "docs/OPENAI_COMPATIBLE_SETUP.md",
    "docs/UPSTREAM_ATTRIBUTION.md",
    "docs/DESIGN_DECISIONS.md",
    "docs/OPERATOR_TRUST_MODEL.md",
    "docs/OPENMAKO_NEXT_PORTS.md",
)
FORBIDDEN_PUBLIC_DOC_VENDOR_ENDPOINTS = (
    "api.xiaoma.best",
    "lanyiapi.com",
)


def _pyproject_description() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^description = "([^"]+)"$', text, flags=re.MULTILINE)
    assert match, "pyproject.toml must declare a project description"
    return match.group(1)


def _setup_description() -> str:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    raise AssertionError("setup.py must declare a setup(description=...)")


def test_package_metadata_uses_focused_public_positioning() -> None:
    descriptions = [_pyproject_description(), _setup_description()]

    assert descriptions == [PUBLIC_DESCRIPTION, PUBLIC_DESCRIPTION]
    for description in descriptions:
        lowered = description.lower()
        for forbidden in FORBIDDEN_DESCRIPTION_TERMS:
            assert forbidden not in lowered


def test_readme_links_public_proof_issue() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Technical Review Entry Points" in readme
    assert "Public proof card" in readme
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in readme
    assert "Technical boundary criticism request" in readme
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in readme
    assert "Technical boundary issue form" in readme
    assert "issues/new?template=technical-boundary-check.yml" in readme
    assert "External review record form" in readme
    assert "issues/new?template=external-review-record.yml" in readme
    assert "already-public technical feedback only" in readme
    assert "a review request rather than endorsement or promotion" in readme
    assert "Technical review packet" in readme
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in readme
    assert "Reproduction guide" in readme
    assert "docs/REPRODUCE_V0_1.md" in readme
    assert "Contributor guide" in readme
    assert "CONTRIBUTING.md" in readme
    assert "Attribution boundary" in readme
    assert "docs/UPSTREAM_ATTRIBUTION.md" in readme
    assert "Agent trend radar" in readme
    assert "docs/AGENT_TREND_RADAR.md" in readme
    assert "Reviewer target map" in readme
    assert "docs/REVIEWER_TARGETS.md" in readme
    assert "Wave 1 review requests" in readme
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in readme
    assert "Wave 1 public target queue" in readme
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in readme
    assert "Wave 1 short-message helper" in readme
    assert "bash scripts/wave1_review_request.sh swe-agent" in readme
    assert "Wave 1 send-ready check" in readme
    assert "bash scripts/wave1_send_ready.sh swe-agent" in readme
    assert "Public share packet" in readme
    assert "docs/PUBLIC_SHARE_PACKET.md" in readme
    assert "Why It Is Worth Checking" in readme


def test_focused_workflow_runs_same_public_gate_as_readme() -> None:
    workflow = (ROOT / ".github" / "workflows" / "focused.yml").read_text(encoding="utf-8")

    assert "Run focused OpenMako evidence gate" in workflow
    assert "bash scripts/public_review_gate.sh" in workflow
    assert "tests/test_agent_planner_contract.py::AgentPlannerContractTest" not in workflow
    assert "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest" not in workflow
    assert "python -m pip install -e . pytest" in workflow


def test_agent_trend_radar_tracks_current_next_build_target() -> None:
    radar = (ROOT / "docs" / "AGENT_TREND_RADAR.md").read_text(encoding="utf-8")

    assert "Last refreshed: 2026-06-05." in radar
    assert "## Current Build Target" in radar
    assert "run-record adapter matrix for supplied transcripts" in radar
    assert "The `run-metrics` evidence extension is already on `main`" in radar
    assert "one fixture and one CLI smoke test per adapter" in radar
    assert "cross-agent supplied-record audit\ncoverage" in radar
    assert "not prove live orchestration, ACP control, broad SWE-bench repair, or\nexternal endorsement" in radar


def test_readme_exposes_reviewer_entry_points_before_scope_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    why_index = readme.index("## Why It Is Worth Checking")
    proof_index = readme.index("## 60-Second Proof")
    benchmark_thread_index = readme.index("## If You Came From A Benchmark Thread")
    review_index = readme.index("## Technical Review Entry Points")
    scope_index = readme.index("## Public v0.1 Scope")

    assert why_index < proof_index
    assert proof_index < review_index
    assert proof_index < benchmark_thread_index < review_index
    assert review_index < scope_index
    why_section = readme[why_index:proof_index]
    assert "Coding-agent evals often collapse into a final pass/fail." in why_section
    assert "make the run evidence inspectable" in why_section
    assert "improve hidden variants" in why_section
    assert "stay inside patch scope" in why_section
    assert "did the required\ntests run as claimed" in why_section
    assert (
        "concrete mismatch between a public claim and\n"
        "the command, workflow, issue, or artifact"
    ) in why_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in why_section.lower()
    proof_section = readme[proof_index:review_index]
    assert "git clone https://github.com/1966536805l-crypto/openmako.git" in proof_section
    assert "python -m pip install -e . pytest" in proof_section
    assert "./scripts/public_review_gate.sh" in proof_section
    assert "bash scripts/public_proof_card.sh" in proof_section
    assert "screenshot-friendly summary" in proof_section
    assert "public-review-gate: running supplied transcript adapter matrix" in proof_section
    assert "adapter-matrix: PASS" in proof_section
    assert "public-review-gate: PASS" in proof_section
    assert "What this checks is narrow" in proof_section
    assert "supplied transcript adapters preserve complete\nsupplied proof fields while rejecting missing-test-proof success claims" in proof_section
    assert "It\ndoes not prove broad unknown-repository repair or external endorsement." in proof_section
    assert "This\nis a local script result, not external reviewer approval." in proof_section
    assert "## If You Came From A Benchmark Thread" in proof_section
    assert "Start with the public gate:" in proof_section
    assert 'The useful review is not "do you like this project?"' in proof_section
    assert "Run `./scripts/public_review_gate.sh`." in proof_section
    assert "For artifact-identity questions, inspect the supplied-record fixture:" in proof_section
    assert (
        "./bin/openmako --no-trust-prompt evidence-court audit --ci --json "
        "examples/evidence_court/artifact_provenance.json"
    ) in proof_section
    assert "Check whether the README claims more than those commands prove." in proof_section
    assert "leave the concrete mismatch on\n   [issue #2]" in proof_section
    assert "If something is unclear, please point to the file, command, workflow, or\nmissing artifact." in proof_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in proof_section.lower()
    review_section = readme[review_index:scope_index]
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in review_section
    assert "issues/new?template=technical-boundary-check.yml" in review_section
    assert "issues/new?template=external-review-record.yml" in review_section
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in review_section
    assert "docs/REPRODUCE_V0_1.md" in review_section
    assert "CONTRIBUTING.md" in review_section
    assert "docs/UPSTREAM_ATTRIBUTION.md" in review_section
    assert "docs/AGENT_TREND_RADAR.md" in review_section
    assert "docs/REVIEWER_TARGETS.md" in review_section
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in review_section
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in review_section
    assert "bash scripts/wave1_review_request.sh swe-agent" in review_section
    assert "bash scripts/wave1_send_ready.sh swe-agent" in review_section
    assert "docs/PUBLIC_SHARE_PACKET.md" in review_section
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in review_section
    assert "https://github.com/1966536805l-crypto/openmako/actions/workflows/focused.yml" in review_section
    assert "./scripts/public_review_gate.sh" in review_section
    assert "This path is for technical boundary review, not promotion." in review_section
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in review_section.lower()


def test_readme_has_runnable_bad_run_demo() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## CI Quickstart" in readme
    assert (
        "./bin/openmako --no-trust-prompt evidence-court record from-jsonl "
        "--output run.json examples/evidence_court/simple_events.jsonl"
    ) in readme
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in readme
    assert "not a native Claude Code, Codex, or Cursor transcript adapter" in readme
    assert "docs/github_actions_evidence_court.md" in readme
    assert "## 10-Second Bad-Run Demo" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo bad-run" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo missing-tests" in readme
    assert "./bin/openmako --no-trust-prompt evidence-court demo out-of-scope" in readme
    assert "## Claim" in readme
    assert "## Evidence" in readme
    assert "## Scope Violations" in readme
    assert "## Test Verification" in readme
    assert "## Suspicious Behavior" in readme
    assert "## Verdict: FAIL" in readme
    assert "## Verdict: SUSPICIOUS" in readme


def test_github_actions_evidence_court_doc_uses_supported_commands() -> None:
    doc = (ROOT / "docs" / "github_actions_evidence_court.md").read_text(encoding="utf-8")

    assert ".github/workflows/evidence-court-demo.yml" in doc
    assert ".github/actions/evidence-court/action.yml" in doc
    assert "repository-local action, not a published Marketplace action" in doc
    assert "asserts that `audit --ci --json` exits with `1`" in doc
    assert "test -f run.json" in doc
    assert "uses: ./.github/actions/evidence-court" in doc
    assert "record: run.json" in doc
    assert "report: evidence-court-report.json" in doc
    assert "actions/upload-artifact@v4" in doc
    assert "openmako evidence-court record from-jsonl --output run.json path/to/events.jsonl" in doc
    assert "openmako evidence-court audit --ci --fail-on suspicious --json run.json" in doc
    assert "does not collect native Claude Code, Codex, Cursor, or SWE-bench logs" in doc
    assert "audits only the supplied `run.json`" in doc


def test_evidence_court_demo_workflow_uses_supported_bad_run_commands() -> None:
    workflow = (ROOT / ".github" / "workflows" / "evidence-court-demo.yml").read_text(encoding="utf-8")

    assert "name: evidence-court-demo" in workflow
    assert "workflow_dispatch:" in workflow
    assert "python -m pip install -e ." in workflow
    assert "openmako evidence-court record from-jsonl --output run.json examples/evidence_court/simple_events.jsonl" in workflow
    assert "uses: ./.github/actions/evidence-court" in workflow
    assert "record: run.json" in workflow
    assert "report: evidence-court-report.json" in workflow
    assert "expected-exit: \"1\"" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "Claude Code" not in workflow
    assert "Codex" not in workflow
    assert "Cursor" not in workflow


def test_evidence_court_composite_action_wraps_supported_cli_commands() -> None:
    action = (ROOT / ".github" / "actions" / "evidence-court" / "action.yml").read_text(encoding="utf-8")

    assert "using: composite" in action
    assert "record:" in action
    assert "report:" in action
    assert "fail-on:" in action
    assert "expected-exit:" in action
    assert 'default: "0"' in action
    assert "openmako evidence-court validate \"$RECORD\"" in action
    assert "openmako evidence-court audit --ci --fail-on \"$FAIL_ON\" --json \"$RECORD\" > \"$REPORT\"" in action
    assert "test \"${audit_exit}\" -eq \"${EXPECTED_EXIT}\"" in action
    assert "Marketplace" not in action
    assert "Claude Code" not in action
    assert "Codex" not in action
    assert "Cursor" not in action


def test_release_checklist_keeps_v01_claims_evidence_gated() -> None:
    checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")

    assert "Do not treat this file as proof that a release already happened." in checklist
    assert "CHANGELOG.md" in checklist
    assert "docs/v0.1_release_notes.md" in checklist
    assert ".github/workflows/focused.yml" in checklist
    assert ".github/workflows/evidence-court-demo.yml" in checklist
    assert "tests/test_public_metadata.py" in checklist
    assert "tests/test_cli_wrappers.py" in checklist
    assert "artifact named `evidence-court-report`" in checklist
    assert "evidence-court-report.json" in checklist
    assert "Do not claim native Claude Code, Codex, Cursor, or SWE-bench transcript" in checklist
    assert "Do not claim broad unknown-repository SWE repair." in checklist
    assert "Do not claim full pytest or hidden benchmark numbers" in checklist
    assert "repository-local composite action" in checklist
    assert "published\n  Marketplace action" in checklist
    assert "git tag -a v0.1.0" in checklist
    assert "git push origin v0.1.0" in checklist
    assert "v0.1 audits supplied records only" in checklist


def test_changelog_v01_draft_stays_inside_public_evidence_boundary() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## v0.1.0 Draft" in changelog
    assert "not proof that `v0.1.0` has been tagged or\npublished" in changelog
    assert "Evidence Court CLI commands" in changelog
    assert "evidence-court/v0.1" in changelog
    assert "repository-local GitHub composite action" in changelog
    assert "evidence-court-report` artifact" in changelog
    assert "evidence-court-report.json" in changelog
    assert "tests/test_public_metadata.py" in changelog
    assert "tests/test_cli_wrappers.py" in changelog
    assert ".github/workflows/focused.yml" in changelog
    assert ".github/workflows/evidence-court-demo.yml" in changelog
    assert "OpenMako v0.1 audits supplied Evidence Court records" in changelog
    assert "v0.1 audits supplied records only" in changelog
    assert "Native Claude Code, Codex, Cursor, or SWE-bench transcript ingestion" in changelog
    assert "Broad unknown-repository SWE repair claims" in changelog
    assert "published Marketplace GitHub Action" in changelog
    assert "Full-suite or hidden benchmark claims" in changelog
    assert "has been released" not in changelog
    assert "published Marketplace action" not in changelog
    assert "broad unknown-repository SWE repair." not in changelog


def test_v01_release_notes_draft_is_publishable_without_overclaiming() -> None:
    notes = (ROOT / "docs" / "v0.1_release_notes.md").read_text(encoding="utf-8")

    assert "# OpenMako v0.1.0 Release Notes Draft" in notes
    assert "Do not publish this text until the v0.1 release checklist has passed" in notes
    assert "OpenMako v0.1 audits supplied Evidence Court records" in notes
    assert "not a replacement for coding agents" in notes
    assert "evidence-court/v0.1" in notes
    assert "openmako evidence-court audit --ci" in notes
    assert "openmako evidence-court record from-jsonl" in notes
    assert "openmako evidence-court validate" in notes
    assert "repository-local GitHub composite action" in notes
    assert "uploads the `evidence-court-report` artifact" in notes
    assert "evidence-court-report.json" in notes
    assert "tests/test_public_metadata.py" in notes
    assert "tests/test_cli_wrappers.py" in notes
    assert ".github/workflows/focused.yml" in notes
    assert ".github/workflows/evidence-court-demo.yml" in notes
    assert "docs/release_checklist.md" in notes
    assert "v0.1 audits supplied records only" in notes
    assert "does not yet ingest native Claude Code,\nCodex, Cursor, or SWE-bench transcripts" in notes
    assert "broad unknown-repository SWE repair" in notes
    assert "published Marketplace GitHub Action" in notes
    assert "has been released" not in notes
    assert "native Claude Code adapter" not in notes
    assert "native Codex adapter" not in notes
    assert "native Cursor adapter" not in notes
    assert "SWE-bench ingestion" not in notes
    assert "replaces Claude Code" not in notes
    assert "full pytest passed" not in notes


def test_readme_uses_reviewable_public_claims() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "demonstrates one narrow public gate" in readme
    assert "## Implementation Boundary" in readme
    assert "## Beyond The Public Gate" in readme
    assert "OpenMako's project policy is clean-room implementation for closed-source tools" in readme
    assert "docs/UPSTREAM_ATTRIBUTION.md" in readme
    assert "vendored-license boundaries" in readme
    for forbidden in FORBIDDEN_README_CLAIMS:
        assert forbidden not in readme


def test_progress_file_is_public_boundary_not_internal_scoreboard() -> None:
    progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")

    assert "public status boundary" in progress
    assert "https://github.com/1966536805l-crypto/openmako/issues/1" in progress
    assert "External technical boundary criticism is requested in issue #2" in progress
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in progress
    assert "not evidence of endorsement or promotion" in progress
    assert ".github/ISSUE_TEMPLATE/technical-boundary-check.yml" in progress
    assert ".github/ISSUE_TEMPLATE/external-review-record.yml" in progress
    assert "already-public\n  external technical reviews only" in progress
    assert "not private messages or self-written\n  summaries" in progress
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in progress
    assert "docs/REPRODUCE_V0_1.md" in progress
    assert "docs/REVIEWER_OUTREACH_DRAFT.md" in progress
    assert "docs/REVIEWER_TARGETS.md" in progress
    assert "separates technical-review targets from\n  broader writer/community targets" in progress
    assert "forbids star, repost, promotion, or\n  endorsement asks" in progress
    assert "docs/AGENT_TREND_RADAR.md" in progress
    assert "maps Hermes/OpenClaw/OpenHands/eval trends to\n  future OpenMako build bets" in progress
    assert "marks them as non-claims until code, fixtures,\n  and CI exist" in progress
    assert "docs/WAVE1_REVIEW_REQUESTS.md" in progress
    assert "not proof that outreach, review, endorsement, stars, or reposts happened" in progress
    assert "docs/WAVE1_PUBLIC_TARGET_QUEUE.md" in progress
    assert "reachable public surfaces" in progress
    assert "not proof that messages\n  were sent or that anyone reviewed the project" in progress
    assert "bash scripts/wave1_thread_reply_ready.sh" in progress
    assert "one thread-specific reply draft" in progress
    assert "does not send messages, create issues, or record outreach as evidence" in progress
    assert "`openhands-benchmarks-718` thread draft was refreshed" in progress
    assert "`output.jsonl` to\n  `output.swtbench.jsonl` artifact identity" in progress
    assert "links only the concrete\n  `swtbench_patch_artifact` fixture" in progress
    assert "not a homepage, star ask, or promotion\n  request" in progress
    assert "send-ready text only, not proof of posting" in progress
    assert "`openhands-benchmarks-708` thread draft was refreshed" in progress
    assert "`332 / 424` mixed\n  test+source patch bucket" in progress
    assert "patch-shape metadata, and the concrete\n  `swtbench_patch_artifact` fixture" in progress
    assert "bash scripts/wave1_review_request.sh" in progress
    assert "without sending messages or recording outreach as evidence" in progress
    assert "bash scripts/wave1_send_ready.sh" in progress
    assert "runs the public review gate before printing\n  a target-specific Wave 1 short message" in progress
    assert "technical review entry points before the v0.1 scope section" in progress
    assert "`60-Second Proof` section before the review links" in progress
    assert "`Why It Is Worth Checking` hook before the\n  proof commands" in progress
    assert "asks for concrete claim/proof mismatches, not promotion" in progress
    assert "`If You Came From A Benchmark Thread` path" in progress
    assert "inspect the\n  `artifact_provenance` fixture for artifact-identity questions" in progress
    assert "compare README\n  claims against the proof commands" in progress
    assert "leave concrete mismatches on issue #2" in progress
    assert "not outreach evidence, endorsement, stars, or reposts" in progress
    assert "minimal issue-comment template" in progress
    assert "links the supplied Codex/OpenHands/SWE-agent\n  transcript adapter checks" in progress
    assert "repository-defined supplied formats only, not native\n  exports, live control, benchmark ingestion, or endorsement" in progress
    assert "scripts/public_review_gate.sh" in progress
    assert "examples/evidence_court/swtbench_patch_artifact.json" in progress
    assert "combines `mixed_test_source` patch-shape\n  metadata with `output.jsonl` to `output.swtbench.jsonl` artifact identity" in progress
    assert "not native benchmark ingestion or score validation" in progress
    assert "scripts/supplied_transcript_adapter_matrix.sh" in progress
    assert "repository-defined Codex, Claude, OpenHands, and SWE-agent style transcripts" in progress
    assert "verifies that each adapter rejects a success claim when\n  command/test proof is missing" in progress
    assert "supplied-format smoke test, not native\n  product export parsing, live agent control, benchmark ingestion, or\n  endorsement" in progress
    assert "scripts/public_proof_card.sh" in progress
    assert "screenshot-friendly proof card with commit, scope, non-proof boundaries,\n  review issue, and external-review record form" in progress
    assert "docs/PUBLIC_SHARE_PACKET.md" in progress
    assert "docs/openmako-review-card.svg" in progress
    assert "optional visual summary for the public\n  gate and issue #2 boundary review" in progress
    assert "not evidence of external review,\n  endorsement, stars, or reposts" in progress
    assert "<=280 character technical\n  review post" in progress
    assert "blocks\n  general-influencer outreach until at least one public technical boundary\n  review exists" in progress
    assert "`run-metrics` evidence extension" in progress
    assert "optional duration, token, cost, command-count, and missing-telemetry fields" in progress
    assert "preserved in Evidence Court audit JSON" in progress
    assert "`patch-shape` evidence extension" in progress
    assert "machine-readable `patch_shape` bucket" in progress
    assert "`mixed_test_source` for runs that edit both test-like and\n  source-like files" in progress
    assert "does not\n  prove a benchmark score should be higher or lower by itself" in progress
    assert "stale internal notes" in progress
    for forbidden in FORBIDDEN_PUBLIC_PROGRESS_CLAIMS:
        assert forbidden not in progress


def test_agent_trend_radar_maps_sources_to_non_claim_development_bets() -> None:
    radar = (ROOT / "docs" / "AGENT_TREND_RADAR.md").read_text(encoding="utf-8")

    assert "OpenMako Agent Trend Radar" in radar
    assert "Last refreshed: 2026-06-05." in radar
    assert "not proof that OpenMako already implements these\ncapabilities" in radar
    assert "not evidence of external review, endorsement, stars, or\nreposts" in radar
    assert "https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent" in radar
    assert "https://docs.openclaw.ai/tools/acp-agents" in radar
    assert "https://github.com/OpenHands/OpenHands" in radar
    assert "https://github.com/harbor-framework/terminal-bench" in radar
    assert "https://github.com/Vexp-ai/vexp-swe-bench" in radar
    assert "https://arxiv.org/abs/2605.14415" in radar
    assert "https://arxiv.org/abs/2605.13139" in radar
    assert "https://arxiv.org/abs/2509.22097" in radar
    assert "https://arxiv.org/abs/2602.02474" in radar
    assert "Evidence Ledger Before Broader Runtime" in radar
    assert "Skill Evolution With Reproducible Approval" in radar
    assert "External Harness Adapter Without Runtime Overclaim" in radar
    assert "Benchmark Telemetry Beyond Pass/Fail" in radar
    assert "Full-Cycle And Secure-Coding Gates" in radar
    assert "Do not claim OpenMako is a Hermes, OpenClaw, OpenHands, SWE-agent, or\n  Terminal-Bench replacement." in radar
    assert "Do not claim ACP, MCP orchestration, long-term memory, skill self-evolution,\n  cloud agent execution, or secure-code benchmarking as current public v0.1\n  capability." in radar
    assert "The `run-metrics` evidence extension is already on `main`" in radar
    assert "run-record adapter matrix for supplied transcripts" in radar
    assert "one fixture and one CLI smoke test per adapter" in radar
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in radar.lower()


def test_technical_review_packet_is_evidence_first_not_promotional() -> None:
    packet = (ROOT / "docs" / "TECHNICAL_REVIEW_PACKET.md").read_text(encoding="utf-8")

    assert "OpenMako v0.1 Technical Review Packet" in packet
    assert "not an endorsement request" in packet
    assert "promotion request" in packet
    assert "star request" in packet
    assert "repost request" in packet
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in packet
    assert "issues/new?template=technical-boundary-check.yml" in packet
    assert "docs/REVIEWER_OUTREACH_DRAFT.md" in packet
    assert "docs/REPRODUCE_V0_1.md" in packet
    assert "docs/PUBLIC_SHARE_PACKET.md" in packet
    assert "./scripts/public_review_gate.sh" in packet
    assert "tests/test_agent_planner_contract.py::AgentPlannerContractTest" in packet
    assert "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest" in packet
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in packet
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in packet
    assert "does not claim native Claude Code" in packet
    assert "## Optional Supplied-Transcript Adapter Checks" in packet
    assert "docs/evidence_court_schema.md" in packet
    assert "record from-codex-transcript" in packet
    assert "record from-claude-transcript" in packet
    assert "record from-openhands-transcript" in packet
    assert "record from-swe-agent-transcript" in packet
    assert "adapter_report.unsupported" in packet
    assert "They do not claim native Codex, Claude,\nOpenHands, or SWE-agent export parsing" in packet
    assert "live agent control, benchmark\ningestion, or external endorsement" in packet
    assert "Does README claim more than the focused tests and CI prove?" in packet
    assert "A useful review points to a specific file, line, command, workflow, or missing\nartifact." in packet
    assert "## Minimal Review Comment Template" in packet
    assert "Verdict: boundary clear / overclaim / unclear" in packet
    assert "README section or line:" in packet
    assert "Test command or workflow:" in packet
    assert "Concrete mismatch or missing proof:" in packet
    assert "Suggested correction:" in packet
    assert "Do not include endorsement, promotion, star, or repost language in the review." in packet
    assert "10000" not in packet
    assert "10,000" not in packet
    assert "大咖" not in packet


def test_reproduce_v01_guide_is_command_first_and_boundary_limited() -> None:
    guide = (ROOT / "docs" / "REPRODUCE_V0_1.md").read_text(encoding="utf-8")

    assert "OpenMako v0.1 Reproduction Guide" in guide
    assert "not an endorsement\nrequest, promotion request, star request, or repost request" in guide
    assert "## Claim Under Test" in guide
    assert "## Fresh Checkout" in guide
    assert "git clone https://github.com/1966536805l-crypto/openmako.git" in guide
    assert "python -m pip install -e . pytest" in guide
    assert "./scripts/public_review_gate.sh" in guide
    assert "<N> passed" in guide
    assert "metadata-test count is intentionally not fixed" in guide
    assert "25 passed" not in guide
    assert "public-review-gate: PASS" in guide
    assert "public-review-gate: auditing artifact provenance fixture" in guide
    assert "public-review-gate: running supplied transcript adapter matrix" in guide
    assert "adapter-matrix: PASS" in guide
    assert "PYTHONPATH" in guide
    assert "stale installed package" in guide
    assert "tests/test_public_metadata.py" in guide
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in guide
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json run.json" in guide
    assert "./scripts/supplied_transcript_adapter_matrix.sh" in guide
    assert "repository-defined Codex, Claude, OpenHands,\nand SWE-agent style transcripts" in guide
    assert "checks that each adapter rejects a\nsuccess claim when command/test proof is missing" in guide
    assert "not native product export parsing or live agent control" in guide
    assert "It does not prove broad unknown-repository SWE repair." in guide
    assert "It does not prove external endorsement." in guide
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in guide.lower()


def test_github_issue_template_routes_boundary_criticism_without_promotion() -> None:
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "technical-boundary-check.yml").read_text(encoding="utf-8")

    assert "Technical boundary check" in template
    assert "Report whether OpenMako v0.1 public claims match repository evidence." in template
    assert "technical boundary criticism only" in template
    assert "not an\n        endorsement request, promotion request, star request, or repost request" in template
    assert "docs/REPRODUCE_V0_1.md" in template
    assert "boundary clear" in template
    assert "overclaim" in template
    assert "unclear" in template
    assert "Evidence checked" in template
    assert "Reproduction result" in template
    assert "./scripts/public_review_gate.sh" in template
    assert "Concrete mismatch or missing proof" in template
    assert "Suggested correction" in template
    assert "not endorsement, promotion, star request, or repost request" in template
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in template.lower()


def test_issue_template_config_routes_reviewers_to_reproduction_first() -> None:
    config = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")

    assert "blank_issues_enabled: false" in config
    assert "Reproduce OpenMako v0.1 first" in config
    assert "docs/REPRODUCE_V0_1.md" in config
    assert "Read the technical review packet" in config
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in config
    assert "Share packet for boundary-clear reviews" in config
    assert "docs/PUBLIC_SHARE_PACKET.md" in config
    assert "Use only after a named reviewer has already posted public technical feedback." in config
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in config.lower()


def test_external_review_record_template_records_public_reviews_only() -> None:
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "external-review-record.yml").read_text(encoding="utf-8")

    assert "External review record" in template
    assert "Record a public external technical review of OpenMako v0.1." in template
    assert "external-review, technical-boundary" in template
    assert "already posted a\n        public technical review" in template
    assert "not an endorsement request, promotion request, star request, or\n        repost request" in template
    assert "Do not use private DMs or unverifiable summaries as\n        evidence" in template
    assert "Reviewer" in template
    assert "Public review link" in template
    assert "Review verdict" in template
    assert "boundary clear" in template
    assert "overclaim found" in template
    assert "Evidence checked by reviewer" in template
    assert "Follow-up needed" in template
    assert "already-public external technical review" in template
    assert "does not ask for endorsement, promotion, stars, reposts, or broader claims" in template
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in template.lower()


def test_contributing_guide_routes_to_evidence_not_promotion() -> None:
    guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Contributing To OpenMako" in guide
    assert "technical boundary criticism before broader\npromotion" in guide
    assert "not an endorsement request, promotion request, star request, or repost\nrequest" in guide
    assert "./scripts/public_review_gate.sh" in guide
    assert "docs/REPRODUCE_V0_1.md" in guide
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in guide
    assert "issues/new?template=technical-boundary-check.yml" in guide
    assert "A focused test that catches a public-boundary drift." in guide
    assert "Claiming broad unknown-repository SWE repair" in guide
    assert "tests/test_public_metadata.py" in guide
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in guide.lower()


def test_public_share_packet_preserves_review_boundary_without_promotion() -> None:
    share_packet = (ROOT / "docs" / "PUBLIC_SHARE_PACKET.md").read_text(encoding="utf-8")

    assert "OpenMako Public Share Packet" in share_packet
    assert "not endorsement, promotion, star request, or repost request" in share_packet
    assert "## Short Public Posts" in share_packet
    assert "Use short posts only as a technical review request" in share_packet
    assert "### Technical Review Request" in share_packet
    assert "Looking for technical boundary criticism" in share_packet
    assert "### Boundary-Clear Follow-Up" in share_packet
    assert "Use this only after a named reviewer has publicly said the boundary is clear." in share_packet
    assert "not a broad agent benchmark" in share_packet
    assert "focused learning-effect gate" in share_packet
    assert "patch-scope discipline" in share_packet
    assert "test-proof evidence" in share_packet
    assert "Evidence Court CLI that audits supplied records" in share_packet
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in share_packet
    assert "https://github.com/1966536805l-crypto/openmako/releases/tag/v0.1.0" in share_packet
    assert "./scripts/public_review_gate.sh" in share_packet
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in share_packet
    assert "docs/openmako-review-card.svg" in share_packet
    assert "Use the review card only as a visual summary after checking the public gate." in share_packet
    assert "not evidence of external review, endorsement, stars, or reposts" in share_packet
    assert "Do not say it proves broad unknown-repository SWE repair." in share_packet
    assert "Do not say it replaces Claude Code, Codex, Cursor, Devin, or other agents." in share_packet
    assert "Do not ask readers to star, repost, or promote the repository." in share_packet
    assert "technical critique that links a concrete" in share_packet
    short_post_match = re.search(
        r"### Technical Review Request\n\n```text\n(?P<post>.*?)\n```",
        share_packet,
        flags=re.DOTALL,
    )
    assert short_post_match, "public share packet must include a short technical review post"
    assert len(short_post_match.group("post")) <= 280
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in share_packet.lower()


def test_openmako_review_card_is_boundary_focused_not_promotional() -> None:
    card = (ROOT / "docs" / "openmako-review-card.svg").read_text(encoding="utf-8")

    assert "OpenMako public review card" in card
    assert "Evidence checks for agent run records" in card
    assert "Current public proof covers: learning effect, patch scope," in card
    assert "test proof, and supplied-record audit." in card
    assert "Boundary check" in card
    assert "github.com/1966536805l-crypto/openmako/issues/2" in card
    assert "Does not claim broad repair or external review." in card
    assert "Tell us where" not in card
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in card.lower()


def test_public_review_gate_script_wraps_reviewer_proof_commands() -> None:
    script = ROOT / "scripts" / "public_review_gate.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "tests/test_agent_planner_contract.py::AgentPlannerContractTest" in text
    assert "tests/test_external_benchmark_multimodule_regression.py::ExternalBenchmarkMultimoduleRegressionTest" in text
    assert "tests/test_public_metadata.py" in text
    assert "./bin/openmako --no-trust-prompt evidence-court record from-jsonl" in text
    assert "./bin/openmako --no-trust-prompt evidence-court audit --ci --json" in text
    assert "expected Evidence Court audit exit 1" in text
    assert '"failure_class": "scope_violation"' in text
    assert '"failed_at": "scope_check"' in text
    assert "public-review-gate: auditing SWTBench patch artifact fixture" in text
    assert "examples/evidence_court/swtbench_patch_artifact.json" in text
    assert '"bucket": "mixed_test_source"' in text
    assert "public-review-gate: running supplied transcript adapter matrix" in text
    assert "bash scripts/supplied_transcript_adapter_matrix.sh" in text
    assert "public-review-gate: PASS" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_supplied_transcript_adapter_matrix_script_is_reviewer_runnable() -> None:
    script = ROOT / "scripts" / "supplied_transcript_adapter_matrix.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert 'export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"' in text
    assert "from-${adapter}-transcript" in text
    assert "smoke_adapter codex" in text
    assert "smoke_adapter claude" in text
    assert "smoke_adapter openhands" in text
    assert "smoke_adapter swe-agent" in text
    assert "smoke_adapter_missing_tests codex" in text
    assert "smoke_adapter_missing_tests claude" in text
    assert "smoke_adapter_missing_tests openhands" in text
    assert "smoke_adapter_missing_tests swe-agent" in text
    assert '"verdict": "PASS"' in text
    assert "--fail-on suspicious --json" in text
    assert '"verdict": "SUSPICIOUS"' in text
    assert '"failure_class": "missing_test_evidence"' in text
    assert "adapter-matrix: PASS" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_public_proof_card_wraps_gate_without_overclaiming() -> None:
    script = ROOT / "scripts" / "public_proof_card.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "openmako-public-proof-card: START" in text
    assert "proof-command: ./scripts/public_review_gate.sh" in text
    assert "./scripts/public_review_gate.sh" in text
    assert "openmako-public-proof-card: PASS" in text
    assert "focused learning-effect gate; public metadata boundary; supplied-record Evidence Court audit" in text
    assert "not-proof: broad unknown-repository SWE repair; external endorsement; star or repost traction" in text
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in text
    assert "issues/new?template=external-review-record.yml" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()


def test_reviewer_outreach_draft_requests_criticism_not_promotion() -> None:
    draft = (ROOT / "docs" / "REVIEWER_OUTREACH_DRAFT.md").read_text(encoding="utf-8")

    assert "Reviewer Outreach Draft" in draft
    assert "technical boundary criticism" in draft
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in draft
    assert "docs/TECHNICAL_REVIEW_PACKET.md" in draft
    assert "docs/PUBLIC_SHARE_PACKET.md" in draft
    assert "I'm not asking for endorsement, stars, reposts, or promotion." in draft
    assert "## Who To Send First" in draft
    assert "Maintainers or reviewers of coding-agent eval, benchmark, or CI tooling." in draft
    assert "agent reliability, test evidence, or\n   benchmark methodology" in draft
    assert "Do not send to general influencers before at least one public technical boundary\nreview exists." in draft
    assert "docs/REVIEWER_TARGETS.md" in draft
    assert "specific file, line, command, workflow, or missing artifact" in draft
    assert "Only after a reviewer has independently said the boundary is clear" in draft
    assert "Do not ask them to promote the project." in draft
    assert "public technical critique on issue #2" in draft
    assert "please star" not in draft.lower()
    assert "please repost" not in draft.lower()
    assert "10,000" not in draft
    assert "10000" not in draft
    assert "大咖" not in draft


def test_reviewer_target_map_prioritizes_public_technical_review() -> None:
    targets = (ROOT / "docs" / "REVIEWER_TARGETS.md").read_text(encoding="utf-8")

    assert "OpenMako Reviewer Target Map" in targets
    assert "Last refreshed: 2026-06-04." in targets
    assert "not proof of endorsement, promotion,\nstars, reposts, or external review" in targets
    assert "Verify each source again before contacting\nanyone" in targets
    assert "The first ask is technical boundary criticism." in targets
    assert "Do not ask for stars, reposts,\npromotion, or endorsement." in targets
    assert "issues/new?template=external-review-record.yml" in targets
    assert "Wave 1 request copy: `docs/WAVE1_REVIEW_REQUESTS.md`" in targets
    assert "Public target queue: `docs/WAVE1_PUBLIC_TARGET_QUEUE.md`" in targets
    assert "| 1 | SWE-bench / SWE-agent researchers and users |" in targets
    assert "https://arxiv.org/abs/2310.06770" in targets
    assert "https://github.com/swe-agent/swe-agent" in targets
    assert "| 1 | Terminal-Bench / Harbor evaluation community |" in targets
    assert "https://github.com/harbor-framework/terminal-bench" in targets
    assert "| 1 | Aider maintainer/community |" in targets
    assert "https://github.com/aider-ai/aider" in targets
    assert "| 1 | OpenHands maintainer/community |" in targets
    assert "https://github.com/OpenHands/OpenHands" in targets
    assert "| 2 | AI engineering writers and conference/community curators |" in targets
    assert "https://swyx.io/about" in targets
    assert "| 2 | Software engineering trade writers |" in targets
    assert "https://blog.pragmaticengineer.com/" in targets
    assert "General AI influencers who do not review code, tests, CI, or benchmark\n  methodology." in targets
    assert "Any private feedback channel that cannot later be linked as public evidence." in targets
    assert "Stop outreach and fix the repository first" in targets
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in targets.lower()


def test_wave1_public_target_queue_tracks_reachable_surfaces_without_claiming_outreach() -> None:
    queue = (ROOT / "docs" / "WAVE1_PUBLIC_TARGET_QUEUE.md").read_text(encoding="utf-8")

    assert "OpenMako Wave 1 Public Target Queue" in queue
    assert "not proof that outreach happened" in queue
    assert "not evidence of endorsement, stars, reposts, or external review" in queue
    assert "bash scripts/public_review_gate.sh" in queue
    assert "bash scripts/wave1_send_ready.sh TARGET" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh THREAD" in queue
    assert "This still does not send the\nmessage or record outreach as evidence." in queue
    assert "Send one short note at a time." in queue
    assert "Do not\ncreate a new issue in another project" in queue
    assert "project norms allow\nmeta/tooling review requests" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues" in queue
    assert "Issues page reachable; discussions page not public." in queue
    assert "https://github.com/harbor-framework/terminal-bench/discussions" in queue
    assert "Discussions page reachable; issues page also reachable." in queue
    assert "https://github.com/Aider-AI/aider/issues" in queue
    assert "https://github.com/OpenHands/OpenHands/issues" in queue
    assert "Existing Threads To Inspect Before Posting" in queue
    assert "These are candidate reading targets, not approved posting targets." in queue
    assert "Best current fit" in queue
    assert "Read-only / weak fit" in queue
    assert "Skip unless directly relevant" in queue
    assert "https://github.com/harbor-framework/terminal-bench/discussions/1357" in queue
    assert "cost of executing a test" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh terminal-bench-1357" in queue
    assert "https://github.com/OpenHands/benchmarks/issues/708" in queue
    assert "non-test patch stripping and patch-shape evidence" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-708" in queue
    assert "https://github.com/OpenHands/benchmarks/issues/718" in queue
    assert "rule changes affect comparability of historical runs" in queue
    assert "bash scripts/wave1_thread_reply_ready.sh openhands-benchmarks-718" in queue
    assert "https://github.com/OpenHands/OpenHands/issues/10767" in queue
    assert "Closed as not planned" in queue
    assert "Do not revive a closed main-repo issue for OpenMako outreach." in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/21" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/580" in queue
    assert "https://github.com/SWE-agent/SWE-agent/issues/563" in queue
    assert "https://github.com/Aider-AI/aider/issues/110" in queue
    assert "https://github.com/Aider-AI/aider/issues/2588" in queue
    assert "Do not revive a solved issue for OpenMako outreach." in queue
    assert "https://github.com/OpenHands/OpenHands/issues/12043" in queue
    assert "Do not post into a bug thread unless the comment addresses that thread's\nexisting question" in queue
    assert "If the fit is weak, skip the thread instead of making noise." in queue
    assert "Do not post the same generic message to multiple threads." in queue
    assert "bash scripts/wave1_review_request.sh swe-agent" in queue
    assert "bash scripts/wave1_review_request.sh terminal-bench" in queue
    assert "bash scripts/wave1_review_request.sh aider" in queue
    assert "bash scripts/wave1_review_request.sh openhands" in queue
    assert "Do not ask for stars, reposts, promotion, endorsement" in queue
    assert "Stop outreach and fix the repository first" in queue
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in queue.lower()


def test_wave1_thread_reply_ready_script_gates_and_prints_specific_messages() -> None:
    script = ROOT / "scripts" / "wave1_thread_reply_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Runs the public review gate" in text
    assert "This does not send messages, create issues" in text
    assert "terminal-bench-1357" in text
    assert "openhands-benchmarks-708" in text
    assert "openhands-benchmarks-718" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "decision: read the thread first; do not post if stale, closed, or off-topic" in text
    assert "cost/version/proof metadata" in text
    assert "332 / 424 mixed bucket" in text
    assert "patch-shape bucket separately from the final SWT-bench score" in text
    assert "expected F2P failure mode from source edits under model_patch" in text
    assert "where `mixed_test_source` is machine-readable and still separate from any score claim" in text
    assert "examples/evidence_court/swtbench_patch_artifact.json" in text
    assert "mixed test+source patch" in text
    assert "first-class verdict/metadata field rather than a post-hoc explanation" in text
    assert "artifact identity, not just the score delta" in text
    assert "output.jsonl can produce a different output.swtbench.jsonl" in text
    assert "eval-time patch stripping changes" in text
    assert "eval rule version, runner version or commit, input/output hashes" in text
    assert "patch-shape bucket" in text
    assert "metadata shape I mean: eval rule version, runner commit, input/output hashes" in text
    assert "while still not treating it as historical re-scoring or native OpenHands/SWTBench ingestion" in text
    assert "Same boundary question here" in text
    assert "runner commit + input/output hashes enough to compare artifacts" in text
    assert "should patch-shape be first-class metadata too" in text
    assert "https://github.com/1966536805l-crypto/openmako/issues/2" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        scripts.mkdir()
        (scripts / "wave1_thread_reply_ready.sh").write_text(text, encoding="utf-8")
        (scripts / "public_review_gate.sh").write_text(
            "#!/usr/bin/env bash\necho public-review-gate: PASS\n",
            encoding="utf-8",
        )
        for path in scripts.iterdir():
            path.chmod(0o755)

        result = subprocess.run(
            ["bash", str(scripts / "wave1_thread_reply_ready.sh"), "terminal-bench-1357"],
            cwd=tmp_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        assert "public-review-gate: PASS" in result.stdout
        assert "wave1-thread-reply-ready: thread=terminal-bench-1357" in result.stdout
        assert "leaderboard row without cost/version/proof metadata" in result.stdout
        assert "I would rather get criticism on the boundary than repo promotion" in result.stdout

        unknown = subprocess.run(
            ["bash", str(scripts / "wave1_thread_reply_ready.sh"), "unknown"],
            cwd=tmp_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert unknown.returncode == 2
        assert "unknown thread: unknown" in unknown.stderr


def test_wave1_send_ready_script_gates_before_printing_message() -> None:
    script = ROOT / "scripts" / "wave1_send_ready.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Runs the public review gate" in text
    assert "This does not send messages, create issues" in text
    assert "bash scripts/public_review_gate.sh" in text
    assert "bash scripts/wave1_review_request.sh \"$target\"" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        scripts = tmp_root / "scripts"
        scripts.mkdir()
        (scripts / "wave1_send_ready.sh").write_text(text, encoding="utf-8")
        (scripts / "public_review_gate.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\necho stub-gate-pass\n",
            encoding="utf-8",
        )
        (scripts / "wave1_review_request.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\necho stub-message-$1\n",
            encoding="utf-8",
        )
        for path in scripts.iterdir():
            path.chmod(path.stat().st_mode | 0o111)

        result = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "swe-agent"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert "stub-gate-pass" in result.stdout
        assert "wave1-send-ready: target=swe-agent" in result.stdout
        assert "stub-message-swe-agent" in result.stdout
        assert result.stdout.index("stub-gate-pass") < result.stdout.index("stub-message-swe-agent")

        unknown = subprocess.run(
            ["bash", str(scripts / "wave1_send_ready.sh"), "unknown"],
            cwd=tmp_root,
            check=False,
            text=True,
            capture_output=True,
        )
        assert unknown.returncode == 2
        assert "unknown target: unknown" in unknown.stderr


def test_wave1_review_requests_are_copyable_without_promotion() -> None:
    requests = (ROOT / "docs" / "WAVE1_REVIEW_REQUESTS.md").read_text(encoding="utf-8")

    assert "OpenMako Wave 1 Review Requests" in requests
    assert "not endorsement\nrequests, promotion requests" in requests
    assert "star requests, repost requests" in requests
    assert "not proof that outreach has happened" in requests
    assert "Send the short note first." in requests
    assert "bash scripts/public_proof_card.sh" in requests
    assert "openmako-public-proof-card: PASS" in requests
    assert "not-proof: broad unknown-repository SWE repair; external endorsement; star or repost traction" in requests
    assert "SWE-Bench / SWE-Agent Review Request" in requests
    assert "short notes for asking technical reviewers to check the v0.1 boundary" in requests
    assert "Can you point out where OpenMako v0.1 overclaims its evidence boundary?" in requests
    assert "Current public proof covers one focused learning-effect gate" in requests
    assert "It does not claim\nSWE-bench-scale repair." in requests
    assert "I'm mainly looking for README lines or proof-command gaps that overclaim." in requests
    assert "Terminal-Bench / Agent-Eval Review Request" in requests
    assert "Can you check OpenMako v0.1's evidence boundary?" in requests
    assert "README lines or proof-command gaps that overclaim" in requests
    assert "not a broad terminal-agent benchmark" in requests
    assert "Aider Community Review Request" in requests
    assert "useful or too noisy from a coding-agent user's view" in requests
    assert "It is not a replacement for Aider or any coding agent." in requests
    assert "OpenHands / Software-Agent Review Request" in requests
    assert "Could you check OpenMako v0.1 for overclaim?" in requests
    assert "not that OpenMako is a full software agent" in requests
    assert "Do not send the boundary-clear follow-up before a named reviewer posts public\n  feedback." in requests
    assert "Do not summarize private feedback as public evidence." in requests
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in requests.lower()


def test_wave1_review_request_script_prints_short_non_promotional_messages() -> None:
    script = ROOT / "scripts" / "wave1_review_request.sh"
    text = script.read_text(encoding="utf-8")

    assert script.exists()
    assert script.stat().st_mode & 0o111
    assert "Prints one short technical-boundary review request." in text
    assert "It does not send messages,\nask for stars, ask for reposts" in text
    assert "swe-agent" in text
    assert "terminal-bench" in text
    assert "aider" in text
    assert "openhands" in text
    assert "Can you point out where OpenMako v0.1 overclaims its evidence boundary?" in text
    assert "Can you check OpenMako v0.1's evidence boundary?" in text
    assert "I'm mainly looking for README lines or proof-command gaps that overclaim." in text
    assert "useful or too noisy from a coding-agent user's view" in text
    assert "Could you check OpenMako v0.1 for overclaim?" in text
    assert "unknown target" in text
    for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
        assert forbidden not in text.lower()

    for target, expected in (
        ("swe-agent", "Can you point out where OpenMako v0.1 overclaims its evidence boundary?"),
        ("terminal-bench", "Can you check OpenMako v0.1's evidence boundary?"),
        ("aider", "useful or too noisy from a coding-agent user's view"),
        ("openhands", "Could you check OpenMako v0.1 for overclaim?"),
    ):
        result = subprocess.run(
            ["bash", str(script), target],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0
        assert expected in result.stdout
        assert "Review issue: https://github.com/1966536805l-crypto/openmako/issues/2" in result.stdout
        for forbidden in ("please star", "please repost", "10,000", "10000", "大咖"):
            assert forbidden not in result.stdout.lower()

    unknown = subprocess.run(
        ["bash", str(script), "unknown"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert unknown.returncode == 2
    assert "unknown target: unknown" in unknown.stderr


def test_root_agent_notes_match_public_evidence_boundary() -> None:
    notes = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert notes.startswith("# OpenMako Local Agent Notes")
    assert "OpenMako is a focused evidence harness for coding-agent repair runs." in notes
    assert "not a public capability claim" in notes
    assert "focused learning-effect gate" in notes
    assert "tests/test_public_metadata.py" in notes
    for forbidden in FORBIDDEN_ROOT_AGENT_NOTES:
        assert forbidden not in notes


def test_quant_reports_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant"

    for filename in ARCHIVED_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()


def test_quant_examples_are_moved_out_of_repository_root() -> None:
    expected_locations = {
        "demo_capacity_comprehensive.py": ROOT / "examples" / "quant" / "capacity",
        "demo_capacity_validation.py": ROOT / "examples" / "quant" / "capacity",
        "example_tick_price_validator.py": ROOT / "examples" / "quant" / "tick_price",
        "realistic_t1_trades.csv": ROOT / "examples" / "quant" / "data",
    }

    for filename in EXAMPLE_ROOT_QUANT_FILES:
        assert not (ROOT / filename).exists()
        assert (expected_locations[filename] / filename).exists()


def test_legacy_quant_test_artifacts_are_archived_out_of_repository_root() -> None:
    archive_dir = ROOT / "docs" / "archive" / "quant" / "legacy_tests"

    for filename in LEGACY_ROOT_QUANT_TEST_FILES:
        assert not (ROOT / filename).exists()
        assert (archive_dir / filename).exists()


def test_high_risk_planning_docs_are_not_public_claims() -> None:
    for relative_path in INTERNAL_PLANNING_DOCS:
        text = (ROOT / relative_path).read_text(encoding="utf-8")

        assert "current public proof is the focused learning-effect gate" in text
        assert "not the current public v0.1 capability claim" in text or "not a public capability claim" in text

    market_scan = (ROOT / "docs" / "MARKET_TOOL_COPY_SCAN.md").read_text(encoding="utf-8")
    assert "Highest-Value Things To Steal Next" not in market_scan

    model_setup = (ROOT / "docs" / "OPENAI_COMPATIBLE_SETUP.md").read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_PUBLIC_DOC_VENDOR_ENDPOINTS:
        assert forbidden not in model_setup
