# 🚀 Investor Engine — Build Report

**Built:** 2026-05-12 (Tue) — Mission Control v2
**Route:** http://127.0.0.1:8888/investor_engine (or sidebar → "Investor Engine")
**Author:** PenPen (subagent)

---

## What it is

A single executive-level dashboard that unifies every wheel-strategy
data source into one screen: signals → composite scoring → candidates →
positions → P&L → backtest verdicts. Replaces the need to bounce between
the Wheel dashboard, the four signal endpoints, Alpaca, and the forecaster.

---

## Files added / modified

| File | Type | Purpose |
|------|------|---------|
| `mission_control/investor_engine.html` | NEW | The dashboard (Chart.js + vanilla JS, no framework). |
| `mission_control/server.py` | MODIFIED | Added 7 new endpoints + 10 helper functions. |
| `mission_control/index.html` | MODIFIED | Added sidebar nav link (with NEW badge). |
| `mission_control/test_investor_engine.py` | NEW | 19-case unit test suite (deterministic, no network). |
| `memory/wheel/account_ledger.json` | NEW | Multi-account ledger schema (paper now, live later). |

## New endpoints (all GET, all JSON)

| Route | TTL cache | Purpose |
|-------|-----------|---------|
| `/api/investor_engine/composite` | 60s | Everything-at-once payload — dashboard's single fetch. |
| `/api/investor_engine/alpaca` | 30s | Account + positions + orders + **all P&L fields** + sector exposure + equity curve. |
| `/api/investor_engine/pnl` | 60s | Multi-period P&L (lifetime / YTD / MTD / by_month×12 / by_year / by_account). |
| `/api/investor_engine/candidates` | 60s | Composite picks ranked, with `in_universe` flag + sector. |
| `/api/investor_engine/insights` | 5min | 7 rotating PenPen-says insights composed server-side. |
| `/api/investor_engine/ledger` | — | Account ledger (paper + future live). |
| `/api/investor_engine/tax_export/<year>` | — | CSV of closed cycles for a tax year (downloadable). |
| `/investor_engine` | — | Static HTML route. |

## What's on the page

1. **🐧 PenPen Says** — rotating insights banner, fades every 8s.
2. **HERO row (4 cards)** — 🏁 Starting Capital, 💰 Current Equity, 📈 Total Net P&L (with $ and %), 🎯 Today's P&L.
3. **💵 Net Positions strip (5 cards)** — Realized, Unrealized, Open Premium at Risk, Premium Gross, Premium Net.
4. **📊 Performance by Period** — Lifetime / YTD / MTD toggle, stats grid (P&L, Wins, Losses, Win Rate, Premium Net, Spend, Trades).
5. **📈 Equity Curve** — line chart with $100K dashed reference line (Chart.js custom plugin).
6. **🧱 Monthly P&L** — 12-month bar chart, realized bars + purple premium-net overlay.
7. **🩺 Signal Health strip** — Politician 🏛️ / Top Trader 🐋 / Analyst 🏦 / News 📰 with top-3 picks, above-threshold count, freshness.
8. **🧠 Forecaster panel** — top 5 composite picks, sources, sector, in-universe flag, weights used.
9. **🆕 Candidates** — composite picks NOT in universe (would be added on next universe refresh).
10. **📍 Open Positions** — Alpaca live with mark-to-market unrealized.
11. **⚠️ Risk & Concentration** — cash, equity, OBP, $-at-risk vs equity, sector exposure with cap.
12. **📜 Recent Activity** — last 10 trade-journal events.
13. **🟡 Working Orders** — live open orders from Alpaca.
14. **🔬 Backtest Verdicts** — per-source vs SPY (forecaster, top_trader, analyst, politician, news).
15. **📅 Period History Table** — Year and month rows; year selector + 📥 **Export Tax Year CSV** button.
16. **⚙️ Wheel Config** — read-only snapshot (safety, risk, paper overrides, VIX regime).

## How P&L is computed

The new `_walk_wheel_trades_for_pnl()` walks `memory/wheel/trades.jsonl`:

| Trade-journal action | What happens |
|----------------------|--------------|
| `submitted` + `side=sell_to_open` | +credit (premium_gross AND premium_net), open leg tracked, strike×100×qty added to open-premium-at-risk. |
| `submitted` + `side=buy_to_close` | -debit (spend); realizes `credit - debit`; reduces premium_net; removes leg from at-risk. |
| `expired_otm` | Realizes the full credit; ticks wins; closes leg. |
| `assigned` | Realized = 0 (rolls into stock cost basis); closes leg. |
| `called_away` | Realized = `call_premium + (strike - stock_cost_basis) × 100`. |
| `simulated` | Skipped (dry-run, never hit market). |

Wins / losses are counted only on closed cycles. Win rate = wins / (wins + losses).
Period buckets (`by_month`, `by_year`) accumulate the same totals so YTD / MTD
breakdowns are O(1) lookups.

## Account ledger (forward-looking)

`memory/wheel/account_ledger.json` stores **multiple accounts** under one
schema so the dashboard already understands paper-vs-live:

```jsonc
{
  "accounts": [{
    "id": "paper-2026-05-12",
    "type": "paper",                 // or "live"
    "starting_capital": 100000,
    "started_at": "...", "ended_at": null,
    "deposits": [], "withdrawals": []
  }],
  "active_account_id": "paper-2026-05-12"
}
```

**When Scott flips to live:**

1. Append a new entry to `accounts[]` with `type: "live"`, fresh starting capital.
2. Set `ended_at` on the paper entry.
3. Update `active_account_id` to the new live entry.
4. The dashboard hero re-points automatically; period history retains the paper run.

The new `📥 Export Tax Year CSV` button serves `/api/investor_engine/tax_export/<year>`
which returns columns: `symbol, occ_symbol, open_date, close_date, holding_period_days,
premium_credit, close_debit, realized_pnl, outcome`. Tax-ready the moment we have closes.

## Test coverage

`python3 mission_control/test_investor_engine.py` — **19 cases, all pass**:

- Cache TTL (hits + expiry)
- Candidates exclude universe members + sorted desc
- Top-10 composite shape
- Signal block missing-file safety
- Insights array non-empty + every item a string
- Composite payload shape (all keys present)
- OCC option symbol stripping (`KO260618P00077500` → `KO`)
- P&L: sell+buy-to-close cycle realizes correctly (profit + loss)
- P&L: expired_otm keeps full credit, ticks win
- P&L: simulated is skipped
- P&L: open-premium-at-risk calculation
- Period payload: 12 monthly buckets, all `YYYY-MM` format
- Account ledger loads, starting_capital surfaced
- Alpaca payload has all 10 required P&L fields
- Tax-export CSV route returns 200 + correct mimetype + header row

## Performance

- Composite endpoint cold: ~70-90ms (Alpaca + 5 file reads).
- Cached: <2ms.
- Front-end: single composite fetch → all sections paint together. Auto-refresh every 60s.

## Known limitations & future work

1. **`submitted` ≠ `filled` proxy.** The walker treats `action == "submitted"`
   as filled (Alpaca paper-fills sells fast in practice). For 100% accuracy
   on the gross-premium number we should cross-reference `/v2/orders?status=filled`
   and adjust by canceled/rejected orders. Currently this slightly overstates
   `premium_gross` if any sell order didn't fill (right now PG's submitted
   order is in trades.jsonl but didn't end up in positions — walker counts it).

2. **EOD log not yet wired.** `memory/wheel/eod_log.jsonl` doesn't exist yet,
   so today's P&L falls back to `equity - starting_capital`. Once the
   wheel runner writes an EOD snapshot daily, today's number becomes a
   true day-over-day delta. The reader already supports it — no UI change
   needed when it lands.

3. **Equity curve is a single point** until EOD log accumulates.
   Already handled gracefully — shows current equity vs the $100K reference.

4. **Sector concentration insight at 100%** because there's only 1 position.
   Threshold pill goes red as designed; once book diversifies, this will
   settle naturally.

5. **Backtest verdicts.** Forecaster backtest reports `no_snapshots_yet`
   until ~5 weeks of weekly composite snapshots accrue. Other signal
   backtests display whatever their respective JSONs report. No work
   needed here, just time.

6. **Multi-account display.** Schema and `by_account[]` payload are
   ready; the period-history table currently shows one account's rows.
   When the live account is added, history table needs a small UI tweak
   to group/expand by account_id.

## How to extend

- **Add a new insight template:** edit `_ie_build_insights()` in server.py.
- **Add a new signal source:** add a `_signal_block(...)` call in `_ie_build_composite()` + a card in `renderSignalHealth()`.
- **Add a new chart:** drop a `<canvas>` + a `render*Chart(data)` function. Composite payload already carries `pnl.by_month`, `pnl.by_year`, `alpaca.equity_curve`, `alpaca.sector_market_value` — plenty to chart.
- **Wire EOD logging:** append a JSON line per market close to `memory/wheel/eod_log.jsonl`:
  ```json
  {"date": "2026-05-12", "equity": 99995.98, "cash": 100094.98, "positions_count": 1}
  ```

## Restart

If server.py changes:
```bash
pkill -f "mission_control/server.py"
nohup python3 mission_control/server.py >> mission_control/mc.log 2>&1 &
```

## Tags

`investor-engine` `wheel-strategy` `paper-trading` `composite-scoring`
`pnl-tracking` `period-accounting` `multi-account` `tax-export`
