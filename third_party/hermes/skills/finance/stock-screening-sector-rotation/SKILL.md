---
name: stock-screening-sector-rotation
description: Use when screening stocks, ranking candidates, comparing sectors, analyzing industry rotation, or building watchlists using multi-factor and sector-strength evidence.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, screener, sectors, rotation, factors, watchlist]
    related_skills: [a-stock-market-analysis, quant-backtesting, news-sentiment-analysis]
---

# Stock Screening and Sector Rotation

## Overview

Use this skill to find and rank candidates rather than analyze only one ticker. The goal is a watchlist with clear selection criteria, sector context, and reasons to include or exclude each name.

## When to Use

- User asks for stock screening, watchlists, strongest sectors, hot themes, or rotation
- User wants multi-factor ranking or industry comparison
- User asks to scan popular stocks or market-wide candidates
- User wants to filter by trend, momentum, valuation, risk, or volume

## Local Tooling

Run from:

```bash
cd /Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst
```

Useful files:

- `smart_stock_screener.py`
- `market_scanner.py`
- `full_market_scanner.py`
- `multi_factor_selector.py`
- `modules/multi_factor_ranker.py`
- `modules/multi_factor_selector.py`
- `modules/sector_analysis.py`
- `modules/sector_rotation_model.py`

Potential commands depend on current scripts:

```bash
python3 smart_stock_screener.py
python3 market_scanner.py
python3 full_market_scanner.py
```

If a script requires data credentials or live data and fails, report the failure without exposing secrets.

## Screening Framework

Define filters before running:

- Universe: A-shares, index constituents, watchlist, sector, or supplied tickers
- Trend: moving average alignment, breakout, relative strength
- Quality: profitability, growth, balance sheet if data exists
- Risk: volatility, drawdown, ST/suspension risk, liquidity
- Timing: momentum confirmation and volume
- Sector: industry strength, rotation phase, policy/news catalyst if verified

Rank candidates with reasons. Avoid presenting a top list as a buy list.

## Output Template

Use a table when possible:

```text
Rank | Code | Name | Sector | Score | Strength | Main Risk | Watch Trigger
```

When the user asks for terse trading output, obey the requested shape exactly. Examples: if they say "只说三支名字", output only three names; if they say "只说名字和代码", output only `Name Code` lines with no extra rationale. For fast follow-ups, do not re-explain the whole methodology unless asked.

End with "what would change the ranking" so the user understands the conditions, unless the user explicitly requested names/codes only.

See `references/a-share-realtime-screening-notes.md` for the Eastmoney full-market scan pattern and score-definition pitfalls learned from realtime A-share screening.

## Common Pitfalls

1. Ranking without a defined universe.
2. Mixing valuation and short-term momentum into one unexplained score.
3. Ignoring liquidity and trading suspension risk.
4. Treating hot sectors as permanently strong.
5. Confusing opportunity/heat scores with cost-performance scores. When users ask “90分” after discussing “性价比”, re-rank with valuation/risk-adjusted cost-performance rather than short-term technical heat.
6. Over-answering rapid screening requests. If the user asks for only a few names, return only the requested names/codes.

## Verification Checklist

- [ ] Universe and filters are stated
- [ ] Ranking criteria are visible
- [ ] Sector context is included
- [ ] Watch triggers are separate from buy recommendations
- [ ] Data limitations are disclosed
