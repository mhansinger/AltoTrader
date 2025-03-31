import pytest
from unittest.mock import patch
from altotrader.krakenticker import KrakenTicker


@pytest.fixture
def ticker():
    """Fixture to create a KrakenTicker instance."""
    return KrakenTicker(asset1="XETH", asset2="ZEUR")


@patch("altotrader.krakenticker.krakenex.API.query_public")
def test_market_price_success(mock_query_public, ticker):
    """Test market_price() when the API returns a valid response."""
    mock_query_public.return_value = {
        "error": [],
        "result": {
            "XETHZEUR": {
                "c": ["3500.12", "1.5"]  # ["last trade price", "lot volume"]
            }
        }
    }

    price = ticker.market_price()
    assert price == 3500.12


@patch("altotrader.krakenticker.krakenex.API.query_public")
def test_market_price_api_error(mock_query_public, ticker):
    """Test market_price() when Kraken API returns an error."""
    mock_query_public.return_value = {
        "error": ["Invalid request"]
    }

    price = ticker.market_price()
    assert price is None


@patch("altotrader.krakenticker.krakenex.API.query_public")
def test_market_price_invalid_response_structure(mock_query_public, ticker):
    """Test market_price() when API response is missing expected fields."""
    mock_query_public.return_value = {
        "error": [],
        "result": {}  # Missing expected trading pair key
    }

    price = ticker.market_price()
    assert price is None


@patch("altotrader.krakenticker.krakenex.API.query_public")
def test_market_price_missing_price_data(mock_query_public, ticker):
    """Test market_price() when API response does not contain 'c' key."""
    mock_query_public.return_value = {
        "error": [],
        "result": {
            "XETHZEUR": {}  # Missing 'c' key
        }
    }

    price = ticker.market_price()
    assert price is None
