import asyncio
from brain import JanusBrain
from PM_Orderbook import PM_OrderBook, MARKET_SLUG as PM_SLUG, stream_orderbook as pm_ws
from Kalshi_Orderbook import KalshiOrderBook, orderbook_websocket as kalshi_ws, MARKET_TICKER as KALSHI_TICKER


# We must import the orderbook instances directly to access their memory


# We need a PM_book instance. I'll assume you will create one in PM_Orderbook or we pass it in.
# For now, let's instantiate it here and pass it into the PM stream.


pm_book = PM_OrderBook()
kalshi_book = KalshiOrderBook()

# Initialize the Brain globally
janus_brain = JanusBrain(kalshi_book, pm_book)

# Callback function to inject into the WebSocket loops
def on_market_update():
    janus_brain.evaluate_arbitrage()


# async def main():
#     print("🚀 Igniting Janus Engine Mark-2 Strategy Engine...")
    
#     # NOTE: You MUST update PM_Orderbook.py and Kalshi_Orderbook.py 
#     # to accept `on_update_callback` in their functions and trigger it!
    
#     await asyncio.gather(
#         kalshi_ws(KALSHI_TICKER, kalshi_book, on_market_update),
#         pm_ws(PM_SLUG, pm_book, on_update_callback=on_market_update)
#     )

# if __name__ == "__main__":
#     asyncio.run(main())

