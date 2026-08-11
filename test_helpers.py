import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from itertools import zip_longest

def get_book_lines(book, title):
    lines = []
    lines.append("="*42)
    lines.append(f"{title:^42}")
    lines.append("="*42)

    lines.append(f"Best YES Bid: {book.best_yes_bid_idx:>2}¢  |  Best NO Bid: {book.best_no_bid_idx:>2}¢")
    lines.append("-" * 42)

    lines.append(f"{'YES':^19} || {'NO':^19}")
    lines.append(f"{'Price(¢)':>8} | {'Vol':<8} || {'Price(¢)':>8} | {'Vol':<8}")
    lines.append("-" * 42)

    def get_row_str(p_v_tuple):
        if p_v_tuple is None:
            return f"{'':>8} | {'':<8}"
        p, v = p_v_tuple
        v_dec = Decimal(str(v)) / Decimal('100')
        v_str = f"{v_dec:f}".rstrip('0').rstrip('.') if '.' in f"{v_dec:f}" else f"{v_dec:f}"
        return f"{p:>8} | {v_str[:8]:<8}"

    # Asks: from highest price (99) to lowest price (1)
    yes_asks = [(p, book.yes_asks[p]) for p in range(99, 0, -1) if book.yes_asks[p] > 0]
    no_asks  = [(p, book.no_asks[p]) for p in range(99, 0, -1) if book.no_asks[p] > 0]

    # Bids: from highest price (99) to lowest price (1)
    yes_bids = [(p, book.yes_bids[p]) for p in range(99, 0, -1) if book.yes_bids[p] > 0]
    no_bids  = [(p, book.no_bids[p]) for p in range(99, 0, -1) if book.no_bids[p] > 0]

    max_asks = max(len(yes_asks), len(no_asks))
    max_bids = max(len(yes_bids), len(no_bids))

    # Print Asks (bottom-aligned so they meet the middle line)
    for i in range(max_asks):
        yes_offset = max_asks - len(yes_asks)
        no_offset  = max_asks - len(no_asks)
        
        y = None if i < yes_offset else yes_asks[i - yes_offset]
        n = None if i < no_offset else no_asks[i - no_offset]
            
        lines.append(f"{get_row_str(y)} || {get_row_str(n)}")

    # Middle line where bid and ask meet
    lines.append("=" * 42)

    # Print Bids (top-aligned so they meet the middle line)
    for i in range(max_bids):
        y = yes_bids[i] if i < len(yes_bids) else None
        n = no_bids[i] if i < len(no_bids) else None
        lines.append(f"{get_row_str(y)} || {get_row_str(n)}")

    lines.append("="*42)
    return lines

def _pretty_print_book(book, title):
    print("\n" + "\n".join(get_book_lines(book, title)) + "\n")

def print_four_books_side_by_side(book1, title1, book2, title2, book3, title3, book4, title4):
    lines1 = get_book_lines(book1, title1)
    lines2 = get_book_lines(book2, title2)
    lines3 = get_book_lines(book3, title3)
    lines4 = get_book_lines(book4, title4)
    
    print()
    for l1, l2, l3, l4 in zip_longest(lines1, lines2, lines3, lines4, fillvalue=" "*42):
        print(f"{l1:<42}  |  {l2:<42}  ||  {l3:<42}  |  {l4:<42}")
    print()

def pretty_print_Kalshi_book(book):
    """
    Prints a human-readable representation of the Kalshi orderbook.
    """
    _pretty_print_book(book, "KALSHI ORDERBOOK")

def pretty_print_PM_Orderbook(book):
    """
    Prints a human-readable representation of the Polymarket orderbook.
    """
    _pretty_print_book(book, "POLYMARKET ORDERBOOK")

class LogBookMock:
    def __init__(self, book_data):
        self.yes_asks = defaultdict(int)
        self.no_asks = defaultdict(int)
        self.yes_bids = defaultdict(int)
        self.no_bids = defaultdict(int)

        for p, v in book_data.get('yes_asks', []):
            self.yes_asks[p] = v
        for p, v in book_data.get('no_asks', []):
            self.no_asks[p] = v
        for p, v in book_data.get('yes_bids', []):
            self.yes_bids[p] = v
        for p, v in book_data.get('no_bids', []):
            self.no_bids[p] = v

        self.best_yes_bid_idx = max(self.yes_bids.keys()) if self.yes_bids else 0
        self.best_no_bid_idx = max(self.no_bids.keys()) if self.no_bids else 0

def analyze_bot_log(date_str):
    """
    Reads the execution CSV and snapshots JSONL for a given date (e.g. '2026-08-10').
    Prints a chronological, human-readable summary of what the bot did and what orderbooks it saw.
    """
    base_dir = os.path.join(os.path.dirname(__file__), 'bot_logs')
    csv_path = os.path.join(base_dir, f'executions_{date_str}.csv')
    jsonl_path = os.path.join(base_dir, f'snapshots_{date_str}.jsonl')

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return
    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found.")
        return

    # Read CSV
    executions = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            executions.append(row)

    # Read JSONL
    snapshots = []
    with open(jsonl_path, 'r') as f:
        for line in f:
            if line.strip():
                snapshots.append(json.loads(line))
                
    # Match and print
    for ex in executions:
        try:
            ex_ts = float(ex['timestamp'])
        except (ValueError, KeyError):
            continue
            
        pair_id = ex.get('pair_id', 'UNKNOWN')
        
        # Find best matching snapshot
        best_snap = None
        min_diff = float('inf')
        for snap in snapshots:
            if snap.get('pair_id') == pair_id:
                diff = abs(float(snap.get('timestamp', 0)) - ex_ts)
                if diff < min_diff and diff < 10.0:
                    min_diff = diff
                    best_snap = snap
        
        print("\n" + "="*80)
        dt = datetime.fromtimestamp(ex_ts).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(f"EXECUTION AT: {dt} | PAIR: {pair_id} | STRATEGY: {ex.get('strategy', '')}")
        print("="*80)
        
        # Convert profit/pnl to dollars (they are in 100ths of a cent)
        def to_dollars(val_str):
            try:
                return float(val_str) / 10000.0
            except (ValueError, TypeError):
                return 0.0

        tp_dollars = to_dollars(ex.get('theoretical_profit'))
        pnl_dollars = to_dollars(ex.get('net_realized_pnl'))
        upnl_dollars = to_dollars(ex.get('unwind_pnl'))
        
        print("Action Taken:")
        print(f"  Intended Qty: {ex.get('intended_qty')} | Theoretical Profit: ${tp_dollars:.4f}")
        print(f"  Kalshi Price: {ex.get('k_price')}¢ | Polymarket Price: {ex.get('p_price')}¢")
        print(f"  Kalshi Fill : {ex.get('k_fill_qty')} (Code: {ex.get('k_status_code')}, {ex.get('k_fill_time_ms')}ms)")
        print(f"  Poly Fill   : {ex.get('p_fill_qty')} (Code: {ex.get('p_status_code')}, {ex.get('p_fill_time_ms')}ms)")
        print(f"  Outcome     : {ex.get('outcome')} | Unwind Action: {ex.get('unwind_action')}")
        print(f"  PnL         : ${pnl_dollars:.4f} (Unwind PnL: ${upnl_dollars:.4f})")
        
        if best_snap:
            print("\n" + "-"*75 + " PRE & POST TRADE ORDERBOOKS " + "-"*75)
            pre_k = LogBookMock(best_snap['pre_trade']['kalshi'])
            pre_p = LogBookMock(best_snap['pre_trade']['pm'])
            post_k = LogBookMock(best_snap['post_trade']['kalshi'])
            post_p = LogBookMock(best_snap['post_trade']['pm'])
            print_four_books_side_by_side(pre_k, "KALSHI PRE-TRADE", pre_p, "POLYMARKET PRE-TRADE", post_k, "KALSHI POST-TRADE", post_p, "POLYMARKET POST-TRADE")
        else:
            print("\n[!] No matching snapshot found within 10 seconds for this execution.")
            
        print("="*80 + "\n")


# Fetch and analyze logs for August 10, 2026
analyze_bot_log('2026-08-10')
