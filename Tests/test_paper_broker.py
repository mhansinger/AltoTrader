"""Tests for PaperBroker and broker utilities."""
import pytest
from altotrader.trader.config import TradingConfig
from altotrader.trader.broker.paper_broker import PaperBroker
from altotrader.trader.broker.binance_broker import BinanceBroker


@pytest.fixture
def cfg():
    return TradingConfig(
        pair="BTC-EUR",
        exchange="kraken",
        initial_invest=1000.0,
        maker_fee=0.0025,
        taker_fee=0.004,
        slippage_pct=0.001,
        paper_trading=True,
    )


@pytest.fixture
def broker(cfg):
    return PaperBroker(cfg)


class TestPaperBroker:
    def test_initial_balance(self, broker, cfg):
        assert broker.get_balance("EUR") == cfg.initial_invest
        assert broker.get_balance("BTC") == 0.0

    def test_buy_reduces_quote_increases_base(self, broker, cfg):
        result = broker.buy("BTC-EUR", quote_amount=500.0, price=50_000.0)
        assert result.side == "buy"
        assert broker.get_balance("EUR") == pytest.approx(500.0)
        assert broker.get_balance("BTC") > 0.0

    def test_buy_applies_taker_fee(self, broker, cfg):
        result = broker.buy("BTC-EUR", quote_amount=1000.0, price=50_000.0)
        expected_fee = 1000.0 * cfg.taker_fee
        assert result.fee == pytest.approx(expected_fee)

    def test_buy_applies_slippage(self, broker, cfg):
        result = broker.buy("BTC-EUR", quote_amount=1000.0, price=50_000.0)
        expected_price = 50_000.0 * (1 + cfg.slippage_pct)
        assert result.price == pytest.approx(expected_price)

    def test_sell_reduces_base_increases_quote(self, broker, cfg):
        broker.buy("BTC-EUR", quote_amount=1000.0, price=50_000.0)
        btc = broker.get_balance("BTC")
        result = broker.sell("BTC-EUR", base_amount=btc, price=50_000.0)
        assert result.side == "sell"
        assert broker.get_balance("BTC") == pytest.approx(0.0, abs=1e-9)
        assert broker.get_balance("EUR") > 0.0

    def test_sell_applies_maker_fee(self, broker, cfg):
        broker.buy("BTC-EUR", quote_amount=1000.0, price=50_000.0)
        btc = broker.get_balance("BTC")
        result = broker.sell("BTC-EUR", base_amount=btc, price=50_000.0)
        assert result.fee > 0.0

    def test_buy_insufficient_balance_raises(self, broker):
        with pytest.raises(ValueError, match="Insufficient EUR"):
            broker.buy("BTC-EUR", quote_amount=99_999.0, price=50_000.0)

    def test_sell_insufficient_base_raises(self, broker):
        with pytest.raises(ValueError, match="Insufficient BTC"):
            broker.sell("BTC-EUR", base_amount=1.0, price=50_000.0)

    def test_cancel_order_always_true(self, broker):
        assert broker.cancel_order("fake-id") is True

    def test_order_result_has_id(self, broker):
        result = broker.buy("BTC-EUR", quote_amount=100.0, price=50_000.0)
        assert result.order_id != ""

    def test_round_trip_less_than_invested(self, broker, cfg):
        """After buy+sell with fees, portfolio value should be < initial_invest."""
        broker.buy("BTC-EUR", quote_amount=1000.0, price=50_000.0)
        btc = broker.get_balance("BTC")
        broker.sell("BTC-EUR", base_amount=btc, price=50_000.0)
        assert broker.get_balance("EUR") < cfg.initial_invest


class TestBinanceBrokerHelpers:
    """Test static helpers without real API connection."""

    def test_to_binance_symbol(self):
        assert BinanceBroker._to_binance_symbol("BTC-EUR") == "BTCEUR"
        assert BinanceBroker._to_binance_symbol("ETH-USDT") == "ETHUSDT"

    def test_round_step(self):
        assert BinanceBroker._round_step(0.123456, 0.001) == pytest.approx(0.123)
        assert BinanceBroker._round_step(1.999, 0.01) == pytest.approx(1.99)
        assert BinanceBroker._round_step(1.0, 0.0) == 1.0  # zero step → unchanged
