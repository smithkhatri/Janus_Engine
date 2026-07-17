import asyncio
import importlib.util
import os
import sys
import threading
from decimal import Decimal

# Import shared logic from the execution engine
from execution import (
    execute_arbitrage,
    get_kalshi_commission,
    get_polymarket_commission,
    get_allocation_and_cost,
)

# Dynamic module importing helper (handles files with hyphens in the name)
def load_module(filename):
    module_name = filename.split(".")[0].replace("-", "_")
    file_path = os.path.abspath(filename)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

# Load the orderbook modules
print("Loading orderbook modules...")
kalshi_mod = load_module("Kalshi_OrderBook_Mark-1.py")
pm_mod = load_module("PolyMarket_OrderBook_Mark-1.py")

# Silence noisy printouts from orderbook submodules to keep console clean
kalshi_mod.PRINT_SNAPSHOT = False
kalshi_mod.PRINT_DELTAS = False
pm_mod.PRINT_SNAPSHOT = False
pm_mod.PRINT_UPDATES = False

# Retrieve market targets from loaded modules
kalshi_ticker = kalshi_mod.MARKET_TICKER
pm_slug = pm_mod.MARKET_SLUG

# Shared memory for orderbook states
latest_kalshi_book = {}
latest_polymarket_book = {}
active_opportunities = {}


def check_direction(asks_A, asks_B, comm_fn_A, comm_fn_B, exchange_a, exchange_b, ticker_a, ticker_b, side_a, side_b, dir_label):
    """
    Walks the asks of both exchanges to find size N that maximizes:
        Profit = N * $1.00 - Cost_A(N) - Cost_B(N)
    """
    total_qty_A = sum(qty for _, qty in asks_A)
    total_qty_B = sum(qty for _, qty in asks_B)
    max_possible_N = min(total_qty_A, total_qty_B)
    
    if max_possible_N == 0:
        return None
        
    best_profit = Decimal('0.0')
    best_N = 0
    best_alloc_A = None
    best_alloc_B = None
    best_cost_A = Decimal('0.0')
    best_cost_B = Decimal('0.0')
    
    for N in range(1, max_possible_N + 1):
        alloc_A, cost_A = get_allocation_and_cost(asks_A, N, comm_fn_A)
        alloc_B, cost_B = get_allocation_and_cost(asks_B, N, comm_fn_B)
        
        if cost_A is None or cost_B is None:
            break # Insufficient depth
            
        profit = Decimal(str(N)) - cost_A - cost_B
        
        # Marginal pricing check: If current level asks sum to >= $1.00,
        # further contracts will only decrease profit.
        price_A = Decimal(str(alloc_A[-1]['price']))
        price_B = Decimal(str(alloc_B[-1]['price']))
        if price_A + price_B >= Decimal('1.00'):
            if profit > best_profit:
                best_profit = profit
                best_N = N
                best_alloc_A = alloc_A
                best_alloc_B = alloc_B
                best_cost_A = cost_A
                best_cost_B = cost_B
            break
            
        if profit > best_profit:
            best_profit = profit
            best_N = N
            best_alloc_A = alloc_A
            best_alloc_B = alloc_B
            best_cost_A = cost_A
            best_cost_B = cost_B
            
    if best_profit > Decimal('0.0') and best_N > 0:
        base_cost_A = sum(Decimal(str(l['base_cost'])) for l in best_alloc_A)
        base_cost_B = sum(Decimal(str(l['base_cost'])) for l in best_alloc_B)
        comm_A = sum(Decimal(str(l['commission'])) for l in best_alloc_A)
        comm_B = sum(Decimal(str(l['commission'])) for l in best_alloc_B)
        
        return {
            "direction": dir_label,
            "size": best_N,
            "profit": float(best_profit),
            "total_cost": float(best_cost_A + best_cost_B),
            "base_cost": float(base_cost_A + base_cost_B),
            "commission": float(comm_A + comm_B),
            "cost_a": float(best_cost_A),
            "cost_b": float(best_cost_B),
            "exchange_a": exchange_a,
            "exchange_b": exchange_b,
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "side_a": side_a,
            "side_b": side_b,
            "alloc_a": best_alloc_A,
            "alloc_b": best_alloc_B,
            "asks_a": asks_A,
            "asks_b": asks_B,
        }
    return None

def check_arbitrage():
    """
    Main evaluation routine. Compares both arbitrage directions:
    1. Buy Kalshi YES + Buy Polymarket NO
    2. Buy Kalshi NO + Buy Polymarket YES
    """
    global active_opportunities
    
    if not latest_kalshi_book or not latest_polymarket_book:
        return
        
    # Extract and sort asks ascending (cheapest first)
    kalshi_yes_asks = sorted(latest_kalshi_book.get("yes_ask", {}).items())
    pm_no_asks = sorted(latest_polymarket_book.get("no_ask", {}).items())
    
    opp_1 = check_direction(
        asks_A=kalshi_yes_asks,
        asks_B=pm_no_asks,
        comm_fn_A=get_kalshi_commission,
        comm_fn_B=get_polymarket_commission,
        exchange_a="kalshi",
        exchange_b="polymarket",
        ticker_a=kalshi_ticker,
        ticker_b=pm_slug,
        side_a="yes",
        side_b="ORDER_INTENT_BUY_SHORT",
        dir_label="BUY KALSHI YES / BUY POLYMARKET NO",
    )
    
    kalshi_no_asks = sorted(latest_kalshi_book.get("no_ask", {}).items())
    pm_yes_asks = sorted(latest_polymarket_book.get("yes_ask", {}).items())
    
    opp_2 = check_direction(
        asks_A=kalshi_no_asks,
        asks_B=pm_yes_asks,
        comm_fn_A=get_kalshi_commission,
        comm_fn_B=get_polymarket_commission,
        exchange_a="kalshi",
        exchange_b="polymarket",
        ticker_a=kalshi_ticker,
        ticker_b=pm_slug,
        side_a="no",
        side_b="ORDER_INTENT_BUY_LONG",
        dir_label="BUY KALSHI NO / BUY POLYMARKET YES",
    )
    
    found_opps = {}
    if opp_1:
        found_opps[opp_1["direction"]] = opp_1
    if opp_2:
        found_opps[opp_2["direction"]] = opp_2
        
    for direction in ["BUY KALSHI YES / BUY POLYMARKET NO", "BUY KALSHI NO / BUY POLYMARKET YES"]:
        opp = found_opps.get(direction)
        last_opp = active_opportunities.get(direction)
        
        if opp:
            # Trigger execution report if new, or size/profit changed meaningfully
            if not last_opp or last_opp["size"] != opp["size"] or abs(last_opp["profit"] - opp["profit"]) > 0.01:
                threading.Thread(
                    target=execute_arbitrage,
                    args=(opp,),
                    daemon=True,
                ).start()
                active_opportunities[direction] = opp
        else:
            # If opportunity closed, log the event and clear it from active
            if last_opp:
                print(f"ℹ️  [Arbitrage Closed] {direction}")
                active_opportunities.pop(direction, None)

# Update callbacks
def on_kalshi_update(book):
    global latest_kalshi_book
    latest_kalshi_book = {k: v.copy() for k, v in book.items()}
    check_arbitrage()

def on_pm_update(book):
    global latest_polymarket_book
    latest_polymarket_book = {k: v.copy() for k, v in book.items()}
    check_arbitrage()

async def _run_feed(name, coro_fn, on_crash_clear, *args, **kwargs):
    """Safety wrapper — restarts a feed coroutine if it exits unexpectedly.
    
    The modules themselves have internal retry loops, so this is defense-in-depth.
    If a module somehow exits, this wrapper restarts it and clears stale book data.
    """
    while True:
        try:
            await coro_fn(*args, **kwargs)
            # Should never reach here (modules loop forever), but handle it
            print(f"⚠️  [{name}] feed exited cleanly — restarting in 5s...")
            on_crash_clear()
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ [{name}] feed crashed: {e}")
            print(f"   └─ Restarting in 5s...")
            on_crash_clear()
            await asyncio.sleep(5)


async def main():
    print(f"\n🚀 Starting Kalshi & Polymarket Arbitrage Engine...")
    print(f"   └─ Kalshi Market Ticker:  {kalshi_ticker}")
    print(f"   └─ Polymarket US Slug:     {pm_slug}")
    print("=" * 60)
    
    def clear_kalshi():
        global latest_kalshi_book
        latest_kalshi_book = {}

    def clear_polymarket():
        global latest_polymarket_book
        latest_polymarket_book = {}

    try:
        await asyncio.gather(
            _run_feed(
                "Kalshi",
                kalshi_mod.orderbook_websocket,
                clear_kalshi,
                on_update_callback=on_kalshi_update,
            ),
            _run_feed(
                "Polymarket",
                pm_mod.stream_orderbook,
                clear_polymarket,
                on_update_callback=on_pm_update,
            ),
        )
    except asyncio.CancelledError:
        print("\nStopping background tasks...")
    except KeyboardInterrupt:
        print("\nShutdown requested by user.")
    except Exception as e:
        print(f"\n❌ Error in main loops: {e}")
    finally:
        print("Engine stopped.")

if __name__ == "__main__":
    asyncio.run(main())
