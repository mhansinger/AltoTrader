
import pandas as pd
import numpy as np
import krakenex
import time
import os
import logging
from typing import List
import datetime

from altotrader.logging_config import setup_logging

# Set up logging configuration
setup_logging()

# Create a logger for this module
logger = logging.getLogger(__name__)


class KrakenTicker(object):
    def __init__(self, asset1: str, asset2: str):
        '''
        Object streamt über krakenex.API die aktuellen Marktpreise
        :param asset1: 'XETH'
        :param asset2: 'XXBT'
        '''

        # TODO: read pairs form config file

        self.asset1: str = asset1
        self.asset2: str = asset2
        self.timestamp = None
        self.k = krakenex.API()
        self.pair = asset1 + asset2
        # TODO: needed?
        self.columns = ['Time', 'Price']
        self.history = pd.DataFrame(
            [np.zeros(len(self.columns))], columns=self.columns)

        logger.info(
            f"Instatiated KrakenTicker with asset1->{self.asset1} and asset2->{self.asset2}")

        # try:
        #     # checks if the series.csv is already existing, if so it reads it in
        #     if (os.path.exists(self.pair + '_Series.csv')):
        #         df_old = pd.read_csv(self.pair + '_Series.csv')
        #         df_old = df_old.drop('Unnamed: 0', 1)
        #         self.history = df_old
        #     else:
        #         self.history = pd.DataFrame(
        #             [np.zeros(len(self.columns))], columns=self.columns)
        # except:
        #     print('sometihngs wrong wiht your time series...')

    def current_timestamp(self) -> datetime:
        timestamp = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return timestamp

    def get_market_price(self) -> float | None:
        """Fetches the latest market price for the trading pair."""
        try:
            # TODO: get several pairs for one query
            market_query = self.k.query_public('Ticker', {'pair': self.pair})

            # Check if response contains 'error' field with any errors
            if 'error' in market_query and market_query['error']:
                logger.error(
                    f"Kraken API returned an error: {market_query['error']}")
                return None

            # Validate that expected keys exist
            if 'result' not in market_query or self.pair not in market_query['result']:
                logger.error(
                    f"Unexpected API response structure: {market_query}")
                return None

            # Extract last trade price
            pair_ticker = market_query['result'][self.pair].get('c', [])
            if not pair_ticker or not isinstance(pair_ticker, list) or len(pair_ticker) < 1:
                logger.error(
                    f"Missing or invalid price data in response: {market_query}")
                return None

            current_price = pair_ticker[0]  # First element is the latest price
            timestamp_now = self.current_timestamp()

            logger.info(f"{self.pair} @ {timestamp_now} -> {current_price}")
            return float(current_price)

        except Exception as e:
            logger.exception(f"Error fetching market price: {e}")
            return None

    # def updateHist(self):
    #     thisPrice = self.market_price()
    #     time = time.strftime("%m.%d.%y_%H:%M:%S", time.localtime())
    #     temp = [[time, thisPrice]]
    #     temp_df = pd.DataFrame(temp, columns=self.columns)
    #     self.history = self.history.append(temp_df)
    #     print(temp_df)
    #     # time.sleep(59)
    #     # self.iterations += 1

    # def writeHist(self):
    #     pd.DataFrame.to_csv(self.history, self.pair + '_Series.csv')


if __name__ == "__main__":
    myTicker = KrakenTicker(asset1="XETH", asset2="ZEUR")
    myTicker.get_market_price()
