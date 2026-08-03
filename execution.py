from helpers import log_trade
from Kalshi_PM_API_request import place_pm_buy_order, place_kalshi_buy_order

def execute_arbitrage(allocs, total_profit_scaled, total_volume, strategy_name, kalshi_side, pm_side, kalshi_ticker, pm_ticker, test_mode=True):
    """
    Handles actual execution logic and calls the background logger.
    """

    for alloc in allocs:
        kalshi_price = alloc['kalshi_price']
        pm_price = alloc['pm_price']
        qty = alloc['qty_scaled_to_100th_of_vol']/100
        
        print(f'Buying {kalshi_ticker} on kalshi')
        print(f'{kalshi_side}: {qty} at {kalshi_price} cent')
        

        if not test_mode:
            place_kalshi_buy_order()
            place_pm_buy_order()

        # place_kalshi_buy_order(kalshi_ticker, )
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
