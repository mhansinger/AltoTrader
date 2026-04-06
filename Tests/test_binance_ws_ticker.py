"""Tests for BinanceWsTicker.

All WebSocket network interactions are mocked.  Tests focus on:
  - _on_message() correctly parses valid 24hrTicker events
  - get_market_query() returns the cached price snapshot
  - get_last_ticker() returns a well-formed DataFrame
  - Sanity checks: non-positive prices, crossed market, wrong event type,
    wrong symbol, malformed JSON
  - Proactive 24 h session reconnect
"""
from __future__ import annotations

import json
import os
import time
import threading
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

MOCK_YAML = os.path.join(os.path.dirname(__file__), "mock_data", "mock_pairs.yaml")

PAIRS = ["BTCEUR", "ETHBTC"]


def _yaml_with_pairs(tmp_path, pairs):
    p = tmp_path / "pairs.yaml"
    p.write_text("items:\n" + "".join(f"  - {x}\n" for x in pairs))
    return str(p)


def _make_ticker(tmp_path, pairs=None):
    from altotrader.ticker.binance_ws_ticker import BinanceWsTicker
    yaml_path = _yaml_with_pairs(tmp_path, pairs or PAIRS)
    return BinanceWsTicker(pairs_yaml=yaml_path)


def _ticker_msg(symbol: str, c: str, a: str, b: str) -> str:
    """Build a valid combined-stream 24hrTicker message."""
    return json.dumps({
        "stream": f"{symbol.lower()}@ticker",
        "data": {
            "e": "24hrTicker",
            "s": symbol,
            "c": c,
            "a": a,
            "b": b,
        },
    })


# ── get_market_query before any data ─────────────────────────────────────────

def test_get_market_query_empty_before_start(tmp_path):
    ticker = _make_ticker(tmp_path)
    assert ticker.get_market_query() == {}


# ── _on_message – valid messages ──────────────────────────────────────────────

class TestOnMessageValid:
    def test_single_pair_stored(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        assert "BTCEUR" in ticker._prices
        assert ticker._prices["BTCEUR"]["c"] == pytest.approx(60000.0)
        assert ticker._prices["BTCEUR"]["a"] == pytest.approx(60010.0)
        assert ticker._prices["BTCEUR"]["b"] == pytest.approx(59990.0)

    def test_two_pairs_stored_independently(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        ticker._on_message(None, _ticker_msg("ETHBTC", "0.050", "0.0501", "0.0499"))
        assert set(ticker._prices.keys()) == {"BTCEUR", "ETHBTC"}

    def test_price_updated_on_second_message(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        ticker._on_message(None, _ticker_msg("BTCEUR", "61000", "61010", "60990"))
        assert ticker._prices["BTCEUR"]["c"] == pytest.approx(61000.0)


# ── _on_message – sanity/validation checks ────────────────────────────────────

class TestOnMessageValidation:
    def test_unknown_symbol_ignored(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("XYZABC", "100", "101", "99"))
        assert "XYZABC" not in ticker._prices

    def test_wrong_event_type_ignored(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        msg = json.dumps({
            "stream": "btceur@kline",
            "data": {"e": "kline", "s": "BTCEUR", "c": "60000", "a": "60010", "b": "59990"},
        })
        ticker._on_message(None, msg)
        assert ticker._prices == {}

    def test_missing_data_key_ignored(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, json.dumps({"stream": "btceur@ticker"}))
        assert ticker._prices == {}

    def test_non_positive_price_skipped(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "0", "60010", "59990"))
        assert "BTCEUR" not in ticker._prices

    def test_negative_price_skipped(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "-1", "59990"))
        assert "BTCEUR" not in ticker._prices

    def test_crossed_market_skipped(self, tmp_path):
        """ask < bid is a crossed market – must be rejected."""
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "59900", "60100"))
        assert "BTCEUR" not in ticker._prices

    def test_malformed_json_does_not_raise(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, "not-json{{")
        assert ticker._prices == {}

    def test_missing_price_field_does_not_raise(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        msg = json.dumps({
            "stream": "btceur@ticker",
            "data": {"e": "24hrTicker", "s": "BTCEUR", "c": "60000"},  # missing a, b
        })
        ticker._on_message(None, msg)
        assert "BTCEUR" not in ticker._prices


# ── get_market_query after data ───────────────────────────────────────────────

class TestGetMarketQuery:
    def test_returns_snapshot_with_both_pairs(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        ticker._on_message(None, _ticker_msg("ETHBTC", "0.050", "0.0501", "0.0499"))
        mq = ticker.get_market_query()
        assert set(mq.keys()) == {"BTCEUR", "ETHBTC"}

    def test_snapshot_is_a_copy(self, tmp_path):
        """Modifying the returned dict must not affect the internal cache."""
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        mq = ticker.get_market_query()
        mq["BTCEUR"]["c"] = 0.0
        assert ticker._prices["BTCEUR"]["c"] == pytest.approx(60000.0)

    def test_timestamp_set_after_query(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        ticker._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        ticker.get_market_query()
        assert ticker.timestamp_last_fetch is not None


# ── get_last_ticker ───────────────────────────────────────────────────────────

class TestGetLastTicker:
    def _ticker_with_data(self, tmp_path):
        t = _make_ticker(tmp_path)
        t._on_message(None, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
        t._on_message(None, _ticker_msg("ETHBTC", "0.050", "0.0501", "0.0499"))
        return t

    def test_close_price(self, tmp_path):
        ticker = self._ticker_with_data(tmp_path)
        df = ticker.get_last_ticker("c")
        assert isinstance(df, pd.DataFrame)
        assert df["BTCEUR"].iloc[0] == pytest.approx(60000.0)

    def test_ask_price(self, tmp_path):
        ticker = self._ticker_with_data(tmp_path)
        df = ticker.get_last_ticker("a")
        assert df["BTCEUR"].iloc[0] == pytest.approx(60010.0)

    def test_bid_price(self, tmp_path):
        ticker = self._ticker_with_data(tmp_path)
        df = ticker.get_last_ticker("b")
        assert df["BTCEUR"].iloc[0] == pytest.approx(59990.0)

    def test_shape(self, tmp_path):
        ticker = self._ticker_with_data(tmp_path)
        df = ticker.get_last_ticker("c")
        assert df.shape == (1, len(PAIRS))

    def test_empty_when_no_data(self, tmp_path):
        ticker = _make_ticker(tmp_path)
        df = ticker.get_last_ticker("c")
        assert df.empty

    def test_invalid_entry_raises(self, tmp_path):
        ticker = self._ticker_with_data(tmp_path)
        with pytest.raises(ValueError, match="ticker_entry"):
            ticker.get_last_ticker("x")


# ── Proactive 24 h reconnect ──────────────────────────────────────────────────

def test_reconnect_triggered_when_session_too_old(tmp_path):
    """When connected_at is beyond MAX_SESSION_SEC, _on_message must call ws.close()."""
    from altotrader.ticker.binance_ws_ticker import _MAX_SESSION_SEC
    ticker = _make_ticker(tmp_path)
    mock_ws = MagicMock()
    # Pretend we've been connected for longer than the session limit
    ticker._connected_at = time.monotonic() - _MAX_SESSION_SEC - 1
    ticker._on_message(mock_ws, _ticker_msg("BTCEUR", "60000", "60010", "59990"))
    mock_ws.close.assert_called_once()


# ── WS URL construction ───────────────────────────────────────────────────────

def test_ws_url_contains_all_streams(tmp_path):
    ticker = _make_ticker(tmp_path, ["BTCEUR", "ETHBTC"])
    url = ticker._ws_url()
    assert "btceur@ticker" in url
    assert "ethbtc@ticker" in url
    assert "stream?streams=" in url


# ── Thread safety ─────────────────────────────────────────────────────────────

def test_concurrent_writes_do_not_raise(tmp_path):
    """Simulate concurrent WS updates from multiple threads."""
    ticker = _make_ticker(tmp_path)
    errors = []

    def write():
        for _ in range(50):
            try:
                ticker._on_message(
                    None,
                    _ticker_msg("BTCEUR", "60000", "60010", "59990"),
                )
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=write) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread-safety errors: {errors}"
