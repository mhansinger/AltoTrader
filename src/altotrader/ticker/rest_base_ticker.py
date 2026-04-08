"""Shared base for REST-based exchange tickers.

Each subclass only needs to implement ``get_market_query()`` which must return
a dict in the normalised format::

    {
        "<PAIR>": {
            "c": <last/close price as float>,
            "a": <ask price as float>,
            "b": <bid price as float>,
        },
        ...
    }

``get_last_ticker()`` is provided here and works identically for every exchange.

The normalised ``get_market_query()`` dict must contain at least the keys
``c``, ``a``, and ``b`` (float).  Adding ``v`` (24 h base-asset volume) is
optional but recommended – it is stored as a 4th ticker_entry in InfluxDB.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd
import requests
import yaml

from altotrader.logging_config import setup_logging
from altotrader.ticker.baseticker import BaseTicker


class RestBaseTicker(BaseTicker):
    """Abstract base for tickers that poll a REST endpoint.

    Args:
        pairs_yaml:  Path to a YAML file listing the trading pairs to track.
        log_dir:     Directory for log files (default: ``'logs'``).
        timeout:     HTTP request timeout in seconds (default: 10).
    """

    #: Override in subclasses – used only for the logger name prefix.
    EXCHANGE: str = "unknown"

    def __init__(self, pairs_yaml: str, log_dir: str = "logs", timeout: int = 10):
        self.pairs_list: List[str] = self.load_yaml(pairs_yaml)
        self.timeout = timeout
        self._timestamp_last_fetch = None

        setup_logging(log_filename=f"{self.EXCHANGE}_ticker.logs", log_dir=log_dir)
        self.logger = logging.getLogger(f"{__name__}.{self.EXCHANGE}")
        self.logger.info(
            f"Initialised {self.EXCHANGE}Ticker with pairs: {self.pairs_list}"
        )

    # ── Pair-format conversion ────────────────────────────────────────────────

    def _to_exchange_pair(self, pair: str) -> str:
        """Convert the unified ``'BTC-EUR'`` format to the exchange-specific symbol.

        The default implementation strips the hyphen separator (``'BTC-EUR'``
        → ``'BTCEUR'``), which works for Binance and MEXC.  Override in
        subclasses that use a different convention.
        """
        return pair.replace("-", "")

    def _exchange_to_unified_map(self) -> Dict[str, str]:
        """Return ``{exchange_symbol: unified_pair}`` for all configured pairs.

        Useful for translating API responses back to the canonical pair name
        used in the YAML file.
        """
        return {self._to_exchange_pair(p): p for p in self.pairs_list}

    # ── HTTP helper ────────────────────────────────────────────────────────────

    def _get(self, url: str, **kwargs) -> dict | list:
        """GET *url* and return parsed JSON.  Raises on HTTP or network errors."""
        resp = requests.get(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ── Shared get_last_ticker ─────────────────────────────────────────────────

    def get_last_ticker(
        self, ticker_entry: str, market_query: Optional[Dict] = None
    ) -> pd.DataFrame:
        """Return a one-row DataFrame with the price for each configured pair.

        Args:
            ticker_entry:  ``'c'`` (close/last), ``'a'`` (ask), or ``'b'`` (bid).
            market_query:  Pre-fetched result from :meth:`get_market_query`.
                           If *None*, fetches fresh data.

        Returns:
            DataFrame with a single timestamp row and one column per pair.
            Empty DataFrame on failure.
        """
        valid_entries = {"c", "a", "b", "v"}
        if ticker_entry not in valid_entries:
            raise ValueError(
                f"Invalid ticker_entry '{ticker_entry}'. Must be one of {valid_entries}."
            )

        if market_query is None:
            market_query = self.get_market_query()
        if not market_query:
            return pd.DataFrame()

        timestamp = self._timestamp_last_fetch
        prices = []

        for pair in self.pairs_list:
            data = market_query.get(pair)
            if not data:
                self.logger.warning(f"No data for pair '{pair}' in market_query")
                continue
            price = data.get(ticker_entry)
            if price is None:
                self.logger.warning(f"Field '{ticker_entry}' missing for pair '{pair}'")
                continue
            prices.append({"timestamp": timestamp, "pair": pair, "price": float(price)})
            self.logger.info(f"{pair} [{ticker_entry}] → {price}")

        if not prices:
            self.logger.warning("No valid prices found for any pair")
            return pd.DataFrame()

        df = pd.DataFrame(prices).pivot(index="timestamp", columns="pair", values="price")
        df.columns.name = None
        return df
