"""Binance WebSocket ticker – real-time price streaming via Binance WS Streams.

Replaces :class:`BinanceTicker` (REST polling) for live data collection.
Runs the WebSocket in a background thread so it integrates transparently
with the existing synchronous :class:`TickerUpdateService`.

Protocol summary
----------------
- Combined stream URL (no subscription message needed):
  ``wss://stream.binance.com:9443/stream?streams=btceur@ticker/ethbtc@ticker``
- Each update is wrapped: ``{"stream": "btceur@ticker", "data": {...}}``
- Data payload (``24hrTicker`` event) includes:

  ============ =============================
  Field        Meaning
  ============ =============================
  ``s``        Symbol (uppercase, e.g. BTCEUR)
  ``c``        Last trade price
  ``a``        Best ask price
  ``b``        Best bid price
  ============ =============================

- Server sends a WebSocket ping frame every 20 s; ``websocket-client``
  replies with a pong automatically so no extra code is required.
- Connections are forcibly closed by Binance after 24 hours.  This class
  reconnects proactively after 23.5 hours and also on any error.

Requirements
------------
    pip install websocket-client

Usage
-----
    from altotrader.ticker.binance_ws_ticker import BinanceWsTicker

    ticker = BinanceWsTicker(pairs_yaml="Examples/binance_pairs.yaml")
    ticker.start()
    ...
    ticker.stop()

Or as a context manager::

    with BinanceWsTicker(pairs_yaml="Examples/binance_pairs.yaml") as ticker:
        service = TickerUpdateService(ticker)
        service.update_pairs_ticker(...)

Pair format
-----------
Pairs in the YAML file must use Binance's uppercase convention (e.g.
``BTCEUR``, ``ETHBTC``, ``SOLUSDT``).  The ticker converts them to
lowercase stream names internally.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict, Optional

from altotrader.logging_config import setup_logging
from altotrader.ticker.rest_base_ticker import RestBaseTicker

_WS_BASE          = "wss://stream.binance.com:9443"
_RECONNECT_DELAY  = 5           # seconds between reconnect attempts
_PING_INTERVAL    = 20          # Binance spec: server pings every 20 s
_PING_TIMEOUT     = 10          # seconds to wait for pong before disconnect
_MAX_SESSION_SEC  = 23.5 * 3600 # reconnect before Binance's 24 h forced close


class BinanceWsTicker(RestBaseTicker):
    """Real-time ticker via Binance WebSocket combined stream.

    Extends :class:`RestBaseTicker` so that :meth:`get_last_ticker` is
    inherited and works out-of-the-box once :meth:`get_market_query`
    provides the cached price snapshot.

    Thread-safe: the price cache is protected by a ``threading.Lock``.
    """

    EXCHANGE = "binance_ws"

    def __init__(self, pairs_yaml: str, log_dir: str = "logs"):
        super().__init__(pairs_yaml, log_dir)

        # Price cache: {SYMBOL (uppercase): {c, a, b}}
        self._prices: Dict[str, Dict[str, float]] = {}
        self._lock   = threading.Lock()

        self._ws    = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event   = threading.Event()
        self._connected_at: Optional[float] = None  # monotonic time

        # Binance stream names are lowercase (e.g. "btceur@ticker")
        self._stream_names = [f"{p.lower()}@ticker" for p in self.pairs_list]

        self.logger.info(
            f"BinanceWsTicker initialised | streams: {self._stream_names}"
        )

    # ── WebSocket URL ─────────────────────────────────────────────────────────

    def _ws_url(self) -> str:
        """Build combined stream URL from configured pairs."""
        streams = "/".join(self._stream_names)
        return f"{_WS_BASE}/stream?streams={streams}"

    # ── Public control interface ──────────────────────────────────────────────

    def start(self) -> None:
        """Connect and start the background WebSocket thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_forever, daemon=True, name="BinanceWsThread"
        )
        self._thread.start()
        self.logger.info("BinanceWsTicker thread started.")

    def stop(self) -> None:
        """Signal the background thread to disconnect and exit."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=10)
        self.logger.info("BinanceWsTicker thread stopped.")

    # ── BaseTicker / RestBaseTicker interface override ────────────────────────

    def get_market_query(self) -> dict:
        """Return latest cached prices as a normalised dict.

        Format (same as :class:`BinanceTicker`)::

            {
                "BTCEUR": {"c": 60000.0, "a": 60010.0, "b": 59990.0},
                ...
            }

        Returns an empty dict if no data has been received from the stream yet.
        """
        with self._lock:
            if not self._prices:
                self.logger.warning("BinanceWsTicker: no data yet – is start() called?")
                return {}
            snapshot = {sym: dict(prices) for sym, prices in self._prices.items()}

        self.timestamp_last_fetch = self.current_timestamp()
        return snapshot

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "BinanceWsTicker":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()

    # ── WebSocket internals ───────────────────────────────────────────────────

    def _run_forever(self) -> None:
        """Reconnect loop – runs inside the daemon thread."""
        try:
            import websocket
        except ImportError:
            self.logger.error(
                "websocket-client is required. Install with: pip install websocket-client"
            )
            return

        while not self._stop_event.is_set():
            url = self._ws_url()
            self.logger.info(f"Connecting to {url} …")
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open    = self._on_open,
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(
                    ping_interval = _PING_INTERVAL,
                    ping_timeout  = _PING_TIMEOUT,
                )
            except Exception as exc:
                self.logger.error(f"WebSocket exception: {exc}")

            if not self._stop_event.is_set():
                self.logger.info(f"Reconnecting in {_RECONNECT_DELAY}s …")
                time.sleep(_RECONNECT_DELAY)

    def _on_open(self, ws) -> None:
        self._connected_at = time.monotonic()
        self.logger.info("Connected to Binance WebSocket stream.")

    def _on_message(self, ws, message: str) -> None:
        # Proactive reconnect before Binance's 24 h forced close
        if (
            self._connected_at is not None
            and time.monotonic() - self._connected_at > _MAX_SESSION_SEC
        ):
            self.logger.info("Session approaching 24 h limit – reconnecting proactively …")
            ws.close()
            return

        try:
            outer = json.loads(message)

            # Combined stream: {"stream": "btceur@ticker", "data": {...}}
            if not isinstance(outer, dict) or "data" not in outer:
                return

            tick = outer["data"]

            if tick.get("e") != "24hrTicker":
                return

            symbol = tick.get("s", "")
            if symbol not in self.pairs_list:
                return

            # Parse the three price fields
            try:
                c = float(tick["c"])   # last price
                a = float(tick["a"])   # best ask
                b = float(tick["b"])   # best bid
            except (KeyError, ValueError, TypeError) as exc:
                self.logger.warning(f"Price parse error for {symbol}: {exc}")
                return

            # Sanity checks
            if c <= 0 or a <= 0 or b <= 0:
                self.logger.warning(
                    f"Non-positive price(s) for {symbol}: "
                    f"c={c}, a={a}, b={b}. Skipping."
                )
                return
            if a < b:
                self.logger.warning(
                    f"Crossed market for {symbol}: ask ({a}) < bid ({b}). Skipping."
                )
                return

            with self._lock:
                self._prices[symbol] = {"c": c, "a": a, "b": b}

            self.logger.debug(f"Tick {symbol}: c={c}, a={a}, b={b}")

        except Exception as exc:
            self.logger.error(
                f"Unexpected error parsing WS message: {exc} | raw: {message[:200]}"
            )

    def _on_error(self, ws, error) -> None:
        self.logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self.logger.info(f"WebSocket closed: {close_status_code} – {close_msg}")


if __name__ == "__main__":
    ticker = BinanceWsTicker(pairs_yaml="Examples/binance_pairs.yaml")
    with ticker:
        print("Streaming … press Ctrl+C to stop")
        while True:
            time.sleep(5)
            q = ticker.get_market_query()
            for sym, prices in q.items():
                print(f"  {sym}: last={prices['c']:.4f}  ask={prices['a']:.4f}  bid={prices['b']:.4f}")
