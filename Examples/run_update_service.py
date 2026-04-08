"""Robust data streaming service for AltoTrader.

Supports two modes (select via --mode flag or MODE env var):

  rest (default)
      Polls the Kraken REST API every POLL_INTERVAL_SECONDS and writes results
      to InfluxDB.  Simpler, no extra dependencies.

  websocket
      Connects to the Kraken WebSocket API for real-time tick data, then
      writes the latest snapshot to InfluxDB every POLL_INTERVAL_SECONDS.
      Requires: pip install websocket-client

Both modes handle failures gracefully:
  - Consecutive failures trigger increasing back-off (up to MAX_BACKOFF_SECONDS)
  - A heartbeat is logged every HEARTBEAT_INTERVAL cycles
  - SIGINT / SIGTERM shut the loop down cleanly

Supported exchanges (--exchange / EXCHANGE env var):
    kraken (default), binance, coinbase, gemini, mexc
    WebSocket mode is only available for kraken and binance.

Usage:
    python Examples/run_update_service.py                              # Kraken REST (default)
    python Examples/run_update_service.py --mode websocket             # Kraken WebSocket
    python Examples/run_update_service.py --exchange binance           # Binance REST
    python Examples/run_update_service.py --exchange binance --mode websocket
    python Examples/run_update_service.py --pairs Examples/binance_pairs.yaml

Environment variables (see env/.env.example):
    INFLUXDB_INIT_BUCKET, INFLUXDB_INIT_ORG, INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN
    MODE=websocket      (alternative to --mode flag)
    EXCHANGE=binance    (alternative to --exchange flag)
"""

import argparse
import logging
import os
import signal
import sys
import time

from altotrader.database.update_service import TickerUpdateService
from altotrader.logging_config import setup_logging

# ── Configuration ──────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 60    # write to InfluxDB every N seconds
MAX_BACKOFF_SECONDS   = 300   # cap for exponential back-off on failures
HEARTBEAT_INTERVAL    = 10    # log heartbeat every N cycles
LOG_DIR    = "logs"

EXCHANGE_PAIRS_YAML = {
    "kraken":   "Examples/kraken_pairs.yaml",
    "binance":  "Examples/binance_pairs.yaml",
    "coinbase": "Examples/coinbase_pairs.yaml",
    "gemini":   "Examples/gemini_pairs.yaml",
    "mexc":     "Examples/mexc_pairs.yaml",
}
WS_EXCHANGES = {"kraken", "binance"}
# ───────────────────────────────────────────────────────────────────────────────


def _make_shutdown_handler(stop_flag: list):
    def handler(signum, frame):
        logging.getLogger(__name__).info(
            f"Received signal {signum} – shutting down gracefully …"
        )
        stop_flag[0] = True
    return handler


def _polling_loop(service: TickerUpdateService, stop_flag: list):
    """Main write loop shared by both REST and WS modes."""
    logger = logging.getLogger(__name__)
    consecutive_failures = 0
    total_success = total_failure = cycle = 0

    while not stop_flag[0]:
        cycle += 1
        success = service.update_pairs_ticker()

        if success:
            consecutive_failures = 0
            total_success += 1
            sleep_time = POLL_INTERVAL_SECONDS
        else:
            consecutive_failures += 1
            total_failure += 1
            backoff = min(
                POLL_INTERVAL_SECONDS * (2 ** (consecutive_failures - 1)),
                MAX_BACKOFF_SECONDS,
            )
            logger.warning(
                f"Update failed (consecutive: {consecutive_failures}). "
                f"Backing off {backoff}s."
            )
            sleep_time = backoff

        if cycle % HEARTBEAT_INTERVAL == 0:
            logger.info(
                f"[Heartbeat] cycle={cycle} | ok={total_success} | fail={total_failure}"
            )

        # Interruptible sleep
        for _ in range(int(sleep_time)):
            if stop_flag[0]:
                break
            time.sleep(1)

    logger.info(
        f"Service stopped. cycles={cycle} | ok={total_success} | fail={total_failure}"
    )


def _make_rest_ticker(exchange: str, pair_yaml: str):
    if exchange == "kraken":
        from altotrader.ticker.krakenticker import KrakenTicker
        return KrakenTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    if exchange == "binance":
        from altotrader.ticker.binanceticker import BinanceTicker
        return BinanceTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    if exchange == "coinbase":
        from altotrader.ticker.coinbaseticker import CoinbaseTicker
        return CoinbaseTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    if exchange == "gemini":
        from altotrader.ticker.geminiticker import GeminiTicker
        return GeminiTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    if exchange == "mexc":
        from altotrader.ticker.mexcticker import MEXCTicker
        return MEXCTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    raise ValueError(f"Unknown exchange: {exchange!r}. Choose from: {list(EXCHANGE_PAIRS_YAML)}")


def _make_ws_ticker(exchange: str, pair_yaml: str):
    if exchange == "kraken":
        from altotrader.ticker.kraken_ws_ticker import KrakenWsTicker
        return KrakenWsTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    if exchange == "binance":
        from altotrader.ticker.binance_ws_ticker import BinanceWsTicker
        return BinanceWsTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    raise ValueError(f"WebSocket mode not supported for {exchange!r}. Supported: {sorted(WS_EXCHANGES)}")


def run_rest(exchange: str, pair_yaml: str):
    """Start the REST-polling streaming service."""
    setup_logging(log_filename="run_update_service.logs", log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting AltoTrader streaming service [mode: REST, exchange: {exchange}]")

    ticker  = _make_rest_ticker(exchange, pair_yaml)
    service = TickerUpdateService(ticker, log_dir=LOG_DIR)

    stop_flag = [False]
    signal.signal(signal.SIGINT,  _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    _polling_loop(service, stop_flag)


def run_websocket(exchange: str, pair_yaml: str):
    """Start the WebSocket streaming service."""
    setup_logging(log_filename="run_update_service.logs", log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting AltoTrader streaming service [mode: WebSocket, exchange: {exchange}]")

    stop_flag = [False]
    signal.signal(signal.SIGINT,  _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    with _make_ws_ticker(exchange, pair_yaml) as ticker:
        # Brief wait for the first WS messages to arrive
        logger.info("Waiting 3s for initial WebSocket data …")
        time.sleep(3)

        service = TickerUpdateService(ticker, log_dir=LOG_DIR)
        _polling_loop(service, stop_flag)


def main():
    parser = argparse.ArgumentParser(description="AltoTrader data streaming service")
    parser.add_argument(
        "--mode",
        choices=["rest", "websocket"],
        default=os.getenv("MODE", "rest"),
        help="Data source mode: 'rest' (default) or 'websocket'",
    )
    parser.add_argument(
        "--exchange",
        choices=list(EXCHANGE_PAIRS_YAML),
        default=os.getenv("EXCHANGE", "kraken"),
        help="Exchange to stream from (default: kraken)",
    )
    parser.add_argument(
        "--pairs",
        default=None,
        help="Path to pairs YAML file (default: exchange-specific yaml in Examples/)",
    )
    args = parser.parse_args()

    pair_yaml = args.pairs or EXCHANGE_PAIRS_YAML[args.exchange]

    if args.mode == "websocket":
        run_websocket(exchange=args.exchange, pair_yaml=pair_yaml)
    else:
        run_rest(exchange=args.exchange, pair_yaml=pair_yaml)


if __name__ == "__main__":
    main()
