import inspect
import os
import pytest
from unittest.mock import patch, Mock
import pandas as pd
from datetime import datetime

# Tests that use patch.object(krakenex.API, ...) only work when the real
# krakenex package is installed.  In environments where its legacy setup.py
# cannot be built, conftest.py stubs it with a MagicMock and these tests are
# skipped automatically.
#
# inspect.isclass() is True only for real Python classes, not for MagicMock
# attributes, making it a reliable guard.
try:
    import krakenex
    _KRAKENEX_REAL = inspect.isclass(krakenex.API)
except Exception:
    _KRAKENEX_REAL = False

needs_real_krakenex = pytest.mark.skipif(
    not _KRAKENEX_REAL,
    reason="krakenex not installable in this environment (legacy setup.py build issue)"
)

from altotrader.ticker.krakenticker import KrakenTicker

# Pairs in the mock YAML use the unified format
ETH_EUR = "ETH-EUR"
BTC_EUR = "BTC-EUR"

# Corresponding Kraken REST pair names (for mocking the API response)
XETHZEUR = "XETHZEUR"
XXBTZEUR = "XXBTZEUR"


def test_load_yaml():
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')

    ticker = KrakenTicker(test_file_path)
    pairs = ticker.load_yaml(test_file_path)

    # YAML now uses unified format
    assert pairs == [ETH_EUR, BTC_EUR]


@needs_real_krakenex
@patch.object(krakenex.API, 'query_public',
              return_value={"result": {
                  "XETHZEUR": {"c": [1743.55], "v": ["100.0", "850.5"]},
              }})
def test_get_market_query(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    market_query = ticker.get_market_query()

    assert isinstance(market_query, dict)
    # Result must be keyed by the unified pair name
    assert ETH_EUR in market_query
    assert market_query[ETH_EUR]["c"][0] == 1743.55
    # Volume is normalised to 24 h value at index 0
    assert market_query[ETH_EUR]["v"][0] == pytest.approx(850.5)


@needs_real_krakenex
@patch.object(krakenex.API, 'query_public',
              return_value={"result": {
                  "XETHZEUR": {"c": [1743.55], "a": [1744.00], "b": [1743.00], "v": ["100.0", "850.5"]},
                  "XXBTZEUR": {"c": [78230.1], "a": [78250.0], "b": [78210.0], "v": ["50.0",  "412.3"]},
              }})
def test_get_market_price_valid(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    df = ticker.get_last_ticker(ticker_entry='c')

    assert isinstance(df, pd.DataFrame)
    assert df.shape == (1, 2)
    assert ETH_EUR in df.columns
    assert BTC_EUR in df.columns
    assert abs(df.index[0] - ticker.current_timestamp()) < pd.Timedelta("1s")
    assert df[ETH_EUR][0] == 1743.55
    assert df[BTC_EUR][0] == 78230.1


@patch.object(krakenex.API, 'query_public', return_value={"result": {}})
def test_get_market_price_no_data(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    df = ticker.get_last_ticker(ticker_entry='c')

    assert df.empty


@patch.object(krakenex.API, 'query_public', side_effect=Exception("API call failed"))
def test_get_market_price_error(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    df = ticker.get_last_ticker(ticker_entry='c')

    assert df.empty
