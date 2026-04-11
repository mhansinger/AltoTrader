"""Integration tests for TradingEngine with PaperBroker."""
import threading
import time
import pytest
from unittest.mock import MagicMock, patch

from altotrader.trader.config import TradingConfig
from altotrader.trader.broker.paper_broker import PaperBroker
from altotrader.trader.position_manager import PositionManager
from altotrader.trader.risk_manager import RiskManager
from altotrader.trader.trading_engine import TradingEngine
from altotrader.trader.signal_generator import Signal


@pytest.fixture
def cfg(tmp_path):
    return TradingConfig(
        pair="BTC-EUR",
        exchange="kraken",
        initial_invest=1000.0,
        window_short=3,
        window_long=5,
        stop_loss_pct=0.10,
        max_drawdown_pct=0.50,
        paper_trading=True,
        poll_interval=0,  # no sleep in tests
    )


@pytest.fixture
def broker(cfg):
    return PaperBroker(cfg)


@pytest.fixture
def pos_mgr(tmp_path):
    return PositionManager(persist_path=str(tmp_path / "positions.json"))


@pytest.fixture
def risk_mgr(cfg):
    return RiskManager(cfg)


def _make_ticker(price_sequence: list[dict]):
    """Create a mock ticker that returns prices from a sequence."""
    ticker = MagicMock()
    ticker.get_market_query.side_effect = [
        {"BTC-EUR": p} for p in price_sequence
    ]
    return ticker


def _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path):
    return TradingEngine(
        config=cfg,
        ticker=ticker,
        broker=broker,
        position_mgr=pos_mgr,
        risk_mgr=risk_mgr,
        log_dir=str(tmp_path),
    )


class TestTradingEngineIteration:
    """Test individual _iteration() calls without threading."""

    def test_hold_during_warmup(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        price = {"c": 50_000.0, "a": 50_010.0, "b": 49_990.0}
        ticker = _make_ticker([price] * 5)
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)
        for _ in range(5):
            engine._iteration()
        # Not enough data for SMA → no position opened
        assert not pos_mgr.is_open("BTC-EUR")

    def test_buy_on_golden_cross(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        # Warm up with flat prices, then drive a golden cross
        flat   = {"c": 100.0, "a": 100.1, "b": 99.9}
        rising = {"c": 500.0, "a": 500.1, "b": 499.9}
        prices = [flat] * cfg.min_prices + [rising] * 5
        ticker = _make_ticker(prices)
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)

        for _ in prices:
            engine._iteration()

        assert pos_mgr.is_open("BTC-EUR")

    def test_sell_on_death_cross(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        # Warm up high → buy → drive price down → death cross → sell
        high  = {"c": 500.0, "a": 500.1, "b": 499.9}
        low   = {"c": 100.0, "a": 100.1, "b": 99.9}
        prices = [high] * cfg.min_prices + [high] * 3 + [low] * 10
        ticker = _make_ticker(prices)
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)

        # First buy manually so we have a position to sell
        from altotrader.trader.position_manager import Position
        from datetime import datetime, timezone
        pos_mgr.open(Position(
            pair="BTC-EUR", exchange="kraken",
            entry_price=500.0, base_amount=0.01,
            quote_invested=5.0,
            entry_time=datetime.now(timezone.utc).isoformat(),
            order_id="test",
        ))
        # Fund the paper broker's BTC balance + large EUR buffer so drawdown doesn't fire
        broker._balance["BTC"] = 0.01
        broker._balance["EUR"] = 10_000.0  # large EUR buffer keeps drawdown < limit
        assert pos_mgr.is_open("BTC-EUR")

        for p in prices:
            engine._iteration()

        assert not pos_mgr.is_open("BTC-EUR")

    def test_stop_loss_triggers_sell(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        from altotrader.trader.position_manager import Position
        from datetime import datetime, timezone

        # Open a position at 50_000
        pos_mgr.open(Position(
            pair="BTC-EUR", exchange="kraken",
            entry_price=50_000.0, base_amount=0.019,
            quote_invested=950.0,
            entry_time=datetime.now(timezone.utc).isoformat(),
            order_id="test",
        ))
        # Add the BTC to the broker's virtual balance
        broker._balance["BTC"] = 0.019
        broker._balance["EUR"] = 50.0

        # Price drops 15% → below stop_loss_pct=10%
        crash_price = {"c": 42_500.0, "a": 42_510.0, "b": 42_490.0}
        ticker = _make_ticker([crash_price])
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)
        engine._iteration()

        assert not pos_mgr.is_open("BTC-EUR")

    def test_no_double_buy(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        from altotrader.trader.position_manager import Position
        from datetime import datetime, timezone

        pos_mgr.open(Position(
            pair="BTC-EUR", exchange="kraken",
            entry_price=50_000.0, base_amount=0.019,
            quote_invested=950.0,
            entry_time=datetime.now(timezone.utc).isoformat(),
            order_id="test",
        ))

        # Even with a BUY signal, no second position should open
        with patch.object(engine := _make_engine(cfg, _make_ticker([
            {"c": 50_000.0, "a": 50_010.0, "b": 49_990.0}
        ]), broker, pos_mgr, risk_mgr, tmp_path),
            "_signal_gen") as mock_sg:
            mock_sg.update.return_value = Signal.BUY
            engine._iteration()

        assert len(pos_mgr._positions) == 1

    def test_ticker_failure_does_not_crash(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        ticker = MagicMock()
        ticker.get_market_query.side_effect = Exception("network error")
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)
        engine._iteration()  # should not raise

    def test_max_drawdown_stops_engine(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        # Set peak high, then drop portfolio below max_drawdown threshold
        risk_mgr.update_peak(1000.0)
        price = {"c": 1.0, "a": 1.1, "b": 0.9}  # trivially low price
        broker._balance["EUR"] = 0.0  # simulate massive loss
        ticker = _make_ticker([price])
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)
        engine._iteration()
        assert engine._stop_flag.is_set()


class TestTradingEngineThread:
    """Test thread start/stop lifecycle."""

    def test_engine_stops_gracefully(self, cfg, broker, pos_mgr, risk_mgr, tmp_path):
        ticker = MagicMock()
        ticker.get_market_query.return_value = {"BTC-EUR": {"c": 50_000.0, "a": 50_010.0, "b": 49_990.0}}
        engine = _make_engine(cfg, ticker, broker, pos_mgr, risk_mgr, tmp_path)
        engine.start()
        time.sleep(0.05)
        engine.stop()
        engine.join(timeout=2.0)
        assert not engine.is_alive()
