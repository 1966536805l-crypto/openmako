---
name: trade-plan-review
description: Use when reviewing a proposed stock trade plan, checklist, thesis, entry, stop, target, risk/reward, execution timing, or post-trade journal entry before action.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, trading-plan, review, checklist, discipline]
    related_skills: [risk-position-sizing, technical-trading-analysis, news-sentiment-analysis]
---

# Trade Plan Review

## Overview

Use this skill to critique a user's proposed trade before they act. The goal is not to say yes or no reflexively, but to expose missing assumptions, define invalidation, check risk, and make the plan executable only if it already respects the user's limits.

## When to Use

- User asks "can I buy/sell/hold this?"
- User provides entry, stop, target, thesis, or position size
- User wants a pre-trade checklist or second opinion
- User wants to review a losing trade, missed trade, or journal entry

## Review Order

1. **Thesis**: what exactly must be true for the trade to work?
2. **Setup**: trend, level, catalyst, or pattern.
3. **Trigger**: what confirms action now rather than later?
4. **Invalidation**: what proves the thesis wrong?
5. **Risk**: position size, max loss, portfolio concentration.
6. **Reward**: realistic target and risk/reward.
7. **Execution**: liquidity, gap risk, limit-up/down risk, event timing.
8. **Exit plan**: stop, partial take-profit, trailing logic, time stop.

## Output Template

```text
Verdict: ready / needs changes / avoid for now
Main issue:
What is good:
What is missing:
Risk check:
Trigger:
Invalidation:
Revised plan:
```

Use "avoid for now" when risk is undefined, the thesis is emotional, the stop is missing, or the plan depends on guaranteed movement.

## Behavioral Guardrails

- Do not intensify fear of missing out.
- Do not tell the user to revenge trade or average down without a risk cap.
- Do not provide personalized financial advice as certainty.
- Encourage waiting when conditions are unclear.
- Never place or simulate a broker order.

## Common Pitfalls

1. Reviewing only upside and skipping invalidation.
2. Accepting a wide stop that breaks the user's max loss.
3. Treating conviction as evidence.
4. Moving the stop after entry without a written reason.

## Verification Checklist

- [ ] Thesis, trigger, and invalidation are distinct
- [ ] Risk/reward and max loss are calculated or requested
- [ ] Execution risks are mentioned
- [ ] The plan is allowed to be "no trade"
- [ ] No trade execution is performed
