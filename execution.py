import asyncio
from helpers import log_trade
from Kalshi_PM_API_request import place_pm_buy_order, place_kalshi_buy_order
from concurrent.futures import ThreadPoolExecutor, as_completed

_executor = ThreadPoolExecutor(max_workers=10)

def execute_arbitrage(allocs, total_profit_scaled, total_volume, strategy_name, kalshi_side, pm_side, kalshi_ticker, pm_ticker, test_mode=True):
    """
    Handles actual execution logic and calls the background logger.
    """

    for alloc in allocs:
        kalshi_price = alloc['kalshi_price'] # Check if price is scaled or not
        pm_price = alloc['pm_price']
        qty = alloc['qty_scaled_to_100th_of_vol']/100

        if not test_mode:
            # 🚨 Fire BOTH legs at the EXACT same instant! 🚨
            k_future = _executor.submit(place_kalshi_buy_order, kalshi_ticker, kalshi_side, kalshi_price, qty)
            p_future = _executor.submit(place_pm_buy_order, pm_ticker, pm_side, pm_price, qty)

            try:
                k_result = k_future.result(timeout=5)
            except Exception as e:
                print(f"🔴 KALSHI LEG FAILED: {e}")
                k_result = None
            try:
                p_result = p_future.result(timeout=5)
            except Exception as e:
                print(f"🔴 PM LEG FAILED: {e}")
                p_result = None
            

            # 🚨 LEG RISK DETECTION (LEVEL 2) 🚨
            k_fill = 0
            if k_result:
                try:
                    # Kalshi returns a requests.Response object
                    k_fill = float(k_result.json().get('fill_count', 0))
                except Exception as e:
                    print(f"⚠️ Could not parse Kalshi fill count: {e}")

            p_fill = 0
            if p_result:
                try:
                    # Polymarket SDK retrieve() returns {'order': {'cumQuantity': X}}
                    order_data = p_result.get('order', {})
                    if order_data:
                        p_fill = float(order_data.get('cumQuantity', 0))
                except Exception as e:
                    print(f"⚠️ Could not parse PM fill count: {e}")

            # Evaluate execution success
            if abs(k_fill - qty) < 0.01 and abs(p_fill - qty) < 0.01:
                print(f"✅ PERFECT ARBITRAGE FILL: {qty} contracts executed successfully.")
            elif k_fill == 0 and p_fill == 0:
                print(f"🤷‍♂️ BOTH LEGS FAILED OR MISSED: 0 contracts filled.")
            else:
                # We have a mismatch!
                if k_fill > 0 and p_fill == 0:
                    print(f"⚠️ CRITICAL: Kalshi filled {k_fill} but PM failed! UNHEDGED POSITION!")
                elif p_fill > 0 and k_fill == 0:
                    print(f"⚠️ CRITICAL: PM filled {p_fill} but Kalshi failed! UNHEDGED POSITION!")
                else:
                    print(f"⚠️ PARTIAL FILL MISMATCH: Kalshi filled {k_fill}, PM filled {p_fill}. UNHEDGED POSITION!")
            
        
        if test_mode:
            print(f'Buying {kalshi_ticker} on kalshi')
            print(f'{kalshi_side}: {qty} at {kalshi_price} cent')
            print()
            print(f'Buying {pm_ticker} on PolyMarket')
            print(f'{pm_side}: {qty} at {pm_price} cent')

            print()
            print()

    # 2. Log the trade instantly to memory
    log_trade(strategy_name, kalshi_side, pm_side, total_volume, total_profit_scaled, allocs)
    
    # # 3. Simulate execution prints
    # print("\n" + "="*50)
    # print(f"🚨 EXECUTING ARBITRAGE: {strategy_name} 🚨")
    # print(f"Total Paired Contracts: {total_volume/100}")
    # print(f"Total Guaranteed Profit: ${(total_profit_scaled/10000):.2f}") 
    # for i, a in enumerate(allocs):
    #     profit_cents = a['profit_scaled_to_100th_of_cent'] / 100
    #     print(f"  Level {i+1}: Buy {a['qty_scaled_to_100th_of_vol']} at Kalshi {a['kalshi_price']}¢ | PM {a['pm_price']}¢ -> Profit: {profit_cents:.2f}¢")
    # print("="*50 + "\n")
