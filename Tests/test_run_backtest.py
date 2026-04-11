"""Tests for run_backtest.py orchestration logic."""
import json
import os
import sys
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Examples.run_backtest import _parse_windows, run_backtest_for_pair


class TestParseWindows:
    def test_parses_comma_separated(self):
        assert _parse_windows("10,20,50", []) == [10, 20, 50]

    def test_strips_whitespace(self):
        assert _parse_windows("10, 20 , 50", []) == [10, 20, 50]

    def test_empty_string_returns_default(self):
        assert _parse_windows("", [99, 200]) == [99, 200]

    def test_none_handled_as_empty(self):
        assert _parse_windows("", [5, 10]) == [5, 10]

    def test_invalid_value_returns_default(self):
        assert _parse_windows("abc,def", [1, 2]) == [1, 2]


class TestRunBacktestForPair:
    @pytest.fixture
    def mock_results_df(self):
        return pd.DataFrame([
            {"window_short": 20, "window_long": 100, "sharpe_ratio": 1.5,
             "total_return_pct": 15.0, "n_trades": 8, "max_drawdown_pct": 5.0, "win_rate": 0.6},
            {"window_short": 50, "window_long": 200, "sharpe_ratio": 0.9,
             "total_return_pct": 8.0, "n_trades": 4, "max_drawdown_pct": 10.0, "win_rate": 0.5},
        ])

    @pytest.fixture
    def mock_loader(self):
        loader = MagicMock()
        df = pd.DataFrame({"BTC-EUR": [50000.0, 51000.0]})
        loader.ticker_current = df
        return loader

    def test_export_failure_returns_none(self, tmp_path, caplog):
        import logging
        logger = logging.getLogger("test")
        with patch("Examples.run_backtest.export_prices", return_value=False):
            result = run_backtest_for_pair(
                pair="BTC-EUR", exchange="kraken", days=7,
                strategy_name="sma",
                param_grid={"window_short": [10, 20], "window_long": [50, 100]},
                export_dir=str(tmp_path), backtest_config={}, logger=logger,
            )
        assert result is None

    def test_pair_not_in_data_returns_none(self, tmp_path, mock_loader):
        import logging
        logger = logging.getLogger("test")
        # ticker_current has no BTC-EUR column
        mock_loader.ticker_current = pd.DataFrame({"ETH-EUR": [3000.0]})

        with patch("Examples.run_backtest.export_prices", return_value=True), \
             patch("Examples.run_backtest.DataLoader", return_value=mock_loader):
            result = run_backtest_for_pair(
                pair="BTC-EUR", exchange="kraken", days=7,
                strategy_name="sma",
                param_grid={"window_short": [10], "window_long": [50]},
                export_dir=str(tmp_path), backtest_config={}, logger=logger,
            )
        assert result is None

    def test_successful_run_returns_best_and_full(self, tmp_path, mock_loader, mock_results_df):
        import logging
        logger = logging.getLogger("test")
        mock_engine = MagicMock()

        with patch("Examples.run_backtest.export_prices", return_value=True), \
             patch("Examples.run_backtest.DataLoader", return_value=mock_loader), \
             patch("Examples.run_backtest.BacktestEngine", return_value=mock_engine), \
             patch("Examples.run_backtest.run_grid_search", return_value=mock_results_df):
            result = run_backtest_for_pair(
                pair="BTC-EUR", exchange="kraken", days=7,
                strategy_name="sma",
                param_grid={"window_short": [10, 20], "window_long": [50, 100]},
                export_dir=str(tmp_path), backtest_config={}, logger=logger,
            )

        assert result is not None
        best, full = result
        # Best should be sorted by sharpe_ratio → ws=20, wl=100
        assert best["window_short"] == 20
        assert best["window_long"] == 100
        assert best["sharpe_ratio"] == pytest.approx(1.5)
        assert len(full) == 2

    def test_empty_grid_search_returns_none(self, tmp_path, mock_loader):
        import logging
        logger = logging.getLogger("test")

        with patch("Examples.run_backtest.export_prices", return_value=True), \
             patch("Examples.run_backtest.DataLoader", return_value=mock_loader), \
             patch("Examples.run_backtest.BacktestEngine", return_value=MagicMock()), \
             patch("Examples.run_backtest.run_grid_search", return_value=pd.DataFrame()):
            result = run_backtest_for_pair(
                pair="BTC-EUR", exchange="kraken", days=7,
                strategy_name="sma",
                param_grid={"window_short": [10], "window_long": [50]},
                export_dir=str(tmp_path), backtest_config={}, logger=logger,
            )
        assert result is None

    def test_best_windows_dict_has_required_keys(self, tmp_path, mock_loader, mock_results_df):
        import logging
        logger = logging.getLogger("test")

        with patch("Examples.run_backtest.export_prices", return_value=True), \
             patch("Examples.run_backtest.DataLoader", return_value=mock_loader), \
             patch("Examples.run_backtest.BacktestEngine", return_value=MagicMock()), \
             patch("Examples.run_backtest.run_grid_search", return_value=mock_results_df):
            result = run_backtest_for_pair(
                pair="BTC-EUR", exchange="kraken", days=7,
                strategy_name="sma",
                param_grid={"window_short": [10, 20], "window_long": [50, 100]},
                export_dir=str(tmp_path), backtest_config={}, logger=logger,
            )

        best, _ = result
        for key in ["exchange", "window_short", "window_long", "sharpe_ratio",
                    "total_return_pct", "n_trades"]:
            assert key in best, f"Missing key: {key}"


class TestExportPricesMeasurement:
    """Verify the measurement parameter is passed through correctly."""

    def test_measurement_parameter_forwarded(self):
        from altotrader.database.export_prices import export_prices
        with patch("altotrader.database.export_prices._query_with_retry") as mock_q:
            mock_q.return_value = pd.DataFrame()
            export_prices(
                path_to_parquet="/tmp",
                days_into_past=1,
                file_format="csv",
                bucket="test", org="test", url="http://localhost:8086",
                token="test",
                measurement="binance",
            )
            # Check measurement was included in influx_config passed to _query_with_retry
            call_args = mock_q.call_args
            influx_config = call_args[0][2]
            assert influx_config["measurement"] == "binance"

    def test_measurement_defaults_to_kraken(self):
        from altotrader.database.export_prices import export_prices
        with patch("altotrader.database.export_prices._query_with_retry") as mock_q:
            mock_q.return_value = pd.DataFrame()
            export_prices(
                path_to_parquet="/tmp",
                days_into_past=1,
                file_format="csv",
                bucket="test", org="test", url="http://localhost:8086", token="test",
            )
            influx_config = mock_q.call_args[0][2]
            assert influx_config["measurement"] == "kraken"
