import threading
from execution import execute_arbitrage
import time


class JanusBrain:
    def __init__(self, kalshi_book, pm_book, kalshi_ticker, pm_ticker, max_spend, test_mode, shared_balance):
        self.kalshi_book = kalshi_book
        self.pm_book = pm_book
        self.max_spend_scaled = int(max_spend * 10000)
        self.remaining_budget_scaled = self.max_spend_scaled
        self.evaluations = 0

        self.kalshi_ticker = kalshi_ticker
        self.pm_ticker = pm_ticker
        self.cooldown_until = 0.0
        self.test_mode = test_mode
        
        # 🚨 SHARED BALANCE (Updated by background syncer, shared across ALL brains) 🚨
        self.shared_balance = shared_balance


    def kalshi_commission(self, n: int, p: int) -> int:
        """ 
        Kalshi: Round up to next cent. 
        Uses integer ceiling division to prevent float precision bugs.
        """
        x = n * 7 * p * (100 - p)
        return (x + 999999) // 1000000
    
    def pm_commission(self, n: int, p: int) -> int:
        """ 
        Polymarket: Banker's rounding.
        """
        x = n * 6 * p * (100 - p)
        return round(x / 1000000)

    def evaluate_arbitrage(self):
        """
        O(1) Instant Trigger. Evaluates if an arbitrage exists on either side.
        """
        self.evaluations += 1

        if time.time() < self.cooldown_until:
            return

        # Scenario A: Kalshi YES + PM NO
        k_yes = self.kalshi_book.best_yes_ask_idx
        p_no = self.pm_book.best_no_ask_idx
        
        # We check < 100 as a quick filter. If the raw prices cross 100, we check deep book.
        if k_yes + p_no < 99: # <======================================================================================================== TEST FOR NOW
            allocs, profit, volume = self._walk_book('yes', 'no')
            if profit > 0 and volume >= 50:
                self._execute_trade(allocs, profit, volume, "Kalshi YES / PM NO", "yes", "no", kalshi_ticker=self.kalshi_ticker, pm_ticker=self.pm_ticker)

                self.cooldown_until = time.time() + 1.5
                return

        # Scenario B: Kalshi NO + PM YES
        k_no = self.kalshi_book.best_no_ask_idx
        p_yes = self.pm_book.best_yes_ask_idx

        if k_no + p_yes < 99: # <======================================================================================================== TEST FOR NOW
            # Maybe add a statement to check if volume is not zero? maybe
            allocs, profit, volume = self._walk_book('no', 'yes')
            if profit > 0 and volume >= 50:
                self._execute_trade(allocs, profit, volume, "Kalshi NO / PM YES", "no", "yes", kalshi_ticker=self.kalshi_ticker, pm_ticker=self.pm_ticker)

                self.cooldown_until = time.time() + 1.5

    def _walk_book(self, kalshi_side, pm_side): 
        """
        Walks the O(1) orderbook arrays using local variables.
        Dynamically calculates exact fees for the maximum available volume at each level.
        Returns: allocations, total_profit_cents, total_contracts_hundredths
        """
        
        # Maybe add a system where you proceed if only best prices from both platform are < 100 after commision. 
        # But wait.. maybe not cause commision depends on the total volume we are buying so, we do have to calculate other stuff first.

        remaining_budget = self.remaining_budget_scaled

        # 🚨 Use the globally synced balances (shared across ALL brains)! 🚨
        k_balance = self.shared_balance.k_balance
        p_balance = self.shared_balance.p_balance

        # 1. Grab local pointers to start the walk
        if kalshi_side == 'yes':
            k_idx = self.kalshi_book.best_yes_ask_idx
            k_asks = self.kalshi_book.yes_asks
        else:
            k_idx = self.kalshi_book.best_no_ask_idx
            k_asks = self.kalshi_book.no_asks

        if pm_side == 'yes':
            p_idx = self.pm_book.best_yes_ask_idx
            p_asks = self.pm_book.yes_asks
        else:
            p_idx = self.pm_book.best_no_ask_idx
            p_asks = self.pm_book.no_asks

        # 2. Local copies of available volume at current pointers
        k_vol = k_asks[k_idx]
        p_vol = p_asks[p_idx]
        
        allocations = []
        total_profit_scaled = 0
        total_contracts = 0

        # 3. Walk the book
        while k_idx < 100 and p_idx < 100:
            # Find the max volume we can match at these specific price levels
            take = min(k_vol, p_vol)

            # Finds the next best price which has volume > 0
            # For both kalshi and pm
            if take == 0:
                # One of the levels emptied out. Walk the pointer up to the next available price.
                if k_vol == 0:
                    k_idx += 1
                    while k_idx < 100 and k_asks[k_idx] == 0:
                        k_idx += 1
                    if k_idx < 100:
                        k_vol = k_asks[k_idx]
                        
                if p_vol == 0:
                    p_idx += 1
                    while p_idx < 100 and p_asks[p_idx] == 0:
                        p_idx += 1
                    if p_idx < 100:
                        p_vol = p_asks[p_idx]
                continue

            # Calculate Exact Fees for this specific 'take' volume
            k_fee = self.kalshi_commission(take, k_idx)
            p_fee = self.pm_commission(take, p_idx)

            # Scale fees by 100 to match our "hundredths of a cent" integer math
            k_fee_scaled = k_fee * 100
            p_fee_scaled = p_fee * 100

            # Base cost: volume * (price_K + price_PM)
            k_cost = (take * k_idx) + k_fee_scaled
            p_cost = (take * p_idx) + p_fee_scaled
            total_cost = k_cost + p_cost

            # Expected revenue (Paired YES/NO always guarantees 100 cents per contract)
            revenue = take * 100
            profit_scaled = revenue - total_cost

            # 🚨 THE MULTI-CONSTRAINT PORTFOLIO LOGIC 🚨
            if k_cost > k_balance or p_cost > p_balance or total_cost > remaining_budget:
                
                # Mathematically solve for the max volume each wallet can afford independently
                max_take_k = (k_balance * take) // k_cost if k_cost > 0 else take
                max_take_p = (p_balance * take) // p_cost if p_cost > 0 else take
                max_take_total = (remaining_budget * take) // total_cost
                
                # The tightest constraint dictates our actual affordable volume
                take = min(max_take_k, max_take_p, max_take_total)
                
                if take == 0:
                    break  # One of our wallets is completely empty!
                    
                # Recalculate exact costs for our new affordable 'take' size
                k_fee_scaled = self.kalshi_commission(take, k_idx) * 100
                p_fee_scaled = self.pm_commission(take, p_idx) * 100

                k_cost = (take * k_idx) + k_fee_scaled
                p_cost = (take * p_idx) + p_fee_scaled
                total_cost = k_cost + p_cost
                
                # Extreme Edge Case Safety: 
                # If rounding made the new calculation exactly 1 unit too expensive
                if k_cost > k_balance or p_cost > p_balance or total_cost > remaining_budget:
                    take -= 1
                    if take <= 0: break
                    k_fee_scaled = self.kalshi_commission(take, k_idx) * 100
                    p_fee_scaled = self.pm_commission(take, p_idx) * 100
                    k_cost = (take * k_idx) + k_fee_scaled
                    p_cost = (take * p_idx) + p_fee_scaled
                    total_cost = k_cost + p_cost

            # Expected revenue
            revenue = take * 100
            profit_scaled = revenue - total_cost


            if profit_scaled > 0:
                # The marginal step is mathematically profitable!
                allocations.append({
                    "kalshi_price": k_idx,
                    "pm_price": p_idx,
                    "qty_scaled_to_100th_of_vol": take,
                    "kalshi_fee_scaled_to_100th_of_cent": k_fee_scaled,
                    "pm_fee_scaled_to_100th_of_cent": p_fee_scaled,
                    "profit_scaled_to_100th_of_cent": profit_scaled,
                    "kalshi_side": kalshi_side,
                    "pm_side": pm_side

                })
                total_profit_scaled += profit_scaled
                total_contracts += take

                # 🚨 DEDUCT FROM ALL THREE WALLETS 🚨
                remaining_budget -= total_cost
                k_balance -= k_cost
                p_balance -= p_cost
                
                # 🚨 OPTIMISTIC DEDUCTION FROM SHARED BALANCE 🚨
                self.shared_balance.k_balance -= k_cost
                self.shared_balance.p_balance -= p_cost
                self.remaining_budget_scaled -= total_cost
                
                # Consume the volume locally for the next loop iteration
                k_vol -= take
                p_vol -= take
            else:
                # The marginal cost (including fees) is no longer profitable. Stop walking.
                break

        return allocations, total_profit_scaled, total_contracts

    def _execute_trade(self, allocs, total_profit, total_volume, strategy_name, kalshi_side, pm_side, kalshi_ticker, pm_ticker):
        # We pass the baton to the execution module in a background daemon thread 
        # so the blocking API calls do not freeze our lightning-fast WebSocket loop!
        threading.Thread(
            target=execute_arbitrage,
            args=(allocs, total_profit, total_volume, strategy_name, kalshi_side, pm_side, kalshi_ticker, pm_ticker, self.test_mode),
            daemon=True
        ).start()
