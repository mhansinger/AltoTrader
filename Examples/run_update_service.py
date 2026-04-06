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

Usage:
    python Examples/run_update_service.py                # REST mode (default)
    python Examples/run_update_service.py --mode websocket
    python Examples/run_update_service.py --pairs Examples/kraken_pairs.yaml

Environment variables (see env/.env.example):
    INFLUXDB_INIT_BUCKET, INFLUXDB_INIT_ORG, INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN
    MODE=websocket   (alternative to --mode flag)
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
PAIRS_YAML = "Examples/kraken_pairs.yaml"
LOG_DIR    = "logs"
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


def run_rest(pair_yaml: str = PAIRS_YAML):
    """Start the REST-polling streaming service."""
    from altotrader.ticker.krakenticker import KrakenTicker

    setup_logging(log_filename="run_update_service.logs", log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)
    logger.info("Starting AltoTrader streaming service [mode: REST]")

    ticker  = KrakenTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    service = TickerUpdateService(ticker, log_dir=LOG_DIR)

    stop_flag = [False]
    signal.signal(signal.SIGINT,  _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    _polling_loop(service, stop_flag)


def run_websocket(pair_yaml: str = PAIRS_YAML):
    """Start the WebSocket streaming service."""
    from altotrader.ticker.kraken_ws_ticker import KrakenWsTicker

    setup_logging(log_filename="run_update_service.logs", log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)
    logger.info("Starting AltoTrader streaming service [mode: WebSocket]")

    stop_flag = [False]
    signal.signal(signal.SIGINT,  _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    with KrakenWsTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR) as ticker:
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
        "--pairs",
        default=PAIRS_YAML,
        help=f"Path to pairs YAML file (default: {PAIRS_YAML})",
    )
    args = parser.parse_args()

    if args.mode == "websocket":
        run_websocket(pair_yaml=args.pairs)
    else:
        run_rest(pair_yaml=args.pairs)


if __name__ == "__main__":
    main()
