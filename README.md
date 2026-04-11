# AltoTrader

Automated crypto trading framework with support for multiple exchanges, InfluxDB data storage, a look-ahead-bias-free backtesting engine, and a live MA crossover trading bot.

## Features

- **Multi-exchange support** – Kraken, Binance, Coinbase, Gemini, MEXC
- **REST and WebSocket tickers** – polling or real-time streaming per exchange
- **Unified pair format** – `BTC-EUR`, `ETH-BTC` across all exchanges
- **InfluxDB v2 storage** – time-series database for market price data
- **Backtesting engine** – MA crossover strategy with slippage, realistic fees, Sharpe ratio, drawdown analysis, grid search
- **Live trading bot** – MA crossover strategy, paper and live mode, Kraken + Binance
- **Docker Compose** – one-command deployment with InfluxDB dashboard; separate stack for the trading bot
- **Export / remote fetch** – pull historical data to CSV or Parquet

---

## Project Structure

```
AltoTrader/
├── src/altotrader/
│   ├── ticker/
│   │   ├── baseticker.py          # Abstract base class
│   │   ├── rest_base_ticker.py    # Shared REST base
│   │   ├── krakenticker.py        # Kraken REST
│   │   ├── kraken_ws_ticker.py    # Kraken WebSocket
│   │   ├── binanceticker.py       # Binance REST
│   │   ├── binance_ws_ticker.py   # Binance WebSocket
│   │   ├── coinbaseticker.py      # Coinbase Exchange REST
│   │   ├── geminiticker.py        # Gemini REST
│   │   └── mexcticker.py          # MEXC REST
│   ├── database/
│   │   ├── update_service.py      # Writes ticker data to InfluxDB
│   │   └── export_prices.py       # Exports data to CSV/Parquet
│   ├── backtest/
│   │   ├── dataloader.py          # Loads and resamples CSV exports
│   │   └── backtest_engine.py     # MA crossover backtest + grid search
│   └── trader/
│       ├── config.py              # TradingConfig dataclass
│       ├── signal_generator.py    # SMA crossover → BUY/SELL/HOLD
│       ├── position_manager.py    # Open positions, P&L, JSON persistence
│       ├── risk_manager.py        # Stop-loss, position sizing, max drawdown
│       ├── trading_engine.py      # Main loop: price → signal → order
│       └── broker/
│           ├── base_broker.py     # Abstract interface
│           ├── paper_broker.py    # Paper trading simulation
│           ├── kraken_broker.py   # Kraken limit orders (krakenex)
│           └── binance_broker.py  # Binance market orders (python-binance)
├── Examples/
│   ├── run_update_service.py      # Data streaming entry point
│   ├── run_trading_bot.py         # Trading bot entry point
│   ├── fetch_from_remote.py       # Fetch data from remote InfluxDB
│   └── *.yaml                     # Pairs configs per exchange
├── docker-compose.yml             # InfluxDB + data streamer
├── docker-compose.trader.yml      # Trading bot (independent stack)
└── env/.env.example
```

---

## Installation

Requires Python ≥ 3.10.

```bash
git clone https://github.com/mhansinger/AltoTrader.git
cd AltoTrader
pip install .
# Development extras (pytest, black …)
pip install ".[dev]"
```

---

## Pair Format

All exchanges use the unified **`BASE-QUOTE`** format:

```
BTC-EUR   ETH-BTC   SOL-USDT   XRP-EUR
```

Each ticker converts internally to the exchange-specific symbol:

| Exchange | Unified | Internal |
|---|---|---|
| Binance / MEXC | `BTC-EUR` | `BTCEUR` |
| Coinbase | `BTC-EUR` | `BTC-EUR` |
| Gemini | `BTC-EUR` | `btceur` |
| Kraken REST | `BTC-EUR` | `XXBTZEUR` |
| Kraken WS | `BTC-EUR` | `XBT/EUR` |

---

## Configuration

Copy `env/.env.example` to `.env` and fill in your values:

```bash
cp env/.env.example .env
```

---

## Data Streaming

Select exchange and mode via `--exchange` / `--mode` flags or environment variables:

```bash
# Kraken REST (default)
python Examples/run_update_service.py

# Kraken WebSocket
python Examples/run_update_service.py --mode websocket

# Binance REST
python Examples/run_update_service.py --exchange binance

# Binance WebSocket
python Examples/run_update_service.py --exchange binance --mode websocket
```

WebSocket mode is available for `kraken` and `binance` only.

### Pairs YAML

Each exchange has its own pairs file in `Examples/`. Edit to add or remove pairs:

```yaml
# Examples/binance_pairs.yaml
items:
  - BTC-EUR
  - ETH-EUR
  - ETH-BTC
```

---

## Docker Deployment

### Data Streamer + InfluxDB

```bash
docker compose up --build -d
```

The InfluxDB dashboard is available at **http://localhost:8086** (use an SSH tunnel for remote access).

```bash
# Binance WebSocket
EXCHANGE=binance MODE=websocket docker compose up --build -d
```

| Variable | Default | Options |
|---|---|---|
| `EXCHANGE` | `kraken` | `kraken`, `binance`, `coinbase`, `gemini`, `mexc` |
| `MODE` | `rest` | `rest`, `websocket` (kraken + binance only) |

### Trading Bot (independent stack)

The trading bot runs in its own Docker Compose stack, completely independent from the streamer. It fetches prices directly from the exchange API.

```bash
# Start in paper trading mode (default – no real orders):
docker compose -f docker-compose.trader.yml up --build -d

# Logs:
docker logs -f altotrader_trader

# Stop:
docker compose -f docker-compose.trader.yml down
```

Configure via `.env`:

```dotenv
TRADER_EXCHANGE=kraken
TRADER_PAIR=BTC-EUR
TRADER_WINDOW_SHORT=50
TRADER_WINDOW_LONG=200
TRADER_INITIAL_INVEST=1000
TRADER_PAPER_TRADING=true          # set to false for live trading
KRAKEN_API_KEY=your-key
KRAKEN_API_SECRET=your-secret
```

**Switch to live trading** (Kraken API key needs **Read + Trade** permissions, no Withdraw):

```bash
# Set TRADER_PAPER_TRADING=false and API keys in .env, then:
docker compose -f docker-compose.trader.yml restart
```

The container auto-restarts on crash and after server reboot (`restart: unless-stopped`). Open positions are persisted to a named Docker volume and restored automatically on restart.

---

## Live Trading Bot

### Quick start

```bash
# Paper trade BTC-EUR on Kraken:
python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR --paper

# Live trade with custom SMA windows:
python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR \
    --short 50 --long 200 --invest 500

# Fast test run (10 s poll, small windows):
python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR \
    --short 5 --long 20 --poll 10 --paper
```

### Strategy

SMA (Simple Moving Average) crossover:
- **Golden Cross** – short SMA crosses above long SMA → BUY
- **Death Cross** – short SMA crosses below long SMA → SELL
- Uses `last` price for signal calculation, `ask` for buy execution, `bid` for sell execution
- Kraken: limit orders (maker fee 0.25 %); Binance: market orders (taker fee 0.1 %)

### Risk controls

| Control | Default | Description |
|---|---|---|
| Stop-loss | 5 % | Force-sell if position loses more than 5 % from entry |
| Max drawdown | 20 % | Halt all trading if portfolio drops 20 % from peak |
| Position size | 95 % | Invest at most 95 % of available capital per trade |

### Architecture

```
Exchange API ──→ Ticker ──→ SignalGenerator (SMA crossover)
                                    │
                             TradingEngine (main loop)
                            ┌───────┴────────┐
                       RiskManager      PositionManager
                    (stop-loss,         (JSON persistence,
                     drawdown)           P&L tracking)
                            └───────┬────────┘
                                 Broker
                          (PaperBroker / KrakenBroker
                           / BinanceBroker)
```

---

## Backtesting

### Quick start

```python
from altotrader.backtest.dataloader     import DataLoader
from altotrader.backtest.backtest_engine import BacktestEngine

loader_config = {
    "export_path": "Examples/ticker_export",
    "latest_days": 20,
    "logs_dir":    "logs",
}
backtest_config = {
    "maker_fee":        0.0025,
    "taker_fee":        0.004,
    "slippage_pct":     0.0005,
    "initial_invest":   1000,
    "base_currency":    "EUR",
    "trading_currency": "BTC",
}

loader   = DataLoader(loader_config)
backtest = BacktestEngine(loader, backtest_config)
metrics  = backtest.run(window_short=50, window_long=200)
print(metrics)
```

### Key metrics returned

| Key | Description |
|---|---|
| `total_return_pct` | Strategy return vs initial invest |
| `buy_and_hold_return_pct` | Passive benchmark |
| `n_trades` | Number of completed round-trips |
| `win_rate` | % of profitable trades |
| `max_drawdown_pct` | Maximum peak-to-trough loss |
| `sharpe_ratio` | Annualised Sharpe (daily returns × √365) |
| `total_fees` / `taker_fees` / `maker_fees` | Fee breakdown |

### Grid search

```python
from altotrader.backtest.backtest_engine import run_grid_search

results = run_grid_search(
    backtest,
    short_windows=[20, 50, 100],
    long_windows=[100, 200, 500],
)
print(results[["window_short", "window_long", "total_return_pct", "sharpe_ratio"]].head())
```

---

## Exporting Data

```bash
python Examples/fetch_from_remote.py \
    --url   http://my-server:8086 \
    --token $INFLUXDB_INIT_ADMIN_TOKEN \
    --org   myorg \
    --bucket altotrader \
    --days  30 \
    --out   data/export.csv
```

---

## Tests

```bash
python -m pytest
```

183 tests, 0 failures.

---

## Disclaimer

This software is for educational purposes only. Automated trading carries significant financial risk. Past backtesting performance does not guarantee future results. Use at your own risk.
