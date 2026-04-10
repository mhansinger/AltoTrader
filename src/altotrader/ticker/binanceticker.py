"""Binance REST ticker.

Uses the public ``/api/v3/ticker/24hr`` endpoint which returns last price,
ask, and bid for all symbols without authentication.

Pair format: ``BTC-EUR``, ``ETH-BTC``, ``SOL-USDT`` …
(unified hyphen-separated format; converted to ``BTCEUR`` internally)
"""
from __future__ import annotations

import json
from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.binance.com/api/v3"


class BinanceTicker(RestBaseTicker):
    """Fetches spot ticker data from the Binance REST API."""

    EXCHANGE = "binance"

    # _to_exchange_pair() inherited default: "BTC-EUR" → "BTCEUR" ✓

    def get_market_query(self) -> Dict:
        """Fetch 24-hour ticker stats for all configured pairs.

        Tries a single batch request first. If Binance rejects it (e.g. one
        invalid symbol causes a 400), falls back to individual requests so that
        valid pairs are still collected.

        Returns:
            Normalised dict ``{unified_pair: {c, a, b, v}}``
        """
        exchange_pairs = [self._to_exchange_pair(p) for p in self.pairs_list]
        reverse        = self._exchange_to_unified_map()

        try:
            params = {"symbols": json.dumps(exchange_pairs, separators=(",", ":"))}
            data   = self._get(f"{_BASE_URL}/ticker/24hr", params=params)
            if isinstance(data, dict):
                data = [data]
            result = self._parse(data, reverse)
        except Exception as exc:
            self.logger.warning(
                f"Binance batch request failed ({exc}), falling back to individual requests"
            )
            result = self._fetch_individually(exchange_pairs, reverse)

        if result:
            self.timestamp_last_fetch = self.current_timestamp()
        else:
            self.logger.warning("Binance returned no data for any pair")
        return result

    def _parse(self, data: list, reverse: Dict) -> Dict:
        result: Dict = {}
        for item in data:
            unified = reverse.get(item["symbol"])
            if unified is None:
                continue
            result[unified] = {
                "c": float(item["lastPrice"]),
                "a": float(item["askPrice"]),
                "b": float(item["bidPrice"]),
                "v": float(item.get("volume", 0.0)),
            }
        return result

    def _fetch_individually(self, exchange_pairs: list, reverse: Dict) -> Dict:
        result: Dict = {}
        for ex_sym in exchange_pairs:
            try:
                data = self._get(f"{_BASE_URL}/ticker/24hr", params={"symbol": ex_sym})
                if isinstance(data, dict):
                    data = [data]
                result.update(self._parse(data, reverse))
            except Exception as exc:
                # Extract HTTP status code if available, otherwise show full error
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                reason = f"HTTP {status}" if status else str(exc).split("\n")[0]
                self.logger.warning(f"Binance: skipping {ex_sym} – {reason}")
        return result


if __name__ == "__main__":
    import time

    ticker = BinanceTicker(pairs_yaml="Examples/binance_pairs.yaml")
    while True:
        mq = ticker.get_market_query()
        for entry in ("c", "a", "b", "v"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
