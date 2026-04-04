import numpy as np
import pandas as pd
import os
from os.path import join
from pathlib import Path
from altotrader.logging_config import setup_logging
import logging


class DataLoader:
    def __init__(self, config_dict: dict):
        self.config_dict = config_dict

        setup_logging(log_filename='dataloader.logs',
                      log_dir=self.config_dict.get('logs_dir'))

        self.logger = logging.getLogger(__name__)

        self.ticker_current = None
        self.ticker_ask = None
        self.ticker_bid = None

        self.rolling_ask_short = self.rolling_ask_long = None
        self.rolling_bid_short = self.rolling_bid_long = None
        self.rolling_current_short = self.rolling_current_long = None

        self._window_long: int = None
        self._window_short: int = None

        # TODO: update config

    def load_csv_export(self) -> pd.DataFrame:
        """reads in CSV exports for ask, bid, current price"""
        self.logger.info('loading exported csv files')

        export_path = self.config_dict.get('export_path')
        days = self.config_dict.get('latest_days')

        def load_and_resample(suffix: str) -> pd.DataFrame:
            path = join(
                export_path, f"krakenticker_latest_{days}d_{suffix}.csv")
            self.logger.debug(f"Loading: {path}")
            df = pd.read_csv(path, index_col="timestamp",
                             parse_dates=["timestamp"])
            df = df.sort_index()
            df = df.drop('ticker_entry', axis=1)

            return df.resample("1min").mean()

        self.ticker_ask = load_and_resample("a")
        self.ticker_bid = load_and_resample("b")
        self.ticker_current = load_and_resample("c")

        # fill NaN if any
        self.ticker_ask = self._iterpolate_nan(self.ticker_ask)
        self.ticker_bid = self._iterpolate_nan(self.ticker_bid)
        self.ticker_current = self._iterpolate_nan(self.ticker_current)

    def compute_rolling_means(self, window_short: int, window_long: int) -> None:
        """computes the rolling means for ask, bid, current dataframes with short and long
        widnow width.

        Args:
            window_short (int): window in mins
            window_long (int): window in mins
        """

        self.logger.info(
            f"Updating rolling means with short {window_short} and long {window_long} windows")

        self._window_long = window_long
        self._window_short = window_short

        if self.ticker_current is None or self.ticker_ask is None or self.ticker_bid is None:
            self.load_csv_export()

        self.rolling_ask_short = self.ticker_ask.rolling(
            f'{window_short}min').mean()
        self.rolling_bid_short = self.ticker_bid.rolling(
            f'{window_short}min').mean()
        self.rolling_current_short = self.ticker_current.rolling(
            f'{window_short}min').mean()

        self.rolling_ask_long = self.ticker_ask.rolling(
            f'{window_long}min').mean()
        self.rolling_bid_long = self.ticker_bid.rolling(
            f'{window_long}min').mean()
        self.rolling_current_long = self.ticker_current.rolling(
            f'{window_long}min').mean()

    def _iterpolate_nan(self, df: pd.DataFrame) -> pd.DataFrame:
        """check if NaN in df. If so, interpolate linearly"""
        assert type(df.index) == pd.core.indexes.datetimes.DatetimeIndex

        if df.isna().any().any():
            df = df.interpolate(method='time')
            self.logger.info(f"NaNs are interpolated")

        return df

    @property
    def window_long(self):
        return self._window_long

    @property
    def window_short(self):
        return self._window_short


if __name__ == '__main__':

    my_dict = {'export_path': "Examples/ticker_export",
               "latest_days": 20, "logs_dir": 'logs'}
    testloader = DataLoader(my_dict)
    testloader.load_csv_export()
    testloader.compute_rolling_means(window_short=50, window_long=200)
