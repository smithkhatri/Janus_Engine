import asyncio
from Kalshi_PM_API_request import get_pm_balance, get_kalshi_balance


async def balance_syncer(shared_balance):
    """
    BACKGROUND TASK: Periodically fetches the true wallet balances from Kalshi/PM APIs 
    and forcefully overwrites the shared balance state. This heals any optimistic deduction errors.
    All brains share this single balance object.
    """
    while True:
        try:
            # 🚨 MUST USE to_thread() SO `requests` DOES NOT BLOCK THE WEBSOCKETS! 🚨
            true_k_balance_dollars = await asyncio.to_thread(get_kalshi_balance)
            true_p_balance_dollars = await asyncio.to_thread(get_pm_balance)
            
            # Convert to scaled units (hundredths of a cent)
            # We use round() to prevent IEEE 754 float truncation issues before int() cast
            shared_balance.k_balance = int(round(true_k_balance_dollars * 10000))
            shared_balance.p_balance = int(round(true_p_balance_dollars * 10000))
            
        except Exception as e:
            # If the API fails, we just ignore it. The engine will keep running on 
            # its optimistic local balance until the API recovers in a few seconds.
            print(f"⚠️ Background balance sync failed: {e}")
            
        # Sync every 2 seconds
        await asyncio.sleep(2)
