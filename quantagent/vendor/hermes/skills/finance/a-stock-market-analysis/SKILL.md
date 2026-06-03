---
name: a-stock-market-analysis
description: Use when analyzing A-share stocks, Chinese market data, company fundamentals, price action, or user-provided stock codes. Produces evidence-based research, avoids investment guarantees, and uses local stock-analyst tools when available.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, stocks, a-shares, market-data, research]
    related_skills: [technical-trading-analysis, risk-position-sizing, stock-screening-sector-rotation]
---

# A-Share Market Analysis

## Overview

Use this skill for Chinese A-share stock analysis and market research. Treat every result as decision support, not personalized investment advice. Be explicit about uncertainty, data freshness, and assumptions.

Prefer local tools under `/Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst` when the user asks for a concrete stock code. Do not invent prices, financial metrics, news, or filings. If live data is unavailable, say so and work from provided data or historical local files.

## When to Use

- User asks to analyze an A-share stock such as `600519`, `000858`, or `601318`
- User asks whether a stock is strong, weak, risky, undervalued, overbought, or suitable to watch
- User wants a concise market read using technicals, fundamentals, sector context, and risk
- User provides screenshots, tables, CSVs, or exported quotes and wants interpretation

Do not use this skill to place trades, bypass broker confirmation, or promise returns.

## Local Tooling

Working directory:

```bash
cd /Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst
```

Common commands:

```bash
python3 stock_analyst.py 600519
python3 stock_analyst.py 600519 --quick
python3 stock_analyst.py 600519 000858 601318
python3 stock_analyst_pro.py 600519
python3 stock_analyst_pro.py 600519 --chart
python3 stock_analyst_pro.py 600519 --compare
```

If a Tushare token or other credential is needed, never print it, log it, or copy it into prompts. Check only whether configuration exists.

## Analysis Template

1. **Data status**: source, timestamp if known, whether data is live or cached.
2. **Trend**: higher timeframe direction, moving averages, price structure.
3. **Momentum**: RSI, MACD, KDJ, Williams %R, volume confirmation.
4. **Risk**: volatility, ATR, drawdown zone, stop invalidation level.
5. **Context**: sector, market regime, liquidity, news or policy if verified.
6. **Decision support**: watchlist, avoid, wait for confirmation, or risk-managed plan.

Use neutral wording such as "bullish evidence", "bearish risk", "needs confirmation", and "invalidated if". Avoid "must buy", "guaranteed", or "sure win".

## Security and Privacy

- Never log full user trading notes, account screenshots, phone numbers, IDs, or broker details.
- Never auto-open user-submitted URLs.
- Never execute user-provided code or formulas.
- Redact account balances unless the user explicitly asks for position sizing and the values are needed.

## Common Pitfalls

1. Treating model output as a price oracle. Always ground conclusions in data.
2. Mixing short-term technical signals with long-term investment claims.
3. Ignoring liquidity, suspension risk, ST status, and limit-up/limit-down constraints.
4. Presenting a single target price without invalidation and risk framing.

## Verification Checklist

- [ ] Stock code and market are confirmed
- [ ] Data freshness is stated
- [ ] No secrets or account identifiers are exposed
- [ ] Recommendation is framed as research, not financial advice
- [ ] Risks and invalidation conditions are included
