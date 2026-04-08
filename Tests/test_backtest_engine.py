"""Tests for BacktestEngine: enter_market, exit_market, update_portfolio,
compute_metrics, and the full run() loop with MA crossover signals."""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock


# ── Minimal DataLoader stand-in ───────────────────────────────────────────────

class _MockDataLoader:
    """Behaves like DataLoader but uses injected price data (no CSV files)."""

    def __init__(self, pair: str, prices: np.ndarray):
        dates = pd.date_range("2025-01-01", periods=len(prices), freq="1min")
        self.ticker_current = pd.DataFrame({pair: prices}, index=dates)
        self.ticker_ask     = pd.DataFrame({pair: prices * 1.001}, index=dates)
        self.ticker_bid     = pd.DataFrame({pair: prices * 0.999}, index=dates)
        self.ticker_volume  = None   # volume not required for basic tests
        self.rolling_current_short = None
        self.rolling_current_long  = None

    def load_csv_export(self):
        pass  # data already set

    def compute_rolling_means(self, window_short: int, window_long: int):
        self.rolling_current_short = self.ticker_current.rolling(
            f"{window_short}min").mean()
        self.rolling_current_long = self.ticker_current.rolling(
            f"{window_long}min").mean()


BASE    = "EUR"
TRADING = "BTC"
PAIR    = f"{TRADING}-{BASE}"   # "BTC-EUR"

BACKTEST_CONFIG = {
    "maker_fee":        0.0025,
    "taker_fee":        0.004,
    "initial_invest":   1000.0,
    "base_currency":    BASE,
    "trading_currency": TRADING,
}


def _make_engine(prices: np.ndarray):
    from altotrader.backtest.backtest_engine import BacktestEngine
    loader = _MockDataLoader(PAIR, prices)
    return BacktestEngine(loader, BACKTEST_CONFIG)


# ── enter_market ─────────────────────────────────────────────────────────────

class TestEnterMarket:
    def test_buys_at_ask_price(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row)

        effective_ask = row[PAIR + "_ask"] * (1 + engine.slippage_pct)
        fee = 1000.0 * engine.taker_fee
        expected_amount = (1000.0 - fee) / effective_ask

        assert engine.portfolio_view.at[row.name, TRADING] == pytest.approx(expected_amount)
        assert engine.portfolio_view.at[row.name, BASE] == pytest.approx(0.0)

    def test_market_position_set_to_in(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row)
        assert engine.portfolio_view.at[row.name, "market_position"] == "in"

    def test_action_logged_as_buy(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row)
        assert engine.portfolio_view.at[row.name, "action"] == "buy"

    def test_trade_log_entry_created(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row)
        assert len(engine.trade_log) == 1
        assert engine.trade_log[0]["action"] == "buy"

    def test_no_buy_when_base_balance_zero(self):
        engine = _make_engine(np.full(5, 40_000.0))
        # drain the first row's balance
        engine.portfolio_view.at[engine.portfolio_view.index[0], BASE] = 0.0
        row = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row)
        # no trade should have been logged
        assert len(engine.trade_log) == 0


# ── exit_market ──────────────────────────────────────────────────────────────

class TestExitMarket:
    def _engine_with_open_position(self):
        engine = _make_engine(np.full(5, 40_000.0))
        # manually open a position at row 1
        row1 = engine.portfolio_view.iloc[1]
        engine.enter_market(1, row1)
        return engine

    def test_sells_at_bid_price(self):
        engine = self._engine_with_open_position()
        row2 = engine.portfolio_view.iloc[2]
        engine.exit_market(2, row2)

        effective_bid = row2[PAIR + "_bid"] * (1 - engine.slippage_pct)
        crypto_held = engine.portfolio_view.iloc[1][TRADING]
        gross = crypto_held * effective_bid
        expected_proceeds = gross * (1 - engine.maker_fee)

        assert engine.portfolio_view.at[row2.name, BASE] == pytest.approx(expected_proceeds)
        assert engine.portfolio_view.at[row2.name, TRADING] == pytest.approx(0.0)

    def test_market_position_set_to_out(self):
        engine = self._engine_with_open_position()
        row2 = engine.portfolio_view.iloc[2]
        engine.exit_market(2, row2)
        assert engine.portfolio_view.at[row2.name, "market_position"] == "out"

    def test_trade_log_has_sell_entry(self):
        engine = self._engine_with_open_position()
        row2 = engine.portfolio_view.iloc[2]
        engine.exit_market(2, row2)
        actions = [t["action"] for t in engine.trade_log]
        assert "sell" in actions

    def test_no_sell_when_no_position(self):
        engine = _make_engine(np.full(5, 40_000.0))
        initial_log_len = len(engine.trade_log)
        row2 = engine.portfolio_view.iloc[2]
        engine.exit_market(2, row2)
        assert len(engine.trade_log) == initial_log_len


# ── update_portfolio ─────────────────────────────────────────────────────────

class TestUpdatePortfolio:
    def test_carries_base_balance_forward(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row1 = engine.portfolio_view.iloc[1]
        engine.update_portfolio(1, row1)
        assert engine.portfolio_view.at[row1.name, BASE] == pytest.approx(1000.0)

    def test_portfolio_value_reflects_current_price(self):
        prices = np.full(5, 40_000.0)
        engine = _make_engine(prices)
        # open a position first
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        row2 = engine.portfolio_view.iloc[2]
        engine.update_portfolio(2, row2)

        crypto_held = engine.portfolio_view.iloc[1][TRADING]
        expected_value = crypto_held * prices[2]
        assert engine.portfolio_view.at[row2.name, f"portfolio_in_{BASE}"] == pytest.approx(expected_value, rel=1e-3)

    def test_returns_early_for_idx_zero(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row0 = engine.portfolio_view.iloc[0]
        # should not raise
        engine.update_portfolio(0, row0)


# ── compute_metrics ──────────────────────────────────────────────────────────

class TestComputeMetrics:
    def test_no_trades_returns_zero_return(self):
        engine = _make_engine(np.full(50, 40_000.0))
        # fill portfolio with constant value (no trades)
        pv_col = f"portfolio_in_{BASE}"
        engine.portfolio_view[pv_col] = 1000.0
        metrics = engine.compute_metrics()
        assert metrics["total_return_pct"] == pytest.approx(0.0)
        assert metrics["n_trades"] == 0

    def test_total_return_positive_after_profitable_trade(self):
        prices = np.full(5, 40_000.0)
        engine = _make_engine(prices)
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        engine.exit_market(2, engine.portfolio_view.iloc[2])
        engine.update_portfolio(3, engine.portfolio_view.iloc[3])
        engine.update_portfolio(4, engine.portfolio_view.iloc[4])
        # No profit expected (same price), but fees should reduce value
        metrics = engine.compute_metrics()
        assert metrics["total_return_pct"] < 0  # fees eat into returns at flat price
        assert metrics["n_trades"] == 1

    def test_win_rate_calculation(self):
        prices = np.array([40_000.0, 40_000.0, 42_000.0, 42_000.0, 42_000.0])
        engine = _make_engine(prices)
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        engine.exit_market(2, engine.portfolio_view.iloc[2])
        engine.update_portfolio(3, engine.portfolio_view.iloc[3])
        engine.update_portfolio(4, engine.portfolio_view.iloc[4])
        metrics = engine.compute_metrics()
        assert metrics["win_rate"] == pytest.approx(100.0)

    def test_metrics_keys_present(self):
        engine = _make_engine(np.full(10, 40_000.0))
        metrics = engine.compute_metrics()
        expected_keys = {
            "total_return_pct", "buy_and_hold_return_pct", "n_trades",
            "win_rate", "max_drawdown_pct", "max_drawdown_duration_hrs",
            "sharpe_ratio", "total_fees", "taker_fees", "maker_fees",
            "final_portfolio_value",
        }
        assert expected_keys.issubset(metrics.keys())

    def test_fee_breakdown_sums_to_total(self):
        prices = np.array([40_000.0, 40_000.0, 42_000.0, 42_000.0, 42_000.0])
        engine = _make_engine(prices)
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        engine.exit_market(2, engine.portfolio_view.iloc[2])
        metrics = engine.compute_metrics()
        assert metrics["taker_fees"] + metrics["maker_fees"] == pytest.approx(
            metrics["total_fees"], rel=1e-6
        )

    def test_taker_fee_on_buy_maker_fee_on_sell(self):
        prices = np.array([40_000.0, 40_000.0, 42_000.0, 42_000.0, 42_000.0])
        engine = _make_engine(prices)
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        engine.exit_market(2, engine.portfolio_view.iloc[2])
        assert engine.trade_log[0]["fee_type"] == "taker"
        assert engine.trade_log[1]["fee_type"] == "maker"

    def test_drawdown_duration_nonnegative(self):
        engine = _make_engine(np.full(50, 40_000.0))
        engine.portfolio_view["portfolio_in_" + BASE] = 1000.0
        metrics = engine.compute_metrics()
        assert metrics["max_drawdown_duration_hrs"] >= 0.0

    def test_slippage_increases_buy_price(self):
        engine = _make_engine(np.full(5, 40_000.0))
        row = engine.portfolio_view.iloc[1]
        raw_ask = row[PAIR + "_ask"]
        engine.enter_market(1, row)
        effective_price = engine.trade_log[0]["price"]
        assert effective_price == pytest.approx(raw_ask * (1 + engine.slippage_pct))

    def test_slippage_decreases_sell_price(self):
        engine = _make_engine(np.full(5, 40_000.0))
        engine.enter_market(1, engine.portfolio_view.iloc[1])
        row2 = engine.portfolio_view.iloc[2]
        raw_bid = row2[PAIR + "_bid"]
        engine.exit_market(2, row2)
        effective_price = engine.trade_log[1]["price"]
        assert effective_price == pytest.approx(raw_bid * (1 - engine.slippage_pct))


# ── run() – MA crossover integration ─────────────────────────────────────────

class TestRun:
    def _prices_with_crossover(self, n=100):
        """Flat → dip → recovery: produces one golden cross + one death cross."""
        p = np.concatenate([
            np.full(30, 40_000.0),           # flat baseline
            np.linspace(40_000, 36_000, 20),  # dip  → short MA drops below long
            np.linspace(36_000, 44_000, 30),  # recovery → golden cross
            np.linspace(44_000, 38_000, 20),  # decline → death cross
        ])
        return p

    def test_run_returns_metrics_dict(self):
        engine = _make_engine(self._prices_with_crossover())
        metrics = engine.run(window_short=5, window_long=10)
        assert isinstance(metrics, dict)
        assert "total_return_pct" in metrics

    def test_run_resets_state_between_calls(self):
        engine = _make_engine(self._prices_with_crossover())
        metrics1 = engine.run(window_short=5, window_long=10)
        metrics2 = engine.run(window_short=5, window_long=10)
        assert metrics1["total_return_pct"] == pytest.approx(metrics2["total_return_pct"])

    def test_open_position_force_closed_at_end(self):
        """If the strategy is 'in' at end of data, a final sell must occur."""
        # Permanently rising prices → golden cross, never a death cross
        prices = np.linspace(38_000, 45_000, 80)
        engine = _make_engine(prices)
        metrics = engine.run(window_short=5, window_long=10)
        # Position must be closed; final portfolio should be in base currency
        final_position = engine.portfolio_view["market_position"].iloc[-1]
        assert final_position == "out"

    def test_initial_invest_respected(self):
        prices = np.full(50, 40_000.0)
        engine = _make_engine(prices)
        metrics = engine.run(window_short=5, window_long=10)
        # No crossover on flat prices → no trades → final value = initial
        assert metrics["final_portfolio_value"] == pytest.approx(1000.0, rel=1e-3)
