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

        Returns:
            Normalised dict ``{unified_pair: {c, a, b}}``
            (e.g. ``{"BTC-EUR": {"c": 60000.0, "a": 60010.0, "b": 59990.0}}``).
        """
        try:
            exchange_pairs = [self._to_exchange_pair(p) for p in self.pairs_list]
            reverse        = self._exchange_to_unified_map()  # BTCEUR → BTC-EUR

            params: dict = {}
            if exchange_pairs:
                params["symbols"] = json.dumps(exchange_pairs)

            data = self._get(f"{_BASE_URL}/ticker/24hr", params=params)
            if isinstance(data, dict):
                data = [data]   # single-symbol response is a plain dict

            result: Dict = {}
            for item in data:
                ex_sym   = item["symbol"]
                unified  = reverse.get(ex_sym)
                if unified is None:
                    continue
                result[unified] = {
                    "c": float(item["lastPrice"]),
                    "a": float(item["askPrice"]),
                    "b": float(item["bidPrice"]),
                    "v": float(item.get("volume", 0.0)),  # 24 h base-asset volume
                }

            if result:
                self.timestamp_last_fetch = self.current_timestamp()
            else:
                self.logger.warning("Binance returned no data for requested pairs")

            return result

        except Exception as exc:
            self.logger.error(f"Binance market query failed: {exc}")
            return {}


if __name__ == "__main__":
    import time

    ticker = BinanceTicker(pairs_yaml="Examples/binance_pairs.yaml")
    while True:
        mq = ticker.get_market_query()
        for entry in ("c", "a", "b", "v"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
