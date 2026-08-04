"""
Orderbook Router — Central nervous system of multi-market Janus Engine.

Routes incoming WebSocket messages to the correct orderbook instance,
then triggers the corresponding brain to evaluate arbitrage.
"""
import json
import threading
from Kalshi_Orderbook import KalshiOrderBook
from PM_Orderbook import PM_OrderBook
from brain import JanusBrain


class SharedBalance:
    """
    Single shared wallet state across ALL market-pair brains.
    You have ONE Kalshi wallet and ONE PM wallet, not one per market.
    """
    def __init__(self):
        self.k_balance = 0  # Kalshi balance in scaled units (hundredths of a cent)
        self.p_balance = 0  # PM balance in scaled units (hundredths of a cent)


class OrderbookRouter:
    def __init__(self, pairs, global_settings):
        self.shared_balance = SharedBalance()
        self.pairs = {}  # pair_id -> {kalshi_book, pm_book, brain, ...}

        # Reverse-lookup maps for routing incoming WS messages
        self.kalshi_ticker_to_pair = {}  # "KXHIGHTSFO-..." -> pair_id
        self.pm_slug_to_pair = {}        # "tc-temp-sfo..." -> pair_id

        test_mode = global_settings.get("test_mode", True)
        per_pair_max = global_settings.get("per_pair_max_dollars", 5)

        for pair_config in pairs:
            if not pair_config.get("enabled", True):
                continue

            pair_id = pair_config["id"]
            k_ticker = pair_config["kalshi_ticker"]
            pm_slug = pair_config["pm_slug"]

            k_book = KalshiOrderBook()
            p_book = PM_OrderBook()
            brain = JanusBrain(
                k_book, p_book,
                kalshi_ticker=k_ticker,
                pm_ticker=pm_slug,
                max_spend=per_pair_max,
                test_mode=test_mode,
                shared_balance=self.shared_balance
            )

            self.pairs[pair_id] = {
                "kalshi_ticker": k_ticker,
                "pm_slug": pm_slug,
                "kalshi_book": k_book,
                "pm_book": p_book,
                "brain": brain
            }

            self.kalshi_ticker_to_pair[k_ticker] = pair_id
            self.pm_slug_to_pair[pm_slug] = pair_id

        print(f"🧠 OrderbookRouter initialized with {len(self.pairs)} market pairs.")

    # ─── Kalshi Routing ───

    def get_kalshi_book(self, market_ticker):
        """Look up the KalshiOrderBook for a given ticker."""
        pair_id = self.kalshi_ticker_to_pair.get(market_ticker)
        if pair_id:
            return self.pairs[pair_id]["kalshi_book"]
        return None

    def on_kalshi_update(self, market_ticker):
        """Trigger the brain for the pair that owns this Kalshi ticker."""
        pair_id = self.kalshi_ticker_to_pair.get(market_ticker)
        if pair_id:
            self.pairs[pair_id]["brain"].evaluate_arbitrage()

    def clear_all_kalshi_books(self):
        """Clear all Kalshi orderbooks on reconnect (fresh snapshots incoming)."""
        for pair in self.pairs.values():
            pair["kalshi_book"].clear()

    # ─── PM Routing ───

    def get_pm_book(self, market_slug):
        """Look up the PM_OrderBook for a given slug."""
        pair_id = self.pm_slug_to_pair.get(market_slug)
        if pair_id:
            return self.pairs[pair_id]["pm_book"]
        return None

    def on_pm_update(self, market_slug):
        """Trigger the brain for the pair that owns this PM slug."""
        pair_id = self.pm_slug_to_pair.get(market_slug)
        if pair_id:
            self.pairs[pair_id]["brain"].evaluate_arbitrage()

    # ─── Helpers ───

    def get_all_kalshi_tickers(self):
        return list(self.kalshi_ticker_to_pair.keys())

    def get_all_pm_slugs(self):
        return list(self.pm_slug_to_pair.keys())
