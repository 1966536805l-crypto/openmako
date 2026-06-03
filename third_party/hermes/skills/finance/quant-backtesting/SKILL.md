---
name: quant-backtesting
description: Use when designing, running, or reviewing stock strategy backtests, performance metrics, historical simulations, and strategy comparisons while checking for overfitting and future leakage.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [finance, quant, backtesting, strategies, validation]
    related_skills: [technical-trading-analysis, risk-position-sizing, stock-screening-sector-rotation]
---

# Quant Backtesting

## Overview

Use this skill for historical strategy testing and performance review. A backtest is a hypothesis check, not proof that a strategy will work live. Always look for future leakage, survivorship bias, transaction costs, liquidity constraints, and parameter overfitting.

## When to Use

- User asks to backtest trend, grid, mean reversion, momentum, dual moving average, or custom strategies
- User asks to compare strategy returns, Sharpe ratio, drawdown, win rate, or equity curve
- User wants to know whether a signal has worked historically
- User asks to validate a trading rule before using it

## Local Tooling

Run from:

```bash
cd /Users/euhualihuawaiigeeeeegehanggeyewo/stock-analyst
```

Common commands:

```bash
python3 stock_analyst_pro.py 600519 --backtest trend
python3 stock_analyst_pro.py 600519 --backtest grid
python3 stock_analyst_pro.py 600519 --backtest mean_reversion
python3 stock_analyst_pro.py 600519 --compare
python3 -m pytest backtest/test_backtest.py
```

Relevant files:

- `backtest_engine.py`
- `trading_strategies.py`
- `backtest/engine.py`
- `backtest/performance.py`
- `backtest/cost_model.py`
- `quality/future_leak_detector.py`

## Review Checklist

For every backtest, report:

- Data range and symbol universe
- Initial capital, transaction costs, slippage assumptions
- Annualized return, total return, Sharpe ratio, max drawdown, win rate
- Number of trades and average holding period
- Worst period and whether the strategy survived it
- Parameters tested and whether they were tuned on the same sample

## Bias Controls

- Use only data available at the decision timestamp.
- Include fees and slippage, especially for short-term strategies.
- Avoid ranking by final return alone; compare drawdown-adjusted metrics.
- If optimizing parameters, split train/test periods or use walk-forward validation.
- Treat small trade counts as weak evidence.

## Common Pitfalls

1. Optimizing on one stock and calling it a general strategy.
2. Forgetting limit-up/limit-down and suspension constraints in A-shares.
3. Reporting high return without drawdown and trade count.
4. Ignoring market regime: bull-market-only performance can be misleading.

## Verification Checklist

- [ ] No future data is used in signal generation
- [ ] Costs and slippage are included or explicitly absent
- [ ] Performance is not summarized by return alone
- [ ] Out-of-sample or regime caveats are stated
- [ ] Result is framed as historical simulation, not a guarantee
