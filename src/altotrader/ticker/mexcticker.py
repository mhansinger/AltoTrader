"""MEXC REST ticker.

MEXC's v3 API is largely compatible with Binance's API format.
This ticker combines two lightweight endpoints:
  - ``/api/v3/ticker/price``      → last price per symbol
  - ``/api/v3/ticker/bookTicker`` → best bid/ask per symbol

Both endpoints return data for all symbols when called without parameters,
so we make only two requests per polling cycle regardless of how many pairs
are configured.

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
        """Fetch last price + best bid/ask for all configured pairs.

        Uses two bulk requests (price + bookTicker) and filters to the
        configured pair list.

        Returns:
            Normalised dict ``{unified_pair: {c, a, b}}``.
        """
        try:
            reverse = self._exchange_to_unified_map()  # BTCUSDT → BTC-USDT

            price_data = self._get(f"{_BASE_URL}/ticker/price")
            book_data  = self._get(f"{_BASE_URL}/ticker/bookTicker")

            # Build lookup maps  {exchange_symbol → value}
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
            for ex_sym, unified in reverse.items():
                if ex_sym not in price_map or ex_sym not in book_map:
                    self.logger.warning(f"MEXC: no data for pair '{unified}' ({ex_sym})")
                    continue
                result[unified] = {
                    "c": price_map[ex_sym],
                    "a": book_map[ex_sym]["a"],
                    "b": book_map[ex_sym]["b"],
                }
                self.logger.debug(
                    f"{unified}: last={price_map[ex_sym]} "
                    f"ask={book_map[ex_sym]['a']} bid={book_map[ex_sym]['b']}"
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
