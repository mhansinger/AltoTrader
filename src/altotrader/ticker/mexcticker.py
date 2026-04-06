"""MEXC REST ticker.

MEXC's v3 API is largely compatible with Binance's API format.
This ticker combines two lightweight endpoints:
  - ``/api/v3/ticker/price``      → last price per symbol
  - ``/api/v3/ticker/bookTicker`` → best bid/ask per symbol

Both endpoints return data for all symbols when called without parameters,
so we make only two requests per polling cycle regardless of how many pairs
are configured.

Pair format: ``BTCUSDT``, ``ETHBTC``, ``SOLUSDT`` …
(MEXC uppercase, no separator – same convention as Binance)
"""
from __future__ import annotations

from typing import Dict

from altotrader.ticker.rest_base_ticker import RestBaseTicker

_BASE_URL = "https://api.mexc.com/api/v3"


class MEXCTicker(RestBaseTicker):
    """Fetches spot ticker data from the MEXC REST API."""

    EXCHANGE = "mexc"

    def get_market_query(self) -> Dict:
        """Fetch last price + best bid/ask for all configured pairs.

        Uses two bulk requests (price + bookTicker) and filters to the
        configured pair list.

        Returns:
            Normalised dict ``{symbol: {c, a, b}}``.
        """
        try:
            price_data = self._get(f"{_BASE_URL}/ticker/price")
            book_data  = self._get(f"{_BASE_URL}/ticker/bookTicker")

            # Build lookup maps  {symbol → value}
            price_map: Dict[str, float] = {}
            for item in (price_data if isinstance(price_data, list) else [price_data]):
                price_map[item["symbol"]] = float(item["price"])

            book_map: Dict[str, Dict] = {}
            for item in (book_data if isinstance(book_data, list) else [book_data]):
                book_map[item["symbol"]] = {
                    "a": float(item["askPrice"]),
                    "b": float(item["bidPrice"]),
                }

            result: Dict = {}
            for pair in self.pairs_list:
                if pair not in price_map or pair not in book_map:
                    self.logger.warning(f"MEXC: no data for pair '{pair}'")
                    continue
                result[pair] = {
                    "c": price_map[pair],
                    "a": book_map[pair]["a"],
                    "b": book_map[pair]["b"],
                }
                self.logger.debug(
                    f"{pair}: last={price_map[pair]} "
                    f"ask={book_map[pair]['a']} bid={book_map[pair]['b']}"
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
        for entry in ("c", "a", "b"):
            print(ticker.get_last_ticker(ticker_entry=entry, market_query=mq))
        time.sleep(60)
