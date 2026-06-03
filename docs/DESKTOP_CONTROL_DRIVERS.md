# Desktop Control Drivers

Date: 2026-05-26

Scope: OpenMako local desktop observation and control stack. This document is
about legal, open-source or public-interface integration. Do not copy
closed-source desktop-agent code, prompts, constants, private APIs, product
strings, or proprietary implementation details.

## Recommended Local Stack

OpenMako should keep desktop control split into three replaceable layers:

- Peekaboo-style observation driver: capture screenshots and window/app context
  through macOS-approved screen capture interfaces.
- DesktopCtl-style execution driver: perform explicit mouse, keyboard, hotkey,
  app activation, and window actions through Accessibility-approved interfaces.
- Screenbox-style structured state driver: merge screenshot, AX tree, OCR, SoM,
  and optional grid data into stable tokens used by the daemon and evals.

The CLI contract remains OpenMako-owned:

```text
observe -> tokenize -> decide -> act -> verify -> record
```

External drivers are adapters behind that contract. They must not own
permission policy, trajectory format, query events, STOP-file behavior, or
high-risk goal blocking.

## Driver Responsibilities

Peekaboo-style observation:

- capture full-screen or window-scoped screenshots;
- report capture failures and missing permissions as typed errors;
- provide image metadata such as dimensions, timestamp, display id, and hash;
- avoid hidden remote streaming or unbounded background recording.

DesktopCtl-style execution:

- expose deterministic primitives: click, move, type, hotkey, scroll, open,
  activate, and optional window focus;
- accept only reviewed, policy-approved actions from OpenMako;
- return action status, target metadata, and error class;
- never bypass `--execute --reviewed --allow-actions` gates.

Screenbox-style state:

- turn visual and accessibility evidence into structured desktop tokens;
- preserve observation id, screen hash, token id, bounds, label/source, and
  confidence;
- allow rechecking a target before action so stale-coordinate clicks fail
  closed;
- keep OCR/SoM/grid as evidence sources, not as direct authority to act.

## Why Structured Tokens Win

Pure screenshot agents usually degrade into guessing coordinates. That is weak
for OpenMako because:

- pixels are not stable across scale, theme, language, display, and window
  movement;
- a screenshot alone cannot prove that the intended target still exists when
  the click fires;
- replay and autopsy become vague because the decision was "click near here",
  not "click token M017 from observation obs_abc with screen hash H".

Structured token plus deterministic execution is stronger:

- the decider chooses a token, not raw coordinates;
- the executor revalidates observation id, screen hash, bounds, and target
  semantics before acting;
- every action is replayable from `query_events`, `trajectory`, screenshot
  hashes, and token ids;
- poison tests can force stale targets, permission failures, and semantic
  verification failures instead of only checking that a screenshot changed.

Rule: the model may propose intent, but the runtime must convert intent into a
bounded token action and verify it deterministically.

## macOS Permissions

Local desktop control depends on host OS permissions. OpenMako cannot grant
them automatically.

Required permissions:

- Screen Recording: needed for screenshot and screen/window observation.
- Accessibility: needed for AX tree inspection and mouse/keyboard control.
- Automation: may be needed when opening or controlling specific apps through
  Apple Events.

Failure behavior:

- missing Screen Recording blocks observation/tokenization;
- missing Accessibility blocks AX and side-effect control;
- missing Automation blocks app-specific open/control paths;
- the daemon must pause or fail closed and write evidence instead of inventing
  screen state.

Do not request broad permissions from a hidden background process. Operators
should be able to see which local binary or terminal app is authorized.

## Overnight Daemon Risk Boundary

`mako desktop-daemon` and `mako desktop-overnight` are bounded local loops, not
general-purpose remote-control systems.

Required boundaries:

- dry-run by default;
- real side effects require `--execute --reviewed --allow-actions`;
- STOP file checked before every daemon step;
- max steps, max minutes, delay, and max tasks enforced by the runner;
- at most one desktop side-effect action per step;
- high-risk goals blocked before action, including payments, trading,
  credential handling, destructive deletion, and message sending;
- all non-ok terminal states write state, query events, trajectory, and autopsy
  when the current contract requires it.

Operational risks:

- stale UI state can cause wrong-target actions if token fences are skipped;
- sleeping displays, locked screens, app updates, modal dialogs, and permission
  prompts can invalidate assumptions;
- long-running loops can amplify small targeting bugs unless step budgets,
  loop detection, and STOP checks are mandatory;
- sensitive apps must remain outside the allowlist until evals prove safe
  behavior for their workflows.

## Legal Integration Boundary

Allowed:

- use open-source packages according to their licenses;
- call public OS APIs and documented CLI interfaces;
- write clean-room adapters that match OpenMako's own driver protocol;
- cite upstream projects and licenses in attribution docs.

Forbidden:

- copying closed-source source code, prompts, private constants, or proprietary
  strings;
- reverse engineering private product behavior to bypass access controls;
- hiding background control from the local operator;
- adding driver code that weakens OpenMako permission gates.

## Acceptance Commands

Documentation-only acceptance:

```bash
test -f docs/DESKTOP_CONTROL_DRIVERS.md
rg -n "Peekaboo|DesktopCtl|Screenbox|structured token|Screen Recording|STOP|--execute --reviewed --allow-actions" docs/DESKTOP_CONTROL_DRIVERS.md README.md
```

If the checkout has `.git`, also inspect:

```bash
git diff -- docs/DESKTOP_CONTROL_DRIVERS.md README.md
```

Runtime smoke commands after drivers are installed and macOS permissions are
granted:

```bash
mako desktop tokenize --include-grid --json
mako desktop decide "点击 Search" --json
mako desktop daemon "搜索 OpenMako" --max-steps 3
mako desktop daemon "搜索 OpenMako" --execute --reviewed --allow-actions --max-steps 3 --delay 1
touch .quantagent/desktop/agent/STOP
mako desktop-daemon status
```

Eval gate:

```bash
mako desktop-eval run --suite suite_l4 --duration-minutes 60
```
