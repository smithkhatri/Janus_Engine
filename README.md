# Janus Engine

![Status](https://img.shields.io/badge/status-offline-lightgrey.svg)

A cross-exchange arbitrage bot for prediction markets. It watches the same event on
Kalshi and Polymarket at the same time, and when the YES price on one venue plus the NO
price on the other adds up to less than 100 cents after fees, it buys both sides. A
matched YES/NO pair always settles at exactly 100 cents, so the difference is the profit.

**Status: offline.** The engine is not running. The
[dashboard](https://smithkhatri.github.io/Janus_Engine/dashboard/) reads a committed
snapshot of the logs from the last time it was.

## What the run looked like

Numbers below come straight from `bot_logs/`, covering 19 June to 17 August 2026:

| | |
|---|---|
| Arbitrage attempts | 1,304 across 240 market pairs |
| Both legs filled | 795 (61%) |
| Net realized P&L | $1,144.67 |
| Realized vs. modelled | 56.4% ($2,028.05 modelled) |
| Median fill latency | 89 ms Kalshi, 120 ms Polymarket |

The gap between modelled and realized profit is the interesting part. Nearly a third of
the attempts (389) got no fill at all, and another 120 filled one leg only and had to be
unwound at a loss. That is the real cost of racing two independent exchanges over two
independent APIs, and it is why the dashboard shows the failed attempts next to the
successful ones instead of hiding them.

## How it works

Two WebSocket connections feed the engine: one to Kalshi carrying every subscribed
ticker, one to Polymarket carrying up to 100 slugs. `orderbook_router.py` takes each
incoming tick and hands it to the right local book, then wakes the brain for that pair.

`brain.py` does the actual decision. Each order book is kept as a 100-slot array indexed
by price in cents, so checking whether an opportunity exists is two array lookups and an
addition rather than a sort or a scan. If the best prices cross, it walks both books
level by level and accumulates cost, fees and quantity until the marginal contract stops
being profitable.

Fees are computed exactly, not approximated, because at two or three cents of edge per
contract the fee is most of the trade:

- Kalshi charges `ceil(0.07 * n * p * (1 - p))` cents, rounded up per order.
- Polymarket charges `0.06 * n * p * (1 - p)` with banker's rounding.

All money is held as integers in hundredths of a cent, so nothing depends on float
behaviour. Sizing is then clipped against three separate limits at once: the Kalshi
wallet, the Polymarket wallet, and a shared budget across every pair, since one pair
filling changes what the others can afford.

`execution.py` fires both legs from a daemon thread. That matters more than it sounds:
the HTTP calls are blocking, and doing them on the event loop would stop the engine
reading market data for the couple of hundred milliseconds the orders are in flight. If
one leg fills and the other does not, the filled side is market-sold immediately to close
the exposure, and the loss on that unwind is logged as realized P&L.

`trade_logger.py` keeps the hot path free of disk I/O. Records go onto a thread-safe
queue and an async task flushes them to CSV in the background. `helpers.py` re-reads the
true wallet balances from both APIs every two seconds and overwrites the locally tracked
ones, which repairs any drift from optimistic deduction.

## Layout

| File | Role |
|---|---|
| `main.py` | Loads the registry, opens both sockets, starts the background tasks |
| `orderbook_router.py` | Routes raw ticks to the correct book and brain |
| `Kalshi_Orderbook.py`, `PM_Orderbook.py` | Per-venue socket clients and book state |
| `brain.py` | Opportunity detection, fee math, sizing |
| `execution.py` | Order placement, partial fills, unwinds |
| `trade_logger.py` | Queued CSV logging and book snapshots |
| `Kalshi_PM_API_request.py` | Auth, balances, order submission |
| `market_registry.json` | Which Kalshi ticker maps to which Polymarket slug |
| `build_static_data.py` | Bundles `bot_logs/*.csv` into `dashboard/data.json` |
| `dashboard/` | Static page that reads that JSON |

## Running it

Requires Python 3.11+ with `websockets`, `aiohttp` and `requests`.

```bash
# credentials go in API_key.env, market pairs in market_registry.json
python main.py
```

Set `global_settings.test_mode` to `true` in `market_registry.json` to log decisions
without sending any orders. Start there.

For the dashboard:

```bash
python build_static_data.py      # rebuild dashboard/data.json from bot_logs/
python dashboard/server.py       # then open http://localhost:8000
```

The page is plain HTML, CSS and one JS file with Chart.js from a CDN, so it also works
as a GitHub Pages site with no build step.

## Known limits

- Profit thresholds and minimum volume are hardcoded in `brain.py` rather than read from
  `market_registry.json`.
- Both venues are taker-only. There is no quoting or queue position logic.
- The unwind path assumes a market sell will fill. In a thin book it will fill worse than
  the logged estimate.
- Pair mapping is manual, so a market that resolves on slightly different terms across
  the two venues would not be caught automatically.
