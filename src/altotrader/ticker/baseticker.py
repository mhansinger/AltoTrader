from abc import ABC, abstractmethod
import datetime
from typing import Dict, List
import pandas as pd
import yaml


class BaseTicker(ABC):
    """Abstract base class defining the interface for ticker providers."""

    @abstractmethod
    def __init__(self, config_source: str):
        """Initialize the ticker with configuration.

        Args:
            config_source: Path to config file or other configuration source
        """
        pass

    def load_yaml(self, pairs_yaml: str) -> list[str]:
        with open(pairs_yaml, "r") as file:
            kraken_pairs = yaml.safe_load(file)

        if isinstance(kraken_pairs, dict):
            pairs_list = list(kraken_pairs.values()).pop()
        elif isinstance(kraken_pairs, list):
            pairs_list = kraken_pairs
        else:
            pairs_list = [kraken_pairs]  # Wrap single value in a list
        return pairs_list

    def current_timestamp(self) -> datetime.datetime:
        timestamp = datetime.datetime.now(datetime.timezone.utc)  # .strftime(
        #     "%Y-%m-%d %H:%M:%S"
        # )
        return timestamp

    @property
    def timestamp_last_fetch(self) -> datetime.datetime:
        return self._timestamp_last_fetch

    @timestamp_last_fetch.setter
    def timestamp_last_fetch(self, value: datetime.datetime):
        if not isinstance(value, datetime.datetime):
            raise ValueError("timestamp_last_fetch must be a datetime object.")
        self._timestamp_last_fetch = value

    @abstractmethod
    def get_market_query(self) -> Dict:
        """Fetch raw market data from API.

        Returns:
            Dictionary of raw market data
        """
        pass

    @abstractmethod
    def get_last_ticker(self, ticker_entry: str) -> pd.DataFrame:
        """Get normalized market ticker prices.
        ticker_entry[str]: c for close, a for ask, b for bid
        For XXBTZEUR: EUR bid for 1 BTC

        Returns:
            DataFrame with:
            - Index: timestamp
            - Columns: trading pairs
            - Values: close prices
        """
        pass
