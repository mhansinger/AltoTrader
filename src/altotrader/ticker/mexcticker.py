"""MEXC REST ticker.

MEXC's v3 API is largely compatible with Binance's API format.
Uses the ``/api/v3/ticker/24hr`` endpoint which returns last price,
ask, bid, and 24 h volume in a single request.

Pair format: ``BTC-USDT``, ``ETH-BTC``, ``SOL-USDT`` …
(unified hyphen-separated format; converted to ``BTCUSDT`` internally)
"""
from __future__ import annotations

from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.mexc.com/api/v3"


class MEXCTicker(RestBaseTicker):
    """Fetches spot ticker data from the MEXC REST API."""

    EXCHANGE = "mexc"

    # _to_exchange_pair() inherited default: "BTC-USDT" → "BTCUSDT" ✓

    def get_market_query(self) -> Dict:
        """Fetch last price, bid/ask, and 24 h volume for all configured pairs.

        Uses a single bulk request to ``/ticker/24hr`` which provides all
        fields (last price, ask, bid, volume) in one call.

        Returns:
            Normalised dict ``{unified_pair: {c, a, b, v}}``.
        """
        try:
            reverse = self._exchange_to_unified_map()  # BTCUSDT → BTC-USDT

            ticker_data = self._get(f"{_BASE_URL}/ticker/24hr")
            if isinstance(ticker_data, dict):
                ticker_data = [ticker_data]  # single-symbol response

            result: Dict = {}
            for item in (ticker_data if isinstance(ticker_data, list) else []):
                ex_sym  = item.get("symbol", "")
                unified = reverse.get(ex_sym)
                if unified is None:
                    continue
                result[unified] = {
                    "c": float(item["lastPrice"]),
                    "a": float(item["askPrice"]),
                    "b": float(item["bidPrice"]),
                    "v": float(item.get("volume", 0.0)),  # 24 h base-asset volume
                }
                self.logger.debug(
                    f"{unified}: last={item['lastPrice']} ask={item['askPrice']} "
                    f"bid={item['bidPrice']} vol={item.get('volume', 0)}"
                )

            if result:
                self.timestamp_last_fetch = self.current_timestamp()
            else:
                self.logger.error("MEXC returned no data for any configured pair")

            return result

        except Exception as exc:
            self.logger.error(f"MEXC market query failed: {exc}")
            return {}


if __name__ == "__main__":
    import time

    ticker = MEXCTicker(pairs_yaml="Examples/mexc_pairs.yaml")
    while True:
        mq = ticker.get_market_query()
        for entry in ("c", "a", "b", "v"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
