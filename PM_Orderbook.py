import asyncio
import base64
import json
import os
import time
# pyrefly: ignore [missing-import]
import websockets
from test_helpers import pretty_print_PM_Orderbook
# pyrefly: ignore [missing-import]
from cryptography.hazmat.primitives.asymmetric import ed25519
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# PRINT_SNAPSHOT = True
# PRINT_UPDATES = True

class PM_OrderBook:
    def __init__(self):
        self.yes_bids = [0] * 101
        self.no_bids  = [0] * 101

        self.yes_asks = [0] * 101
        self.no_asks  = [0] * 101

        self.best_yes_bid_idx = 0
        self.best_yes_ask_idx = 100

        self.best_no_bid_idx =  0
        self.best_no_ask_idx =  100

    def update_book(self, raw_bids, raw_asks):
        self.fast_wipe()

        for lvl in raw_bids:
            price = self.price_str_to_int(lvl["px"]["value"]) # Price in cent
            qty = self.qty_str_to_int(lvl["qty"])
            self.yes_bids[price] = qty
            self.no_asks[100-price] = qty

            if qty > 0 and price > self.best_yes_bid_idx:
                self.best_yes_bid_idx = price

        for lvl in raw_asks:
            price = self.price_str_to_int(lvl["px"]["value"]) # Price in cent
            qty = self.qty_str_to_int(lvl["qty"])
            self.yes_asks[price] = qty
            self.no_bids[100-price] = qty

            if qty > 0 and price < self.best_yes_ask_idx:
                self.best_yes_ask_idx = price
        
        self.best_no_bid_idx = 100 - self.best_yes_ask_idx
        self.best_no_ask_idx = 100 - self.best_yes_bid_idx


    def price_str_to_int(self, price_str):
        return (round(float(price_str) * 100))

    def qty_str_to_int(self, qty_str):
        return (round(float(qty_str) * 100))
    
    def fast_wipe(self):
        # The [:] means "replace the contents of the existing list in memory"
        # rather than creating a new list object.
        self.yes_bids[:] = (0 for _ in range(101))
        self.no_bids[:] = (0 for _ in range(101))
        self.yes_asks[:] = (0 for _ in range(101))
        self.no_asks[:] = (0 for _ in range(101))

        self.best_yes_bid_idx = 0
        self.best_yes_ask_idx = 100

        self.best_no_bid_idx =  0
        self.best_no_ask_idx =  100



def _load_market_config(key):
    """Read a KEY = VALUE from market_slugs.txt (next to this script)."""
    import pathlib
    cfg_path = pathlib.Path(__file__).resolve().parent / "configuration.txt"
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


MARKET_SLUG = _load_market_config("PM_MARKET_SLUG")
load_dotenv("API_key.env")
KEY_ID = os.getenv("PM_KEY_ID")
SECRET_KEY_B64 = os.getenv("PM_SECRET_KEY")
WS_URL = "wss://api.polymarket.us/v1/ws/markets"
WS_PATH = "/v1/ws/markets"


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


async def stream_orderbook(market_slug, PM_book, on_update_callback=None):
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
                print(f"Connected. Subscribing to market data for {market_slug}")

                subscribe_msg = {
                    "subscribe": {
                        "requestId": "md-sub-1",
                        "subscriptionType": 1,
                        "marketSlugs": [market_slug],
                    }
                }
                await ws.send(json.dumps(subscribe_msg))

                # PM_book is now passed in as an argument

                # Reset backoff on successful connection
                backoff = 1
                # first_message = True

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

                    bids = market_data.get("bids") or []
                    offers = market_data.get("offers") or []

                    PM_book.update_book(bids, offers)
                    if on_update_callback:
                        on_update_callback()

                    # if first_message:
                    #     if PRINT_SNAPSHOT:
                    #         print_formatted_book(PM_ORDERBOOK)
                    #     first_message = False

                    # pretty_print_PM_Orderbook(PM_book)

                    

                    



        except asyncio.CancelledError:
            print("🛑 [Polymarket] Connection cancelled.")
            raise
        except Exception as e:
            print(f"⚠️  [Polymarket] WebSocket disconnected: {e}")
            print(f"   └─ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


# if __name__ == "__main__":
#     asyncio.run(stream_orderbook(MARKET_SLUG))
