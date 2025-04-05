import pandas as pd
import numpy as np
import krakenex
import time
import os
import logging
from typing import List
import datetime
import yaml

from altotrader.logging_config import setup_logging
from altotrader.ticker.baseticker import BaseTicker

# Set up logging configuration
setup_logging()

# Create a logger for this module
logger = logging.getLogger(__name__)


class KrakenTicker(BaseTicker):
    def __init__(self, pairs_yaml: str):
        """
        Object streamt über krakenex.API die aktuellen Marktpreise
        """

        self.timestamp = None
        self.k = krakenex.API()
        self.pairs_list = self.load_yaml(pairs_yaml)

        logger.info(
            f"Instatiated KrakenTicker with asset pairs: {self.pairs_list}")

    def get_market_query(self) -> dict:
        try:
            response = self.k.query_public("Ticker")
            return response.get("result", {})
        except Exception as e:
            print(f"Error fetching market result: {e}")
            return {}

    def get_market_price(self) -> pd.DataFrame:
        """Fetches the latest market prices for the trading pairs as a DataFrame."""

        market_prices = []

        try:
            market_query = self.get_market_query()
            if not isinstance(market_query, dict):
                logger.error(f"Invalid market query response: {market_query}")
                return pd.DataFrame()  # Return empty DataFrame if invalid response

            timestamp_now = pd.to_datetime(self.current_timestamp())

            for pair in self.pairs_list:
                pair_data = market_query.get(pair, {})
                pair_ticker = pair_data.get("c", [])

                if (
                    not pair_ticker
                    or not isinstance(pair_ticker, list)
                    or len(pair_ticker) < 1
                ):
                    logger.error(
                        f"Missing or invalid price data for {pair}: {pair_data}"
                    )
                    continue

                current_price = float(pair_ticker[0])

                market_prices.append(
                    {"timestamp": timestamp_now, "pair": pair, "price": current_price}
                )
                logger.info(f"{pair} -> {current_price}")

            if not market_prices:
                logger.warning("No valid market prices found.")
                return pd.DataFrame(columns=["pair", "price"]).set_index(
                    pd.to_datetime([])
                )

            df = pd.DataFrame(market_prices, columns=[
                              "timestamp", "pair", "price"])

            df = df.pivot(index="timestamp", columns="pair", values="price")

            return df

        except Exception as e:
            logger.exception(f"Error fetching market prices: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    myTicker = KrakenTicker(pairs_yaml="Examples/kraken_pairs.yaml")
    while True:
        myTicker.get_market_price()
        time.sleep(60)
