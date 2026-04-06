"""Gemini REST ticker.

Uses the public ``/v1/pubticker/{symbol}`` endpoint – no authentication
required.  One HTTP request is made per trading pair.

Pair format: ``BTC-EUR``, ``ETH-USD``, ``ETH-BTC`` …
(unified hyphen-separated format; converted to lowercase ``btceur`` internally)
"""
from __future__ import annotations

from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.gemini.com/v1"


class GeminiTicker(RestBaseTicker):
    """Fetches spot ticker data from the Gemini REST API."""

    EXCHANGE = "gemini"

    def _to_exchange_pair(self, pair: str) -> str:
        """Gemini uses lowercase, no-separator symbols: ``BTC-EUR`` → ``btceur``."""
        return pair.replace("-", "").lower()

    def get_market_query(self) -> Dict:
        """Fetch ticker for every configured pair (one request each).

        Returns:
            Normalised dict ``{unified_pair: {c, a, b}}``
            (keys are the original YAML pair names, e.g. ``'BTC-EUR'``).
        """
        result: Dict = {}

        for pair in self.pairs_list:
            try:
                ex_sym = self._to_exchange_pair(pair)   # btceur
                data   = self._get(f"{_BASE_URL}/pubticker/{ex_sym}")
                result[pair] = {
                    "c": float(data["last"]),
                    "a": float(data["ask"]),
                    "b": float(data["bid"]),
                }
                self.logger.debug(
                    f"{pair}: last={data['last']} ask={data['ask']} bid={data['bid']}"
                )
            except Exception as exc:
                self.logger.warning(f"Gemini fetch failed for '{pair}': {exc}")

        if result:
            self.timestamp_last_fetch = self.current_timestamp()
        else:
            self.logger.error("Gemini returned no data for any pair")

        return result


if __name__ == "__main__":
    import time

    ticker = GeminiTicker(pairs_yaml="Examples/gemini_pairs.yaml")
    while True:
        mq = ticker.get_market_query()
        for entry in ("c", "a", "b"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
