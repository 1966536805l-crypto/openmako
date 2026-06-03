---
name: risk-position-sizing
description: Use when calculating trading risk, stop loss, take profit, position size, Kelly-style sizing, batch entry plans, portfolio exposure, and risk limits for stock trades.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, risk, position-sizing, portfolio, money-management]
    related_skills: [a-stock-market-analysis, technical-trading-analysis, trade-plan-review]
---

# Risk and Position Sizing

## Overview

Use this skill to turn a trading idea into a risk-bounded plan. Focus on capital preservation, invalidation levels, position sizing, and portfolio exposure. The agent may calculate, critique, and explain risk, but must not place trades or pressure the user to act.

## When to Use

- User asks how many shares to buy or how much capital to allocate
- User asks for stop-loss, take-profit, risk/reward, or batch entry plans
- User provides account size, entry price, stop price, or target price
- User wants to control max loss, drawdown, or concentration risk

## Local Tooling

Run from:

```bash
cd /Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst
```

Relevant files:

- `money_management.py`
- `risk_assessment.py`
- `modules/risk_position_sizer.py`
- `modules/portfolio_constraint_engine.py`
- `modules/confidence_evaluator.py`
- `test_trading_coach.py`

## Core Formulas

Risk per share:

```text
risk_per_share = abs(entry_price - stop_price)
```

Max position by risk budget:

```text
shares = floor((capital * risk_percent) / risk_per_share)
```

Position value cap:

```text
shares = min(shares, floor((capital * max_position_percent) / entry_price))
```

Risk/reward:

```text
risk_reward = abs(target_price - entry_price) / abs(entry_price - stop_price)
```

For A-shares, round share quantities to valid board lots when appropriate.

## Output Template

- Capital used for calculation
- Entry, stop, target, and invalidation
- Risk per share and total max loss
- Suggested shares or position percentage
- Risk/reward ratio
- Batch plan if requested
- Concentration warning if position is large

If the user has not provided capital or stop price, ask for the missing value or provide a formula-only answer.

## Safety Rules

- Never ask for broker passwords, account numbers, or API keys.
- Avoid storing or logging portfolio details.
- Treat screenshots as sensitive.
- If the plan risks more than the stated limit, reject the plan clearly.

## Common Pitfalls

1. Sizing from confidence instead of invalidation distance.
2. Using a stop level that has no market-structure basis.
3. Ignoring correlation across positions in the same sector.
4. Averaging down without a pre-defined max exposure.

## Verification Checklist

- [ ] Stop price or invalidation is explicit
- [ ] Max loss is shown in currency and percent
- [ ] Share count respects position caps
- [ ] Portfolio concentration is considered
- [ ] No sensitive account details are repeated unnecessarily
