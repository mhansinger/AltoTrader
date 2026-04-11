"""Tests for TradingConfig and SignalGenerator."""
import pytest
from altotrader.trader.config import TradingConfig
from altotrader.trader.signal_generator import Signal, SignalGenerator


# ── TradingConfig ─────────────────────────────────────────────────────────────

class TestTradingConfig:
    def test_defaults(self):
        cfg = TradingConfig(pair="BTC-EUR", exchange="kraken")
        assert cfg.base_currency == "BTC"
        assert cfg.quote_currency == "EUR"
        assert cfg.paper_trading is True
        assert cfg.min_prices == cfg.window_long + 10

    def test_short_long_validation(self):
        with pytest.raises(ValueError, match="window_short"):
            TradingConfig(pair="BTC-EUR", exchange="kraken", window_short=200, window_long=50)

    def test_equal_windows_invalid(self):
        with pytest.raises(ValueError):
            TradingConfig(pair="BTC-EUR", exchange="kraken", window_short=100, window_long=100)

    def test_pair_parsing(self):
        cfg = TradingConfig(pair="ETH-USDT", exchange="binance")
        assert cfg.base_currency == "ETH"
        assert cfg.quote_currency == "USDT"


# ── SignalGenerator ───────────────────────────────────────────────────────────

class TestSignalGenerator:
    def _make_gen(self, short=3, long=5, min_prices=None):
        return SignalGenerator(window_short=short, window_long=long, min_prices=min_prices)

    def test_hold_during_warmup(self):
        gen = self._make_gen(short=3, long=5, min_prices=7)
        for _ in range(6):
            assert gen.update(100.0) == Signal.HOLD
        assert not gen.is_warmed_up

    def test_warmed_up_after_min_prices(self):
        gen = self._make_gen(short=3, long=5, min_prices=5)
        for _ in range(5):
            gen.update(100.0)
        assert gen.is_warmed_up

    def test_hold_when_flat(self):
        gen = self._make_gen(short=3, long=5, min_prices=5)
        for _ in range(10):
            assert gen.update(100.0) == Signal.HOLD

    def test_golden_cross_emits_buy(self):
        """Price rises sharply after flat → short SMA crosses above long SMA."""
        gen = self._make_gen(short=3, long=5, min_prices=5)
        # Feed flat prices to warm up (short == long)
        for _ in range(5):
            gen.update(100.0)
        # Now drive short SMA above long SMA
        signals = [gen.update(p) for p in [100.0, 100.0, 200.0, 200.0, 200.0]]
        assert Signal.BUY in signals

    def test_death_cross_emits_sell(self):
        """Price falls sharply after rising → short SMA crosses below long SMA."""
        gen = self._make_gen(short=3, long=5, min_prices=5)
        # Warm up at high price so both SMAs are high
        for _ in range(5):
            gen.update(200.0)
        # Drive price down sharply so short SMA drops below long SMA
        signals = [gen.update(p) for p in [200.0, 200.0, 50.0, 50.0, 50.0]]
        assert Signal.SELL in signals

    def test_n_prices_counter(self):
        gen = self._make_gen()
        for i in range(4):
            gen.update(float(i))
        assert gen.n_prices == 4

    def test_invalid_windows_raise(self):
        with pytest.raises(ValueError):
            SignalGenerator(window_short=10, window_long=5)

    def test_only_one_buy_on_single_cross(self):
        """A single golden cross should not keep emitting BUY every tick."""
        gen = self._make_gen(short=3, long=5, min_prices=5)
        for _ in range(5):
            gen.update(100.0)
        # One sharp rise
        gen.update(500.0)
        gen.update(500.0)
        gen.update(500.0)
        # Now price stays flat at high level → no more crossovers
        signals = [gen.update(500.0) for _ in range(10)]
        assert Signal.BUY not in signals
