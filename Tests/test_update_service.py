"""Tests for TickerUpdateService: retry logic, config validation,
and the write pipeline."""

import pytest
import time
from unittest.mock import MagicMock, patch, call
import pandas as pd
from influxdb_client.client.exceptions import InfluxDBError

from altotrader.database.update_service import TickerUpdateService, _MAX_RETRIES, _RETRY_BASE_DELAY


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_service():
    """Return a TickerUpdateService wired to a mock KrakenTicker."""
    ticker = MagicMock()
    ticker.get_market_query.return_value = {"XXBTZEUR": {"c": [40000.0]}}
    ticker.get_last_ticker.return_value = pd.DataFrame(
        {"XXBTZEUR": [40000.0]},
        index=pd.to_datetime(["2025-01-01 00:00:00"])
    )
    service = TickerUpdateService(ticker, log_dir="logs")
    return service


_VALID_CONFIG = {
    "bucket": "kraken",
    "org":    "testorg",
    "url":    "http://localhost:8086",
    "token":  "testtoken",
}


# ── _fetch_market_query_with_retry ────────────────────────────────────────────

class TestFetchMarketQueryWithRetry:
    def test_returns_result_on_first_success(self):
        service = _make_service()
        result = service._fetch_market_query_with_retry()
        assert result == {"XXBTZEUR": {"c": [40000.0]}}
        assert service.ticker.get_market_query.call_count == 1

    def test_retries_on_empty_result(self):
        service = _make_service()
        service.ticker.get_market_query.side_effect = [
            {},           # fail
            {},           # fail
            {"XXBTZEUR": {"c": [40000.0]}},  # success
        ]
        with patch("altotrader.database.update_service.time.sleep"):
            result = service._fetch_market_query_with_retry()
        assert result == {"XXBTZEUR": {"c": [40000.0]}}
        assert service.ticker.get_market_query.call_count == 3

    def test_returns_empty_dict_after_all_retries_fail(self):
        service = _make_service()
        service.ticker.get_market_query.return_value = {}
        with patch("altotrader.database.update_service.time.sleep"):
            result = service._fetch_market_query_with_retry()
        assert result == {}
        assert service.ticker.get_market_query.call_count == _MAX_RETRIES

    def test_sleep_duration_doubles(self):
        service = _make_service()
        service.ticker.get_market_query.return_value = {}
        sleep_calls = []

        with patch("altotrader.database.update_service.time.sleep",
                   side_effect=lambda s: sleep_calls.append(s)):
            service._fetch_market_query_with_retry()

        # Sleeps: 2, 4, 8  (between 4 attempts = 3 sleeps)
        assert sleep_calls == [
            _RETRY_BASE_DELAY * (2 ** i) for i in range(_MAX_RETRIES - 1)
        ]


# ── _write_points / _write_points_with_retry ─────────────────────────────────

class TestWritePoints:
    def test_returns_false_for_empty_points(self):
        service = _make_service()
        result = service._write_points([], _VALID_CONFIG)
        assert result is False

    def test_returns_false_on_influx_error(self):
        service = _make_service()
        with patch("altotrader.database.update_service.InfluxDBClient") as MockClient:
            mock_ctx = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            mock_ctx.write_api.return_value.write.side_effect = InfluxDBError(
                message="test error"
            )
            from influxdb_client import Point
            pts = [Point("kraken").field("price", 1.0)]
            result = service._write_points(pts, _VALID_CONFIG)
        assert result is False

    def test_returns_false_on_connection_error(self):
        service = _make_service()
        with patch("altotrader.database.update_service.InfluxDBClient") as MockClient:
            MockClient.side_effect = ConnectionError("refused")
            from influxdb_client import Point
            pts = [Point("kraken").field("price", 1.0)]
            result = service._write_points(pts, _VALID_CONFIG)
        assert result is False


class TestWritePointsWithRetry:
    def test_succeeds_on_first_attempt(self):
        service = _make_service()
        service._write_points = MagicMock(return_value=True)
        result = service._write_points_with_retry(["pt"], _VALID_CONFIG)
        assert result is True
        assert service._write_points.call_count == 1

    def test_retries_on_failure(self):
        service = _make_service()
        service._write_points = MagicMock(side_effect=[False, False, True])
        with patch("altotrader.database.update_service.time.sleep"):
            result = service._write_points_with_retry(["pt"], _VALID_CONFIG)
        assert result is True
        assert service._write_points.call_count == 3

    def test_returns_false_after_all_retries_fail(self):
        service = _make_service()
        service._write_points = MagicMock(return_value=False)
        with patch("altotrader.database.update_service.time.sleep"):
            result = service._write_points_with_retry(["pt"], _VALID_CONFIG)
        assert result is False
        assert service._write_points.call_count == _MAX_RETRIES


# ── update_pairs_ticker ───────────────────────────────────────────────────────

class TestUpdatePairsTicker:
    def test_returns_false_on_missing_config(self):
        service = _make_service()
        # No env vars set, no explicit args → config values are None
        result = service.update_pairs_ticker(
            bucket=None, org=None, url=None, token=None
        )
        assert result is False

    def test_returns_false_when_market_query_empty(self):
        service = _make_service()
        service.ticker.get_market_query.return_value = {}
        with patch("altotrader.database.update_service.time.sleep"):
            result = service.update_pairs_ticker(
                bucket="b", org="o", url="http://localhost:8086", token="t"
            )
        assert result is False

    def test_returns_false_when_ticker_data_empty(self):
        service = _make_service()
        service.ticker.get_last_ticker.return_value = pd.DataFrame()
        with patch("altotrader.database.update_service.time.sleep"), \
             patch.object(service, "_write_points_with_retry", return_value=True):
            result = service.update_pairs_ticker(
                bucket="b", org="o", url="http://localhost:8086", token="t"
            )
        assert result is False

    def test_calls_write_with_points_for_all_entries(self):
        service = _make_service()
        written_calls = []

        def fake_write(points, config):
            written_calls.append(len(points))
            return True

        with patch.object(service, "_write_points_with_retry", side_effect=fake_write):
            result = service.update_pairs_ticker(
                bucket="b", org="o", url="http://localhost:8086", token="t"
            )

        assert result is True
        # 3 ticker entries (a, b, c) × 1 pair × 1 timestamp = 3 points total
        assert sum(written_calls) == 3
