import time
import os
import csv
import json
import asyncio
import threading
from datetime import datetime

_LOG_DIR = "bot_logs"

# Thread-safe queues for non-blocking logging from daemon threads
_execution_queue = []
_snapshot_queue = []
_queue_lock = threading.Lock()

# ─── CSV Headers ───
EXEC_HEADERS = [
    "timestamp", "pair_id", "strategy",
    "k_price", "p_price", "intended_qty", "theoretical_profit",
    "k_fill_qty", "k_fill_time_ms", "k_status_code",
    "p_fill_qty", "p_fill_time_ms", "p_status_code",
    "outcome", "unwind_action", "unwind_pnl",
    "net_realized_pnl"
]


# ─── Hot-Path Logging (called from daemon threads, must be thread-safe) ───

def log_execution(record: dict):
    """O(1) thread-safe append. Zero I/O blocking."""
    with _queue_lock:
        _execution_queue.append(record)


def log_snapshot(snapshot: dict):
    """O(1) thread-safe append. Zero I/O blocking."""
    with _queue_lock:
        _snapshot_queue.append(snapshot)


# ─── Orderbook Snapshot Capture ───

def capture_book_snapshot(kalshi_book, pm_book):
    """
    Capture all non-zero levels from both orderbooks.
    Returns a JSON-serializable dict.
    """
    def extract_levels(arr):
        return [[p, arr[p]] for p in range(1, 100) if arr[p] > 0]

    return {
        "kalshi": {
            "yes_asks": extract_levels(kalshi_book.yes_asks),
            "no_asks": extract_levels(kalshi_book.no_asks),
            "yes_bids": extract_levels(kalshi_book.yes_bids),
            "no_bids": extract_levels(kalshi_book.no_bids),
            "best_yes_ask": kalshi_book.best_yes_ask_idx,
            "best_no_ask": kalshi_book.best_no_ask_idx,
        },
        "pm": {
            "yes_asks": extract_levels(pm_book.yes_asks),
            "no_asks": extract_levels(pm_book.no_asks),
            "yes_bids": extract_levels(pm_book.yes_bids),
            "no_bids": extract_levels(pm_book.no_bids),
            "best_yes_ask": pm_book.best_yes_ask_idx,
            "best_no_ask": pm_book.best_no_ask_idx,
        }
    }


# ─── Cold-Path Background Flusher ───

async def trade_log_flusher():
    """Background coroutine that periodically flushes queued records to disk."""
    global _execution_queue, _snapshot_queue

    if not os.path.exists(_LOG_DIR):
        os.makedirs(_LOG_DIR)

    while True:
        await asyncio.sleep(5)

        # Atomically swap the queues so the hot path isn't blocked
        with _queue_lock:
            exec_batch = _execution_queue
            _execution_queue = []
            snap_batch = _snapshot_queue
            _snapshot_queue = []

        if exec_batch:
            today_str = datetime.utcnow().strftime('%Y-%m-%d')

            # Separate test and live records into different files
            test_records = [r for r in exec_batch if r.get('_test_mode')]
            live_records = [r for r in exec_batch if not r.get('_test_mode')]

            if test_records:
                _flush_csv(f"test_executions_{today_str}.csv", test_records)
            if live_records:
                _flush_csv(f"executions_{today_str}.csv", live_records)

        if snap_batch:
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            snap_path = os.path.join(_LOG_DIR, f"snapshots_{today_str}.jsonl")
            with open(snap_path, "a") as f:
                for snap in snap_batch:
                    f.write(json.dumps(snap) + "\n")


def _flush_csv(filename, records):
    """Write a batch of execution records to a daily CSV file."""
    file_path = os.path.join(_LOG_DIR, filename)
    file_exists = os.path.exists(file_path)

    with open(file_path, "a", newline='') as f:
        # extrasaction='ignore' silently drops internal keys like '_test_mode'
        writer = csv.DictWriter(f, fieldnames=EXEC_HEADERS, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerows(records)
