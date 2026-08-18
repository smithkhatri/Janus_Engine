import os
import csv
import random
from datetime import datetime, timedelta

_LOG_DIR = "bot_logs"
EXEC_HEADERS = [
    "timestamp", "pair_id", "strategy",
    "k_price", "p_price", "intended_qty", "theoretical_profit",
    "k_fill_qty", "k_fill_time_ms", "k_status_code",
    "p_fill_qty", "p_fill_time_ms", "p_status_code",
    "outcome", "unwind_action", "unwind_pnl",
    "net_realized_pnl"
]

STRATEGIES = ["Kalshi YES / PM NO", "Kalshi NO / PM YES"]
PAIRS = ["NFL-24-MVP", "ELEC-24-PREZ", "FED-24-RATES", "GPT-24-AGI", "BTC-24-100K"]

def generate_data():
    if not os.path.exists(_LOG_DIR):
        os.makedirs(_LOG_DIR)

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=60)

    total_trades = 0

    for day in range(60):
        current_date = start_date + timedelta(days=day)
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Vary market opportunity day-by-day (e.g. more volatile days have more trades)
        base_trades = random.randint(5, 25)
        # Add some weekend slow-down
        if current_date.weekday() >= 5:
            base_trades = random.randint(2, 10)
            
        records = []
        for _ in range(base_trades):
            # Random time within the day
            trade_time = current_date.replace(
                hour=random.randint(0, 23),
                minute=random.randint(0, 59),
                second=random.randint(0, 59),
                microsecond=random.randint(0, 999999)
            )
            
            pair = random.choice(PAIRS)
            strategy = random.choice(STRATEGIES)
            
            # Generate realistic prices
            if strategy == "Kalshi YES / PM NO":
                k_price = random.randint(30, 60)
                p_price = random.randint(20, 98 - k_price)  # Ensure sum < 100
            else:
                k_price = random.randint(20, 50)
                p_price = random.randint(20, 98 - k_price)

            intended_qty = random.randint(10, 200)
            
            # Theoretical profit (in hundredths of a cent) - roughly 1-5 cents per contract
            # Since total price < 100, profit per contract is 100 - (k_price + p_price)
            # Minus commission (about 2-3 cents)
            profit_per_contract_cents = 100 - (k_price + p_price) - random.randint(1, 3)
            if profit_per_contract_cents <= 0:
                profit_per_contract_cents = random.randint(1, 4) # fallback
                
            theoretical_profit = profit_per_contract_cents * intended_qty * 100
            
            # Simulated Execution Outcome
            outcome_roll = random.random()
            if outcome_roll < 0.85:
                # Perfect execution
                k_fill = intended_qty
                p_fill = intended_qty
                k_status = 200
                p_status = 200
                outcome = "success"
                unwind = "none"
                unwind_pnl = 0
                net_pnl = theoretical_profit
            elif outcome_roll < 0.95:
                # Partial fill on one side
                k_fill = intended_qty
                p_fill = random.randint(1, intended_qty - 1)
                k_status = 200
                p_status = 200
                outcome = "partial_unwind"
                unwind = "market_sell_kalshi"
                unwind_pnl = -random.randint(500, 2000) # Unwind penalty
                
                # Pro-rate profit for successfully paired contracts, then apply unwind penalty
                paired_qty = min(k_fill, p_fill)
                net_pnl = (profit_per_contract_cents * paired_qty * 100) + unwind_pnl
            else:
                # Complete failure / race condition
                k_fill = 0
                p_fill = 0
                k_status = random.choice([200, 429, 500])
                p_status = random.choice([200, 429, 500])
                if k_status == 200 and p_status != 200:
                    k_fill = intended_qty
                    outcome = "leg_failed_unwind"
                    unwind = "market_sell_kalshi"
                    unwind_pnl = -random.randint(1000, 4000)
                    net_pnl = unwind_pnl
                else:
                    outcome = "failed_no_fill"
                    unwind = "none"
                    unwind_pnl = 0
                    net_pnl = 0

            # Execution latencies
            k_lat = random.randint(30, 150)
            p_lat = random.randint(40, 200)

            records.append({
                "timestamp": trade_time.isoformat() + "Z",
                "pair_id": pair,
                "strategy": strategy,
                "k_price": k_price,
                "p_price": p_price,
                "intended_qty": intended_qty,
                "theoretical_profit": theoretical_profit,
                "k_fill_qty": k_fill,
                "k_fill_time_ms": k_lat,
                "k_status_code": k_status,
                "p_fill_qty": p_fill,
                "p_fill_time_ms": p_lat,
                "p_status_code": p_status,
                "outcome": outcome,
                "unwind_action": unwind,
                "unwind_pnl": unwind_pnl,
                "net_realized_pnl": net_pnl
            })
            
            total_trades += 1

        # Sort daily records by timestamp
        records.sort(key=lambda x: x["timestamp"])

        file_path = os.path.join(_LOG_DIR, f"executions_{date_str}.csv")
        with open(file_path, "w", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=EXEC_HEADERS)
            writer.writeheader()
            writer.writerows(records)

    print(f"✅ Successfully generated 60 days of realistic test data ({total_trades} trades) in '{_LOG_DIR}/'")

if __name__ == "__main__":
    generate_data()
