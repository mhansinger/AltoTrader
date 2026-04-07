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
        self.ticker_volume = None

        self.rolling_ask_short = self.rolling_ask_long = None
        self.rolling_bid_short = self.rolling_bid_long = None
        self.rolling_current_short = self.rolling_current_long = None

        self._window_long: int = None
        self._window_short: int = None

        # TODO: update config

    def load_csv_export(self) -> None:
        """Load CSV exports for ask, bid, and current price.

        Supports two config modes:

        **Single source** (backward compatible)::

            {
                "export_path": "exports/kraken",
                "file_prefix": "kraken",   # default: "krakenticker"
                "latest_days": 30,
            }

        **Multiple sources** – useful when streaming from different exchange
        buckets.  All sources are loaded and merged column-wise (outer join
        on the time index, then NaN-interpolated)::

            {
                "export_sources": [
                    {"export_path": "exports/kraken",  "file_prefix": "kraken",  "latest_days": 30},
                    {"export_path": "exports/binance", "file_prefix": "binance", "latest_days": 30},
                ],
            }
        """
        self.logger.info('loading exported csv files')

        # Build a list of (export_path, prefix, days) tuples
        sources = self.config_dict.get('export_sources')
        if sources:
            # Multi-source mode
            source_list = [
                (s['export_path'],
                 s.get('file_prefix', 'krakenticker'),
                 s.get('latest_days', self.config_dict.get('latest_days', 30)))
                for s in sources
            ]
        else:
            # Single-source mode (backward compatible)
            source_list = [(
                self.config_dict.get('export_path'),
                self.config_dict.get('file_prefix', 'krakenticker'),
                self.config_dict.get('latest_days', 30),
            )]

        def load_source(export_path: str, prefix: str, days: int, suffix: str) -> pd.DataFrame:
            path = join(export_path, f"{prefix}_latest_{days}d_{suffix}.csv")
            self.logger.debug(f"Loading: {path}")
            df = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])
            df = df.sort_index()
            if 'ticker_entry' in df.columns:
                df = df.drop('ticker_entry', axis=1)
            return df.resample("1min").mean()

        def load_and_merge(suffix: str) -> pd.DataFrame:
            frames = []
            for export_path, prefix, days in source_list:
                try:
                    frames.append(load_source(export_path, prefix, days, suffix))
                except FileNotFoundError as e:
                    self.logger.warning(f"File not found, skipping source: {e}")
            if not frames:
                raise RuntimeError(
                    f"No CSV files could be loaded for suffix '{suffix}'. "
                    "Check export_path and file_prefix in your config."
                )
            if len(frames) == 1:
                return frames[0]
            # Outer-join on time index; duplicate pair columns are averaged
            combined = pd.concat(frames, axis=1)
            # Group duplicate column names and take the mean
            merged = combined.T.groupby(level=0).mean().T
            n_sources = len(frames)
            n_pairs   = len(merged.columns)
            self.logger.info(
                f"Merged {n_sources} source(s) for suffix='{suffix}': "
                f"{n_pairs} unique pair(s) total"
            )
            return merged

        self.ticker_ask     = load_and_merge("a")
        self.ticker_bid     = load_and_merge("b")
        self.ticker_current = load_and_merge("c")

        # Volume is optional – tolerate missing files gracefully
        try:
            self.ticker_volume = load_and_merge("v")
        except RuntimeError:
            self.logger.info(
                "No volume ('v') CSV files found – ticker_volume will be None. "
                "Re-export from InfluxDB to include volume data."
            )
            self.ticker_volume = None

        # fill NaN if any
        self.ticker_ask = self._iterpolate_nan(self.ticker_ask)
        self.ticker_bid = self._iterpolate_nan(self.ticker_bid)
        self.ticker_current = self._iterpolate_nan(self.ticker_current)
        if self.ticker_volume is not None:
            self.ticker_volume = self._iterpolate_nan(self.ticker_volume)

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
            self.load_csv_export()  # also loads ticker_volume if available

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
        """check if NaN in df. If so, log details and interpolate linearly."""
        assert type(df.index) == pd.core.indexes.datetimes.DatetimeIndex

        if df.isna().any().any():
            total_nans = int(df.isna().sum().sum())
            for col in df.columns:
                col_nans = df[col].isna()
                if not col_nans.any():
                    continue
                n = int(col_nans.sum())
                # Find contiguous NaN blocks
                groups = (col_nans != col_nans.shift()).cumsum()
                blocks = [
                    (g.index[0], g.index[-1])
                    for _, g in col_nans.groupby(groups)
                    if g.all()
                ]
                block_str = ", ".join(f"{s} → {e}" for s, e in blocks[:5])
                if len(blocks) > 5:
                    block_str += f" … (+{len(blocks) - 5} more)"
                self.logger.warning(
                    f"Column '{col}': {n} NaN(s) in {len(blocks)} block(s): {block_str}"
                )
            self.logger.info(
                f"Interpolating {total_nans} NaN value(s) across {df.shape[1]} column(s)"
            )
            df = df.interpolate(method='time')

        return df

    def check_gaps(self, expected_freq: str = "1min", warn_threshold: int = 5) -> dict:
        """Detect time-series gaps in the loaded ticker data.

        A gap is any interval between consecutive timestamps that is larger
        than *expected_freq*.  This is useful to detect periods where the
        data streaming service was down.

        Args:
            expected_freq:   Expected minimum interval between rows, as a
                             pandas offset string (default: '1min').
            warn_threshold:  Log a WARNING (instead of DEBUG) for gaps longer
                             than this many multiples of *expected_freq*.

        Returns:
            dict with keys 'current', 'ask', 'bid', each containing a list of
            (start_timestamp, end_timestamp, gap_minutes) tuples.

        Raises:
            RuntimeError: if load_csv_export() has not been called yet.
        """
        if self.ticker_current is None:
            raise RuntimeError("No data loaded – call load_csv_export() first.")

        freq_td = pd.tseries.frequencies.to_offset(expected_freq)
        results = {}

        for name, df in [("current", self.ticker_current),
                          ("ask",     self.ticker_ask),
                          ("bid",     self.ticker_bid)]:
            gaps = []
            idx = df.index
            deltas = idx[1:] - idx[:-1]
            for i, delta in enumerate(deltas):
                if delta > freq_td:
                    gap_mins = delta.total_seconds() / 60
                    entry = (idx[i], idx[i + 1], round(gap_mins, 1))
                    gaps.append(entry)
                    multiples = delta / freq_td
                    msg = (
                        f"Gap in {name!r} data: {idx[i]} → {idx[i+1]} "
                        f"({gap_mins:.1f} min)"
                    )
                    if multiples >= warn_threshold:
                        self.logger.warning(msg)
                    else:
                        self.logger.debug(msg)

            results[name] = gaps
            self.logger.info(
                f"Gap check [{name}]: {len(gaps)} gap(s) found "
                f"(threshold: {expected_freq})"
            )

        return results

    @property
    def window_long(self):
        return self._window_long

    @property
    def window_short(self):
        return self._window_short


if __name__ == '__main__':

    my_dict = {
        'export_path': "Examples/ticker_export",
        "latest_days": 20,
        "file_prefix": "altotrader",  # must match InfluxDB bucket name
        "logs_dir":    'logs',
    }
    testloader = DataLoader(my_dict)
    testloader.load_csv_export()
    testloader.compute_rolling_means(window_short=50, window_long=200)
