import json
import asyncio
from orderbook_router import OrderbookRouter
from Kalshi_Orderbook import orderbook_websocket as kalshi_ws
from PM_Orderbook import stream_orderbook as pm_ws
from helpers import balance_syncer
from trade_logger import trade_log_flusher


def load_registry(path="market_registry.json"):
    with open(path) as f:
        return json.load(f)


async def main():
    registry = load_registry()
    pairs = registry["pairs"]
    settings = registry["global_settings"]

    # Build the router (creates all orderbooks + brains)
    router = OrderbookRouter(pairs, settings)

    # Extract all tickers and slugs for the WS subscriptions
    kalshi_tickers = router.get_all_kalshi_tickers()
    pm_slugs = router.get_all_pm_slugs()

    print(f"🚀 Igniting Janus Engine Mark-2 — {len(kalshi_tickers)} markets loaded.")
    print(f"   Kalshi tickers: {kalshi_tickers}")
    print(f"   PM slugs: {pm_slugs}")

    await asyncio.gather(
        kalshi_ws(kalshi_tickers, router),          # 1 connection, N tickers
        pm_ws(pm_slugs, router),                    # 1 connection, up to 100 slugs
        trade_log_flusher(),
        balance_syncer(router.shared_balance)
    )

if __name__ == "__main__":
    asyncio.run(main())
