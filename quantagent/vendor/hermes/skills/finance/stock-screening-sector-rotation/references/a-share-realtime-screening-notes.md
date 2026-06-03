# A-share realtime screening notes

Session-derived workflow for rapid A-share scans using public Eastmoney quote endpoints.

## Practical scan pattern

1. Use Eastmoney full-market quote list as the current universe:
   - Endpoint: `https://push2.eastmoney.com/api/qt/clist/get`
   - Useful params: `fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23`, `fid=f3`, `pn`, `pz`, `fields=f12,f14,f2,f3,f5,f6,f8,f9,f10,f15,f16,f17,f18,f20,f21,f23,f62,f124`
   - `f12` code, `f14` name, `f2` price, `f3` change %, `f6` amount, `f8` turnover, `f9` PE, `f10` volume ratio, `f15/f16/f17/f18` high/low/open/prev close, `f20/f21` market cap, `f23` PB, `f62` main inflow.
2. Fetch daily K-lines only for a reduced pool to avoid unnecessary load:
   - Endpoint: `https://push2his.eastmoney.com/api/qt/stock/kline/get`
   - `secid=1.CODE` for Shanghai-style `6/9` codes, else `0.CODE`; `klt=101`, `fqt=1`, `lmt=60-90`.
3. For full-market cost-performance screening, separate the score from short-term momentum:
   - Cost-performance: valuation + drawdown/volatility risk + trend + liquidity/fund flow.
   - Limit-up opportunity: today’s strength, close near high/limit, volume/turnover, main inflow, market-cap tradability.
   - Technical opportunity: trend/momentum/volume can produce many `>=80` candidates and is not the same as “性价比90”.
4. Be explicit about which score is being used when the user says “90分/80分”: ask only if needed, otherwise infer from the immediately preceding phrase (e.g. “性价比高” means cost-performance, not heat/opportunity).

## Output lessons

- If the user asks for only names/codes (e.g. “只说三支名字”, “只说名字和代码”), output exactly that and no rationale.
- For fast trading questions, keep warnings minimal: one short uncertainty sentence is enough unless the user asks for detailed risk.
- Do not present a “涨停机会最大” result as guaranteed; phrase it as current model’s top-ranked candidate.
