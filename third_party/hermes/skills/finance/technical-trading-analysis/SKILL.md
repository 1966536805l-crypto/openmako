---
name: technical-trading-analysis
description: Use when evaluating chart structure, technical indicators, momentum, support/resistance, entry triggers, exits, or short-term trading setups for stocks without executing trades.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, trading, technical-analysis, indicators, charts]
    related_skills: [a-stock-market-analysis, quant-backtesting, risk-position-sizing]
---

# Technical Trading Analysis

## Overview

Use this skill to analyze price action, trend, volume, momentum, volatility, and chart patterns. The goal is to produce a disciplined read of what the chart currently supports, what would confirm it, and what would invalidate it.

Technical signals are probabilistic. Do not claim certainty, do not predict exact future prices as facts, and do not use technical analysis alone to justify large risk.

## When to Use

- User asks for K-line, MACD, RSI, KDJ, ATR, OBV, SAR, Williams %R, moving averages, or support/resistance
- User asks for entry, stop, take-profit, breakout, pullback, or trend continuation conditions
- User wants a chart or indicator interpretation from local historical data
- User asks whether a signal is bullish, bearish, or neutral

## Local Tooling

Run from:

```bash
cd /Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst
```

Useful modules and commands:

```bash
python3 stock_analyst_pro.py 600519
python3 stock_analyst_pro.py 600519 --chart
python3 test_technical_timing.py
python3 test_timing_confirmed.py
```

Relevant files include:

- `advanced_technical_analysis.py`
- `technical_analysis.py`
- `modules/technical_timing_model.py`
- `modules/signal_explainer.py`
- `visualization.py`

## Signal Framework

Analyze in this order:

1. **Regime**: trending, ranging, high-volatility, low-liquidity, or unclear.
2. **Trend**: price vs key moving averages, slope, higher highs/lows.
3. **Momentum**: MACD, RSI, KDJ, Williams %R, divergence.
4. **Volume**: OBV, volume expansion, failed breakout volume.
5. **Volatility**: ATR and position-size implications.
6. **Levels**: support, resistance, gap zones, invalidation.
7. **Trigger**: the exact condition needed before action.

If indicators conflict, say that the setup is mixed and identify what would resolve the conflict.

## Output Style

Use compact, trader-friendly structure:

- Bias: bullish, bearish, neutral, or mixed
- Evidence: 3-5 bullets grounded in indicators or price action
- Trigger: condition required for confirmation
- Invalidation: condition that proves the idea wrong
- Risk note: volatility, liquidity, or event risk

## Common Pitfalls

1. Calling every oversold reading a buy signal. Oversold can stay oversold in a downtrend.
2. Ignoring confirmation volume on breakouts.
3. Using a stop that is tighter than normal ATR noise.
4. Overfitting a pattern name when the structure is unclear.

## Verification Checklist

- [ ] The timeframe is stated or inferred cautiously
- [ ] Indicators are interpreted in context
- [ ] Conflicting signals are disclosed
- [ ] Entry trigger and invalidation are separate
- [ ] No order is placed automatically
