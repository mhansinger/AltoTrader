"""Coinbase Exchange (formerly Coinbase Pro) REST ticker.

Uses the public ``/products/{product_id}/ticker`` endpoint – no authentication
required.  One HTTP request is made per trading pair.

Pair format: ``BTC-EUR``, ``ETH-BTC``, ``SOL-USD`` …
(Coinbase already uses hyphen-separated pairs, so no conversion is needed)
"""
from __future__ import annotations

from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.exchange.coinbase.com"


class CoinbaseTicker(RestBaseTicker):
    """Fetches spot ticker data from the Coinbase Exchange REST API."""

    EXCHANGE = "coinbase"

    def _to_exchange_pair(self, pair: str) -> str:
        """Coinbase natively uses the unified 'BTC-EUR' format – no conversion."""
        return pair

    def get_market_query(self) -> Dict:
        """Fetch ticker for every configured pair (one request each).

        Returns:
            Normalised dict ``{unified_pair: {c, a, b}}``.
        """
        result: Dict = {}

        for pair in self.pairs_list:
            try:
                data = self._get(f"{_BASE_URL}/products/{pair}/ticker")
                result[pair] = {
                    "c": float(data["price"]),
                    "a": float(data["ask"]),
                    "b": float(data["bid"]),
                    "v": float(data.get("volume", 0.0)),  # 24 h base-asset volume
                }
                self.logger.debug(
                    f"{pair}: last={data['price']} ask={data['ask']} bid={data['bid']} "
                    f"vol={data.get('volume', 0)}"
                )
            except Exception as exc:
                self.logger.warning(f"Coinbase fetch failed for '{pair}': {exc}")

        if result:
            self.timestamp_last_fetch = self.current_timestamp()
        else:
            self.logger.error("Coinbase returned no data for any pair")

        return result


if __name__ == "__main__":
    import time

    ticker = CoinbaseTicker(pairs_yaml="Examples/coinbase_pairs.yaml")
    while True:
        mq = ticker.get_market_query()
        for entry in ("c", "a", "b", "v"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
