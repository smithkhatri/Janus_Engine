"""
Execution engine for the ClawBack arbitrage bot.

Consolidates: commission calculation, orderbook cost allocation, balance checks,
capital gating, and order placement on Kalshi & Polymarket US.

Called by brain.py — this is the single source of truth for trade execution.
"""

import os
import uuid
import time
import threading
import base64
import requests
import datetime
from decimal import Decimal, ROUND_UP, ROUND_HALF_EVEN
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, ed25519
from cryptography.hazmat.backends import default_backend
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

import bot_logger
# pyrefly: ignore [missing-import]
from polymarket_us import PolymarketUS

load_dotenv("API_key.env")

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_API_KEY_ID = os.getenv("KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")

PM_KEY_ID = os.getenv("PM_KEY_ID")
PM_SECRET_KEY = os.getenv("PM_SECRET_KEY")

# Use at most 95% of available balance when capital is insufficient
CAPITAL_LIMIT_PCT = Decimal("0.95")

# Execution guard: prevent duplicate/rapid-fire trades
_execution_lock = threading.Lock()
_last_execution_ts = 0.0           # monotonic timestamp of last trade
EXECUTION_COOLDOWN_SEC = 5         # seconds to wait between trade attempts

# ═══════════════════════════════════════════════════════════════════
# KALSHI AUTH
# ═══════════════════════════════════════════════════════════════════

with open(KALSHI_PRIVATE_KEY_PATH, "rb") as _f:
    _kalshi_pk = serialization.load_pem_private_key(
        _f.read(), password=None, backend=default_backend()
    )


def _kalshi_request(method: str, path: str, data: dict | None = None):
    """Authenticated Kalshi API request (GET or POST)."""
    ts = str(int(datetime.datetime.now().timestamp() * 1000))
    sign_path = urlparse(KALSHI_BASE_URL + path).path
    msg = f"{ts}{method}{sign_path}".encode("utf-8")
    sig = _kalshi_pk.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    headers = {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }
    url = KALSHI_BASE_URL + path
    if method == "GET":
        return requests.get(url, headers=headers)
    return requests.post(url, headers=headers, json=data)


# ═══════════════════════════════════════════════════════════════════
# POLYMARKET AUTH
# ═══════════════════════════════════════════════════════════════════

_pm_ed_key = ed25519.Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(PM_SECRET_KEY)[:32]
)

_pm_client = PolymarketUS(key_id=PM_KEY_ID, secret_key=PM_SECRET_KEY)


def _pm_auth_headers(method: str, path: str) -> dict:
    """Build Ed25519-signed auth headers for Polymarket US REST API."""
    ts = str(int(time.time() * 1000))
    message = f"{ts}{method}{path}"
    sig = base64.b64encode(_pm_ed_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": PM_KEY_ID,
        "X-PM-Timestamp": ts,
        "X-PM-Signature": sig,
        "Content-Type": "application/json",
    }


# ═══════════════════════════════════════════════════════════════════
# COMMISSION FUNCTIONS  (also imported by brain.py)
# ═══════════════════════════════════════════════════════════════════

def get_kalshi_commission(n: int, p: float) -> Decimal:
    """Kalshi fee: n × 0.07 × p × (1 − p), rounded UP to nearest cent."""
    n_d, p_d = Decimal(str(n)), Decimal(str(p))
    return (n_d * Decimal("0.07") * p_d * (Decimal("1") - p_d)).quantize(
        Decimal("0.01"), rounding=ROUND_UP
    )


def get_polymarket_commission(n: int, p: float) -> Decimal:
    """Polymarket fee: n × 0.06 × p × (1 − p), banker's rounding."""
    n_d, p_d = Decimal(str(n)), Decimal(str(p))
    return (n_d * Decimal("0.06") * p_d * (Decimal("1") - p_d)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )


# ═══════════════════════════════════════════════════════════════════
# ALLOCATION LOGIC  (also imported by brain.py)
# ═══════════════════════════════════════════════════════════════════

def get_allocation_and_cost(asks, N, comm_fn):
    """
    Walk the ask ladder, buying N contracts cheapest-first.
    Returns (allocation_list, total_cost_Decimal) or (None, None) if
    orderbook depth is insufficient.
    """
    alloc, remaining, total = [], N, Decimal("0")
    for price, qty in asks:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        comm = comm_fn(take, price)
        base = Decimal(str(take)) * Decimal(str(price))
        alloc.append({
            "price": float(price),
            "qty": int(take),
            "base_cost": float(base),
            "commission": float(comm),
            "total_cost": float(base + comm),
        })
        total += base + comm
        remaining -= take
    return (None, None) if remaining > 0 else (alloc, total)


# ═══════════════════════════════════════════════════════════════════
# BALANCE CHECKS
# ═══════════════════════════════════════════════════════════════════

def get_kalshi_balance() -> float:
    """Return available Kalshi balance in dollars."""
    resp = _kalshi_request("GET", "/portfolio/balance")
    return resp.json()["balance"] / 100


def get_pm_balance() -> float:
    """Return available Polymarket balance in dollars."""
    path = "/v1/account/balances"
    resp = requests.get(
        f"https://api.polymarket.us{path}",
        headers=_pm_auth_headers("GET", path),
    )
    return float(resp.json()["balances"][0]["currentBalance"])


# ═══════════════════════════════════════════════════════════════════
# ORDER PLACEMENT
# ═══════════════════════════════════════════════════════════════════

def _place_kalshi_order(ticker, side, price_cents, count):
    """
    Place an IOC limit order on Kalshi.
    price_cents: int (1–99 range, cents, representing the price of the option being bought)
    count:       int (number of contracts)
    """
    # Map "yes"/"no" side to Kalshi V2 book side ("bid"/"ask") and adjust price if needed
    if side == "yes":
        api_side = "bid"
        api_price_cents = price_cents
    elif side == "no":
        api_side = "ask"
        api_price_cents = 100 - price_cents
    else:
        api_side = side
        api_price_cents = price_cents

    price_dollars_str = f"{api_price_cents / 100:.4f}"

    data = {
        "ticker": ticker,
        "side": api_side,
        "count": str(count),
        "price": price_dollars_str,
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": str(uuid.uuid4()),
    }
    return _kalshi_request("POST", "/portfolio/events/orders", data)


def _place_pm_order(slug, intent, price_str, count):
    """Place an IOC limit order on Polymarket US."""
    return _pm_client.orders.create({
        "marketSlug": slug,
        "intent": intent,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": price_str, "currency": "USD"},
        "quantity": count,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
    })


# ═══════════════════════════════════════════════════════════════════
# CAPITAL GATING
# ═══════════════════════════════════════════════════════════════════

def _max_affordable_n(asks, budget, comm_fn, upper_n):
    """Binary-search for the largest N whose total cost ≤ budget."""
    budget_dec = Decimal(str(budget))
    lo, hi, best = 1, upper_n, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        _, cost = get_allocation_and_cost(asks, mid, comm_fn)
        if cost is not None and cost <= budget_dec:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


# ═══════════════════════════════════════════════════════════════════
# TERMINAL COLOURS
# ═══════════════════════════════════════════════════════════════════

_B = "\033[1m"       # bold
_G = "\033[92m"      # green
_C = "\033[96m"      # cyan
_Y = "\033[93m"      # yellow
_R = "\033[91m"      # red
_0 = "\033[0m"       # reset


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT — called by brain.py on every opportunity
# ═══════════════════════════════════════════════════════════════════

def execute_arbitrage(opportunity: dict):
    """
    Thread-safe entry point with cooldown guard.
    Prevents concurrent and rapid re-execution of trades.
    """
    if not _execution_lock.acquire(blocking=False):
        bot_logger.log("EXECUTION_SKIPPED", "Another execution is already in progress — skipping.")
        return  # Another execution is already in progress
    try:
        elapsed = time.monotonic() - _last_execution_ts
        if elapsed < EXECUTION_COOLDOWN_SEC:
            remaining = EXECUTION_COOLDOWN_SEC - elapsed
            print(f"{_Y}⏳ Cooldown active "
                  f"({remaining:.1f}s remaining) "
                  f"— skipping signal{_0}")
            bot_logger.log("COOLDOWN_SKIP", f"Cooldown active — {remaining:.1f}s remaining. Signal ignored.")
            return
        _do_execute(opportunity)
    finally:
        _execution_lock.release()


def _do_execute(opportunity: dict):
    """
    Full execution pipeline:
      1. Print opportunity report
      2. Fetch balances & gate capital
      3. Place orders on both exchanges
    """
    global _last_execution_ts

    direction  = opportunity["direction"]
    size       = opportunity["size"]
    profit     = opportunity["profit"]
    total_cost = opportunity["total_cost"]
    base_cost  = opportunity["base_cost"]
    commission = opportunity["commission"]
    roi = (profit / total_cost * 100) if total_cost > 0 else 0

    # ── 1. Signal report ────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"{_B}{_G}🚨 ARBITRAGE SIGNAL DETECTED 🚨{_0}")
    print(f"{'=' * 60}")
    print(f"{_B}Direction:{_0}   {_C}{direction}{_0}")
    print(f"{_B}Contracts:{_0}   {size}")
    print(f"{_B}Est. Cost:{_0}   ${total_cost:.2f}  "
          f"(Base: ${base_cost:.2f} | Comm: ${commission:.2f})")
    print(f"{_B}Revenue:{_0}     ${float(size):.2f}  (Guaranteed Payout)")
    print(f"{_B}Net Profit:{_0}  {_G}${profit:.2f}{_0}  "
          f"({_B}ROI: {roi:.2f}%{_0})")

    # Log full trade summary
    bot_logger.log_trade_summary(
        direction=direction,
        contracts=size,
        total_cost=total_cost,
        base_cost=base_cost,
        commission=commission,
        profit=profit,
        roi=roi,
        exchange_a=opportunity["exchange_a"],
        ticker_a=opportunity["ticker_a"],
        side_a=opportunity.get("side_a", "N/A"),
        alloc_a=opportunity["alloc_a"],
        exchange_b=opportunity["exchange_b"],
        ticker_b=opportunity["ticker_b"],
        side_b=opportunity.get("side_b", "N/A"),
        alloc_b=opportunity["alloc_b"],
    )
    print(f"{'-' * 60}")

    # Proposed execution steps
    print(f"{_B}PROPOSED EXECUTION STEPS:{_0}")
    for step, exch_key, tick_key, alloc_key in [
        ("1", "exchange_a", "ticker_a", "alloc_a"),
        ("2", "exchange_b", "ticker_b", "alloc_b"),
    ]:
        exch   = opportunity[exch_key]
        ticker = opportunity[tick_key]
        alloc  = opportunity[alloc_key]
        print(f"\n  {_B}{step}. BUY on {exch.upper()} ({ticker}){_0}")
        for i, lvl in enumerate(alloc, 1):
            print(f"     └─ Level {i}: Buy {lvl['qty']} contracts "
                  f"@ ${lvl['price']:.2f}  "
                  f"(Base: ${lvl['base_cost']:.2f} | "
                  f"Comm: ${lvl['commission']:.2f})")

    # ── 2. Capital gating ───────────────────────────────────────
    try:
        kalshi_bal = get_kalshi_balance()
        pm_bal     = get_pm_balance()
    except Exception as e:
        print(f"\n{_R}❌ Balance fetch failed: {e} — skipping trade{_0}")
        print(f"{'=' * 60}\n")
        bot_logger.log("BALANCE_FETCH_FAILED", f"Error: {e}\nTrade skipped.")
        return

    cost_a = float(opportunity["cost_a"])      # kalshi leg
    cost_b = float(opportunity["cost_b"])      # polymarket leg
    asks_a = opportunity["asks_a"]
    asks_b = opportunity["asks_b"]

    affordable_n = size

    print(f"\n{_B}CAPITAL CHECK:{_0}")
    print(f"  Kalshi balance:      ${kalshi_bal:>10.2f}   |   "
          f"Leg cost: ${cost_a:.2f}")
    print(f"  Polymarket balance:  ${pm_bal:>10.2f}   |   "
          f"Leg cost: ${cost_b:.2f}")

    bot_logger.log("CAPITAL_CHECK", (
        f"Kalshi balance:     ${kalshi_bal:.4f}   |  Leg A cost: ${cost_a:.4f}\n"
        f"Polymarket balance: ${pm_bal:.4f}   |  Leg B cost: ${cost_b:.4f}\n"
        f"Requested contracts: {size}"
    ))

    if cost_a > kalshi_bal:
        budget_a = float(Decimal(str(kalshi_bal)) * CAPITAL_LIMIT_PCT)
        affordable_n = _max_affordable_n(
            asks_a, budget_a, get_kalshi_commission, size
        )
        print(f"  {_Y}⚠ Kalshi underfunded — capped to "
              f"{affordable_n} contracts "
              f"(95% of ${kalshi_bal:.2f}){_0}")
        bot_logger.log("CAPITAL_INSUFFICIENT",
            f"Kalshi underfunded. Balance: ${kalshi_bal:.4f}, Need: ${cost_a:.4f}\n"
            f"Capped to {affordable_n} contracts (95% of balance = ${budget_a:.4f})")

    if cost_b > pm_bal:
        budget_b = float(Decimal(str(pm_bal)) * CAPITAL_LIMIT_PCT)
        pm_cap = _max_affordable_n(
            asks_b, budget_b, get_polymarket_commission, size
        )
        affordable_n = min(affordable_n, pm_cap)
        print(f"  {_Y}⚠ PM underfunded — capped to "
              f"{affordable_n} contracts "
              f"(95% of ${pm_bal:.2f}){_0}")
        bot_logger.log("CAPITAL_INSUFFICIENT",
            f"Polymarket underfunded. Balance: ${pm_bal:.4f}, Need: ${cost_b:.4f}\n"
            f"Capped to {affordable_n} contracts (95% of balance = ${budget_b:.4f})")

    if affordable_n < 1:
        print(f"  {_R}✗ Insufficient capital — skipping trade{_0}")
        print(f"{'=' * 60}\n")
        bot_logger.log("TRADE_ABORTED", "Insufficient capital on one or both exchanges. 0 contracts affordable.")
        return

    # Recalculate allocations at the (possibly reduced) size
    final_alloc_a, final_cost_a = get_allocation_and_cost(
        asks_a, affordable_n, get_kalshi_commission
    )
    final_alloc_b, final_cost_b = get_allocation_and_cost(
        asks_b, affordable_n, get_polymarket_commission
    )
    if final_alloc_a is None or final_alloc_b is None:
        print(f"  {_R}✗ Depth exhausted at adjusted size — skipping{_0}")
        print(f"{'=' * 60}\n")
        bot_logger.log("TRADE_ABORTED", f"Orderbook depth exhausted at adjusted size ({affordable_n} contracts).")
        return

    final_profit = Decimal(str(affordable_n)) - final_cost_a - final_cost_b
    if final_profit <= 0:
        print(f"  {_Y}✗ No profit at affordable size — skipping{_0}")
        print(f"{'=' * 60}\n")
        bot_logger.log("TRADE_ABORTED",
            f"No profit at affordable size ({affordable_n} contracts).\n"
            f"Adjusted cost: ${float(final_cost_a + final_cost_b):.4f}  |  "
            f"Revenue: ${affordable_n:.2f}  |  Profit: ${float(final_profit):.4f}")
        return

    if affordable_n < size:
        adj_roi = (
            float(final_profit)
            / float(final_cost_a + final_cost_b) * 100
        )
        print(f"\n  {_B}Adjusted trade:{_0} {affordable_n} contracts  |  "
              f"Profit: {_G}${float(final_profit):.2f}{_0}  |  "
              f"ROI: {adj_roi:.2f}%")
        bot_logger.log("TRADE_SIZE_ADJUSTED",
            f"Original size: {size} → Adjusted: {affordable_n} contracts\n"
            f"Adjusted profit: ${float(final_profit):.4f}  |  ROI: {adj_roi:.2f}%")

    # ── 3. Place orders ─────────────────────────────────────────
    side_a   = opportunity["side_a"]       # "yes" or "no"
    side_b   = opportunity["side_b"]       # PM intent string
    ticker_a = opportunity["ticker_a"]
    ticker_b = opportunity["ticker_b"]

    # Kalshi: sweep the book up to worst (highest) ask → price in cents
    worst_a = max(lvl["price"] for lvl in final_alloc_a)
    kalshi_price_cents = int(round(worst_a * 100))

    # PM API always uses YES-denominated price,
    # so complement the NO-ask price for SHORT orders
    worst_b = max(lvl["price"] for lvl in final_alloc_b)
    if side_b == "ORDER_INTENT_BUY_SHORT":
        pm_price_str = f"{1.0 - worst_b:.2f}"
    else:
        pm_price_str = f"{worst_b:.2f}"

    print(f"\n{_B}PLACING ORDERS …{_0}")
    bot_logger.log_section("PLACING ORDERS")

    # --- Kalshi leg ---
    try:
        k_resp = _place_kalshi_order(
            ticker_a, side_a, kalshi_price_cents, affordable_n
        )
        if k_resp.status_code == 201:
            k_data = k_resp.json()
            print(f"  {_G}✓ Kalshi filled{_0}   |  "
                  f"ID: {k_data.get('order_id', 'N/A')}  |  "
                  f"Remaining: {k_data.get('remaining_count', 'N/A')}")
            bot_logger.log_order_result(
                exchange="kalshi", ticker=ticker_a, side=side_a,
                price=f"{kalshi_price_cents}¢", count=affordable_n,
                success=True,
                response_data=(
                    f"Order ID: {k_data.get('order_id', 'N/A')}  |  "
                    f"Remaining: {k_data.get('remaining_count', 'N/A')}  |  "
                    f"Full response: {k_data}"
                ),
            )
        else:
            print(f"  {_R}✗ Kalshi error "
                  f"{k_resp.status_code}: {k_resp.text}{_0}")
            bot_logger.log_order_result(
                exchange="kalshi", ticker=ticker_a, side=side_a,
                price=f"{kalshi_price_cents}¢", count=affordable_n,
                success=False,
                response_data=f"HTTP {k_resp.status_code}: {k_resp.text}",
            )
    except Exception as e:
        print(f"  {_R}✗ Kalshi exception: {e}{_0}")
        bot_logger.log_order_result(
            exchange="kalshi", ticker=ticker_a, side=side_a,
            price=f"{kalshi_price_cents}¢", count=affordable_n,
            success=False, response_data=f"Exception: {e}",
        )

    # --- Polymarket leg ---
    try:
        pm_resp = _place_pm_order(
            ticker_b, side_b, pm_price_str, affordable_n
        )
        print(f"  {_G}✓ PM order placed{_0}  |  Response: {pm_resp}")
        bot_logger.log_order_result(
            exchange="polymarket", ticker=ticker_b, side=side_b,
            price=pm_price_str, count=affordable_n,
            success=True, response_data=str(pm_resp),
        )
    except Exception as e:
        print(f"  {_R}✗ PM exception: {e}{_0}")
        bot_logger.log_order_result(
            exchange="polymarket", ticker=ticker_b, side=side_b,
            price=pm_price_str, count=affordable_n,
            success=False, response_data=f"Exception: {e}",
        )

    _last_execution_ts = time.monotonic()
    bot_logger.log("TRADE_CYCLE_COMPLETE",
        f"Direction: {direction}\n"
        f"Final contracts: {affordable_n}\n"
        f"Final profit: ${float(final_profit):.4f}\n"
        f"Kalshi leg:     {ticker_a} {side_a} @ {kalshi_price_cents}¢ × {affordable_n}\n"
        f"PM leg:         {ticker_b} {side_b} @ {pm_price_str} × {affordable_n}")
    print(f"{'=' * 60}\n")
