"""Entry point for the live / paper trading bot.

Usage examples:

    # Paper trade BTC-EUR on Kraken with default SMA(50/200):
    python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR --paper

    # Live trade ETH-USDT on Binance with custom windows:
    python Examples/run_trading_bot.py --exchange binance --pair ETH-USDT \\
        --short 20 --long 100 --invest 500

    # Fast paper test (10 s poll, tiny SMA windows):
    python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR \\
        --short 5 --long 20 --poll 10 --paper

    # Pre-warm SignalGenerator from Hetzner InfluxDB via SSH tunnel:
    #   ssh -L 8086:localhost:8086 root@<hetzner-ip> -N &
    python Examples/run_trading_bot.py --exchange kraken --pair BTC-EUR \\
        --warmup --influx-url http://localhost:8086

Environment variables (alternative to flags):
    EXCHANGE, PAIR, WINDOW_SHORT, WINDOW_LONG, INITIAL_INVEST,
    POLL_INTERVAL, PAPER_TRADING=true|false
    KRAKEN_API_KEY, KRAKEN_API_SECRET
    BINANCE_API_KEY, BINANCE_API_SECRET
    INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN, INFLUXDB_INIT_ORG, INFLUXDB_INIT_BUCKET
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

# Allow running from the repo root without installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from altotrader.logging_config import setup_logging
from altotrader.trader.config import TradingConfig
from altotrader.trader.position_manager import PositionManager
from altotrader.trader.risk_manager import RiskManager
from altotrader.trader.trading_engine import TradingEngine


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AltoTrader – MA crossover trading bot")
    p.add_argument("--exchange", default=os.environ.get("EXCHANGE", "kraken"),
                   choices=["kraken", "binance"], help="Exchange to trade on")
    p.add_argument("--pair",     default=os.environ.get("PAIR", "BTC-EUR"),
                   help="Trading pair in unified format, e.g. BTC-EUR")
    p.add_argument("--short",    type=int, default=int(os.environ.get("WINDOW_SHORT", 50)),
                   help="Short SMA window (ticks)")
    p.add_argument("--long",     type=int, default=int(os.environ.get("WINDOW_LONG", 200)),
                   help="Long SMA window (ticks)")
    p.add_argument("--invest",   type=float, default=float(os.environ.get("INITIAL_INVEST", 1000)),
                   help="Initial capital in quote currency")
    p.add_argument("--poll",     type=int, default=int(os.environ.get("POLL_INTERVAL", 60)),
                   help="Seconds between price fetches")
    p.add_argument("--paper",    action="store_true",
                   default=os.environ.get("PAPER_TRADING", "true").lower() == "true",
                   help="Paper trading mode (no real orders)")
    p.add_argument("--log-dir",  default="logs", help="Log directory")

    # ── InfluxDB warm-up (optional) ──────────────────────────────────────────
    p.add_argument("--warmup", action="store_true",
                   default=os.environ.get("WARMUP_FROM_INFLUXDB", "false").lower() == "true",
                   help="Pre-seed SMA buffer from InfluxDB history before trading starts")
    p.add_argument("--influx-url",    default=os.environ.get("INFLUX_URL"),
                   help="InfluxDB URL for warm-up (e.g. http://localhost:8086)")
    p.add_argument("--influx-token",  default=os.environ.get("INFLUXDB_INIT_ADMIN_TOKEN"),
                   help="InfluxDB API token")
    p.add_argument("--influx-org",    default=os.environ.get("INFLUXDB_INIT_ORG"),
                   help="InfluxDB organisation")
    p.add_argument("--influx-bucket", default=os.environ.get("INFLUXDB_INIT_BUCKET"),
                   help="InfluxDB bucket")
    p.add_argument("--warmup-days",   type=int, default=7,
                   help="How many days of history to use for warm-up (default: 7)")
    return p.parse_args()


def _build_ticker(exchange: str, pair: str):
    """Instantiate the correct ticker for the given exchange."""
    if exchange == "kraken":
        from altotrader.ticker.krakenticker import KrakenTicker
        import tempfile, yaml, os
        # Write a minimal pairs YAML to a temp file
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump({"items": [pair]}, tmp)
        tmp.close()
        return KrakenTicker(pairs_yaml=tmp.name)
    elif exchange == "binance":
        from altotrader.ticker.binanceticker import BinanceTicker
        import tempfile, yaml
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump({"items": [pair]}, tmp)
        tmp.close()
        return BinanceTicker(pairs_yaml=tmp.name)
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")


def _build_broker(exchange: str, config: TradingConfig):
    """Instantiate the appropriate broker (paper or live)."""
    if config.paper_trading:
        from altotrader.trader.broker.paper_broker import PaperBroker
        return PaperBroker(config)

    if exchange == "kraken":
        from altotrader.trader.broker.kraken_broker import KrakenBroker
        return KrakenBroker(config)
    elif exchange == "binance":
        from altotrader.trader.broker.binance_broker import BinanceBroker
        return BinanceBroker(config)
    else:
        raise ValueError(f"Unsupported exchange for live trading: {exchange}")


def main() -> None:
    args = _parse_args()
    setup_logging(log_filename="trading_bot.log", log_dir=args.log_dir)
    logger = logging.getLogger(__name__)

    mode = "PAPER" if args.paper else "LIVE"
    logger.info(
        f"Starting AltoTrader [{mode}] | {args.exchange} {args.pair} | "
        f"SMA({args.short}/{args.long}) | invest={args.invest} | poll={args.poll}s"
    )

    config = TradingConfig(
        pair=args.pair,
        exchange=args.exchange,
        window_short=args.short,
        window_long=args.long,
        initial_invest=args.invest,
        paper_trading=args.paper,
        poll_interval=args.poll,
    )

    ticker       = _build_ticker(args.exchange, args.pair)
    broker       = _build_broker(args.exchange, config)
    position_mgr = PositionManager(persist_path=f"{args.log_dir}/positions.json")
    risk_mgr     = RiskManager(config)

    engine = TradingEngine(
        config=config,
        ticker=ticker,
        broker=broker,
        position_mgr=position_mgr,
        risk_mgr=risk_mgr,
        log_dir=args.log_dir,
    )

    # ── Optional: pre-warm SignalGenerator from InfluxDB ────────────────────
    if args.warmup:
        missing = [name for name, val in [
            ("--influx-url",    args.influx_url),
            ("--influx-token",  args.influx_token),
            ("--influx-org",    args.influx_org),
            ("--influx-bucket", args.influx_bucket),
        ] if not val]
        if missing:
            logger.warning(
                f"Warm-up skipped – missing InfluxDB parameters: {', '.join(missing)}. "
                "Set via flags or env vars (INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN, "
                "INFLUXDB_INIT_ORG, INFLUXDB_INIT_BUCKET)."
            )
        else:
            n = engine.warmup_from_influxdb(
                url=args.influx_url,
                token=args.influx_token,
                org=args.influx_org,
                bucket=args.influx_bucket,
                days=args.warmup_days,
            )
            if n == 0:
                logger.warning("Warm-up returned 0 prices – bot will warm up organically.")

    # Graceful shutdown on SIGTERM / SIGINT
    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig} – stopping engine …")
        engine.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    engine.start()
    engine.join()
    logger.info("AltoTrader stopped.")


if __name__ == "__main__":
    main()
