"""Tests for multi-exchange REST tickers: Binance, Coinbase, Gemini, MEXC.

All HTTP calls are mocked with unittest.mock so no real network access is
needed.  The test suite verifies:
  - get_market_query() returns the normalised {pair: {c, a, b}} dict
  - get_last_ticker() returns a correctly shaped DataFrame for c / a / b
  - Invalid ticker_entry raises ValueError
  - HTTP errors (non-200) result in an empty dict / empty DataFrame
  - Partial failures (one pair missing) are handled gracefully
"""
from __future__ import annotations

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_YAML = os.path.join(os.path.dirname(__file__), "mock_data", "mock_pairs.yaml")

# Pair names used across the tests (must match mock_pairs.yaml)
PAIR1 = "XETHZEUR"
PAIR2 = "XXBTZEUR"

# Exchange-specific pair sets
BINANCE_PAIRS   = ["BTCEUR", "ETHBTC"]
COINBASE_PAIRS  = ["BTC-EUR", "ETH-BTC"]
GEMINI_PAIRS    = ["btceur", "ethbtc"]
MEXC_PAIRS      = ["BTCUSDT", "ETHBTC"]


def _yaml_with_pairs(tmp_path, pairs: list) -> str:
    """Write a temporary YAML file and return its path."""
    p = tmp_path / "pairs.yaml"
    p.write_text("items:\n" + "".join(f"  - {x}\n" for x in pairs))
    return str(p)


def _mock_response(json_data, status_code: int = 200):
    """Build a mock requests.Response."""
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
        yaml_path = _yaml_with_pairs(tmp_path, BINANCE_PAIRS)
        return BinanceTicker(pairs_yaml=yaml_path)

    def _binance_response(self):
        return [
            {"symbol": "BTCEUR", "lastPrice": "60000.00", "askPrice": "60010.00", "bidPrice": "59990.00"},
            {"symbol": "ETHBTC", "lastPrice": "0.050",    "askPrice": "0.0501",    "bidPrice": "0.0499"},
        ]

    def test_get_market_query_returns_normalised_dict(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        assert set(mq.keys()) == set(BINANCE_PAIRS)
        assert mq["BTCEUR"]["c"] == pytest.approx(60000.0)
        assert mq["BTCEUR"]["a"] == pytest.approx(60010.0)
        assert mq["BTCEUR"]["b"] == pytest.approx(59990.0)

    def test_get_last_ticker_close(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("c", market_query=mq)
        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) == set(BINANCE_PAIRS)
        assert df["BTCEUR"].iloc[0] == pytest.approx(60000.0)

    def test_get_last_ticker_ask(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("a", market_query=mq)
        assert df["BTCEUR"].iloc[0] == pytest.approx(60010.0)

    def test_get_last_ticker_bid(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response(self._binance_response())):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("b", market_query=mq)
        assert df["BTCEUR"].iloc[0] == pytest.approx(59990.0)

    def test_invalid_ticker_entry_raises(self, tmp_path):
        ticker = self._make(tmp_path)
        with pytest.raises(ValueError, match="ticker_entry"):
            ticker.get_last_ticker("x", market_query={"BTCEUR": {"c": 1, "a": 1, "b": 1}})

    def test_http_error_returns_empty_dict(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response({}, status_code=500)):
            mq = ticker.get_market_query()
        assert mq == {}

    def test_single_symbol_response_as_dict(self, tmp_path):
        """Binance returns a plain dict (not a list) for single-symbol requests."""
        ticker = self._make(tmp_path)
        single = {"symbol": "BTCEUR", "lastPrice": "60000.00",
                  "askPrice": "60010.00", "bidPrice": "59990.00"}
        # Inject ETHBTC from pairs but response only has BTCEUR
        with patch("requests.get", return_value=_mock_response(single)):
            mq = ticker.get_market_query()
        assert "BTCEUR" in mq

    def test_timestamp_set_after_fetch(self, tmp_path):
        ticker = self._make(tmp_path)
        with patch("requests.get", return_value=_mock_response(self._binance_response())):
            ticker.get_market_query()
        assert ticker.timestamp_last_fetch is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CoinbaseTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoinbaseTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.coinbaseticker import CoinbaseTicker
        yaml_path = _yaml_with_pairs(tmp_path, COINBASE_PAIRS)
        return CoinbaseTicker(pairs_yaml=yaml_path)

    def _response_for(self, pair: str):
        data = {
            "BTC-EUR": {"price": "60000.00", "ask": "60010.00", "bid": "59990.00"},
            "ETH-BTC": {"price": "0.050",    "ask": "0.0501",   "bid": "0.0499"},
        }
        return data[pair]

    def test_get_market_query_both_pairs(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in COINBASE_PAIRS]
        with patch("requests.get", side_effect=responses):
            mq = ticker.get_market_query()
        assert set(mq.keys()) == set(COINBASE_PAIRS)
        assert mq["BTC-EUR"]["c"] == pytest.approx(60000.0)
        assert mq["BTC-EUR"]["a"] == pytest.approx(60010.0)
        assert mq["BTC-EUR"]["b"] == pytest.approx(59990.0)

    def test_partial_failure_still_returns_good_pairs(self, tmp_path):
        ticker = self._make(tmp_path)
        import requests as req
        good  = _mock_response(self._response_for("BTC-EUR"))
        error = _mock_response({}, status_code=503)
        with patch("requests.get", side_effect=[good, error]):
            mq = ticker.get_market_query()
        assert "BTC-EUR" in mq
        assert "ETH-BTC" not in mq

    def test_get_last_ticker_shape(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in COINBASE_PAIRS]
        with patch("requests.get", side_effect=responses):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("c", market_query=mq)
        assert df.shape == (1, len(COINBASE_PAIRS))

    def test_all_fail_returns_empty(self, tmp_path):
        ticker = self._make(tmp_path)
        errors = [_mock_response({}, status_code=503)] * len(COINBASE_PAIRS)
        with patch("requests.get", side_effect=errors):
            mq = ticker.get_market_query()
        assert mq == {}
        df = ticker.get_last_ticker("c", market_query=mq)
        assert df.empty


# ═══════════════════════════════════════════════════════════════════════════════
# GeminiTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeminiTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.geminiticker import GeminiTicker
        yaml_path = _yaml_with_pairs(tmp_path, GEMINI_PAIRS)
        return GeminiTicker(pairs_yaml=yaml_path)

    def _response_for(self, pair: str):
        data = {
            "btceur": {"last": "60000.00", "ask": "60010.00", "bid": "59990.00"},
            "ethbtc": {"last": "0.050",    "ask": "0.0501",   "bid": "0.0499"},
        }
        return data[pair.lower()]

    def test_get_market_query_normalised(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in GEMINI_PAIRS]
        with patch("requests.get", side_effect=responses):
            mq = ticker.get_market_query()
        assert set(mq.keys()) == set(GEMINI_PAIRS)
        assert mq["btceur"]["c"] == pytest.approx(60000.0)

    def test_uppercase_pairs_preserved(self, tmp_path):
        """Pairs defined in YAML as uppercase should remain uppercase as dict keys."""
        from altotrader.ticker.geminiticker import GeminiTicker
        yaml_path = _yaml_with_pairs(tmp_path, ["BTCEUR"])
        ticker = GeminiTicker(pairs_yaml=yaml_path)
        resp = _mock_response({"last": "60000", "ask": "60010", "bid": "59990"})
        with patch("requests.get", return_value=resp):
            mq = ticker.get_market_query()
        assert "BTCEUR" in mq  # key must match the original YAML spelling

    def test_partial_failure(self, tmp_path):
        ticker = self._make(tmp_path)
        good  = _mock_response(self._response_for("btceur"))
        error = _mock_response({}, status_code=404)
        with patch("requests.get", side_effect=[good, error]):
            mq = ticker.get_market_query()
        assert "btceur" in mq
        assert "ethbtc" not in mq

    def test_get_last_ticker_bid(self, tmp_path):
        ticker = self._make(tmp_path)
        responses = [_mock_response(self._response_for(p)) for p in GEMINI_PAIRS]
        with patch("requests.get", side_effect=responses):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("b", market_query=mq)
        assert df["btceur"].iloc[0] == pytest.approx(59990.0)


# ═══════════════════════════════════════════════════════════════════════════════
# MEXCTicker
# ═══════════════════════════════════════════════════════════════════════════════

class TestMEXCTicker:
    def _make(self, tmp_path):
        from altotrader.ticker.mexcticker import MEXCTicker
        yaml_path = _yaml_with_pairs(tmp_path, MEXC_PAIRS)
        return MEXCTicker(pairs_yaml=yaml_path)

    def _price_response(self):
        return [
            {"symbol": "BTCUSDT", "price": "60000.00"},
            {"symbol": "ETHBTC",  "price": "0.050"},
            {"symbol": "OTHERXYZ", "price": "1.0"},  # should be filtered out
        ]

    def _book_response(self):
        return [
            {"symbol": "BTCUSDT", "askPrice": "60010.00", "bidPrice": "59990.00"},
            {"symbol": "ETHBTC",  "askPrice": "0.0501",   "bidPrice": "0.0499"},
            {"symbol": "OTHERXYZ", "askPrice": "1.01",    "bidPrice": "0.99"},
        ]

    def test_get_market_query_two_requests(self, tmp_path):
        ticker = self._make(tmp_path)
        resps = [
            _mock_response(self._price_response()),
            _mock_response(self._book_response()),
        ]
        with patch("requests.get", side_effect=resps) as mock_get:
            mq = ticker.get_market_query()
        assert mock_get.call_count == 2  # one for price, one for bookTicker

    def test_get_market_query_normalised(self, tmp_path):
        ticker = self._make(tmp_path)
        resps = [
            _mock_response(self._price_response()),
            _mock_response(self._book_response()),
        ]
        with patch("requests.get", side_effect=resps):
            mq = ticker.get_market_query()
        assert set(mq.keys()) == set(MEXC_PAIRS)
        assert mq["BTCUSDT"]["c"] == pytest.approx(60000.0)
        assert mq["BTCUSDT"]["a"] == pytest.approx(60010.0)
        assert mq["BTCUSDT"]["b"] == pytest.approx(59990.0)

    def test_unknown_pair_excluded(self, tmp_path):
        """OTHERXYZ is in the API response but not in pairs_yaml – must be excluded."""
        ticker = self._make(tmp_path)
        resps = [
            _mock_response(self._price_response()),
            _mock_response(self._book_response()),
        ]
        with patch("requests.get", side_effect=resps):
            mq = ticker.get_market_query()
        assert "OTHERXYZ" not in mq

    def test_http_error_returns_empty(self, tmp_path):
        ticker = self._make(tmp_path)
        error = _mock_response({}, status_code=500)
        with patch("requests.get", return_value=error):
            mq = ticker.get_market_query()
        assert mq == {}

    def test_get_last_ticker_ask(self, tmp_path):
        ticker = self._make(tmp_path)
        resps = [
            _mock_response(self._price_response()),
            _mock_response(self._book_response()),
        ]
        with patch("requests.get", side_effect=resps):
            mq = ticker.get_market_query()
        df = ticker.get_last_ticker("a", market_query=mq)
        assert df["BTCUSDT"].iloc[0] == pytest.approx(60010.0)

    def test_timestamp_set(self, tmp_path):
        ticker = self._make(tmp_path)
        resps = [
            _mock_response(self._price_response()),
            _mock_response(self._book_response()),
        ]
        with patch("requests.get", side_effect=resps):
            ticker.get_market_query()
        assert ticker.timestamp_last_fetch is not None
