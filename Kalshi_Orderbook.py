import asyncio
import json
import base64
import time
# pyrefly: ignore [missing-import]
import websockets
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
# from test_helpers import pretty_print_Kalshi_book

# Kalshi Orderbook
# We are only dealing with prices that are in whole cents
# This does not take prices in fraciton of cent like 0.012 only 0.01
# Also volume can only have max 2 trailing decimal
class KalshiOrderBook:
    def __init__(self):
        self.yes_bids = [0] * 101
        self.no_bids  = [0] * 101

        self.yes_asks = [0] * 101
        self.no_asks  = [0] * 101

        self.best_yes_bid_idx = 0
        self.best_yes_ask_idx = 100

        self.best_no_bid_idx =  0
        self.best_no_ask_idx =  100

    def clear(self):
        """Reset orderbook on reconnect or fresh snapshot."""
        self.yes_bids = [0] * 101
        self.no_bids =  [0] * 101

        self.yes_asks = [0] * 101
        self.no_asks =  [0] * 101

        self.best_yes_bid_idx = 0
        self.best_yes_ask_idx = 100

        self.best_no_bid_idx =  0
        self.best_no_ask_idx =  100



    def apply_snapshot(self, yes_bids_raw, no_bids_raw):
        self.clear()
        
        for price_str, qty_str in yes_bids_raw:
            price_in_cent = self.price_str_to_int(price_str)
            self.yes_bids[price_in_cent] = self._qty_str_to_int(qty_str)
            self.no_asks[100-price_in_cent] = self._qty_str_to_int(qty_str)
        
        for price_str, qty_str in no_bids_raw:
            price_in_cent = self.price_str_to_int(price_str)
            self.no_bids[price_in_cent] = self._qty_str_to_int(qty_str)
            self.yes_asks[100-price_in_cent] = self._qty_str_to_int(qty_str)
        
        for p in range(99, 0, -1):
            if self.yes_bids[p] > 0:
                self.best_yes_bid_idx = p
                break
        
        for p in range(99, 0, -1):
            if self.no_bids[p] > 0:
                self.best_no_bid_idx = p
                break
        
        self.best_yes_ask_idx = 100 - self.best_no_bid_idx
        self.best_no_ask_idx = 100 - self.best_yes_bid_idx

    def apply_delta(self, price_str, delta_str, side):
        price_in_cent = self.price_str_to_int(price_str)
        
        if side == 'yes':
            new_volume = self.yes_bids[price_in_cent] + self._qty_str_to_int(delta_str)
            self._check_volume(new_volume)
            self.yes_bids[price_in_cent] = new_volume
            self.no_asks[100-price_in_cent] = new_volume

            if new_volume > 0 and price_in_cent > self.best_yes_bid_idx:
                self.best_yes_bid_idx = price_in_cent
            
            elif price_in_cent == self.best_yes_bid_idx and new_volume == 0:

                for p in range(self.best_yes_bid_idx - 1, 0, -1):
                    if self.yes_bids[p] > 0:
                        self.best_yes_bid_idx = p
                        break
            
                else:
                    self.best_yes_bid_idx = 0

        if side == 'no':
            new_volume = self.no_bids[price_in_cent] + self._qty_str_to_int(delta_str)
            self._check_volume(new_volume)
            self.no_bids[price_in_cent] = new_volume
            self.yes_asks[100-price_in_cent] = new_volume

            if new_volume > 0 and price_in_cent > self.best_no_bid_idx:
                self.best_no_bid_idx = price_in_cent
            
            elif price_in_cent == self.best_no_bid_idx and new_volume == 0:
                for p in range(self.best_no_bid_idx - 1, 0, -1):
                    if self.no_bids[p] > 0:
                        self.best_no_bid_idx = p
                        break
                else:
                    self.best_no_bid_idx = 0

        self.best_yes_ask_idx = 100 - self.best_no_bid_idx
        self.best_no_ask_idx = 100 - self.best_yes_bid_idx      

    def _check_volume(self, new_volume):
        if new_volume < 0:
            # This acts as a tripwire. It instantly aborts the current execution
            # and throws the engine down to your `except Exception as e:` block!
            raise ValueError(f"Desync detected! Volume dropped below zero: {new_volume}")

    def price_str_to_int(self, price_str):
        return round(float(price_str) * 100) # returns in cent
    
    def _qty_str_to_int(self, qty_str): # input format
        return round(float(qty_str) * 100)


def _load_market_config(key):
    # Reads single market name
    # So this is only for Janus_Engine_V1.0
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


MARKET_TICKER = _load_market_config("KALSHI_MARKET_TICKER")
PRINT_SNAPSHOT = _load_market_config("PRINT_SNAPSHOT")
PRINT_DELTAS = _load_market_config("PRINT_DELTAS")

import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv("API_key.env")

# Configuration
KEY_ID = os.getenv("KALSHI_KEY_ID")
PRIVATE_KEY_PATH = os.getenv('KALSHI_PRIVATE_KEY_PATH')
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

def sign_pss_text(private_key, text: str) -> str:
    """Sign message using RSA-PSS"""
    message = text.encode('utf-8')
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

def create_headers(private_key, method: str, path: str) -> dict:
    """Create authentication headers"""
    timestamp = str(int(time.time() * 1000))
    msg_string = timestamp + method + path.split('?')[0]
    signature = sign_pss_text(private_key, msg_string)

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

async def orderbook_websocket(market_ticker, book: KalshiOrderBook = None, on_update_callback = None):
    if book is None: book = KalshiOrderBook()

    with open(PRIVATE_KEY_PATH, 'rb') as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None
        )

    backoff = 1
    max_backoff = 30

    while True:
        try:
            # Fresh auth headers for each attempt (timestamp-signed)
            ws_headers = create_headers(private_key, "GET", "/trade-api/ws/v2")

            async with websockets.connect(
                WS_URL,
                additional_headers=ws_headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as websocket:
                print(f"Connected! Subscribing to orderbook for {market_ticker}")

                
                book.clear()
                expected_seq = None
                last_snapshot_time = time.time()

                subscribe_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_ticker": market_ticker
                    }
                }

                await websocket.send(json.dumps(subscribe_msg))

                # Reset backoff on successful connection
                backoff = 1

                async for message in websocket:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "subscribed":
                        print(f"Subscribed: {data}")

                    elif msg_type == "orderbook_snapshot":
                        expected_seq = data.get("seq")
                        last_snapshot_time = time.time()
                        
                        yes_bids = data.get('msg', {}).get('yes_dollars_fp', [])
                        no_bids = data.get('msg', {}).get('no_dollars_fp', [])

                        book.apply_snapshot(yes_bids, no_bids)
                        if on_update_callback:
                            on_update_callback()
                        
                    elif msg_type == "orderbook_delta":
                        # 1-hour periodic reconnect safety mechanism
                        if time.time() - last_snapshot_time > 3600 * 2:
                            print("🔄 2 hour elapsed since last snapshot. Reconnecting to sync orderbook (just in case)...")
                            break
                            
                        seq = data.get("seq")
                        if expected_seq is not None and seq is not None:
                            if seq != expected_seq + 1:
                                print(f"⚠️ Sequence gap detected (expected {expected_seq + 1}, got {seq}). Reconnecting to resync...")
                                break  # Break loop to trigger reconnect
                        if seq is not None:
                            expected_seq = seq
                            
                        msg_payload = data.get('msg', {})

                        price_str = msg_payload.get('price_dollars')
                        delta_str = msg_payload.get('delta_fp')
                        side = msg_payload.get('side')

                        if not price_str or not delta_str or not side:
                            continue # Skip if payload is malformed

                        book.apply_delta(price_str, delta_str, side)

                        if on_update_callback:
                            on_update_callback()

                        # pretty_print_Kalshi_book(book)

        except asyncio.CancelledError:
            print("🛑 [Kalshi] Connection cancelled.")
            raise

        except Exception as e:
            print(f"⚠️  [Kalshi] WebSocket disconnected: {e}")
            print(f"   └─ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


# if __name__ == "__main__":
#     asyncio.run(orderbook_websocket(MARKET_TICKER, kalshi_orderbook_1))


