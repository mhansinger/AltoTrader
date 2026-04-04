"""Robust polling loop for the AltoTrader data streaming service.

Fetches Kraken ticker prices every POLL_INTERVAL_SECONDS and writes them to
InfluxDB. Handles network outages and API errors gracefully:

  - Consecutive failures trigger increasing back-off (up to MAX_BACKOFF_SECONDS)
  - A summary of success/failure counts is logged every HEARTBEAT_INTERVAL cycles
  - SIGINT / SIGTERM shut the loop down cleanly

Usage:
    python Examples/run_update_service.py

Environment variables (see env/ for a template):
    INFLUXDB_INIT_BUCKET, INFLUXDB_INIT_ORG, INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN
"""

import signal
import sys
import time
import logging

from altotrader.database.update_service import TickerUpdateService
from altotrader.ticker.krakenticker import KrakenTicker
from altotrader.logging_config import setup_logging

# ── Configuration ─────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 60       # how often to fetch & write prices
MAX_BACKOFF_SECONDS = 300        # cap for back-off on consecutive failures
HEARTBEAT_INTERVAL = 10          # log a heartbeat every N successful cycles
PAIRS_YAML = "Examples/kraken_pairs.yaml"
LOG_DIR = "logs"
# ──────────────────────────────────────────────────────────────────────────────


def _make_shutdown_handler(stop_flag: list):
    """Returns a signal handler that sets stop_flag[0] = True."""
    def handler(signum, frame):
        logging.getLogger(__name__).info(
            f"Received signal {signum}, shutting down gracefully...")
        stop_flag[0] = True
    return handler


def run_update(pair_yaml: str = PAIRS_YAML):
    setup_logging(log_filename='run_update_service.logs', log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)

    ticker = KrakenTicker(pairs_yaml=pair_yaml, log_dir=LOG_DIR)
    service = TickerUpdateService(ticker, log_dir=LOG_DIR)

    stop_flag = [False]
    signal.signal(signal.SIGINT, _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    consecutive_failures = 0
    total_success = 0
    total_failure = 0
    cycle = 0

    logger.info("AltoTrader update service started.")

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
            # Exponential back-off capped at MAX_BACKOFF_SECONDS
            backoff = min(POLL_INTERVAL_SECONDS * (2 ** (consecutive_failures - 1)),
                          MAX_BACKOFF_SECONDS)
            logger.warning(
                f"Update failed (consecutive failures: {consecutive_failures}). "
                f"Backing off for {backoff}s."
            )
            sleep_time = backoff

        if cycle % HEARTBEAT_INTERVAL == 0:
            logger.info(
                f"[Heartbeat] cycle={cycle} | ok={total_success} | fail={total_failure}"
            )

        # Interruptible sleep: check stop_flag every second
        for _ in range(int(sleep_time)):
            if stop_flag[0]:
                break
            time.sleep(1)

    logger.info(
        f"Update service stopped. Total cycles: {cycle} | "
        f"success: {total_success} | failure: {total_failure}"
    )


if __name__ == '__main__':
    pair_yaml = sys.argv[1] if len(sys.argv) > 1 else PAIRS_YAML
    run_update(pair_yaml=pair_yaml)
