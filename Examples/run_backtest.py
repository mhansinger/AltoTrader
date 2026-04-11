"""Backtest orchestration script.

Fetches data from InfluxDB (or loads from local CSV), runs a grid search over
the chosen strategy's parameter combinations for each configured pair, and
writes results to disk.

Supported strategies
--------------------
``sma``            Classic SMA crossover (original – grid sweeps short/long windows)
``ema``            Option A: EMA crossover + ATR trailing stop + 4h trend filter
``momentum``       Option B: Time-series momentum + ATR trailing stop
``bollinger_rsi``  Option C: Bollinger Bands + RSI mean-reversion

Output (written to RESULTS_DIR, default ``results/``)
------------------------------------------------------
results_{PAIR}_{STRATEGY}.csv   – full grid search DataFrame sorted by Sharpe
best_params.json                – best parameters per pair × strategy

Usage
-----
# SMA crossover (original behaviour):
python Examples/run_backtest.py --strategy sma --pairs BTC-EUR

# EMA crossover with custom grid:
python Examples/run_backtest.py --strategy ema --pairs BTC-EUR \\
    --ema-short 50,100,200 --ema-long 200,500,1000 --atr-multiplier 1.5,2.0,2.5

# Momentum:
python Examples/run_backtest.py --strategy momentum --pairs BTC-EUR \\
    --lookback-period 120,240,480 --entry-threshold 0.01,0.02,0.03

# Bollinger Bands + RSI:
python Examples/run_backtest.py --strategy bollinger_rsi --pairs BTC-EUR \\
    --bb-period 60,120,240 --rsi-period 30,60 --rsi-oversold 30,35

# Via environment variables (Docker):
BACKTEST_STRATEGY=ema BACKTEST_PAIRS=BTC-EUR python Examples/run_backtest.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from altotrader.backtest.backtest_engine import BacktestEngine, run_grid_search
from altotrader.backtest.dataloader import DataLoader
from altotrader.backtest.strategies import get_strategy, AVAILABLE_STRATEGIES
from altotrader.database.export_prices import export_prices
from altotrader.logging_config import setup_logging

_DEFAULT_SHORT_WINDOWS = [10, 20, 50, 100]
_DEFAULT_LONG_WINDOWS  = [100, 200, 300, 500]


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AltoTrader Backtest – supports SMA, EMA, Momentum, Bollinger/RSI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── General ──
    p.add_argument("--pairs",     default=os.environ.get("BACKTEST_PAIRS", "BTC-EUR"),
                   help="Comma-separated pairs, e.g. BTC-EUR,ETH-EUR")
    p.add_argument("--exchange",  default=os.environ.get("BACKTEST_EXCHANGE", "kraken"),
                   choices=["kraken", "binance"])
    p.add_argument("--days",      type=int,
                   default=int(os.environ.get("BACKTEST_DAYS", 30)))
    p.add_argument("--strategy",  default=os.environ.get("BACKTEST_STRATEGY", "sma"),
                   choices=["sma"] + AVAILABLE_STRATEGIES,
                   help="Which strategy to backtest (default: sma)")
    p.add_argument("--results-dir", default=os.environ.get("RESULTS_DIR", "results"))
    p.add_argument("--sort-by",   default="sharpe_ratio",
                   help="Metric to rank grid search results by (default: sharpe_ratio)")

    # ── Fees / execution ──
    p.add_argument("--maker-fee",      type=float, default=0.0025)
    p.add_argument("--taker-fee",      type=float, default=0.004)
    p.add_argument("--slippage",       type=float, default=0.0005)
    p.add_argument("--initial-invest", type=float, default=1000.0)

    # ── SMA strategy parameters ──
    p.add_argument("--short-windows", default=os.environ.get("BACKTEST_SHORT_WINDOWS", ""),
                   help="[sma] Comma-separated short SMA windows, e.g. 10,20,50,100")
    p.add_argument("--long-windows",  default=os.environ.get("BACKTEST_LONG_WINDOWS", ""),
                   help="[sma] Comma-separated long SMA windows, e.g. 100,200,300,500")

    # ── EMA strategy parameters (Option A) ──
    p.add_argument("--ema-short",      default=os.environ.get("BACKTEST_EMA_SHORT", "50,100"),
                   help="[ema] Short EMA spans in minutes, e.g. 50,100,200")
    p.add_argument("--ema-long",       default=os.environ.get("BACKTEST_EMA_LONG", "200,500"),
                   help="[ema] Long EMA spans in minutes, e.g. 200,500,1000")
    p.add_argument("--atr-multiplier", default=os.environ.get("BACKTEST_ATR_MULTIPLIER", "1.5,2.0,2.5"),
                   help="[ema/momentum] ATR trailing-stop multipliers, e.g. 1.5,2.0,2.5")
    p.add_argument("--no-trend-filter", action="store_true",
                   help="[ema/bollinger_rsi] Disable the 4h 200-EMA trend guard")

    # ── Momentum strategy parameters (Option B) ──
    p.add_argument("--lookback-period",  default=os.environ.get("BACKTEST_LOOKBACK", "120,240,480"),
                   help="[momentum] Return lookback windows in minutes, e.g. 120,240,480")
    p.add_argument("--entry-threshold",  default=os.environ.get("BACKTEST_ENTRY_THRESH", "0.01,0.02,0.03"),
                   help="[momentum] Minimum return to enter, e.g. 0.01,0.02,0.03")
    p.add_argument("--exit-threshold",   default="-0.005",
                   help="[momentum] Return level to exit (default: -0.005)")

    # ── Bollinger/RSI parameters (Option C) ──
    p.add_argument("--bb-period",      default=os.environ.get("BACKTEST_BB_PERIOD", "60,120,240"),
                   help="[bollinger_rsi] BB rolling window in minutes, e.g. 60,120,240")
    p.add_argument("--bb-std",         default="2.0",
                   help="[bollinger_rsi] BB std-dev multiplier (default: 2.0)")
    p.add_argument("--rsi-period",     default=os.environ.get("BACKTEST_RSI_PERIOD", "30,60"),
                   help="[bollinger_rsi] RSI window in minutes, e.g. 30,60")
    p.add_argument("--rsi-oversold",   default=os.environ.get("BACKTEST_RSI_OVERSOLD", "30,35"),
                   help="[bollinger_rsi] RSI buy threshold, e.g. 30,35,40")
    p.add_argument("--rsi-overbought", default="65",
                   help="[bollinger_rsi] RSI sell threshold (default: 65)")

    return p.parse_args()


def _parse_windows(raw: str, default: list[int]) -> list[int]:
    """Backward-compatible alias for _ints (used in legacy tests)."""
    return _ints(raw, default)


def _floats(raw: str, default: list[float]) -> list[float]:
    if not raw:
        return default
    try:
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return default


def _ints(raw: str, default: list[int]) -> list[int]:
    if not raw:
        return default
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return default


# ── Per-pair runner ───────────────────────────────────────────────────────────

def run_backtest_for_pair(
    pair: str,
    exchange: str,
    days: int,
    strategy_name: str,
    param_grid: dict,
    export_dir: str,
    backtest_config: dict,
    logger: logging.Logger,
    sort_by: str = "sharpe_ratio",
) -> tuple[dict, "pd.DataFrame"] | None:
    """Export data, load it, run the chosen strategy's grid search.

    Returns ``(best_params_dict, full_results_df)`` or ``None`` on failure.
    """
    base, quote = pair.split("-")
    logger.info("=" * 60)
    logger.info(f"Pair: {pair} | strategy={strategy_name} | exchange={exchange} | days={days}")

    # ── Export from InfluxDB ──────────────────────────────────────────────────
    logger.info(f"Exporting {days}d of data from InfluxDB…")
    ok = export_prices(
        path_to_parquet=export_dir,
        days_into_past=days,
        file_format="csv",
        measurement=exchange,
    )
    if not ok:
        logger.error(f"Export failed for {pair}, skipping.")
        return None

    # ── Load CSV ──────────────────────────────────────────────────────────────
    bucket = os.environ.get("INFLUXDB_INIT_BUCKET", "altotrader")
    loader = DataLoader({
        "export_path": export_dir,
        "file_prefix": bucket,
        "latest_days": days,
        "logs_dir":    "logs",
    })
    try:
        loader.load_csv_export()
    except Exception as exc:
        logger.error(f"DataLoader failed: {exc}")
        return None

    if loader.ticker_current is None or pair not in loader.ticker_current.columns:
        available = list(loader.ticker_current.columns) if loader.ticker_current is not None else []
        logger.error(f"Pair {pair!r} not in exported data. Available: {available}")
        return None

    # ── BacktestEngine ────────────────────────────────────────────────────────
    cfg    = {**backtest_config, "trading_currency": base, "base_currency": quote}
    engine = BacktestEngine(loader, cfg, log_dir="logs")

    # ── SMA crossover (original) ──────────────────────────────────────────────
    if strategy_name == "sma":
        short_windows = param_grid.get("window_short", _DEFAULT_SHORT_WINDOWS)
        long_windows  = param_grid.get("window_long",  _DEFAULT_LONG_WINDOWS)

        import pandas as _pd
        results = run_grid_search(engine, short_windows, long_windows)
        if results.empty:
            logger.error(f"SMA grid search returned no results for {pair}")
            return None
        results = results.sort_values(sort_by, ascending=False).reset_index(drop=True)
        best    = results.iloc[0]

        logger.info(
            f"Best SMA: short={int(best['window_short'])} long={int(best['window_long'])}  "
            f"{sort_by}={best[sort_by]:.3f}  return={best['total_return_pct']:+.2f}%"
        )
        return {
            "strategy":            strategy_name,
            "exchange":            exchange,
            "window_short":        int(best["window_short"]),
            "window_long":         int(best["window_long"]),
            "sharpe_ratio":        round(float(best["sharpe_ratio"]), 4),
            "total_return_pct":    round(float(best["total_return_pct"]), 4),
            "n_trades":            int(best["n_trades"]),
            "max_drawdown_pct":    round(float(best.get("max_drawdown_pct", 0)), 4),
            "win_rate":            round(float(best.get("win_rate", 0)), 4),
        }, results

    # ── Pluggable strategy ────────────────────────────────────────────────────
    strategy = get_strategy(strategy_name)
    n_combos = 1
    for v in param_grid.values():
        n_combos *= len(v)
    logger.info(f"Running grid search: {n_combos} combinations")

    results = engine.run_strategy_grid_search(strategy, param_grid, sort_by=sort_by)

    if results.empty:
        logger.error(f"Grid search returned no results for {pair}")
        return None

    best = results.iloc[0]
    param_keys = list(param_grid.keys())

    logger.info(
        f"Best {strategy_name}: "
        + "  ".join(f"{k}={best[k]}" for k in param_keys if k in best)
        + f"  {sort_by}={best[sort_by]:.3f}  return={best['total_return_pct']:+.2f}%"
    )

    best_dict = {"strategy": strategy_name, "exchange": exchange}
    for k in param_keys:
        if k in best:
            best_dict[k] = best[k]
    best_dict.update({
        "sharpe_ratio":     round(float(best["sharpe_ratio"]), 4),
        "total_return_pct": round(float(best["total_return_pct"]), 4),
        "n_trades":         int(best["n_trades"]),
        "max_drawdown_pct": round(float(best.get("max_drawdown_pct", 0)), 4),
        "win_rate":         round(float(best.get("win_rate", 0)), 4),
    })
    return best_dict, results


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    setup_logging(log_filename="backtest.log", log_dir="logs")
    logger = logging.getLogger(__name__)

    pairs        = [p.strip() for p in args.pairs.split(",") if p.strip()]
    strategy     = args.strategy
    trend_filter = not args.no_trend_filter

    # ── Build param_grid depending on strategy ───────────────────────────────
    if strategy == "sma":
        param_grid = {
            "window_short": _ints(args.short_windows, _DEFAULT_SHORT_WINDOWS),
            "window_long":  _ints(args.long_windows,  _DEFAULT_LONG_WINDOWS),
        }

    elif strategy == "ema":
        param_grid = {
            "ema_short":      _ints(args.ema_short, [50, 100]),
            "ema_long":       _ints(args.ema_long, [200, 500]),
            "atr_multiplier": _floats(args.atr_multiplier, [1.5, 2.0, 2.5]),
            "trend_filter":   [trend_filter],
        }

    elif strategy == "momentum":
        param_grid = {
            "lookback_period":  _ints(args.lookback_period, [120, 240, 480]),
            "entry_threshold":  _floats(args.entry_threshold, [0.01, 0.02, 0.03]),
            "exit_threshold":   _floats(args.exit_threshold, [-0.005]),
            "atr_multiplier":   _floats(args.atr_multiplier, [2.0, 2.5]),
        }

    elif strategy == "bollinger_rsi":
        param_grid = {
            "bb_period":      _ints(args.bb_period, [60, 120, 240]),
            "bb_std":         _floats(args.bb_std, [2.0]),
            "rsi_period":     _ints(args.rsi_period, [30, 60]),
            "rsi_oversold":   _floats(args.rsi_oversold, [30, 35]),
            "rsi_overbought": _floats(args.rsi_overbought, [65]),
            "trend_filter":   [trend_filter],
        }
    else:
        logger.error(f"Unknown strategy: {strategy}")
        sys.exit(1)

    results_dir = Path(args.results_dir)
    export_dir  = str(results_dir / "exports")
    results_dir.mkdir(parents=True, exist_ok=True)
    Path(export_dir).mkdir(parents=True, exist_ok=True)

    backtest_config = {
        "maker_fee":      args.maker_fee,
        "taker_fee":      args.taker_fee,
        "slippage_pct":   args.slippage,
        "initial_invest": args.initial_invest,
    }

    logger.info(
        f"AltoTrader Backtest | strategy={strategy} | pairs={pairs} | "
        f"exchange={args.exchange} | days={args.days}"
    )
    logger.info(f"Param grid: {param_grid}")

    best_params: dict = {}
    failed_pairs: list = []

    for pair in pairs:
        result = run_backtest_for_pair(
            pair=pair,
            exchange=args.exchange,
            days=args.days,
            strategy_name=strategy,
            param_grid=param_grid,
            export_dir=export_dir,
            backtest_config=backtest_config,
            logger=logger,
            sort_by=args.sort_by,
        )
        if result is None:
            failed_pairs.append(pair)
            continue

        best, full_results = result
        best_params[pair] = best

        pair_slug = pair.replace("-", "")
        csv_path  = results_dir / f"results_{pair_slug}_{strategy}.csv"
        full_results.to_csv(csv_path, index=False)
        logger.info(f"Full results → {csv_path}")

    best_params["updated_at"] = datetime.now(timezone.utc).isoformat()
    json_path = results_dir / "best_params.json"
    with open(json_path, "w") as f:
        json.dump(best_params, f, indent=2)
    logger.info(f"Best params → {json_path}")

    if failed_pairs:
        logger.warning(f"Failed pairs: {failed_pairs}")
    logger.info("Backtest complete.")


if __name__ == "__main__":
    main()
