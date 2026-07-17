import asyncio
import base64
import json
import time
# pyrefly: ignore [missing-import]
import websockets
# pyrefly: ignore [missing-import]
from cryptography.hazmat.primitives import serialization, hashes
# pyrefly: ignore [missing-import]
from cryptography.hazmat.primitives.asymmetric import padding





MARKET_TICKER = "KXHIGHMIA-26JUL16-B92.5"  # Replace with any open market <--------------------------------------------------------






#===============================================================================================================================
#INITIAL SETUP

# Printing configuration toggles
PRINT_SNAPSHOT = False
PRINT_DELTAS = False

#===============================================================================================================================


kalshi_book = {"yes_bid": {}, "yes_ask": {}, "no_bid": {}, "no_ask": {}}

import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv("API_key.env")

# Configuration
KEY_ID = os.getenv("KEY_ID")
PRIVATE_KEY_PATH = os.getenv('PRIVATE_KEY_PATH')
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
    print("               KALSHI ORDERBOOK               ")
    print("==============================================")
    print_contract_book("YES", "yes_bid", "yes_ask")
    print_contract_book("NO", "no_bid", "no_ask")
    print("==============================================\n")

async def orderbook_websocket(on_update_callback=None):
    """Connect to WebSocket and subscribe to orderbook with auto-reconnection."""
    global kalshi_book

    # Load private key once (reused across reconnections)
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
                print(f"Connected! Subscribing to orderbook for {MARKET_TICKER}")

                # Clear stale data before receiving fresh snapshot
                kalshi_book = {"yes_bid": {}, "yes_ask": {}, "no_bid": {}, "no_ask": {}}

                # Subscribe to orderbook
                subscribe_msg = {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_ticker": MARKET_TICKER
                    }
                }
                await websocket.send(json.dumps(subscribe_msg))

                # Reset backoff on successful connection
                backoff = 1

                # Process messages
                async for message in websocket:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "subscribed":
                        print(f"Subscribed: {data}")

                    elif msg_type == "orderbook_snapshot":
                        yes_bids = data.get('msg', {}).get('yes_dollars_fp', [])
                        no_bids = data.get('msg', {}).get('no_dollars_fp', [])

                        for bid in yes_bids:
                            price = round(float(bid[0]), 2)
                            kalshi_book['yes_bid'][price] = int(float(bid[1]))

                            ask_price = round(1.0 - price, 2)
                            kalshi_book['no_ask'][ask_price] = int(float(bid[1]))
                            
                        for bid in no_bids:
                            price = round(float(bid[0]), 2)
                            kalshi_book['no_bid'][price] = int(float(bid[1]))

                            ask_price = round(1.0 - price, 2)
                            kalshi_book['yes_ask'][ask_price] = int(float(bid[1]))
                        
                        if PRINT_SNAPSHOT:
                            print_formatted_book(kalshi_book)
                        if on_update_callback is not None:
                            on_update_callback(kalshi_book)

                    elif msg_type == "orderbook_delta":
                        msg_payload = data.get('msg', {})
                        
                        
                        # 1. Extract the delta values safely
                        price_str = msg_payload.get('price_dollars')
                        delta_str = msg_payload.get('delta_fp')
                        side = msg_payload.get('side')
                        
                        if not price_str or not delta_str or not side:
                            continue # Skip if payload is malformed
                        
                        # 2. Convert to float dollars for safe math and exact dictionary matching
                        price = round(float(price_str), 2)
                        ask_price = round(1.0 - price, 2)
                        delta_qty = int(float(delta_str))

                        # The client_order_id field is optional - only present when you caused the change
                        if 'client_order_id' in msg_payload and PRINT_DELTAS:
                            print(f"Orderbook update (your order {msg_payload['client_order_id']}): {data}")

                        if PRINT_DELTAS:
                            print(f"\n>>> DELTA RECEIVED: Side: {side.upper()} | Price: ${float(price_str):.2f} | Delta Volume: {delta_qty:+d}")

                        # 3. Process YES Bids and derive NO Asks THEN UPDATE kalshi_book
                        if side == "yes":
                            current_qty = kalshi_book['yes_bid'].get(price, 0)
                            new_qty = current_qty + delta_qty
                            
                            if new_qty <= 0:
                                kalshi_book['yes_bid'].pop(price, None)
                                kalshi_book['no_ask'].pop(ask_price, None)
                            else:
                                kalshi_book['yes_bid'][price] = new_qty
                                kalshi_book['no_ask'][ask_price] = new_qty
                                
                        # 4. Process NO Bids and derive YES Asks
                        elif side == "no":
                            current_qty = kalshi_book['no_bid'].get(price, 0)
                            new_qty = current_qty + delta_qty
                            
                            if new_qty <= 0:
                                kalshi_book['no_bid'].pop(price, None)
                                kalshi_book['yes_ask'].pop(ask_price, None)
                            else:
                                kalshi_book['no_bid'][price] = new_qty
                                kalshi_book['yes_ask'][ask_price] = new_qty

                        if PRINT_DELTAS:
                            print_formatted_book(kalshi_book, delta_side=side, delta_price=price, delta_qty=delta_qty)
                        if on_update_callback is not None:
                            on_update_callback(kalshi_book)


                    elif msg_type == "error":
                        print(f"Error: {data}")

        except asyncio.CancelledError:
            print("🛑 [Kalshi] Connection cancelled.")
            raise
        except Exception as e:
            print(f"⚠️  [Kalshi] WebSocket disconnected: {e}")
            print(f"   └─ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

# Run the example
if __name__ == "__main__":
    asyncio.run(orderbook_websocket())

