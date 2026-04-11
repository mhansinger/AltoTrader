"""Tests for PositionManager and RiskManager."""
import json
import os
import tempfile
import pytest
from datetime import datetime, timezone

from altotrader.trader.config import TradingConfig
from altotrader.trader.position_manager import Position, PositionManager
from altotrader.trader.risk_manager import RiskManager


@pytest.fixture
def cfg():
    return TradingConfig(
        pair="BTC-EUR",
        exchange="kraken",
        initial_invest=1000.0,
        stop_loss_pct=0.05,
        max_drawdown_pct=0.20,
        max_position_pct=0.95,
    )


@pytest.fixture
def tmp_path_json(tmp_path):
    return str(tmp_path / "positions.json")


@pytest.fixture
def pos_mgr(tmp_path_json):
    return PositionManager(persist_path=tmp_path_json)


@pytest.fixture
def sample_position():
    return Position(
        pair="BTC-EUR",
        exchange="kraken",
        entry_price=50_000.0,
        base_amount=0.019,
        quote_invested=950.0,
        entry_time=datetime.now(timezone.utc).isoformat(),
        order_id="test-order-1",
    )


# ── PositionManager ───────────────────────────────────────────────────────────

class TestPositionManager:
    def test_no_position_initially(self, pos_mgr):
        assert not pos_mgr.is_open("BTC-EUR")
        assert pos_mgr.get("BTC-EUR") is None

    def test_open_position(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        assert pos_mgr.is_open("BTC-EUR")
        assert pos_mgr.get("BTC-EUR") == sample_position

    def test_open_duplicate_ignored(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        pos_mgr.open(sample_position)  # second open should be ignored
        assert len(pos_mgr._positions) == 1

    def test_close_position(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        result = pos_mgr.close("BTC-EUR", exit_price=55_000.0, fee=0.0)
        assert not pos_mgr.is_open("BTC-EUR")
        assert result["pnl_abs"] > 0  # profit because exit > entry

    def test_close_nonexistent_returns_empty(self, pos_mgr):
        result = pos_mgr.close("ETH-EUR", exit_price=3000.0)
        assert result == {}

    def test_pnl_profitable(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        pnl = pos_mgr.get_pnl("BTC-EUR", current_price=55_000.0)
        assert pnl > 0

    def test_pnl_loss(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        pnl = pos_mgr.get_pnl("BTC-EUR", current_price=40_000.0)
        assert pnl < 0

    def test_pnl_no_position(self, pos_mgr):
        assert pos_mgr.get_pnl("BTC-EUR", current_price=50_000.0) == 0.0

    def test_persistence(self, tmp_path_json, sample_position):
        mgr1 = PositionManager(persist_path=tmp_path_json)
        mgr1.open(sample_position)

        mgr2 = PositionManager(persist_path=tmp_path_json)
        assert mgr2.is_open("BTC-EUR")
        loaded = mgr2.get("BTC-EUR")
        assert loaded.entry_price == sample_position.entry_price

    def test_trade_history_after_close(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        pos_mgr.close("BTC-EUR", exit_price=52_000.0, fee=5.0)
        assert len(pos_mgr.trade_history) == 1
        assert pos_mgr.trade_history[0]["pair"] == "BTC-EUR"

    def test_close_records_pnl_pct(self, pos_mgr, sample_position):
        pos_mgr.open(sample_position)
        result = pos_mgr.close("BTC-EUR", exit_price=55_000.0, fee=0.0)
        expected_pct = ((0.019 * 55_000.0) - 950.0) / 950.0 * 100
        assert result["pnl_pct"] == pytest.approx(expected_pct, rel=1e-3)


# ── RiskManager ───────────────────────────────────────────────────────────────

class TestRiskManager:
    def test_stop_loss_not_triggered(self, cfg, sample_position):
        rm = RiskManager(cfg)
        # Only 2% drop, threshold is 5%
        assert not rm.check_stop_loss(sample_position, current_price=49_000.0)

    def test_stop_loss_triggered(self, cfg, sample_position):
        rm = RiskManager(cfg)
        # 10% drop, threshold is 5%
        assert rm.check_stop_loss(sample_position, current_price=45_000.0)

    def test_stop_loss_exact_boundary(self, cfg, sample_position):
        rm = RiskManager(cfg)
        # Exactly at 5% → not triggered (< not <=)
        price_at_limit = sample_position.entry_price * (1 - cfg.stop_loss_pct)
        assert not rm.check_stop_loss(sample_position, current_price=price_at_limit)

    def test_position_size(self, cfg):
        rm = RiskManager(cfg)
        size = rm.position_size(available_capital=1000.0, price=50_000.0)
        assert size == pytest.approx(1000.0 * cfg.max_position_pct)

    def test_position_size_zero_capital(self, cfg):
        rm = RiskManager(cfg)
        assert rm.position_size(available_capital=0.0, price=50_000.0) == 0.0

    def test_max_drawdown_not_triggered(self, cfg):
        rm = RiskManager(cfg)
        rm.update_peak(1000.0)
        assert not rm.check_max_drawdown(850.0)  # 15% drop, limit is 20%

    def test_max_drawdown_triggered(self, cfg):
        rm = RiskManager(cfg)
        rm.update_peak(1000.0)
        assert rm.check_max_drawdown(750.0)  # 25% drop, limit is 20%

    def test_trading_halted_after_drawdown(self, cfg):
        rm = RiskManager(cfg)
        rm.update_peak(1000.0)
        rm.check_max_drawdown(750.0)
        assert rm.is_halted
        # Should remain halted even if value recovers
        assert rm.check_max_drawdown(1000.0)

    def test_no_drawdown_before_peak_set(self, cfg):
        rm = RiskManager(cfg)
        assert not rm.check_max_drawdown(500.0)

    def test_peak_updates_on_new_high(self, cfg):
        rm = RiskManager(cfg)
        rm.update_peak(1000.0)
        rm.update_peak(1200.0)
        rm.update_peak(900.0)
        assert rm._peak_portfolio_value == 1200.0
