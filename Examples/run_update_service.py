"""Robust data streaming service for AltoTrader.

Supports two modes (select via --mode flag or MODE env var):

  rest (default)
      Polls each exchange REST API every POLL_INTERVAL_SECONDS and writes
      results to InfluxDB.

  websocket
      Connects to the exchange WebSocket API for real-time tick data, then
      writes the latest snapshot to InfluxDB every POLL_INTERVAL_SECONDS.
      Only supported for: kraken, binance.

Multiple exchanges run in parallel threads. Each gets its own polling loop
and writes data to InfluxDB under its exchange name as the measurement.

Both modes handle failures gracefully:
  - Consecutive failures trigger increasing back-off (up to MAX_BACKOFF_SECONDS)
  - A heartbeat is logged every HEARTBEAT_INTERVAL cycles
  - SIGINT / SIGTERM shut all loops down cleanly

Supported exchanges (--exchanges / EXCHANGES env var, comma-separated):
    kraken, binance, gemini, coinbase, mexc
    Default: kraken,binance,gemini
    WebSocket mode is only available for kraken and binance.

Usage:
    python Examples/run_update_service.py                                        # default (kraken,binance,gemini REST)
    python Examples/run_update_service.py --exchanges kraken                     # single exchange
    python Examples/run_update_service.py --exchanges kraken,binance --mode websocket
    python Examples/run_update_service.py --exchanges binance --mode websocket

Environment variables (see env/.env.example):
    INFLUXDB_INIT_BUCKET, INFLUXDB_INIT_ORG, INFLUX_URL, INFLUXDB_INIT_ADMIN_TOKEN
    MODE=websocket              (alternative to --mode flag)
    EXCHANGES=kraken,binance    (alternative to --exchanges flag)
"""

import argparse
import logging
import os
import signal
import threading
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
DEFAULT_EXCHANGES = "kraken,binance,gemini"
# ───────────────────────────────────────────────────────────────────────────────


def _make_shutdown_handler(stop_flag: list):
    def handler(signum, frame):
        logging.getLogger(__name__).info(
            f"Received signal {signum} – shutting down gracefully …"
        )
        stop_flag[0] = True
    return handler


def _polling_loop(service: TickerUpdateService, stop_flag: list, exchange: str):
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
                f"[{exchange}] Update failed (consecutive: {consecutive_failures}). "
                f"Backing off {backoff}s."
            )
            sleep_time = backoff

        if cycle % HEARTBEAT_INTERVAL == 0:
            logger.info(
                f"[{exchange}] [Heartbeat] cycle={cycle} | ok={total_success} | fail={total_failure}"
            )

        # Interruptible sleep
        for _ in range(int(sleep_time)):
            if stop_flag[0]:
                break
            time.sleep(1)

    logger.info(
        f"[{exchange}] Service stopped. cycles={cycle} | ok={total_success} | fail={total_failure}"
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


def _run_exchange_rest(exchange: str, pair_yaml: str, stop_flag: list):
    """Thread target: REST polling loop for a single exchange."""
    logger = logging.getLogger(__name__)
    logger.info(f"[{exchange}] Starting REST streaming")
    try:
        ticker  = _make_rest_ticker(exchange, pair_yaml)
        service = TickerUpdateService(ticker, log_dir=LOG_DIR)
        _polling_loop(service, stop_flag, exchange)
    except Exception as exc:
        logger.error(f"[{exchange}] Thread crashed: {exc}", exc_info=True)


def _run_exchange_websocket(exchange: str, pair_yaml: str, stop_flag: list):
    """Thread target: WebSocket polling loop for a single exchange."""
    logger = logging.getLogger(__name__)
    logger.info(f"[{exchange}] Starting WebSocket streaming")
    try:
        with _make_ws_ticker(exchange, pair_yaml) as ticker:
            logger.info(f"[{exchange}] Waiting 3s for initial WebSocket data …")
            time.sleep(3)
            service = TickerUpdateService(ticker, log_dir=LOG_DIR)
            _polling_loop(service, stop_flag, exchange)
    except Exception as exc:
        logger.error(f"[{exchange}] Thread crashed: {exc}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="AltoTrader data streaming service")
    parser.add_argument(
        "--mode",
        choices=["rest", "websocket"],
        default=os.getenv("MODE", "rest"),
        help="Data source mode: 'rest' (default) or 'websocket'",
    )
    parser.add_argument(
        "--exchanges",
        default=os.getenv("EXCHANGES", DEFAULT_EXCHANGES),
        help=f"Comma-separated list of exchanges (default: {DEFAULT_EXCHANGES})",
    )
    parser.add_argument(
        "--pairs",
        default=None,
        help="Path to a single pairs YAML file (only valid when streaming one exchange)",
    )
    args = parser.parse_args()

    exchanges = [e.strip() for e in args.exchanges.split(",") if e.strip()]

    unknown = [e for e in exchanges if e not in EXCHANGE_PAIRS_YAML]
    if unknown:
        parser.error(f"Unknown exchange(s): {unknown}. Choose from: {list(EXCHANGE_PAIRS_YAML)}")

    if args.mode == "websocket":
        unsupported = [e for e in exchanges if e not in WS_EXCHANGES]
        if unsupported:
            parser.error(f"WebSocket not supported for: {unsupported}. Supported: {sorted(WS_EXCHANGES)}")

    if args.pairs and len(exchanges) > 1:
        parser.error("--pairs can only be used when streaming a single exchange")

    setup_logging(log_filename="run_update_service.logs", log_dir=LOG_DIR)
    logger = logging.getLogger(__name__)
    logger.info(f"Starting AltoTrader [mode: {args.mode}, exchanges: {exchanges}]")

    stop_flag = [False]
    signal.signal(signal.SIGINT,  _make_shutdown_handler(stop_flag))
    signal.signal(signal.SIGTERM, _make_shutdown_handler(stop_flag))

    run_fn = _run_exchange_websocket if args.mode == "websocket" else _run_exchange_rest

    if len(exchanges) == 1:
        pair_yaml = args.pairs or EXCHANGE_PAIRS_YAML[exchanges[0]]
        run_fn(exchanges[0], pair_yaml, stop_flag)
    else:
        threads = []
        for exchange in exchanges:
            pair_yaml = EXCHANGE_PAIRS_YAML[exchange]
            t = threading.Thread(
                target=run_fn,
                args=(exchange, pair_yaml, stop_flag),
                name=f"streamer-{exchange}",
                daemon=False,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()


if __name__ == "__main__":
    main()
