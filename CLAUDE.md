# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install ".[dev]"

# Run all tests
python -m pytest

# Run a single test file
python -m pytest Tests/test_update_service.py

# Run a single test by name
python -m pytest Tests/test_update_service.py::TestClassName::test_method_name

# Format code
black src/ Tests/

# Start local stack (InfluxDB + streamer)
docker compose up --build -d

# Stream data locally without Docker
python Examples/run_update_service.py --mode rest
python Examples/run_update_service.py --mode websocket

# Export historical data from InfluxDB
python Examples/fetch_from_remote.py --url http://localhost:8086 --token $TOKEN --org myorg --bucket altotrader --days 30 --out data/export.csv
```

## Architecture

**Three functional layers:**

1. **Ticker** (`src/altotrader/ticker/`) – Fetches live prices from exchanges. All tickers inherit from `BaseTicker` → `RestBaseTicker`. Each exchange implements `get_last_ticker()` and `_to_exchange_pair()` to convert the unified `BASE-QUOTE` format (e.g. `BTC-EUR`) to the exchange-specific symbol. REST and WebSocket variants are drop-in replacements for `TickerUpdateService`.

2. **Database** (`src/altotrader/database/`) – `TickerUpdateService` polls any ticker and writes ask/bid/close prices to InfluxDB with retry + exponential backoff. `export_prices.py` queries InfluxDB and writes CSV or Parquet files.

3. **Backtest** (`src/altotrader/backtest/`) – `DataLoader` loads CSV exports and resamples to 1-minute bars; supports merging data from multiple sources. `BacktestEngine` runs an MA crossover strategy with realistic fees and slippage; `run_grid_search()` sweeps window parameters.

**Data flow:**
Exchange API → Ticker → `TickerUpdateService` → InfluxDB → `export_prices.py` → CSV/Parquet → `DataLoader` → `BacktestEngine`

## Docker

`docker compose up --build -d` starts two containers locally:
- **influxdb** (port 8086) – persists data in named volumes `influxdb_data` / `influxdb_config`
- **altotrader_streamer** – runs `Examples/run_update_service.py`; waits for InfluxDB health check

Configuration comes from `.env` (copy from `env/.env.example`). Key variables: `INFLUXDB_INIT_ORG`, `INFLUXDB_INIT_BUCKET`, `INFLUXDB_INIT_ADMIN_TOKEN`, `INFLUX_URL`.

## Pair Format

All exchanges use unified `BASE-QUOTE` (e.g. `BTC-EUR`, `ETH-BTC`). Each ticker class converts internally. Adding a new pair means adding it to the relevant `Examples/<exchange>_pairs.yaml`.

## Tests

Tests live in `Tests/`. `conftest.py` at the project root adds `src/` to the path and mocks `krakenex` when unavailable. Two Kraken tests are skipped in CI via an environment guard.
