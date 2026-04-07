"""Kraken WebSocket ticker – real-time price streaming via Kraken WS API v1.

Replaces the REST-polling KrakenTicker for live data collection.  Runs the
WebSocket in a background thread so it integrates with the existing synchronous
TickerUpdateService without any changes.

Requirements
------------
    pip install websocket-client

Usage
-----
    from altotrader.ticker.kraken_ws_ticker import KrakenWsTicker
    ticker = KrakenWsTicker(pairs_yaml="Examples/kraken_pairs.yaml")
    ticker.start()          # connect and start background thread
    ...
    ticker.stop()           # graceful shutdown

Or use it as a context manager:

    with KrakenWsTicker(pairs_yaml="Examples/kraken_pairs.yaml") as ticker:
        service = TickerUpdateService(ticker)
        service.update_pairs_ticker(...)

Pair format
-----------
Pairs in the YAML file use the unified hyphen-separated convention (e.g.
``BTC-EUR``, ``ETH-BTC``).  The ticker converts them to Kraken's WS format
(``XBT/EUR``, ``ETH/XBT``) automatically via *PAIR_MAP*.  Add any missing
mappings to PAIR_MAP as needed.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from altotrader.logging_config import setup_logging
from altotrader.ticker.baseticker import BaseTicker

# ── Unified pair → Kraken WS pair name mapping ────────────────────────────────
# Add new pairs here as needed.
PAIR_MAP: Dict[str, str] = {
    "BTC-EUR":  "XBT/EUR",
    "ETH-EUR":  "ETH/EUR",
    "ETH-BTC":  "ETH/XBT",
    "SOL-EUR":  "SOL/EUR",
    "SOL-BTC":  "SOL/XBT",
    "ADA-EUR":  "ADA/EUR",
    "ADA-BTC":  "ADA/XBT",
    "LINK-EUR": "LINK/EUR",
    "LINK-BTC": "LINK/XBT",
    "XRP-EUR":  "XRP/EUR",
    "XRP-BTC":  "XRP/XBT",
    "DOT-EUR":  "DOT/EUR",
    "DOT-BTC":  "DOT/XBT",
}
# Reverse mapping: WS name → unified pair name
_WS_TO_UNIFIED: Dict[str, str] = {v: k for k, v in PAIR_MAP.items()}

_WS_URL = "wss://ws.kraken.com"
_RECONNECT_DELAY = 5   # seconds between reconnect attempts
_PING_INTERVAL   = 30  # seconds between keepalive pings


class KrakenWsTicker(BaseTicker):
    """Real-time ticker via Kraken WebSocket API.

    Thread-safe: prices are stored in a dict updated by the WS thread and read
    by the main thread (via get_market_query / get_last_ticker).
    """

    def __init__(self, pairs_yaml: str, log_dir: str = "logs"):
        self.pairs_list = self.load_yaml(pairs_yaml)
        self._timestamp_last_fetch: Optional[datetime] = None

        setup_logging(log_filename="kraken_ws_ticker.logs", log_dir=log_dir)
        self.logger = logging.getLogger(__name__)

        # Latest prices keyed by WS pair name
        self._prices: Dict[str, Dict[str, float]] = {}  # {ws_pair: {c, a, b, v}}
        self._lock = threading.Lock()

        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Build WS subscription list (skip unmapped pairs with a warning)
        self._ws_pairs = []
        for rest_pair in self.pairs_list:
            ws_pair = PAIR_MAP.get(rest_pair)
            if ws_pair:
                self._ws_pairs.append(ws_pair)
            else:
                self.logger.warning(
                    f"No WS mapping for REST pair {rest_pair!r}. "
                    "Add it to PAIR_MAP in kraken_ws_ticker.py."
                )

        self.logger.info(
            f"KrakenWsTicker initialised | pairs: {self._ws_pairs}"
        )

    # ── Public interface (compatible with BaseTicker / TickerUpdateService) ───

    def start(self):
        """Connect and start the background WebSocket thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_forever, daemon=True, name="KrakenWsThread"
        )
        self._thread.start()
        self.logger.info("WebSocket thread started.")

    def stop(self):
        """Signal the background thread to disconnect and exit."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=10)
        self.logger.info("WebSocket thread stopped.")

    def get_market_query(self) -> dict:
        """Return latest cached prices keyed by unified pair name.

        Returns a dict keyed by unified pair name (e.g. 'BTC-EUR'), with
        sub-dicts for c/a/b/v (list format for KrakenTicker compatibility).
        Returns an empty dict if no data has been received yet.
        """
        with self._lock:
            result = {}
            for ws_pair, prices in self._prices.items():
                unified = _WS_TO_UNIFIED.get(ws_pair)
                if unified:
                    result[unified] = {
                        "c": [prices.get("c", 0.0)],
                        "a": [prices.get("a", 0.0)],
                        "b": [prices.get("b", 0.0)],
                        "v": [prices.get("v", 0.0)],  # 24 h rolling volume
                    }
            if result:
                self.timestamp_last_fetch = self.current_timestamp()
            return result

    def get_last_ticker(self, ticker_entry: str, market_query: dict = None) -> pd.DataFrame:
        """Return a one-row DataFrame with the latest prices (same as KrakenTicker)."""
        valid_entries = {"c", "a", "b", "v"}
        if ticker_entry not in valid_entries:
            raise ValueError(f"ticker_entry must be one of {valid_entries}")

        if market_query is None:
            market_query = self.get_market_query()

        if not market_query:
            self.logger.warning("No WebSocket data available yet.")
            return pd.DataFrame()

        rows = []
        ts = self.timestamp_last_fetch or self.current_timestamp()
        for rest_pair, data in market_query.items():
            price = data.get(ticker_entry, [None])[0]
            if price is not None:
                rows.append({"timestamp": ts, "pair": rest_pair, "price": float(price)})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).pivot(index="timestamp", columns="pair", values="price")
        return df

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # ── WebSocket internals ───────────────────────────────────────────────────

    def _run_forever(self):
        """Reconnect loop – runs in the background thread."""
        try:
            import websocket
        except ImportError:
            self.logger.error(
                "websocket-client is required for WebSocket streaming. "
                "Install it with: pip install websocket-client"
            )
            return

        while not self._stop_event.is_set():
            self.logger.info(f"Connecting to {_WS_URL} …")
            try:
                self._ws = websocket.WebSocketApp(
                    _WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=_PING_INTERVAL)
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")

            if not self._stop_event.is_set():
                self.logger.info(f"Reconnecting in {_RECONNECT_DELAY}s …")
                time.sleep(_RECONNECT_DELAY)

    def _on_open(self, ws):
        self.logger.info("WebSocket connected. Subscribing to ticker …")
        subscribe_msg = json.dumps({
            "event": "subscribe",
            "pair": self._ws_pairs,
            "subscription": {"name": "ticker"},
        })
        ws.send(subscribe_msg)

    def _on_message(self, ws, message: str):
        try:
            data = json.loads(message)

            # Subscription confirmations and heartbeats are dicts
            if isinstance(data, dict):
                event = data.get("event", "")
                if event == "heartbeat":
                    self.logger.debug("Heartbeat received.")
                elif event in ("subscriptionStatus", "systemStatus"):
                    self.logger.debug(f"WS event: {data}")
                return

            # Ticker updates are arrays: [channelID, {ticker_data}, "ticker", "XBT/EUR"]
            if not isinstance(data, list) or len(data) < 4:
                return
            if data[2] != "ticker":
                return

            ws_pair   = data[3]
            tick_data = data[1]

            # Validate required price fields before parsing
            required_fields = ("c", "a", "b")
            if not isinstance(tick_data, dict) or not all(
                k in tick_data and tick_data[k] for k in required_fields
            ):
                self.logger.warning(
                    f"Incomplete tick data for {ws_pair}: "
                    f"missing/empty fields. Raw: {str(tick_data)[:200]}"
                )
                return

            try:
                close_price = float(tick_data["c"][0])
                ask_price   = float(tick_data["a"][0])
                bid_price   = float(tick_data["b"][0])
                # v = [volume_today, volume_24h]; take the 24 h rolling value
                v_raw    = tick_data.get("v", [0.0, 0.0])
                volume   = float(v_raw[1]) if len(v_raw) >= 2 else float(v_raw[0])
            except (ValueError, TypeError, IndexError) as exc:
                self.logger.warning(
                    f"Could not parse tick prices for {ws_pair}: {exc}"
                )
                return

            # Sanity checks
            if close_price <= 0 or ask_price <= 0 or bid_price <= 0:
                self.logger.warning(
                    f"Non-positive price(s) for {ws_pair}: "
                    f"c={close_price}, a={ask_price}, b={bid_price}. Skipping."
                )
                return
            if ask_price < bid_price:
                self.logger.warning(
                    f"Crossed market for {ws_pair}: "
                    f"ask ({ask_price}) < bid ({bid_price}). Skipping."
                )
                return

            # Store close, ask, bid, and 24 h volume
            with self._lock:
                self._prices[ws_pair] = {
                    "c": close_price,
                    "a": ask_price,
                    "b": bid_price,
                    "v": volume,
                }
            self.logger.debug(f"Tick {ws_pair}: {self._prices[ws_pair]}")

        except Exception as e:
            self.logger.error(f"Error parsing WS message: {e} | raw: {message[:200]}")

    def _on_error(self, ws, error):
        self.logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.info(f"WebSocket closed: {close_status_code} {close_msg}")


if __name__ == "__main__":
    import time as _time

    ticker = KrakenWsTicker(pairs_yaml="Examples/kraken_pairs.yaml")
    with ticker:
        print("Streaming for 30 seconds …")
        for _ in range(30):
            _time.sleep(1)
            q = ticker.get_market_query()
            if q:
                pair = next(iter(q))
                print(f"  {pair}: close={q[pair]['c'][0]:.2f}")
