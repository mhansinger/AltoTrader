"""Tests for multi-exchange REST tickers: Binance, Coinbase, Gemini, MEXC.

All HTTP calls are mocked with unittest.mock so no real network access is
needed.  The test suite verifies:
  - get_market_query() returns the normalised {unified_pair: {c, a, b}} dict
  - get_last_ticker() returns a correctly shaped DataFrame for c / a / b
  - Invalid ticker_entry raises ValueError
  - HTTP errors (non-200) result in an empty dict / empty DataFrame
  - Partial failures (one pair missing) are handled gracefully

Pair format: all tickers use the unified 'BTC-EUR' convention in their YAML
files.  Each ticker converts internally to the exchange-specific symbol.
"""
from __future__ import annotations

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

MOCK_YAML = os.path.join(os.path.dirname(__file__), "mock_data", "mock_pairs.yaml")

# Unified pair names (used in YAML and returned by get_market_query)
BINANCE_PAIRS   = ["BTC-EUR", "ETH-BTC"]
COINBASE_PAIRS  = ["BTC-EUR", "ETH-BTC"]
GEMINI_PAIRS    = ["BTC-EUR", "ETH-BTC"]
MEXC_PAIRS      = ["BTC-USDT", "ETH-BTC"]


def _yaml_with_pairs(tmp_path, pairs: list) -> str:
    p = tmp_path / "pairs.yaml"
    p.write_text("items:\n" + "".join(f"  - {x}\n" for x in pairs))
    return str(p)


def _mock_response(json_data, status_code: int = 200):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data
    m.raise_for_status.side_effect = (
        None if status_code < 400
        else __import__("requests").HTTPError(response=m)
    )
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# BinanceTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestBinanceTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.binanceticker import BinanceTicker
        return BinanceTicker(pairs_yaml=_yaml_with_pairs(tmp_path, BINANCE_PAIRS))

    def _binance_response(self):
        # Binance returns uppercase, no-hyphen symbols
        return [
            {"symbol": "BTCEUR", "lastPrice": "60000.00", "askPrice": "60010.00",
             "bidPrice": "59990.00", "volume": "1234.5"},
            {"symbol": "ETHBTC", "lastPrice": "0.050",    "askPrice": "0.0501",
             "bidPrice": "0.0499", "volume": "5000.0"},
        ]

    def test_get_market_query_keyed_by_unified_pair(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        # Keys must be unified pair names, not exchange symbols
        assert set(mq.keys()) == set(BINANCE_PAIRS)
        assert mq["BTC-EUR"]["c"] == pytest.approx(60000.0)
        assert mq["BTC-EUR"]["a"] == pytest.approx(60010.0)
        assert mq["BTC-EUR"]["b"] == pytest.approx(59990.0)
        assert mq["BTC-EUR"]["v"] == pytest.approx(1234.5)

    def test_get_last_ticker_close(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("c", market_query=mq)
        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) == set(BINANCE_PAIRS)
        assert df["BTC-EUR"].iloc[0] == pytest.approx(60000.0)

    def test_get_last_ticker_ask(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("a", market_query=mq)
        assert df["BTC-EUR"].iloc[0] == pytest.approx(60010.0)

    def test_get_last_ticker_bid(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("b", market_query=mq)
        assert df["BTC-EUR"].iloc[0] == pytest.approx(59990.0)

    def test_invalid_ticker_entry_raises(self, tmp_path):
        ticker = self._make(tmp_path)
        with pytest.raises(ValueError, match="ticker_entry"):
            ticker.get_last_ticker("x", market_query={"BTC-EUR": {"c": 1, "a": 1, "b": 1}})

    def test_http_error_returns_empty_dict(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response({}, status_code=500)):
            mq = ticker.get_market_query()
        assert mq == {}

    def test_single_symbol_response_as_dict(self, tmp_path):
        """Binance returns a plain dict (not a list) for single-symbol requests."""
        ticker = self._make(tmp_path)
        single = {"symbol": "BTCEUR", "lastPrice": "60000.00",
                  "askPrice": "60010.00", "bidPrice": "59990.00", "volume": "500.0"}
        with patch("requests.Session.get", return_value=_mock_response(single)):
            mq = ticker.get_market_query()
        assert "BTC-EUR" in mq

    def test_timestamp_set_after_fetch(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._binance_response())):
            ticker.get_market_query()
        assert ticker.timestamp_last_fetch is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CoinbaseTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoinbaseTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.coinbaseticker import CoinbaseTicker
        return CoinbaseTicker(pairs_yaml=_yaml_with_pairs(tmp_path, COINBASE_PAIRS))

    def _response_for(self, pair: str):
        data = {
            "BTC-EUR": {"price": "60000.00", "ask": "60010.00", "bid": "59990.00", "volume": "800.0"},
            "ETH-BTC": {"price": "0.050",    "ask": "0.0501",   "bid": "0.0499",   "volume": "3000.0"},
        }
        return data[pair]

    def test_get_market_query_both_pairs(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in COINBASE_PAIRS]
        with patch("requests.Session.get", side_effect=responses):
            mq = ticker.get_market_query()
        assert set(mq.keys()) == set(COINBASE_PAIRS)
        assert mq["BTC-EUR"]["c"] == pytest.approx(60000.0)
        assert mq["BTC-EUR"]["a"] == pytest.approx(60010.0)
        assert mq["BTC-EUR"]["b"] == pytest.approx(59990.0)
        assert mq["BTC-EUR"]["v"] == pytest.approx(800.0)

    def test_partial_failure_still_returns_good_pairs(self, tmp_path):
        ticker = self._make(tmp_path)
        good  = _mock_response(self._response_for("BTC-EUR"))
        error = _mock_response({}, status_code=503)
        with patch("requests.Session.get", side_effect=[good, error]):
            mq = ticker.get_market_query()
        assert "BTC-EUR" in mq
        assert "ETH-BTC" not in mq

    def test_get_last_ticker_shape(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in COINBASE_PAIRS]
        with patch("requests.Session.get", side_effect=responses):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("c", market_query=mq)
        assert df.shape == (1, len(COINBASE_PAIRS))

    def test_all_fail_returns_empty(self, tmp_path):
        ticker = self._make(tmp_path)
        errors = [_mock_response({}, status_code=503)] * len(COINBASE_PAIRS)
        with patch("requests.Session.get", side_effect=errors):
            mq = ticker.get_market_query()
        assert mq == {}
        assert ticker.get_last_ticker("c", market_query=mq).empty


# ═══════════════════════════════════════════════════════════════════════════════
# GeminiTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeminiTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.geminiticker import GeminiTicker
        return GeminiTicker(pairs_yaml=_yaml_with_pairs(tmp_path, GEMINI_PAIRS))

    def _response_for(self, pair: str):
        data = {
            "BTC-EUR": {"last": "60000.00", "ask": "60010.00", "bid": "59990.00",
                        "volume": {"BTC": "250.0", "EUR": "15000000", "timestamp": 1234567890}},
            "ETH-BTC": {"last": "0.050",    "ask": "0.0501",   "bid": "0.0499",
                        "volume": {"ETH": "5000.0", "BTC": "250.0", "timestamp": 1234567890}},
        }
        return data[pair]

    def test_get_market_query_normalised(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in GEMINI_PAIRS]
        with patch("requests.Session.get", side_effect=responses):
            mq = ticker.get_market_query()
        # Keys must be unified names, not Gemini's lowercase
        assert set(mq.keys()) == set(GEMINI_PAIRS)
        assert mq["BTC-EUR"]["c"] == pytest.approx(60000.0)
        assert mq["BTC-EUR"]["v"] == pytest.approx(250.0)   # base-asset (BTC) volume

    def test_to_exchange_pair_converts_to_lowercase(self, tmp_path):
        """Gemini uses lowercase no-separator symbols internally."""
        ticker = self._make(tmp_path)
        assert ticker._to_exchange_pair("BTC-EUR") == "btceur"
        assert ticker._to_exchange_pair("ETH-BTC") == "ethbtc"

    def test_partial_failure(self, tmp_path):
        ticker = self._make(tmp_path)
        good  = _mock_response(self._response_for("BTC-EUR"))
        error = _mock_response({}, status_code=404)
        with patch("requests.Session.get", side_effect=[good, error]):
            mq = ticker.get_market_query()
        assert "BTC-EUR" in mq
        assert "ETH-BTC" not in mq

    def test_get_last_ticker_bid(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in GEMINI_PAIRS]
        with patch("requests.Session.get", side_effect=responses):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("b", market_query=mq)
        assert df["BTC-EUR"].iloc[0] == pytest.approx(59990.0)


# ═══════════════════════════════════════════════════════════════════════════════
# MEXCTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestMEXCTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.mexcticker import MEXCTicker
        return MEXCTicker(pairs_yaml=_yaml_with_pairs(tmp_path, MEXC_PAIRS))

    def _24hr_response(self):
        """MEXC /ticker/24hr response – single request with all fields."""
        return [
            {"symbol": "BTCUSDT",  "lastPrice": "60000.00", "askPrice": "60010.00",
             "bidPrice": "59990.00", "volume": "1234.5"},
            {"symbol": "ETHBTC",   "lastPrice": "0.050",    "askPrice": "0.0501",
             "bidPrice": "0.0499", "volume": "5000.0"},
            {"symbol": "OTHERUSD", "lastPrice": "1.0",      "askPrice": "1.01",
             "bidPrice": "0.99",   "volume": "9999.0"},
        ]

    def test_get_market_query_one_request(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())) as mock_get:
            ticker.get_market_query()
        assert mock_get.call_count == 1

    def test_get_market_query_keyed_by_unified(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())):
            mq = ticker.get_market_query()
        # Keys must be unified names ("BTC-USDT"), not exchange symbols ("BTCUSDT")
        assert set(mq.keys()) == set(MEXC_PAIRS)
        assert mq["BTC-USDT"]["c"] == pytest.approx(60000.0)
        assert mq["BTC-USDT"]["a"] == pytest.approx(60010.0)
        assert mq["BTC-USDT"]["b"] == pytest.approx(59990.0)
        assert mq["BTC-USDT"]["v"] == pytest.approx(1234.5)

    def test_unknown_pair_excluded(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())):
            mq = ticker.get_market_query()
        assert "OTHERUSD" not in mq
        assert "OTHER-USD" not in mq

    def test_http_error_returns_empty(self, tmp_path):
        ticker = self._make(tmp_path)
        error = _mock_response({}, status_code=500)
        with patch("requests.Session.get", return_value=error):
            mq = ticker.get_market_query()
        assert mq == {}

    def test_get_last_ticker_ask(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("a", market_query=mq)
        assert df["BTC-USDT"].iloc[0] == pytest.approx(60010.0)

    def test_get_last_ticker_volume(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("v", market_query=mq)
        assert df["BTC-USDT"].iloc[0] == pytest.approx(1234.5)

    def test_timestamp_set(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.Session.get", return_value=_mock_response(self._24hr_response())):
            ticker.get_market_query()
        assert ticker.timestamp_last_fetch is not None
