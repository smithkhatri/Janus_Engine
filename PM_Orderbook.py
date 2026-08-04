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


async def stream_orderbook(market_slugs, router):
    """
    Multi-market Polymarket WebSocket.
    Subscribes to ALL slugs on a single connection and routes
    each message to the correct orderbook via the router.
    """
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
                print(f"[PM] Connected! Subscribing to {len(market_slugs)} markets.")

                subscribe_msg = {
                    "subscribe": {
                        "requestId": "md-sub-1",
                        "subscriptionType": 1,
                        "marketSlugs": market_slugs,
                    }
                }
                await ws.send(json.dumps(subscribe_msg))

                # Reset backoff on successful connection
                backoff = 1

                async for raw in ws:
                    data = json.loads(raw)

                    if "heartbeat" in data:
                        continue  # keep-alive, nothing to do

                    if data.get("error"):
                        print(f"[PM] Error: {data['error']}")
                        continue

                    market_data = data.get("marketData")
                    if market_data is None:
                        continue

                    # Route by marketSlug
                    slug = market_data.get("marketSlug")
                    bids = market_data.get("bids") or []
                    offers = market_data.get("offers") or []

                    book = router.get_pm_book(slug)
                    if book:
                        book.update_book(bids, offers)
                        router.on_pm_update(slug)

        except asyncio.CancelledError:
            print("🛑 [Polymarket] Connection cancelled.")
            raise
        except Exception as e:
            print(f"⚠️  [Polymarket] WebSocket disconnected: {e}")
            print(f"   └─ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
