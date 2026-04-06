"""Binance REST ticker.

Uses the public ``/api/v3/ticker/24hr`` endpoint which returns last price,
ask, and bid for all symbols without authentication.

Pair format: ``BTCEUR``, ``ETHBTC``, ``SOLUSDT`` …
(Binance spot symbol convention – uppercase, no separator)
"""
from __future__ import annotations

import json
from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.binance.com/api/v3"


class BinanceTicker(RestBaseTicker):
    """Fetches spot ticker data from the Binance REST API."""

    EXCHANGE = "binance"

    def get_market_query(self) -> Dict:
        """Fetch 24-hour ticker stats for all configured pairs.

        Returns:
            Normalised dict ``{symbol: {c, a, b}}``.
        """
        try:
            params: dict = {}
            if self.pairs_list:
                params["symbols"] = json.dumps(self.pairs_list)

            data = self._get(f"{_BASE_URL}/ticker/24hr", params=params)
            if isinstance(data, dict):
                data = [data]   # single-symbol response is a plain dict

            result: Dict = {}
            for item in data:
                sym = item["symbol"]
                if sym not in self.pairs_list:
                    continue
                result[sym] = {
                    "c": float(item["lastPrice"]),
                    "a": float(item["askPrice"]),
                    "b": float(item["bidPrice"]),
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
        for entry in ("c", "a", "b"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
