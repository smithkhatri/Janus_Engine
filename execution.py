import time
from Kalshi_PM_API_request import (
    place_pm_buy_order, place_kalshi_buy_order,
    unwind_kalshi, unwind_pm
)
from trade_logger import log_execution, log_snapshot, capture_book_snapshot
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=10)


def execute_arbitrage(allocs, strategy_name,
                      kalshi_side, pm_side, kalshi_ticker, pm_ticker,
                      pair_id, test_mode, log_orderbooks, pre_snapshot,
                      kalshi_book, pm_book):
    """
    Execute arbitrage with auto-unwind on leg mismatch.
    On any mismatch, immediately sells back the filled leg and aborts remaining allocations.
    """

    for i, alloc in enumerate(allocs):
        k_price = alloc['kalshi_price']
        p_price = alloc['pm_price']
        qty = alloc['qty_scaled_to_100th_of_vol'] / 100
        theoretical_profit = alloc['profit_scaled_to_100th_of_cent']

        # Base record (common to both test and live)
        record = {
            "timestamp": time.time(),
            "pair_id": pair_id,
            "strategy": strategy_name,
            "k_price": k_price,
            "p_price": p_price,
            "intended_qty": qty,
            "theoretical_profit": theoretical_profit,
            "_test_mode": test_mode,  # Internal flag, excluded from CSV by extrasaction='ignore'
        }

        if test_mode:
            # Test mode: log what the bot WOULD have done, no API calls
            record.update({
                "k_fill_qty": "", "k_fill_time_ms": "", "k_status_code": "",
                "p_fill_qty": "", "p_fill_time_ms": "", "p_status_code": "",
                "outcome": "TEST",
                "unwind_action": "", "unwind_pnl": "",
                "net_realized_pnl": "",
            })
            log_execution(record)
            print(f"[TEST] {pair_id} | {strategy_name} | "
                  f"{kalshi_side}@K{k_price} + {pm_side}@P{p_price} | qty={qty}")
            continue

        # ─── LIVE EXECUTION ───
        t_start = time.time()

        # Fire both legs simultaneously
        k_future = _executor.submit(
            place_kalshi_buy_order, kalshi_ticker, kalshi_side, k_price, qty)
        p_future = _executor.submit(
            place_pm_buy_order, pm_ticker, pm_side, p_price, qty)

        # Wait for Kalshi result
        k_result = None
        k_status = 0
        try:
            k_result = k_future.result(timeout=10)
            k_status = k_result.status_code if hasattr(k_result, 'status_code') else 0
        except Exception as e:
            print(f"🔴 KALSHI LEG FAILED: {e}")
        k_elapsed = int((time.time() - t_start) * 1000)

        # Wait for PM result
        p_result = None
        p_status = 0
        try:
            p_result = p_future.result(timeout=10)
            p_status = 200 if p_result else 0
        except Exception as e:
            print(f"🔴 PM LEG FAILED: {e}")
        p_elapsed = int((time.time() - t_start) * 1000)

        # Parse fill quantities
        k_fill = _parse_kalshi_fill(k_result)
        p_fill = _parse_pm_fill(p_result)

        # Classify outcome and unwind if needed
        outcome, unwind_action, unwind_pnl = _classify_and_unwind(
            k_fill, p_fill, qty, k_price, p_price,
            kalshi_side, pm_side, kalshi_ticker, pm_ticker
        )

        # Calculate net realized PnL (estimated, in hundredths of cent)
        if outcome == "PERFECT":
            net_pnl = theoretical_profit
        elif outcome == "BOTH_MISS":
            net_pnl = 0
        else:
            matched = min(k_fill, p_fill)
            # Matched portion earns profit (ignoring fees — rough estimate)
            matched_profit = int(matched * (100 - k_price - p_price) * 100) if matched > 0 else 0
            net_pnl = matched_profit + unwind_pnl  # unwind_pnl is negative

        record.update({
            "k_fill_qty": k_fill,
            "k_fill_time_ms": k_elapsed,
            "k_status_code": k_status,
            "p_fill_qty": p_fill,
            "p_fill_time_ms": p_elapsed,
            "p_status_code": p_status,
            "outcome": outcome,
            "unwind_action": unwind_action,
            "unwind_pnl": unwind_pnl,
            "net_realized_pnl": net_pnl,
        })

        log_execution(record)

        # Console output
        if outcome == "PERFECT":
            print(f"✅ PERFECT FILL: {qty} on {pair_id}. Profit: {theoretical_profit / 100:.2f}¢")
        elif outcome == "BOTH_MISS":
            print(f"🤷 BOTH MISSED on {pair_id}: 0 filled.")
        else:
            print(f"⚠️ {outcome} on {pair_id}: K={k_fill}, P={p_fill}. "
                  f"{unwind_action}. Est. loss: {unwind_pnl / 100:.2f}¢")

        # On ANY mismatch, abort remaining allocations — the book has moved
        if outcome not in ("PERFECT", "BOTH_MISS"):
            remaining = len(allocs) - i - 1
            if remaining > 0:
                print(f"🛑 Aborting {remaining} remaining allocation(s) for {pair_id}.")
            break

    # ─── Orderbook Snapshots ───
    if log_orderbooks and pre_snapshot is not None:
        snapshot_entry = {
            "timestamp": time.time(),
            "pair_id": pair_id,
            "strategy": strategy_name,
            "pre_trade": pre_snapshot,
        }
        # Post-trade snapshot only in live mode (test mode has no market impact)
        if not test_mode:
            snapshot_entry["post_trade"] = capture_book_snapshot(kalshi_book, pm_book)
        log_snapshot(snapshot_entry)


# ─── Fill Parsers ───

def _parse_kalshi_fill(result):
    """Extract fill count from Kalshi API response (requests.Response object)."""
    if not result:
        return 0.0
    try:
        return float(result.json().get('fill_count', 0))
    except Exception:
        return 0.0


def _parse_pm_fill(result):
    """Extract fill count from PM SDK response (dict with 'order' key)."""
    if not result:
        return 0.0
    try:
        order_data = result.get('order', {})
        if order_data:
            return float(order_data.get('cumQuantity', 0))
    except Exception:
        pass
    return 0.0


def _parse_pm_sell_fill(result):
    """Parse PM sell/unwind fill from the SDK response."""
    if not result:
        return 0.0
    try:
        order_data = result.get('order', {})
        if order_data:
            return float(order_data.get('cumQuantity', 0))
    except Exception:
        pass
    return 0.0


# ─── Outcome Classification & Auto-Unwind ───

def _classify_and_unwind(k_fill, p_fill, intended_qty, k_price, p_price,
                          kalshi_side, pm_side, kalshi_ticker, pm_ticker):
    """
    Classify execution outcome and auto-unwind mismatched legs.

    Returns: (outcome, unwind_action, unwind_pnl)
        outcome: "PERFECT" | "BOTH_MISS" | "K_ONLY" | "P_ONLY" | "PARTIAL"
        unwind_action: description of what was unwound (or "NONE")
        unwind_pnl: estimated loss from unwind (negative, in hundredths of cent)
                     WORST-CASE estimate — actual loss is usually much less.
    """
    k_ok = abs(k_fill - intended_qty) < 0.01
    p_ok = abs(p_fill - intended_qty) < 0.01

    # ─── Both filled perfectly ───
    if k_ok and p_ok:
        return "PERFECT", "NONE", 0

    # ─── Both missed completely ───
    if k_fill == 0 and p_fill == 0:
        return "BOTH_MISS", "NONE", 0

    # ─── Kalshi filled, PM missed → sell back Kalshi ───
    if k_fill > 0 and p_fill == 0:
        action = f"SELL_K_{kalshi_side.upper()}"
        unwind_result = unwind_kalshi(kalshi_ticker, kalshi_side, k_fill)
        unwind_fill = _parse_kalshi_fill(unwind_result)

        # Worst-case: buy opposite at 99¢ → pair costs (k_price + 99), pays 100
        # Loss per contract = k_price - 1 cents
        est_loss = int(k_fill * max(k_price - 1, 1) * 100)

        if unwind_fill == 0:
            print(f"🚨🚨 UNWIND FAILED! Naked {kalshi_side}: {k_fill} on {kalshi_ticker}!")
            action += "_FAILED"
        else:
            print(f"🔄 Unwound K {kalshi_side} {k_fill}qty. Fill: {unwind_fill}")

        return "K_ONLY", action, -est_loss

    # ─── PM filled, Kalshi missed → sell back PM ───
    if p_fill > 0 and k_fill == 0:
        action = f"SELL_P_{pm_side.upper()}"
        unwind_result = unwind_pm(pm_ticker, pm_side, p_fill)
        unwind_fill = _parse_pm_sell_fill(unwind_result)

        # Worst-case: sell at 1¢ → loss = p_price - 1 cents per contract
        est_loss = int(p_fill * max(p_price - 1, 1) * 100)

        if unwind_fill == 0:
            print(f"🚨🚨 UNWIND FAILED! Naked {pm_side}: {p_fill} on {pm_ticker}!")
            action += "_FAILED"
        else:
            print(f"🔄 Unwound P {pm_side} {p_fill}qty. Fill: {unwind_fill}")

        return "P_ONLY", action, -est_loss

    # ─── Both filled, different amounts → unwind the excess ───
    if k_fill > p_fill:
        excess = round(k_fill - p_fill, 2)
        action = f"SELL_K_{kalshi_side.upper()}_{excess}"
        unwind_result = unwind_kalshi(kalshi_ticker, kalshi_side, excess)
        unwind_fill = _parse_kalshi_fill(unwind_result)
        est_loss = int(excess * max(k_price - 1, 1) * 100)

        if unwind_fill == 0:
            print(f"🚨🚨 UNWIND FAILED! K excess {kalshi_side}: {excess} on {kalshi_ticker}!")
            action += "_FAILED"
        else:
            print(f"🔄 PARTIAL: K={k_fill}, P={p_fill}. Unwound K excess {excess}. Fill: {unwind_fill}")

        return "PARTIAL", action, -est_loss

    elif p_fill > k_fill:
        excess = round(p_fill - k_fill, 2)
        action = f"SELL_P_{pm_side.upper()}_{excess}"
        unwind_result = unwind_pm(pm_ticker, pm_side, excess)
        unwind_fill = _parse_pm_sell_fill(unwind_result)
        est_loss = int(excess * max(p_price - 1, 1) * 100)

        if unwind_fill == 0:
            print(f"🚨🚨 UNWIND FAILED! P excess {pm_side}: {excess} on {pm_ticker}!")
            action += "_FAILED"
        else:
            print(f"🔄 PARTIAL: K={k_fill}, P={p_fill}. Unwound P excess {excess}. Fill: {unwind_fill}")

        return "PARTIAL", action, -est_loss

    else:
        # Both filled equally but less than intended — no unwind needed
        print(f"⚠️ PARTIAL MATCHED: K={k_fill}, P={p_fill} (intended {intended_qty}).")
        return "PARTIAL", "NONE", 0
