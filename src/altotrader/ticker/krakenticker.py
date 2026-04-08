import pandas as pd
import numpy as np
import krakenex
import time
import os
import logging
from typing import Dict, List
import datetime

from altotrader.logging_config import setup_logging
from altotrader.ticker.baseticker import BaseTicker

# ── Unified pair → Kraken REST pair mapping ───────────────────────────────────
# Add new pairs here as needed.
KRAKEN_UNIFIED_TO_REST: Dict[str, str] = {
    "BTC-EUR":  "XXBTZEUR",
    "ETH-EUR":  "XETHZEUR",
    "ETH-BTC":  "XETHXXBT",
    "SOL-EUR":  "SOLZEUR",
    "SOL-BTC":  "SOLXBT",
    "ADA-EUR":  "ADAZEUR",
    "ADA-BTC":  "ADAXBT",
    "LINK-EUR": "LINKZEUR",
    "LINK-BTC": "LINKXBT",
    "XRP-EUR":  "XXRPZEUR",
    "XRP-BTC":  "XXRPXXBT",
    "DOT-EUR":  "DOTZEUR",
    "DOT-BTC":  "DOTXBT",
}

# Reverse: Kraken REST pair → unified
_REST_TO_UNIFIED: Dict[str, str] = {v: k for k, v in KRAKEN_UNIFIED_TO_REST.items()}


class KrakenTicker(BaseTicker):
    EXCHANGE = "kraken"

    def __init__(self, pairs_yaml: str, log_dir: str = 'logs'):
        """
        Object streamt über krakenex.API die aktuellen Marktpreise.

        Pairs in the YAML must use the unified 'BTC-EUR' format.
        """

        self.timestamp = None
        self.k = krakenex.API()
        self.pairs_list = self.load_yaml(pairs_yaml)
        self._timestamp_last_fetch: datetime.datetime = None

        setup_logging(log_filename='krakenticker.logs', log_dir=log_dir)

        self.logger = logging.getLogger(__name__)

        # Warn about pairs not in the mapping
        for pair in self.pairs_list:
            if pair not in KRAKEN_UNIFIED_TO_REST:
                self.logger.warning(
                    f"No Kraken REST mapping for '{pair}'. "
                    "Add it to KRAKEN_UNIFIED_TO_REST in krakenticker.py."
                )

        self.logger.info(
            f"Instantiated KrakenTicker with pairs: {self.pairs_list}")

    def get_market_query(self) -> dict:
        """Fetch all Kraken ticker data and return it keyed by unified pair names.

        The raw Kraken response uses list fields (e.g. ``c[0]`` = last price,
        ``v[1]`` = 24 h rolling volume).  Volume is normalised so that index 0
        always holds the 24 h value, consistent with how other entries are read.

        Returns:
            ``{"BTC-EUR": {"c": [...], "a": [...], "b": [...], "v": [...]}, ...}``
        """
        try:
            response = self.k.query_public("Ticker")
            self.timestamp_last_fetch = self.current_timestamp()
            raw = response.get("result", {})

            # Translate Kraken REST keys to unified pair names
            result = {}
            for rest_key, data in raw.items():
                unified = _REST_TO_UNIFIED.get(rest_key)
                if unified is not None:
                    entry = dict(data)
                    # Normalise volume: Kraken v = [today, 24h] – expose 24 h at index 0 as float
                    if "v" in entry and isinstance(entry["v"], list) and len(entry["v"]) >= 2:
                        entry["v"] = [float(entry["v"][1])]
                    result[unified] = entry

            return result
        except Exception as e:
            self.logger.error(f"Error fetching market result: {e}")
            return {}

    def get_last_ticker(self, ticker_entry: str, market_query: dict = None) -> pd.DataFrame:
        """Fetches the latest ticker prices for the trading pairs as a DataFrame.

        Args:
            ticker_entry (str): only accepts c -> close, a -> ask, b -> bid
            market_query (dict): inject from self.get_market_query()

        Returns:
            pd.DataFrame: ticker values with timestamp index, columns = unified pairs
        """

        self.logger.debug(f"ticker_entry: {ticker_entry}")

        valid_entries = {"c", "a", "b", "v"}
        if ticker_entry not in valid_entries:
            self.logger.error(
                f"Invalid ticker_entry '{ticker_entry}'. Must be one of {valid_entries}.")
            raise ValueError(
                f"Invalid ticker_entry '{ticker_entry}'. Must be one of {valid_entries}.")

        market_prices = []

        try:
            if market_query is None:
                market_query = self.get_market_query()

            if not isinstance(market_query, dict):
                self.logger.error(
                    f"Invalid market query response: {market_query}")
                return pd.DataFrame()

            timestamp_now = self.timestamp_last_fetch

            for pair in self.pairs_list:
                pair_data   = market_query.get(pair, {})
                pair_ticker = pair_data.get(ticker_entry, [])

                if (
                    not pair_ticker
                    or not isinstance(pair_ticker, list)
                    or len(pair_ticker) < 1
                ):
                    self.logger.error(
                        f"Missing or invalid ticker data for {pair}: "
                        f"{pair_data} on {ticker_entry}"
                    )
                    continue

                current_price = float(pair_ticker[0])

                market_prices.append(
                    {"timestamp": timestamp_now, "pair": pair, "price": current_price}
                )
                self.logger.debug(f"{pair} -> {current_price}")

            if not market_prices:
                self.logger.warning("No valid market prices found.")
                return pd.DataFrame(columns=["pair", "price"]).set_index(
                    pd.to_datetime([])
                )

            df = pd.DataFrame(market_prices, columns=[
                              "timestamp", "pair", "price"])

            df = df.pivot(index="timestamp", columns="pair", values="price")

            return df

        except Exception as e:
            self.logger.exception(f"Error fetching market prices: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    myTicker = KrakenTicker(
        pairs_yaml="Examples/kraken_pairs.yaml", log_dir='logs')
    while True:
        market_query = myTicker.get_market_query()
        myTicker.get_last_ticker(ticker_entry='c', market_query=market_query)
        myTicker.get_last_ticker(ticker_entry='a', market_query=market_query)
        time.sleep(60)
