"""Backtest orchestration script.

Fetches data from InfluxDB, runs a grid search over SMA window combinations
for each configured pair, and writes results to disk.

Output (written to RESULTS_DIR, default ``results/``):
    results_{PAIR}.csv      – full grid search DataFrame, sorted by Sharpe ratio
    best_windows.json       – best windows per pair (for the trading engine)

Usage::

    # Via CLI flags:
    python Examples/run_backtest.py \\
        --pairs BTC-EUR,ETH-EUR \\
        --exchange kraken \\
        --days 30 \\
        --short-windows 10,20,50,100 \\
        --long-windows 100,200,300,500

    # Via environment variables (Docker):
    BACKTEST_PAIRS=BTC-EUR,ETH-EUR \\
    BACKTEST_EXCHANGE=kraken \\
    BACKTEST_DAYS=30 \\
    BACKTEST_SHORT_WINDOWS=10,20,50,100 \\
    BACKTEST_LONG_WINDOWS=100,200,300,500 \\
    python Examples/run_backtest.py
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
from altotrader.database.export_prices import export_prices
from altotrader.logging_config import setup_logging

_DEFAULT_SHORT_WINDOWS = [10, 20, 50, 100]
_DEFAULT_LONG_WINDOWS  = [100, 200, 300, 500]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AltoTrader Backtest Grid Search")
    p.add_argument("--pairs",          default=os.environ.get("BACKTEST_PAIRS", "BTC-EUR"),
                   help="Comma-separated pairs, e.g. BTC-EUR,ETH-EUR")
    p.add_argument("--exchange",       default=os.environ.get("BACKTEST_EXCHANGE", "kraken"),
                   choices=["kraken", "binance"],
                   help="Exchange whose InfluxDB measurement to query")
    p.add_argument("--days",           type=int,
                   default=int(os.environ.get("BACKTEST_DAYS", 30)),
                   help="Days of historical data to fetch from InfluxDB")
    p.add_argument("--short-windows",  default=os.environ.get("BACKTEST_SHORT_WINDOWS", ""),
                   help="Comma-separated short SMA windows, e.g. 10,20,50,100")
    p.add_argument("--long-windows",   default=os.environ.get("BACKTEST_LONG_WINDOWS", ""),
                   help="Comma-separated long SMA windows, e.g. 100,200,300,500")
    p.add_argument("--results-dir",    default=os.environ.get("RESULTS_DIR", "results"),
                   help="Directory to write results JSON and CSV files")
    p.add_argument("--maker-fee",      type=float, default=0.0025)
    p.add_argument("--taker-fee",      type=float, default=0.004)
    p.add_argument("--slippage",       type=float, default=0.0005)
    p.add_argument("--initial-invest", type=float, default=1000.0)
    return p.parse_args()


def _parse_windows(raw: str, default: list[int]) -> list[int]:
    if not raw:
        return default
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return default


def run_backtest_for_pair(
    pair: str,
    exchange: str,
    days: int,
    short_windows: list[int],
    long_windows: list[int],
    export_dir: str,
    backtest_config: dict,
    logger: logging.Logger,
) -> dict | None:
    """Run export + grid search for a single pair.

    Returns the best-windows dict or None on failure.
    """
    base, quote = pair.split("-")
    logger.info(f"{'='*60}")
    logger.info(f"Processing pair: {pair} | exchange={exchange} | days={days}")

    # ── Step 1: Export data from InfluxDB ────────────────────────────
    logger.info(f"Exporting {days}d of data from InfluxDB ({exchange})…")
    ok = export_prices(
        path_to_parquet=export_dir,
        days_into_past=days,
        file_format="csv",
        measurement=exchange,
    )
    if not ok:
        logger.error(f"Export failed for {pair}, skipping.")
        return None

    # ── Step 2: Load CSV into DataLoader ─────────────────────────────
    bucket = os.environ.get("INFLUXDB_INIT_BUCKET", "altotrader")
    loader_config = {
        "export_path": export_dir,
        "file_prefix": bucket,
        "latest_days": days,
        "logs_dir":    "logs",
    }
    loader = DataLoader(loader_config)
    try:
        loader.load_csv_export()
    except Exception as exc:
        logger.error(f"DataLoader failed for {pair}: {exc}")
        return None

    # Check the pair is actually in the data
    if loader.ticker_current is None or pair not in loader.ticker_current.columns:
        available = list(loader.ticker_current.columns) if loader.ticker_current is not None else []
        logger.error(
            f"Pair {pair!r} not found in exported data. "
            f"Available: {available}"
        )
        return None

    # ── Step 3: BacktestEngine + Grid Search ─────────────────────────
    cfg = {**backtest_config, "trading_currency": base, "base_currency": quote}
    engine = BacktestEngine(loader, cfg, log_dir="logs")

    logger.info(
        f"Running grid search: {len(short_windows)}×{len(long_windows)} = "
        f"{sum(1 for s in short_windows for l in long_windows if s < l)} valid combos"
    )
    results = run_grid_search(engine, short_windows, long_windows)

    if results.empty:
        logger.error(f"Grid search returned no results for {pair}")
        return None

    # Sort by Sharpe ratio (more robust than raw return)
    results = results.sort_values("sharpe_ratio", ascending=False).reset_index(drop=True)
    best = results.iloc[0]

    logger.info(
        f"Best windows for {pair}: short={int(best['window_short'])} "
        f"long={int(best['window_long'])} | "
        f"sharpe={best['sharpe_ratio']:.3f} | "
        f"return={best['total_return_pct']:+.2f}% | "
        f"trades={int(best['n_trades'])}"
    )
    return {
        "exchange":        exchange,
        "window_short":    int(best["window_short"]),
        "window_long":     int(best["window_long"]),
        "sharpe_ratio":    round(float(best["sharpe_ratio"]), 4),
        "total_return_pct": round(float(best["total_return_pct"]), 4),
        "n_trades":        int(best["n_trades"]),
        "max_drawdown_pct": round(float(best.get("max_drawdown_pct", 0)), 4),
        "win_rate":        round(float(best.get("win_rate", 0)), 4),
    }, results


def main() -> None:
    args = _parse_args()
    setup_logging(log_filename="backtest.log", log_dir="logs")
    logger = logging.getLogger(__name__)

    pairs         = [p.strip() for p in args.pairs.split(",") if p.strip()]
    short_windows = _parse_windows(args.short_windows, _DEFAULT_SHORT_WINDOWS)
    long_windows  = _parse_windows(args.long_windows,  _DEFAULT_LONG_WINDOWS)

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
        f"AltoTrader Backtest | pairs={pairs} | exchange={args.exchange} | "
        f"days={args.days} | short={short_windows} | long={long_windows}"
    )

    best_windows: dict = {}
    failed_pairs: list = []

    for pair in pairs:
        result = run_backtest_for_pair(
            pair=pair,
            exchange=args.exchange,
            days=args.days,
            short_windows=short_windows,
            long_windows=long_windows,
            export_dir=export_dir,
            backtest_config=backtest_config,
            logger=logger,
        )
        if result is None:
            failed_pairs.append(pair)
            continue

        best, full_results = result
        best_windows[pair] = best

        # Save full grid search results
        pair_slug = pair.replace("-", "")
        csv_path  = results_dir / f"results_{pair_slug}.csv"
        full_results.to_csv(csv_path, index=False)
        logger.info(f"Full results saved → {csv_path}")

    # ── Write best_windows.json ───────────────────────────────────────
    best_windows["updated_at"] = datetime.now(timezone.utc).isoformat()
    json_path = results_dir / "best_windows.json"
    with open(json_path, "w") as f:
        json.dump(best_windows, f, indent=2)
    logger.info(f"Best windows saved → {json_path}")

    if failed_pairs:
        logger.warning(f"Failed pairs: {failed_pairs}")
    logger.info("Backtest complete.")


if __name__ == "__main__":
    main()
