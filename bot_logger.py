"""
Bot Logger — per-run log file for the ClawBack arbitrage engine.

Every time the script starts, a new log file is created under `logs/`
with the exact start timestamp in its name, e.g.:

    logs/bot_log_2026-07-17_16-43-10.log

All entries include a precise timestamp and a human-readable description
of the action taken (or attempted).
"""

import os
import datetime
import threading

# ═══════════════════════════════════════════════════════════════════
# LOG INITIALISATION  (runs once at import time)
# ═══════════════════════════════════════════════════════════════════

_RUN_START = datetime.datetime.now()
_RUN_STAMP = _RUN_START.strftime("%Y-%m-%d_%H-%M-%S")

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

LOG_FILE_PATH = os.path.join(_LOG_DIR, f"bot_log_{_RUN_STAMP}.log")

_write_lock = threading.Lock()


def _timestamp() -> str:
    """Return a human-readable timestamp: 2026-07-17 16:43:10.123"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _write(text: str):
    """Thread-safe append to the log file."""
    with _write_lock:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(text)


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def log(event: str, details: str = ""):
    """
    Write a single log entry.

    Parameters
    ----------
    event   : short label, e.g. "ORDER_PLACED", "BALANCE_CHECK"
    details : multi-line body with all the context
    """
    ts = _timestamp()
    entry = f"[{ts}]  {event}\n"
    if details:
        # Indent every detail line for readability
        for line in details.strip().splitlines():
            entry += f"    {line}\n"
    entry += "\n"
    _write(entry)


def log_section(title: str):
    """Print a visual separator to make scanning the log easier."""
    ts = _timestamp()
    bar = "=" * 70
    _write(f"\n{bar}\n  [{ts}]  {title}\n{bar}\n\n")


def log_trade_summary(
    direction: str,
    contracts: int,
    total_cost: float,
    base_cost: float,
    commission: float,
    profit: float,
    roi: float,
    exchange_a: str,
    ticker_a: str,
    side_a: str,
    alloc_a: list,
    exchange_b: str,
    ticker_b: str,
    side_b: str,
    alloc_b: list,
):
    """Log a complete trade opportunity summary in a readable block."""
    lines = [
        f"Direction:    {direction}",
        f"Contracts:    {contracts}",
        f"Total Cost:   ${total_cost:.4f}  (Base: ${base_cost:.4f}  |  Commission: ${commission:.4f})",
        f"Revenue:      ${contracts:.2f}  (Guaranteed payout at $1.00/contract)",
        f"Net Profit:   ${profit:.4f}",
        f"ROI:          {roi:.2f}%",
        "",
        f"--- Leg A: {exchange_a.upper()} ({ticker_a}) — Side: {side_a} ---",
    ]
    for i, lvl in enumerate(alloc_a, 1):
        lines.append(
            f"  Level {i}:  Buy {lvl['qty']} contracts @ ${lvl['price']:.4f}  "
            f"(Base: ${lvl['base_cost']:.4f}  |  Comm: ${lvl['commission']:.4f})"
        )
    lines.append("")
    lines.append(f"--- Leg B: {exchange_b.upper()} ({ticker_b}) — Side: {side_b} ---")
    for i, lvl in enumerate(alloc_b, 1):
        lines.append(
            f"  Level {i}:  Buy {lvl['qty']} contracts @ ${lvl['price']:.4f}  "
            f"(Base: ${lvl['base_cost']:.4f}  |  Comm: ${lvl['commission']:.4f})"
        )

    log("ARBITRAGE_SIGNAL_DETECTED", "\n".join(lines))


def log_order_result(exchange: str, ticker: str, side: str, price: str,
                     count: int, success: bool, response_data: str = ""):
    """Log the result of a single order placement."""
    status = "SUCCESS" if success else "FAILED"
    lines = [
        f"Exchange:   {exchange.upper()}",
        f"Ticker:     {ticker}",
        f"Side:       {side}",
        f"Price:      {price}",
        f"Contracts:  {count}",
        f"Status:     {status}",
    ]
    if response_data:
        lines.append(f"Response:   {response_data}")
    log(f"ORDER_{status}", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# STARTUP BANNER
# ═══════════════════════════════════════════════════════════════════

_write(
    f"{'=' * 70}\n"
    f"  ClawBack Arbitrage Engine — Run Log\n"
    f"  Started: {_RUN_START.strftime('%Y-%m-%d %H:%M:%S')}\n"
    f"  Log File: {LOG_FILE_PATH}\n"
    f"{'=' * 70}\n\n"
)
