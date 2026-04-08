# AltoTrader

Automated crypto trading framework with support for multiple exchanges, InfluxDB data storage, and a look-ahead-bias-free backtesting engine.

## Features

- **Multi-exchange support** – Kraken, Binance, Coinbase, Gemini, MEXC
- **REST and WebSocket tickers** – polling or real-time streaming per exchange
- **Unified pair format** – `BTC-EUR`, `ETH-BTC` across all exchanges
- **InfluxDB v2 storage** – time-series database for market price data
- **Backtesting engine** – MA crossover strategy with slippage, realistic fees, Sharpe ratio, drawdown analysis, grid search
- **Docker Compose** – one-command deployment with InfluxDB dashboard
- **Export / remote fetch** – pull historical data to CSV or Parquet

---

## Project Structure

```
AltoTrader/
├── src/altotrader/
│   ├── ticker/
│   │   ├── baseticker.py          # Abstract base class
│   │   ├── rest_base_ticker.py    # Shared REST base (get_last_ticker, _to_exchange_pair)
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
│   └── backtest/
│       ├── dataloader.py          # Loads and resamples CSV exports
│       └── backtest_engine.py     # MA crossover backtest + grid search
├── Examples/
│   ├── run_update_service.py      # Data collection entry point
│   ├── fetch_from_remote.py       # Fetch data from remote InfluxDB
│   ├── kraken_pairs.yaml
│   ├── binance_pairs.yaml
│   ├── coinbase_pairs.yaml
│   ├── gemini_pairs.yaml
│   └── mexc_pairs.yaml
├── Dockerfile
├── docker-compose.yml
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

```dotenv
INFLUXDB_INIT_BUCKET=altotrader
INFLUXDB_INIT_ORG=myorg
INFLUXDB_INIT_ADMIN_TOKEN=your-token-here
INFLUXDB_INIT_PASSWORD=your-password
INFLUX_URL=http://localhost:8086
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

# Gemini / Coinbase / MEXC (REST only)
python Examples/run_update_service.py --exchange gemini
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

Pass a custom file with `--pairs Examples/my_pairs.yaml`.

---

## Docker Deployment

Build and start InfluxDB + the streaming service:

```bash
docker compose up --build -d
```

The InfluxDB dashboard is available at **http://localhost:8086** (or your server's IP).

Control exchange and mode via environment variables:

```bash
# Binance WebSocket
EXCHANGE=binance MODE=websocket docker compose up --build -d

# Gemini REST
EXCHANGE=gemini docker compose up -d
```

Or set them permanently in `.env`:

```dotenv
EXCHANGE=binance
MODE=websocket
```

| Variable | Default | Options |
|---|---|---|
| `EXCHANGE` | `kraken` | `kraken`, `binance`, `coinbase`, `gemini`, `mexc` |
| `MODE` | `rest` | `rest`, `websocket` (kraken + binance only) |

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
    "slippage_pct":     0.0005,   # 0.05 % slippage on each side
    "initial_invest":   1000,
    "base_currency":    "EUR",    # pair will be constructed as "BTC-EUR"
    "trading_currency": "BTC",
}

loader  = DataLoader(loader_config)
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
| `max_drawdown_duration_hrs` | Longest drawdown period (hours) |
| `sharpe_ratio` | Annualised Sharpe (daily returns × √365) |
| `total_fees` / `taker_fees` / `maker_fees` | Fee breakdown |
| `final_portfolio_value` | End portfolio value |

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

### Visualisation

```python
backtest.plot_results(show=True, save_path="backtest.png")
```

---

## Exporting Data

Export data from a local or remote InfluxDB to CSV or Parquet:

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

100 tests, 2 skipped (Kraken build-environment guard in CI).

---

## Disclaimer

This software is for educational purposes only. Automated trading carries significant financial risk. Past backtesting performance does not guarantee future results. Use at your own risk.
