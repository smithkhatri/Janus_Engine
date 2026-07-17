import asyncio
import base64
import json
import os
import time

# pyrefly: ignore [missing-import]
import websockets
# pyrefly: ignore [missing-import]
from cryptography.hazmat.primitives.asymmetric import ed25519
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
# ===============================================================================
# https://gateway.polymarket.us/v1/events/slug/
# ===============================================================================
PRINT_SNAPSHOT = True
PRINT_UPDATES = True

PM_ORDERBOOK = {"yes_bid": {}, "yes_ask": {}, "no_bid": {}, "no_ask": {}}
# ===============================================================================
# SETUP
# ===============================================================================



def _load_market_config(key):
    """Read a KEY = VALUE from market_slugs.txt (next to this script)."""
    import pathlib
    cfg_path = pathlib.Path(__file__).resolve().parent / "market_slugs.txt"
    with open(cfg_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip()
    raise RuntimeError(f"{key} not found in {cfg_path}")

MARKET_SLUG = _load_market_config("MARKET_SLUG")





load_dotenv("API_key.env")
KEY_ID = os.getenv("PM_KEY_ID")
SECRET_KEY_B64 = os.getenv("PM_SECRET_KEY")  # base64-encoded, from the developer portal

WS_URL = "wss://api.polymarket.us/v1/ws/markets"
WS_PATH = "/v1/ws/markets"

# ===============================================================================


def build_auth_headers(secret_key_b64: str, key_id: str, method: str, path: str) -> dict:
    """Build the Ed25519-signed auth headers Polymarket US expects on the WS handshake."""
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(secret_key_b64)[:32]
    )

    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()

    return {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
    }

def print_formatted_book(book, delta_side=None, delta_price=None, delta_qty=None):
    """Prints the orderbook in a clear, human-readable format.
    
    YES contract and NO contract books are printed separately.
    For each, Asks are printed on top (sorted descending) and Bids on bottom (sorted descending),
    separated by a spread gap in the middle.
    """
    # Track the active delta updates to show next to volume
    deltas = {}
    if delta_side is not None and delta_price is not None and delta_qty is not None:
        if delta_side == "yes":
            deltas[('yes_bid', delta_price)] = delta_qty
            deltas[('no_ask', round(1.0 - delta_price, 2))] = delta_qty
        elif delta_side == "no":
            deltas[('no_bid', delta_price)] = delta_qty
            deltas[('yes_ask', round(1.0 - delta_price, 2))] = delta_qty

    def format_volume(volume, delta_val):
        if volume == 0 or delta_val is None:
            return f"{volume}"
        sign = "+" if delta_val > 0 else ""
        return f"{volume} ({sign}{delta_val})"

    def format_price(p):
        return f"${p:.2f}"

    def print_contract_book(contract_name, bids_key, asks_key):
        bids = book.get(bids_key, {})
        asks = book.get(asks_key, {})
        
        # Sort asks descending (so lowest ask is closest to the middle gap)
        sorted_ask_prices = sorted(asks.keys(), reverse=True)
        # Sort bids descending (so highest bid is closest to the middle gap)
        sorted_bid_prices = sorted(bids.keys(), reverse=True)
        
        # Calculate spread
        best_bid = max(bids.keys()) if bids else None
        best_ask = min(asks.keys()) if asks else None
        if best_bid is not None and best_ask is not None:
            spread_val = round(best_ask - best_bid, 2)
            spread_str = f"Spread: {format_price(spread_val)}"
        else:
            spread_str = "Spread: N/A"

        print(f"\n--- {contract_name} CONTRACT ---")
        print("ASKS:")
        if not sorted_ask_prices:
            print("  (Empty)")
        for p in sorted_ask_prices:
            vol = asks[p]
            delta_val = deltas.get((asks_key, p))
            print(f"  Price: {format_price(p)} | Vol: {format_volume(vol, delta_val)}")
            
        print(f"\n  [ {spread_str} ]\n")
        
        if not sorted_bid_prices:
            print("  (Empty)")
        for p in sorted_bid_prices:
            vol = bids[p]
            delta_val = deltas.get((bids_key, p))
            print(f"  Price: {format_price(p)} | Vol: {format_volume(vol, delta_val)}")
        print("BIDS:")

    print("\n==============================================")
    print("             POLYMARKET ORDERBOOK             ")
    print(f" Market: {MARKET_SLUG}")
    print("==============================================")
    print_contract_book("YES", "yes_bid", "yes_ask")
    print_contract_book("NO", "no_bid", "no_ask")
    print("==============================================\n")

def clean_qty(qty_str):
    return int(float(qty_str))

async def stream_orderbook(on_update_callback=None):
    global PM_ORDERBOOK

    backoff = 1
    max_backoff = 30

    while True:
        try:
            # Fresh auth headers for each attempt (timestamp-signed)
            headers = build_auth_headers(SECRET_KEY_B64, KEY_ID, "GET", WS_PATH)

            async with websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:
                print(f"Connected. Subscribing to market data for {MARKET_SLUG}")

                subscribe_msg = {
                    "subscribe": {
                        "requestId": "md-sub-1",
                        "subscriptionType": 1,
                        "marketSlugs": [MARKET_SLUG],
                    }
                }
                await ws.send(json.dumps(subscribe_msg))

                # Reset backoff on successful connection
                backoff = 1
                first_message = True

                async for raw in ws:
                    data = json.loads(raw)

                    if "heartbeat" in data:
                        continue  # keep-alive, nothing to do

                    if data.get("error"):
                        print(f"Error: {data['error']}")
                        continue

                    market_data = data.get("marketData")
                    if market_data is None:
                        # Might be a trade or lite payload depending on what you subscribed to
                        print(f"Non-book message: {data}")
                        continue

                    # Populate PM_ORDERBOOK from the marketData payload
                    PM_ORDERBOOK = {"yes_bid": {}, "yes_ask": {}, "no_bid": {}, "no_ask": {}}
                    bids = market_data.get("bids") or []
                    offers = market_data.get("offers") or []
                    for lvl in bids:
                        price = round(float(lvl["px"]["value"]), 2)
                        qty = clean_qty(lvl["qty"])
                        PM_ORDERBOOK["yes_bid"][price] = qty
                        PM_ORDERBOOK["no_ask"][round(1.0 - price, 2)] = qty
                    for lvl in offers:
                        price = round(float(lvl["px"]["value"]), 2)
                        qty = clean_qty(lvl["qty"])
                        PM_ORDERBOOK["yes_ask"][price] = qty
                        PM_ORDERBOOK["no_bid"][round(1.0 - price, 2)] = qty

                    if on_update_callback is not None:
                        on_update_callback(PM_ORDERBOOK)

                    if first_message:
                        if PRINT_SNAPSHOT:
                            print_formatted_book(PM_ORDERBOOK)
                        first_message = False
                    else:
                        # Note: Polymarket US resends the FULL book on every update,
                        # there's no incremental delta to merge like on Kalshi.
                        if PRINT_UPDATES:
                            print_formatted_book(PM_ORDERBOOK)

        except asyncio.CancelledError:
            print("🛑 [Polymarket] Connection cancelled.")
            raise
        except Exception as e:
            print(f"⚠️  [Polymarket] WebSocket disconnected: {e}")
            print(f"   └─ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


if __name__ == "__main__":
    asyncio.run(stream_orderbook())
