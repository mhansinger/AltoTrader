"""Tests for the pluggable strategy framework.

Covers:
* BaseStrategy interface contract
* Strategy registry (get_strategy, AVAILABLE_STRATEGIES)
* BacktestEngine.run_strategy() + run_strategy_grid_search()
* Each concrete strategy: ImprovedMACrossover, MomentumStrategy, BollingerRSIStrategy
"""

import numpy as np
import pandas as pd
import pytest

from altotrader.backtest.strategies import (
    get_strategy,
    AVAILABLE_STRATEGIES,
    ImprovedMACrossover,
    MomentumStrategy,
    BollingerRSIStrategy,
)
from altotrader.backtest.strategies.base import BaseStrategy


# ── Shared mock infrastructure ────────────────────────────────────────────────

PAIR = "BTC-EUR"
BASE = "EUR"
TRADING = "BTC"

BACKTEST_CONFIG = {
    "maker_fee":        0.0025,
    "taker_fee":        0.004,
    "initial_invest":   1000.0,
    "base_currency":    BASE,
    "trading_currency": TRADING,
}


class _MockDataLoader:
    """Minimal DataLoader stand-in – no CSV files required."""

    def __init__(self, pair: str, prices: np.ndarray, volume: np.ndarray = None):
        n     = len(prices)
        dates = pd.date_range("2025-01-01", periods=n, freq="1min")

        self.ticker_current = pd.DataFrame({pair: prices},          index=dates)
        self.ticker_ask     = pd.DataFrame({pair: prices * 1.001},  index=dates)
        self.ticker_bid     = pd.DataFrame({pair: prices * 0.999},  index=dates)

        if volume is not None:
            self.ticker_volume = pd.DataFrame({pair: volume}, index=dates)
        else:
            self.ticker_volume = None

        self.rolling_current_short = None
        self.rolling_current_long  = None

    def load_csv_export(self):
        pass

    def compute_rolling_means(self, window_short: int, window_long: int):
        self.rolling_current_short = self.ticker_current.rolling(
            f"{window_short}min").mean()
        self.rolling_current_long = self.ticker_current.rolling(
            f"{window_long}min").mean()


def _make_engine(prices: np.ndarray, volume: np.ndarray = None):
    from altotrader.backtest.backtest_engine import BacktestEngine
    loader = _MockDataLoader(PAIR, prices, volume=volume)
    return BacktestEngine(loader, BACKTEST_CONFIG)


def _trending_prices(n=500):
    """Smooth uptrend: good for EMA golden-cross and momentum entries."""
    return np.linspace(30_000, 50_000, n)


def _ranging_prices(n=500):
    """Oscillating prices: good for mean-reversion entries."""
    t = np.linspace(0, 8 * np.pi, n)
    return 40_000 + 2_000 * np.sin(t)


def _volatile_ranging(n=600):
    """Wide swings around a mean: ideal for Bollinger/RSI."""
    t = np.linspace(0, 10 * np.pi, n)
    return 40_000 + 3_000 * np.sin(t) + np.random.default_rng(42).normal(0, 100, n)


# ── Registry tests ────────────────────────────────────────────────────────────

class TestRegistry:
    def test_available_strategies_not_empty(self):
        assert len(AVAILABLE_STRATEGIES) >= 3

    def test_get_strategy_returns_instance(self):
        for name in AVAILABLE_STRATEGIES:
            s = get_strategy(name)
            assert isinstance(s, BaseStrategy)

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            get_strategy("nonexistent_strategy_xyz")

    def test_each_strategy_has_name(self):
        for name in AVAILABLE_STRATEGIES:
            s = get_strategy(name)
            assert isinstance(s.name, str) and len(s.name) > 0

    def test_registry_returns_fresh_instance_each_call(self):
        s1 = get_strategy("ema")
        s2 = get_strategy("ema")
        assert s1 is not s2


# ── BacktestEngine.run_strategy() ─────────────────────────────────────────────

class TestRunStrategy:
    def test_returns_metrics_dict(self):
        engine = _make_engine(_trending_prices(400))
        metrics = engine.run_strategy(get_strategy("ema"), ema_short=10, ema_long=30)
        assert isinstance(metrics, dict)
        assert "total_return_pct" in metrics

    def test_metrics_keys_match_compute_metrics(self):
        engine   = _make_engine(_trending_prices(400))
        metrics  = engine.run_strategy(get_strategy("ema"), ema_short=10, ema_long=30)
        expected = {
            "total_return_pct", "buy_and_hold_return_pct", "n_trades",
            "win_rate", "max_drawdown_pct", "max_drawdown_duration_hrs",
            "sharpe_ratio", "total_fees", "taker_fees", "maker_fees",
            "final_portfolio_value",
        }
        assert expected.issubset(metrics.keys())

    def test_state_reset_between_runs(self):
        engine  = _make_engine(_trending_prices(400))
        strat   = get_strategy("ema")
        m1 = engine.run_strategy(strat, ema_short=10, ema_long=30)
        m2 = engine.run_strategy(strat, ema_short=10, ema_long=30)
        assert m1["total_return_pct"] == pytest.approx(m2["total_return_pct"])

    def test_position_force_closed_at_end(self):
        """Permanently rising prices → position entered but never death-crossed."""
        engine = _make_engine(_trending_prices(400))
        engine.run_strategy(get_strategy("ema"), ema_short=10, ema_long=30,
                            trend_filter=False)
        assert engine.portfolio_view["market_position"].iloc[-1] == "out"

    def test_different_strategies_give_different_results(self):
        prices = _volatile_ranging(600)
        e1 = _make_engine(prices)
        e2 = _make_engine(prices)
        m_ema  = e1.run_strategy(get_strategy("ema"),          ema_short=10, ema_long=30, trend_filter=False)
        m_brsi = e2.run_strategy(get_strategy("bollinger_rsi"), bb_period=30, rsi_period=14, trend_filter=False)
        # At minimum the number of trades should differ between strategies
        assert m_ema["n_trades"] != m_brsi["n_trades"] or \
               m_ema["total_return_pct"] != m_brsi["total_return_pct"]


# ── BacktestEngine.run_strategy_grid_search() ─────────────────────────────────

class TestRunStrategyGridSearch:
    def test_returns_dataframe(self):
        engine = _make_engine(_trending_prices(400))
        df = engine.run_strategy_grid_search(
            get_strategy("ema"),
            param_grid={"ema_short": [10, 20], "ema_long": [30, 50], "trend_filter": [False]},
        )
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 4  # 2 × 2 combinations

    def test_sorted_by_sharpe(self):
        engine = _make_engine(_trending_prices(400))
        df = engine.run_strategy_grid_search(
            get_strategy("ema"),
            param_grid={"ema_short": [10, 20], "ema_long": [30, 50], "trend_filter": [False]},
        )
        assert df["sharpe_ratio"].iloc[0] >= df["sharpe_ratio"].iloc[-1]

    def test_param_columns_present(self):
        engine = _make_engine(_trending_prices(400))
        df = engine.run_strategy_grid_search(
            get_strategy("ema"),
            param_grid={"ema_short": [10], "ema_long": [30], "trend_filter": [False]},
        )
        assert "ema_short" in df.columns
        assert "ema_long" in df.columns

    def test_sort_by_return(self):
        engine = _make_engine(_trending_prices(400))
        df = engine.run_strategy_grid_search(
            get_strategy("ema"),
            param_grid={"ema_short": [10, 20], "ema_long": [30, 50], "trend_filter": [False]},
            sort_by="total_return_pct",
        )
        assert df["total_return_pct"].iloc[0] >= df["total_return_pct"].iloc[-1]


# ── ImprovedMACrossover (Option A) ────────────────────────────────────────────

class TestImprovedMACrossover:
    def _run(self, prices, **kwargs):
        defaults = dict(ema_short=10, ema_long=30, trend_filter=False)
        defaults.update(kwargs)
        return _make_engine(prices).run_strategy(get_strategy("ema"), **defaults)

    def test_runs_on_trending_data(self):
        m = self._run(_trending_prices(400))
        assert isinstance(m["total_return_pct"], float)

    def test_no_trades_on_flat_prices(self):
        m = self._run(np.full(300, 40_000.0))
        assert m["n_trades"] == 0

    def test_trend_filter_reduces_trades(self):
        prices = _ranging_prices(600)
        m_no_filter  = self._run(prices, trend_filter=False)
        m_filter_on  = self._run(prices, trend_filter=True)
        # Trend filter should block some entries → fewer or equal trades
        assert m_filter_on["n_trades"] <= m_no_filter["n_trades"]

    def test_atr_stop_triggers_on_sharp_reversal(self):
        """Price rises then drops sharply – trailing stop should trigger a sell."""
        rise = np.linspace(30_000, 50_000, 200)
        fall = np.linspace(50_000, 35_000, 150)
        prices = np.concatenate([rise, fall])
        m = self._run(prices, atr_multiplier=1.0, trend_filter=False)
        # With a tight multiplier the stop should be hit during the fall
        assert m["n_trades"] >= 1

    def test_volume_filter_accepted(self):
        """Volume filter should not crash even with volume data present."""
        prices = _trending_prices(400)
        volume = np.ones(400) * 100.0
        engine = _make_engine(prices, volume=volume)
        m = engine.run_strategy(
            get_strategy("ema"),
            ema_short=10, ema_long=30, trend_filter=False,
            volume_filter_window=30,
        )
        assert isinstance(m["total_return_pct"], float)


# ── MomentumStrategy (Option B) ──────────────────────────────────────────────

class TestMomentumStrategy:
    def _run(self, prices, **kwargs):
        defaults = dict(lookback_period=30, entry_threshold=0.01,
                        exit_threshold=-0.005, atr_multiplier=2.0,
                        min_holding_bars=5)
        defaults.update(kwargs)
        return _make_engine(prices).run_strategy(get_strategy("momentum"), **defaults)

    def test_runs_on_trending_data(self):
        m = self._run(_trending_prices(400))
        assert isinstance(m["total_return_pct"], float)

    def test_enters_on_positive_momentum(self):
        m = self._run(_trending_prices(400))
        # Rising price → positive momentum → should enter at least once
        assert m["n_trades"] >= 1

    def test_no_trades_on_flat_prices(self):
        m = self._run(np.full(300, 40_000.0))
        assert m["n_trades"] == 0

    def test_exit_on_negative_momentum(self):
        """Rise then fall: momentum exit should close position."""
        prices = np.concatenate([
            np.linspace(30_000, 50_000, 250),
            np.linspace(50_000, 30_000, 250),
        ])
        m = self._run(prices, lookback_period=30, entry_threshold=0.01)
        assert m["n_trades"] >= 1

    def test_high_threshold_reduces_trades(self):
        prices = _trending_prices(400)
        m_low  = self._run(prices, entry_threshold=0.005)
        m_high = self._run(prices, entry_threshold=0.10)
        assert m_high["n_trades"] <= m_low["n_trades"]


# ── BollingerRSIStrategy (Option C) ──────────────────────────────────────────

class TestBollingerRSIStrategy:
    def _run(self, prices, **kwargs):
        defaults = dict(bb_period=30, rsi_period=14,
                        rsi_oversold=40, rsi_overbought=60,
                        trend_filter=False)
        defaults.update(kwargs)
        return _make_engine(prices).run_strategy(get_strategy("bollinger_rsi"), **defaults)

    def test_runs_on_oscillating_data(self):
        m = self._run(_volatile_ranging(500))
        assert isinstance(m["total_return_pct"], float)

    def test_enters_on_oversold_dip(self):
        """Wide oscillations should trigger multiple oversold entries."""
        m = self._run(_volatile_ranging(600), rsi_oversold=45)
        assert m["n_trades"] >= 1

    def test_no_trades_on_flat_prices(self):
        """Flat prices → no BB breakout → no trades."""
        m = self._run(np.full(300, 40_000.0))
        assert m["n_trades"] == 0

    def test_trend_filter_blocks_entries_in_downtrend(self):
        """Prices in persistent downtrend → trend filter should block entries."""
        downtrend = np.linspace(60_000, 30_000, 500)
        m_filter  = self._run(downtrend, trend_filter=True,  rsi_oversold=45)
        m_no_filt = self._run(downtrend, trend_filter=False, rsi_oversold=45)
        assert m_filter["n_trades"] <= m_no_filt["n_trades"]

    def test_exit_on_mean_reversion(self):
        """Price dips below lower band then recovers – should exit at mean."""
        prices = _volatile_ranging(600)
        m = self._run(prices, bb_period=30, rsi_oversold=45, rsi_overbought=55)
        assert m["n_trades"] >= 1

    def test_tighter_bands_more_entries(self):
        """Smaller bb_std → bands tighter → more price excursions → more entries."""
        prices = _volatile_ranging(600)
        m_tight = self._run(prices, bb_std=1.0, rsi_oversold=45)
        m_wide  = self._run(prices, bb_std=3.0, rsi_oversold=45)
        assert m_tight["n_trades"] >= m_wide["n_trades"]
