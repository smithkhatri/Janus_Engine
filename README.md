# Janus Engine: High-Frequency Cross-Exchange Arbitrage

![Janus Engine Architecture](https://img.shields.io/badge/Status-Active-brightgreen.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Architecture](https://img.shields.io/badge/Architecture-Asynchronous%20%7C%20O(1)-orange.svg)

Janus Engine is a high-performance, asynchronous arbitrage engine designed to capitalize on fleeting price inefficiencies between prediction markets (Kalshi and Polymarket).

## 🚀 Overview

The system streams live orderbook data via WebSockets from multiple exchanges, maintains an internal O(1) representation of the books, and mathematically solves for the optimal cross-exchange execution volumes under multi-wallet constraints.

**Key Features:**
- **Asynchronous Architecture:** Built on Python's `asyncio` to handle multiple high-frequency WebSocket streams without blocking the main event loop.
- **O(1) Orderbook Walk:** The core "Brain" evaluates arbitrage opportunities in $O(1)$ time by maintaining direct-indexed arrays of the orderbook, avoiding expensive sorting or searching during hot-path execution.
- **Multi-Wallet Constraint Optimization:** Dynamically calculates exact commission structures across both exchanges (Kalshi's fractional cent rounding and Polymarket's Banker's rounding) to solve for the maximum profitable volume that can be afforded simultaneously across 3 wallets (Kalshi, Polymarket, and the Total Shared Budget).
- **Daemon Thread Execution:** Isolates blocking execution I/O in daemon threads to prevent freezing the WebSocket event loops, allowing the bot to continue listening to market ticks while trades are in flight.
- **Optimistic Concurrency:** Updates shared balances optimistically upon discovering profitable trades to prevent over-allocating capital in concurrent market evaluations.

## 🧠 System Architecture

1. **Orderbook Router (`orderbook_router.py`):** Ingests raw websocket ticks and routes them to the correct local `Kalshi_Orderbook` or `PM_Orderbook` instances.
2. **The Brain (`brain.py`):** Evaluates `k_yes + p_no < 100` instantaneously. If an opportunity exists, it walks the book level-by-level, calculating marginal cost including exact exchange fees.
3. **Execution Engine (`execution.py`):** Spawns a background thread to fire concurrent HTTP requests to both exchanges. Handles partial fills, failure states, and unwind logic to minimize delta exposure.
4. **Trade Logger (`trade_logger.py`):** Uses thread-safe queues and an asynchronous cold-path flusher to log metrics with zero hot-path I/O blocking.

## 📊 Performance & Dashboard

The project includes a lightweight frontend dashboard to visualize trading performance over time, parsing log data to calculate metrics like Win Rate, Realized PnL, and Total Volume Traded.

**👉 [View the Live Trading Dashboard](https://<YOUR_GITHUB_USERNAME>.github.io/Janus_Engine/dashboard/)**

*(Note: To host this yourself, simply enable GitHub Pages on your repository and point it to the `main` branch. The dashboard is fully static!)*

### Generating New Dashboard Data (Local)
If you run the bot and generate new logs, you can compile them into the static JSON file used by the dashboard:
```bash
python build_static_data.py
```
Then, simply open `dashboard/index.html` in your browser.

## 🛠 Setup & Installation

1. Clone the repository.
2. Install dependencies (e.g., `websockets`, `aiohttp`, `requests`).
3. Set your API credentials in `API_key.env`.
4. Configure target markets in `market_registry.json`.
5. Ignite the engine:
   ```bash
   python main.py
   ```

## 📈 Future Enhancements (Roadmap)
- **C++ Core:** Migrating the hot-path `brain.py` logic to a C++ extension for ultra-low latency execution.
- **Machine Learning Overlays:** Predicting orderbook imbalances to anticipate directional moves seconds before they occur.
- **Advanced Hedging:** Implementing statistical arbitrage if perfect pairs are temporarily unavailable.

---
*Built as a showcase for Quant / SWE / ML roles. Demonstrates low-latency systems design, concurrent programming, and algorithmic trading concepts.*
