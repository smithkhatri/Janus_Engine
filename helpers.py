import time
import os
import csv
import asyncio
from datetime import datetime
from Kalshi_PM_API_request import get_pm_balance, get_kalshi_balance

# Global in-memory queue for lightning-fast logging (Hot Path)
_trade_queue = []
_LOG_DIR = "bot_logs"

def log_trade(strategy, k_side, p_side, total_vol_scaled, total_profit_scaled, allocs):
    """
    HOT PATH: O(1) memory append. Zero I/O blocking.
    """
    timestamp = time.time()
    
    # 🚀 EFFICIENCY TRICK: Instead of saving a giant JSON array of allocations, 
    # we compress it into a tiny readable string like "100@K45/P40|50@K46/P40"
    allocs_str = "|".join([
        f"{a['qty_scaled_to_100th_of_vol']}@K{a['kalshi_price']}/P{a['pm_price']}" 
        for a in allocs
    ])

    _trade_queue.append((
        timestamp, strategy, k_side, p_side, 
        total_vol_scaled, total_profit_scaled, allocs_str
    ))

async def log_flusher():
    """
    COLD PATH: Runs in the background, writes to daily CSV files.
    """
    global _trade_queue
    
    if not os.path.exists(_LOG_DIR):
        os.makedirs(_LOG_DIR)

    while True:
        await asyncio.sleep(5)  # Wake up every 5 seconds to flush to disk
        
        if _trade_queue:
            # Instantly swap the list so the engine isn't blocked
            
            to_write = _trade_queue
            _trade_queue = []
            
            # 🚀 EFFICIENCY TRICK: Daily Log Rotation (trades_2026-08-02.csv)
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            file_path = os.path.join(_LOG_DIR, f"trades_{today_str}.csv")
            
            file_exists = os.path.exists(file_path)
            
            with open(file_path, "a", newline='') as f:
                writer = csv.writer(f)
                # Write headers only if it's a brand new file
                if not file_exists:
                    writer.writerow(["timestamp", "strategy", "kalshi_side", "pm_side", "volume_scaled", "profit_scaled", "allocations"])
                
                # Write all accumulated trades at once
                writer.writerows(to_write)

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

