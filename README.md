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

The backtest engine simulates a strategy on historical 1-minute price data with
realistic fees and slippage.  It supports four strategies that can be switched
at the command line or in Python.

### Available strategies

| Key | Name | Entry condition | Exit condition |
|---|---|---|---|
| `sma` | SMA Crossover *(original)* | Short SMA crosses above long SMA | Short SMA crosses below long SMA |
| `ema` | **Option A – Improved EMA** | Short EMA crosses above long EMA + volume ok + 4h trend up | ATR trailing stop **or** death cross |
| `momentum` | **Option B – Momentum** | N-period return > threshold | Return falls below exit threshold **or** ATR stop |
| `bollinger_rsi` | **Option C – Bollinger + RSI** | Price < lower Bollinger Band **and** RSI < oversold level | Price reverts to middle band **or** RSI overbought |

> **Why multiple strategies?**
> SMA crossover is simple but reacts slowly and produces many false signals in
> sideways markets.  The three new strategies address different market regimes:
> *Option A* improves trend-following, *Option B* captures multi-hour momentum,
> *Option C* exploits mean-reversion dips inside a broader uptrend.

---

### Quick start – Python API

```python
from altotrader.backtest import BacktestEngine, DataLoader, get_strategy

loader_config = {
    "export_path": "Examples/ticker_export",
    "latest_days": 30,
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

loader  = DataLoader(loader_config)
engine  = BacktestEngine(loader, backtest_config)

# ── Option A: Improved EMA crossover ─────────────────────────────────────────
metrics = engine.run_strategy(
    get_strategy("ema"),
    ema_short=50,          # short EMA window in minutes
    ema_long=200,          # long  EMA window in minutes
    atr_multiplier=2.0,    # trailing stop = peak - 2 × ATR
    trend_filter=True,     # only buy when price > 4h 200-EMA
)

# ── Option B: Momentum ────────────────────────────────────────────────────────
metrics = engine.run_strategy(
    get_strategy("momentum"),
    lookback_period=240,   # measure return over last 4 h
    entry_threshold=0.02,  # enter if 4h return > 2 %
    exit_threshold=-0.005, # exit  if 4h return < -0.5 %
    atr_multiplier=2.5,
)

# ── Option C: Bollinger Bands + RSI ──────────────────────────────────────────
metrics = engine.run_strategy(
    get_strategy("bollinger_rsi"),
    bb_period=120,         # 2-hour Bollinger Bands
    bb_std=2.0,            # band width in standard deviations
    rsi_period=60,         # 1-hour RSI
    rsi_oversold=35,       # buy when RSI drops below 35
    rsi_overbought=65,     # sell when RSI rises above 65
    trend_filter=True,     # only buy above 4h 200-EMA
)

# ── Original SMA crossover (unchanged) ───────────────────────────────────────
metrics = engine.run(window_short=50, window_long=200)

print(metrics)
engine.plot_results()
```

---

### Grid search – find the best parameters

Each strategy exposes different tunable parameters.  Use `run_strategy_grid_search`
to sweep all combinations and rank them by Sharpe ratio (or any other metric).

```python
# Option A – EMA
results = engine.run_strategy_grid_search(
    get_strategy("ema"),
    param_grid={
        "ema_short":      [30, 50, 100],
        "ema_long":       [200, 500, 1000],
        "atr_multiplier": [1.5, 2.0, 2.5],
        "trend_filter":   [True],
    },
)

# Option B – Momentum
results = engine.run_strategy_grid_search(
    get_strategy("momentum"),
    param_grid={
        "lookback_period": [120, 240, 480],
        "entry_threshold": [0.01, 0.02, 0.03],
        "atr_multiplier":  [2.0, 2.5],
    },
)

# Option C – Bollinger + RSI
results = engine.run_strategy_grid_search(
    get_strategy("bollinger_rsi"),
    param_grid={
        "bb_period":    [60, 120, 240],
        "rsi_period":   [30, 60],
        "rsi_oversold": [30, 35, 40],
    },
)

print(results.head())          # sorted by sharpe_ratio by default
engine.plot_results()          # plot the best run
```

---

### Command-line interface

The `Examples/run_backtest.py` script exports data from InfluxDB, runs the full
grid search, and saves results to CSV + JSON.  Switch strategies with `--strategy`.

```bash
# Option A – EMA crossover
python Examples/run_backtest.py \
    --strategy ema \
    --pairs BTC-EUR \
    --ema-short 50,100,200 \
    --ema-long 200,500,1000 \
    --atr-multiplier 1.5,2.0,2.5

# Option B – Momentum
python Examples/run_backtest.py \
    --strategy momentum \
    --pairs BTC-EUR \
    --lookback-period 120,240,480 \
    --entry-threshold 0.01,0.02,0.03

# Option C – Bollinger Bands + RSI
python Examples/run_backtest.py \
    --strategy bollinger_rsi \
    --pairs BTC-EUR \
    --bb-period 60,120,240 \
    --rsi-period 30,60 \
    --rsi-oversold 30,35

# Original SMA (backward compatible)
python Examples/run_backtest.py \
    --strategy sma \
    --pairs BTC-EUR \
    --short-windows 10,20,50,100 \
    --long-windows 100,200,300,500

# Disable the 4h trend filter (Options A and C)
python Examples/run_backtest.py --strategy ema --no-trend-filter ...

# Sort results by return instead of Sharpe
python Examples/run_backtest.py --strategy ema --sort-by total_return_pct ...
```

Output files (in `results/` by default):

- `results_{PAIR}_{STRATEGY}.csv` – full grid search table, one row per parameter combination
- `best_params.json` – best parameters per pair, ready to feed into the trading bot

---

### Strategy parameters reference

**Option A – `ema`**

| Parameter | Default | Description |
|---|---|---|
| `ema_short` | 50 | Short EMA span (minutes) |
| `ema_long` | 200 | Long EMA span (minutes) |
| `atr_period` | 60 | ATR estimation window (minutes) |
| `atr_multiplier` | 2.0 | Trailing stop distance in ATR multiples |
| `volume_filter_window` | 60 | Volume MA window; set 0 to disable |
| `trend_filter` | True | Require price > 4h 200-EMA before entry |

**Option B – `momentum`**

| Parameter | Default | Description |
|---|---|---|
| `lookback_period` | 240 | Return measurement window (minutes) |
| `entry_threshold` | 0.02 | Minimum return to trigger entry (e.g. 0.02 = 2 %) |
| `exit_threshold` | -0.005 | Return level that triggers exit |
| `atr_multiplier` | 2.5 | Trailing stop distance in ATR multiples |
| `min_holding_bars` | 60 | Minimum hold time after a trade (minutes) |

**Option C – `bollinger_rsi`**

| Parameter | Default | Description |
|---|---|---|
| `bb_period` | 120 | Bollinger Band rolling window (minutes) |
| `bb_std` | 2.0 | Band width in standard deviations |
| `rsi_period` | 60 | RSI look-back window (minutes) |
| `rsi_oversold` | 35 | RSI buy threshold (enter below) |
| `rsi_overbought` | 65 | RSI sell threshold (exit above) |
| `trend_filter` | True | Require price > 4h 200-EMA before entry |

---

### Key metrics returned by every strategy

| Key | Description |
|---|---|
| `total_return_pct` | Strategy return vs initial investment |
| `buy_and_hold_return_pct` | Passive benchmark (buy at start, sell at end) |
| `n_trades` | Number of completed round-trips (buy + sell) |
| `win_rate` | Percentage of profitable trades |
| `max_drawdown_pct` | Largest peak-to-trough loss during the period |
| `sharpe_ratio` | Annualised Sharpe ratio (daily returns × √365) |
| `total_fees` / `taker_fees` / `maker_fees` | Fee breakdown in base currency |

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

---

## Disclaimer

This software is for educational purposes only. Automated trading carries
significant financial risk. Past backtesting performance does not guarantee
future results. Use at your own risk.
