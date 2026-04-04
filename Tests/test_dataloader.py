"""Tests for DataLoader: CSV loading, NaN interpolation, and rolling means
for current, ask, and bid price series."""

import pytest
import numpy as np
import pandas as pd
import os
import tempfile

from altotrader.backtest.dataloader import DataLoader


PAIR = "XXBTZEUR"
N_ROWS = 200  # enough for a long rolling window in tests


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_csv_files(tmp_dir: str, n_rows: int = N_ROWS, pair: str = PAIR,
                    introduce_nans: bool = False) -> dict:
    """Write the three CSV files (a, b, c) that DataLoader expects and return
    the loader_dict pointing at them."""

    dates = pd.date_range("2025-01-01", periods=n_rows, freq="1min")
    prices = np.linspace(40_000, 42_000, n_rows)

    for suffix, multiplier in [("a", 1.001), ("b", 0.999), ("c", 1.0)]:
        df = pd.DataFrame(
            {"ticker_entry": suffix, pair: prices * multiplier},
            index=dates,
        )
        df.index.name = "timestamp"
        if introduce_nans and suffix == "c":
            df.iloc[5:8, df.columns.get_loc(pair)] = np.nan
        filename = f"krakenticker_latest_20d_{suffix}.csv"
        df.to_csv(os.path.join(tmp_dir, filename))

    return {"export_path": tmp_dir, "latest_days": 20, "logs_dir": tmp_dir}


# ── load_csv_export ───────────────────────────────────────────────────────────

class TestLoadCsvExport:
    def test_loads_all_three_frames(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)
        loader.load_csv_export()

        assert loader.ticker_current is not None
        assert loader.ticker_ask is not None
        assert loader.ticker_bid is not None

    def test_frames_have_datetime_index(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)
        loader.load_csv_export()

        assert isinstance(loader.ticker_current.index, pd.DatetimeIndex)
        assert isinstance(loader.ticker_ask.index, pd.DatetimeIndex)
        assert isinstance(loader.ticker_bid.index, pd.DatetimeIndex)

    def test_pair_column_present(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)
        loader.load_csv_export()

        assert PAIR in loader.ticker_current.columns
        assert PAIR in loader.ticker_ask.columns
        assert PAIR in loader.ticker_bid.columns

    def test_no_nan_after_load(self, tmp_path):
        config = _make_csv_files(str(tmp_path), introduce_nans=True)
        loader = DataLoader(config)
        loader.load_csv_export()

        assert not loader.ticker_current.isna().any().any()

    def test_ask_higher_than_bid(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)
        loader.load_csv_export()

        assert (loader.ticker_ask[PAIR] > loader.ticker_bid[PAIR]).all()


# ── compute_rolling_means ─────────────────────────────────────────────────────

class TestComputeRollingMeans:
    @pytest.fixture
    def loader(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        dl = DataLoader(config)
        dl.load_csv_export()
        return dl

    def test_all_six_rolling_means_computed(self, loader):
        loader.compute_rolling_means(window_short=10, window_long=50)
        assert loader.rolling_current_short is not None
        assert loader.rolling_current_long  is not None
        assert loader.rolling_ask_short     is not None
        assert loader.rolling_ask_long      is not None
        assert loader.rolling_bid_short     is not None
        assert loader.rolling_bid_long      is not None

    def test_time_based_rolling_has_no_nan(self, loader):
        # pandas time-based rolling windows (e.g. '10min') do not produce a
        # warm-up NaN period – every row has at least itself in the window.
        loader.compute_rolling_means(window_short=10, window_long=50)
        assert loader.rolling_current_short[PAIR].isna().sum() == 0
        assert loader.rolling_current_long[PAIR].isna().sum() == 0

    def test_window_properties_set(self, loader):
        loader.compute_rolling_means(window_short=15, window_long=60)
        assert loader.window_short == 15
        assert loader.window_long  == 60

    def test_short_ma_smoother_than_raw(self, loader):
        loader.compute_rolling_means(window_short=20, window_long=100)
        raw_std = loader.ticker_current[PAIR].std()
        ma_std  = loader.rolling_current_short[PAIR].dropna().std()
        assert ma_std < raw_std

    def test_long_ma_smoother_than_short_ma(self, loader):
        loader.compute_rolling_means(window_short=10, window_long=60)
        short_std = loader.rolling_current_short[PAIR].dropna().std()
        long_std  = loader.rolling_current_long[PAIR].dropna().std()
        assert long_std <= short_std


# ── _iterpolate_nan ───────────────────────────────────────────────────────────

class TestInterpolateNan:
    def test_interpolates_missing_values(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)

        dates = pd.date_range("2025-01-01", periods=10, freq="1min")
        values = pd.Series([1.0, np.nan, np.nan, 4.0, 5.0,
                            6.0, 7.0, 8.0, 9.0, 10.0], index=dates)
        df = pd.DataFrame({"price": values})

        result = loader._iterpolate_nan(df)
        assert not result.isna().any().any()

    def test_no_change_when_no_nans(self, tmp_path):
        config = _make_csv_files(str(tmp_path))
        loader = DataLoader(config)

        dates = pd.date_range("2025-01-01", periods=5, freq="1min")
        df = pd.DataFrame({"price": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=dates)
        original = df.copy()

        result = loader._iterpolate_nan(df)
        pd.testing.assert_frame_equal(result, original)
