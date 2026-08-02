from decimal import Decimal

def _pretty_print_book(book, title):
    print("\n" + "="*42)
    print(f"{title:^42}")
    print("="*42)

    print(f"Best YES Bid: {book.best_yes_bid_idx:>2}¢  |  Best NO Bid: {book.best_no_bid_idx:>2}¢")
    print("-" * 42)

    print(f"{'YES':^19} || {'NO':^19}")
    print(f"{'Price(¢)':>8} | {'Vol':<8} || {'Price(¢)':>8} | {'Vol':<8}")
    print("-" * 42)

    def format_row(p_v_tuple):
        if p_v_tuple is None:
            return f"{'':>8} | {'':<8}"
        p, v = p_v_tuple
        v_dec = Decimal(str(v)) / Decimal('100')
        return f"{p:>8} | {v_dec:<8}"

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
        
        if i < yes_offset:
            y = None
        else:
            y = yes_asks[i - yes_offset]
            
        if i < no_offset:
            n = None
        else:
            n = no_asks[i - no_offset]
            
        print(f"{format_row(y)} || {format_row(n)}")

    # Middle line where bid and ask meet
    print("=" * 42)

    # Print Bids (top-aligned so they meet the middle line)
    for i in range(max_bids):
        y = yes_bids[i] if i < len(yes_bids) else None
        n = no_bids[i] if i < len(no_bids) else None
        print(f"{format_row(y)} || {format_row(n)}")

    print("="*42 + "\n")

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
