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
                    introduce_nans: bool = False, include_volume: bool = True) -> dict:
    """Write CSV files (a, b, c, and optionally v) that DataLoader expects."""

    dates = pd.date_range("2025-01-01", periods=n_rows, freq="1min")
    prices = np.linspace(40_000, 42_000, n_rows)

    suffixes = [("a", 1.001), ("b", 0.999), ("c", 1.0)]
    if include_volume:
        # Simulate 24 h volume (e.g. BTC amounts, ranging 1–10)
        volume = np.linspace(1.0, 10.0, n_rows)
        suffixes.append(("v", None))

    for item in suffixes:
        suffix, multiplier = item
        if suffix == "v":
            values = volume
        else:
            values = prices * multiplier
        df = pd.DataFrame(
            {"ticker_entry": suffix, pair: values},
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

class TestMultiSource:
    """DataLoader with export_sources list (multiple exchange buckets)."""

    def _make_source(self, tmp_dir, prefix, pair, n_rows=50):
        """Write CSV files for one exchange bucket into tmp_dir."""
        dates  = pd.date_range("2025-01-01", periods=n_rows, freq="1min")
        prices = np.linspace(40_000, 42_000, n_rows)
        os.makedirs(tmp_dir, exist_ok=True)
        for suffix, mult in [("a", 1.001), ("b", 0.999), ("c", 1.0)]:
            df = pd.DataFrame({pair: prices * mult}, index=dates)
            df.index.name = "timestamp"
            df.to_csv(os.path.join(tmp_dir, f"{prefix}_latest_20d_{suffix}.csv"))

    def test_loads_two_sources_and_merges_columns(self, tmp_path):
        kraken_dir  = str(tmp_path / "kraken")
        binance_dir = str(tmp_path / "binance")
        self._make_source(kraken_dir,  "kraken",  "BTC-EUR")
        self._make_source(binance_dir, "binance", "ETH-BTC")

        config = {
            "export_sources": [
                {"export_path": kraken_dir,  "file_prefix": "kraken",  "latest_days": 20},
                {"export_path": binance_dir, "file_prefix": "binance", "latest_days": 20},
            ],
            "logs_dir": str(tmp_path),
        }
        loader = DataLoader(config)
        loader.load_csv_export()

        # Both pairs must appear as columns
        assert "BTC-EUR" in loader.ticker_current.columns
        assert "ETH-BTC" in loader.ticker_current.columns

    def test_same_pair_two_sources_combined(self, tmp_path):
        """Two sources with the same pair – columns deduplicated by pandas join."""
        dir_a = str(tmp_path / "a")
        dir_b = str(tmp_path / "b")
        self._make_source(dir_a, "src_a", "BTC-EUR")
        self._make_source(dir_b, "src_b", "BTC-EUR")

        config = {
            "export_sources": [
                {"export_path": dir_a, "file_prefix": "src_a", "latest_days": 20},
                {"export_path": dir_b, "file_prefix": "src_b", "latest_days": 20},
            ],
            "logs_dir": str(tmp_path),
        }
        loader = DataLoader(config)
        loader.load_csv_export()
        assert loader.ticker_current is not None

    def test_missing_source_warns_but_loads_rest(self, tmp_path):
        """A missing file in one source should not crash – others still load."""
        good_dir = str(tmp_path / "good")
        self._make_source(good_dir, "good", "BTC-EUR")

        config = {
            "export_sources": [
                {"export_path": good_dir,              "file_prefix": "good",    "latest_days": 20},
                {"export_path": str(tmp_path / "bad"), "file_prefix": "missing", "latest_days": 20},
            ],
            "logs_dir": str(tmp_path),
        }
        loader = DataLoader(config)
        loader.load_csv_export()
        assert "BTC-EUR" in loader.ticker_current.columns

    def test_single_source_via_export_sources(self, tmp_path):
        """export_sources with one entry behaves identically to single-source mode."""
        d = str(tmp_path / "kraken")
        self._make_source(d, "kraken", "BTC-EUR")
        config = {
            "export_sources": [
                {"export_path": d, "file_prefix": "kraken", "latest_days": 20},
            ],
            "logs_dir": str(tmp_path),
        }
        loader = DataLoader(config)
        loader.load_csv_export()
        assert "BTC-EUR" in loader.ticker_current.columns


class TestVolumeLoader:
    """DataLoader correctly loads and exposes ticker_volume when v CSV exists."""

    def test_ticker_volume_loaded(self, tmp_path):
        config = _make_csv_files(str(tmp_path), include_volume=True)
        loader = DataLoader(config)
        loader.load_csv_export()
        assert loader.ticker_volume is not None
        assert PAIR in loader.ticker_volume.columns

    def test_ticker_volume_no_nans(self, tmp_path):
        config = _make_csv_files(str(tmp_path), include_volume=True)
        loader = DataLoader(config)
        loader.load_csv_export()
        assert not loader.ticker_volume.isna().any().any()

    def test_ticker_volume_none_when_missing(self, tmp_path):
        """If no volume CSV exists, ticker_volume should be None (not an error)."""
        config = _make_csv_files(str(tmp_path), include_volume=False)
        loader = DataLoader(config)
        loader.load_csv_export()
        assert loader.ticker_volume is None

    def test_ticker_volume_values_increase(self, tmp_path):
        """Volume values should match the monotonically increasing test data."""
        config = _make_csv_files(str(tmp_path), include_volume=True)
        loader = DataLoader(config)
        loader.load_csv_export()
        # First value < last value (linspace 1→10)
        assert loader.ticker_volume[PAIR].iloc[0] < loader.ticker_volume[PAIR].iloc[-1]


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
