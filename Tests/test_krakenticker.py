import pytest
from unittest.mock import patch, Mock
import pandas as pd
from datetime import datetime
import krakenex
import os
from altotrader.ticker.krakenticker import KrakenTicker

# Test the _load_yaml method


def test_load_yaml():
    # Get the path to the mock_pairs.yaml file located in the Tests/ directory
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')

    # Instantiate KrakenTicker with the correct path
    ticker = KrakenTicker(test_file_path)

    # Call the load_yaml method directly (it should have been called in __init__)
    pairs = ticker.load_yaml(test_file_path)

    # Verify that the list returned is correct
    assert pairs == ['XETHZEUR', 'XXBTZEUR']


# # Test the get_market_query method with a successful response


@patch.object(krakenex.API, 'query_public', return_value={"result": {"XETHZEUR": {"c": [1743.55]}}})
def test_get_market_query(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    # Call the method to get the market query
    market_query = ticker.get_market_query()

    # Assert the response contains the expected data
    assert isinstance(market_query, dict)
    assert "XETHZEUR" in market_query
    assert market_query["XETHZEUR"]["c"][0] == 1743.55

# # Test the get_market_price method with a valid response


@patch.object(krakenex.API, 'query_public', return_value={"result": {"XETHZEUR": {"c": [1743.55]}, "XXBTZEUR": {"c": [78230.1]}}})
def test_get_market_price_valid(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    # Call the method to get the market price DataFrame
    df = ticker.get_last_ticker(ticker_entry='c')

    # Assert the returned DataFrame has the expected shape and columns
    assert isinstance(df, pd.DataFrame)
    assert df.shape == (1, 2)  # 1 row, 2 columns (XETHZEUR and XXBTZEUR)
    assert 'XETHZEUR' in df.columns
    assert 'XXBTZEUR' in df.columns
    assert abs(df.index[0] - ticker.current_timestamp()) < pd.Timedelta("1s")
    assert df['XETHZEUR'][0] == 1743.55
    assert df['XXBTZEUR'][0] == 78230.1

# # Test the get_market_price method when no valid data is returned


@patch.object(krakenex.API, 'query_public', return_value={"result": {}})
def test_get_market_price_no_data(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    # Call the method to get the market price DataFrame
    df = ticker.get_last_ticker(ticker_entry='c')

    # Assert the returned DataFrame is empty
    assert df.empty


# # Test the get_market_price method with an error in the API cal
@patch.object(krakenex.API, 'query_public', side_effect=Exception("API call failed"))
def test_get_market_price_error(mock_query_public):
    test_file_path = os.path.join(os.path.dirname(
        __file__), 'mock_data/mock_pairs.yaml')
    ticker = KrakenTicker(test_file_path)

    # Call the method to get the market price DataFrame
    df = ticker.get_last_ticker(ticker_entry='c')

    # Assert the returned DataFrame is empty
    assert df.empty
