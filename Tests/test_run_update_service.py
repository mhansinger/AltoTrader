"""Tests for run_update_service.py: exchange selection, multi-exchange threading,
EXCHANGES env var parsing, and the dynamic measurement name in _generate_points."""

import threading
import time
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ticker(exchange: str):
    ticker = MagicMock()
    ticker.EXCHANGE = exchange
    ticker.get_market_query.return_value = {
        "BTC-EUR": {"c": 60000.0, "a": 60010.0, "b": 59990.0, "v": 100.0}
    }
    ticker.get_last_ticker.return_value = pd.DataFrame(
        {"BTC-EUR": [60000.0]},
        index=pd.to_datetime(["2025-01-01 00:00:00"])
    )
    return ticker


# ── _make_rest_ticker ─────────────────────────────────────────────────────────

class TestMakeRestTicker:
    def _call(self, exchange, tmp_path):
        yaml = tmp_path / "pairs.yaml"
        yaml.write_text("items:\n  - BTC-EUR\n")
        from Examples.run_update_service import _make_rest_ticker
        return _make_rest_ticker(exchange, str(yaml))

    def test_kraken(self, tmp_path):
        from altotrader.ticker.krakenticker import KrakenTicker
        t = self._call("kraken", tmp_path)
        assert isinstance(t, KrakenTicker)

    def test_binance(self, tmp_path):
        from altotrader.ticker.binanceticker import BinanceTicker
        t = self._call("binance", tmp_path)
        assert isinstance(t, BinanceTicker)

    def test_gemini(self, tmp_path):
        from altotrader.ticker.geminiticker import GeminiTicker
        t = self._call("gemini", tmp_path)
        assert isinstance(t, GeminiTicker)

    def test_coinbase(self, tmp_path):
        from altotrader.ticker.coinbaseticker import CoinbaseTicker
        t = self._call("coinbase", tmp_path)
        assert isinstance(t, CoinbaseTicker)

    def test_mexc(self, tmp_path):
        from altotrader.ticker.mexcticker import MEXCTicker
        t = self._call("mexc", tmp_path)
        assert isinstance(t, MEXCTicker)

    def test_unknown_raises(self, tmp_path):
        yaml = tmp_path / "pairs.yaml"
        yaml.write_text("items:\n  - BTC-EUR\n")
        from Examples.run_update_service import _make_rest_ticker
        with pytest.raises(ValueError, match="Unknown exchange"):
            _make_rest_ticker("unknown", str(yaml))


# ── _make_ws_ticker ───────────────────────────────────────────────────────────

class TestMakeWsTicker:
    def _call(self, exchange, tmp_path):
        yaml = tmp_path / "pairs.yaml"
        yaml.write_text("items:\n  - BTC-EUR\n")
        from Examples.run_update_service import _make_ws_ticker
        return _make_ws_ticker(exchange, str(yaml))

    def test_kraken_ws(self, tmp_path):
        from altotrader.ticker.kraken_ws_ticker import KrakenWsTicker
        t = self._call("kraken", tmp_path)
        assert isinstance(t, KrakenWsTicker)
        t.stop()

    def test_binance_ws(self, tmp_path):
        from altotrader.ticker.binance_ws_ticker import BinanceWsTicker
        t = self._call("binance", tmp_path)
        assert isinstance(t, BinanceWsTicker)

    def test_unsupported_exchange_raises(self, tmp_path):
        yaml = tmp_path / "pairs.yaml"
        yaml.write_text("items:\n  - BTC-EUR\n")
        from Examples.run_update_service import _make_ws_ticker
        with pytest.raises(ValueError, match="WebSocket mode not supported"):
            _make_ws_ticker("gemini", str(yaml))


# ── EXCHANGES env var parsing ─────────────────────────────────────────────────

class TestExchangesParsing:
    def _parse(self, exchanges_str):
        """Simulate how main() parses the EXCHANGES string."""
        return [e.strip() for e in exchanges_str.split(",") if e.strip()]

    def test_single_exchange(self):
        assert self._parse("kraken") == ["kraken"]

    def test_multiple_exchanges(self):
        assert self._parse("kraken,binance,gemini") == ["kraken", "binance", "gemini"]

    def test_whitespace_trimmed(self):
        assert self._parse("kraken, binance , gemini") == ["kraken", "binance", "gemini"]

    def test_empty_segments_ignored(self):
        assert self._parse("kraken,,gemini") == ["kraken", "gemini"]


# ── _generate_points uses ticker.EXCHANGE as measurement ─────────────────────

class TestGeneratePointsMeasurement:
    def test_measurement_name_from_ticker_exchange(self):
        from altotrader.database.update_service import TickerUpdateService
        ticker = _make_ticker("binance")
        service = TickerUpdateService(ticker, log_dir="logs")

        df = pd.DataFrame(
            {"BTC-EUR": [60000.0]},
            index=pd.to_datetime(["2025-01-01 00:00:00"])
        )
        points = service._generate_points(df, "c")
        assert len(points) == 1
        assert points[0]._name == "binance"

    def test_measurement_name_kraken(self):
        from altotrader.database.update_service import TickerUpdateService
        ticker = _make_ticker("kraken")
        service = TickerUpdateService(ticker, log_dir="logs")

        df = pd.DataFrame(
            {"BTC-EUR": [60000.0]},
            index=pd.to_datetime(["2025-01-01 00:00:00"])
        )
        points = service._generate_points(df, "c")
        assert points[0]._name == "kraken"

    def test_fallback_when_no_exchange_attr(self):
        from altotrader.database.update_service import TickerUpdateService
        ticker = MagicMock()
        del ticker.EXCHANGE  # remove EXCHANGE so getattr falls back to default
        ticker.get_market_query.return_value = {}
        ticker.get_last_ticker.return_value = pd.DataFrame()
        service = TickerUpdateService(ticker, log_dir="logs")

        df = pd.DataFrame(
            {"BTC-EUR": [60000.0]},
            index=pd.to_datetime(["2025-01-01 00:00:00"])
        )
        points = service._generate_points(df, "c")
        assert points[0]._name == "ticker"


# ── Multi-exchange threading ──────────────────────────────────────────────────

class TestMultiExchangeThreading:
    def test_all_exchanges_called(self):
        """Each exchange thread calls update_pairs_ticker at least once."""
        from altotrader.database.update_service import TickerUpdateService
        from Examples.run_update_service import _polling_loop, POLL_INTERVAL_SECONDS

        called = []

        def make_service(exchange):
            ticker = _make_ticker(exchange)
            service = MagicMock(spec=TickerUpdateService)
            service.update_pairs_ticker.side_effect = lambda: called.append(exchange) or True
            return service

        stop_flag = [False]
        exchanges = ["kraken", "binance", "gemini"]
        threads = []

        for ex in exchanges:
            svc = make_service(ex)
            t = threading.Thread(
                target=_polling_loop,
                args=(svc, stop_flag, ex),
                daemon=True,
            )
            t.start()
            threads.append(t)

        time.sleep(0.2)
        stop_flag[0] = True

        for t in threads:
            t.join(timeout=5)

        assert set(called) == {"kraken", "binance", "gemini"}

    def test_stop_flag_stops_all_threads(self):
        """Setting stop_flag[0]=True stops all polling loops."""
        from Examples.run_update_service import _polling_loop

        stop_flag = [False]
        finished = []

        def run(name):
            svc = MagicMock()
            svc.update_pairs_ticker.return_value = True
            _polling_loop(svc, stop_flag, name)
            finished.append(name)

        threads = [
            threading.Thread(target=run, args=(ex,), daemon=True)
            for ex in ["kraken", "binance"]
        ]
        for t in threads:
            t.start()

        time.sleep(0.1)
        stop_flag[0] = True

        for t in threads:
            t.join(timeout=5)

        assert set(finished) == {"kraken", "binance"}
