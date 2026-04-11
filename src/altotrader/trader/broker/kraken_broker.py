"""Kraken broker – places real limit orders via krakenex.

Order flow:
  1. Place limit buy at ``ask * (1 + slippage)`` / limit sell at ``bid * (1 - slippage)``
  2. Poll order status every 5 s for up to 60 s
  3. Cancel and raise if not filled within timeout

API keys are read from the environment:
  ``KRAKEN_API_KEY`` and ``KRAKEN_API_SECRET``
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone

import krakenex

from altotrader.trader.broker.base_broker import BaseBroker, OrderResult
from altotrader.trader.config import TradingConfig

# Kraken pair mapping (unified → Kraken REST symbol)
# We reuse the logic from KrakenTicker._to_exchange_pair
_KRAKEN_PAIR_MAP: dict[str, str] = {
    "BTC-EUR":  "XXBTZEUR",
    "BTC-USD":  "XXBTZUSD",
    "ETH-EUR":  "XETHZEUR",
    "ETH-USD":  "XETHZUSD",
    "ETH-BTC":  "XETHXXBT",
    "XRP-EUR":  "XXRPZEUR",
    "XRP-USD":  "XXRPZUSD",
    "SOL-EUR":  "SOLEUR",
    "SOL-USD":  "SOLUSD",
    "DOGE-EUR": "DOGEEUR",
    "DOGE-USD": "DOGEUSD",
}

_FILL_POLL_INTERVAL = 5    # seconds between status checks
_FILL_TIMEOUT       = 60   # seconds before we cancel and give up


class KrakenBroker(BaseBroker):
    """Places real limit orders on Kraken.

    Args:
        config: TradingConfig (fee/slippage parameters used for execution price).
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

        api_key    = os.environ.get("KRAKEN_API_KEY", "")
        api_secret = os.environ.get("KRAKEN_API_SECRET", "")
        if not api_key or not api_secret:
            raise EnvironmentError(
                "KRAKEN_API_KEY and KRAKEN_API_SECRET must be set for live trading."
            )

        self._api = krakenex.API(key=api_key, secret=api_secret)

    # ── BaseBroker interface ──────────────────────────────────────────────────

    def buy(self, pair: str, quote_amount: float, price: float) -> OrderResult:
        """Place a limit buy order at ``price * (1 + slippage)``."""
        ex_pair    = self._to_kraken_pair(pair)
        limit_price = round(price * (1 + self.config.slippage_pct), 5)
        volume     = quote_amount / limit_price  # approximate base amount

        response = self._api.query_private("AddOrder", {
            "pair":      ex_pair,
            "type":      "buy",
            "ordertype": "limit",
            "price":     str(limit_price),
            "volume":    f"{volume:.8f}",
        })
        self._raise_for_error(response)

        order_id = response["result"]["txid"][0]
        self.logger.info(
            f"Kraken BUY limit placed | pair={ex_pair} price={limit_price} "
            f"vol={volume:.8f} | txid={order_id}"
        )

        filled = self._wait_for_fill(order_id)
        fee    = quote_amount * self.config.taker_fee
        return OrderResult(
            order_id=order_id,
            pair=pair,
            side="buy",
            price=limit_price,
            base_amount=filled.get("vol_exec", volume),
            quote_amount=quote_amount,
            fee=fee,
            timestamp=datetime.now(timezone.utc),
            raw=response,
        )

    def sell(self, pair: str, base_amount: float, price: float) -> OrderResult:
        """Place a limit sell order at ``price * (1 - slippage)``."""
        ex_pair    = self._to_kraken_pair(pair)
        limit_price = round(price * (1 - self.config.slippage_pct), 5)

        response = self._api.query_private("AddOrder", {
            "pair":      ex_pair,
            "type":      "sell",
            "ordertype": "limit",
            "price":     str(limit_price),
            "volume":    f"{base_amount:.8f}",
        })
        self._raise_for_error(response)

        order_id   = response["result"]["txid"][0]
        self.logger.info(
            f"Kraken SELL limit placed | pair={ex_pair} price={limit_price} "
            f"vol={base_amount:.8f} | txid={order_id}"
        )

        filled     = self._wait_for_fill(order_id)
        gross      = base_amount * limit_price
        fee        = gross * self.config.maker_fee
        return OrderResult(
            order_id=order_id,
            pair=pair,
            side="sell",
            price=limit_price,
            base_amount=base_amount,
            quote_amount=gross - fee,
            fee=fee,
            timestamp=datetime.now(timezone.utc),
            raw=response,
        )

    def get_balance(self, currency: str) -> float:
        response = self._api.query_private("Balance")
        self._raise_for_error(response)
        balances = response.get("result", {})
        # Kraken uses e.g. "ZEUR" for EUR, "XXBT" for BTC
        kraken_key = self._to_kraken_currency(currency)
        return float(balances.get(kraken_key, 0.0))

    def cancel_order(self, order_id: str) -> bool:
        response = self._api.query_private("CancelOrder", {"txid": order_id})
        if response.get("error"):
            self.logger.warning(f"Cancel failed for {order_id}: {response['error']}")
            return False
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _wait_for_fill(self, order_id: str) -> dict:
        """Poll until the order is fully filled or timeout. Cancel if timeout."""
        deadline = time.time() + _FILL_TIMEOUT
        while time.time() < deadline:
            time.sleep(_FILL_POLL_INTERVAL)
            resp = self._api.query_private("QueryOrders", {
                "txid": order_id, "trades": False
            })
            if resp.get("error"):
                self.logger.warning(f"QueryOrders error: {resp['error']}")
                continue
            order = resp.get("result", {}).get(order_id, {})
            status = order.get("status", "")
            if status == "closed":
                self.logger.info(f"Order {order_id} filled.")
                return order
            self.logger.debug(f"Order {order_id} status={status}, waiting...")

        self.logger.warning(f"Order {order_id} not filled within {_FILL_TIMEOUT}s – cancelling.")
        self.cancel_order(order_id)
        raise TimeoutError(f"Kraken order {order_id} not filled within {_FILL_TIMEOUT}s")

    @staticmethod
    def _to_kraken_pair(pair: str) -> str:
        """Convert unified pair to Kraken REST symbol."""
        if pair in _KRAKEN_PAIR_MAP:
            return _KRAKEN_PAIR_MAP[pair]
        # Fallback: remove hyphen and uppercase
        return pair.replace("-", "").upper()

    @staticmethod
    def _to_kraken_currency(currency: str) -> str:
        """Map unified currency code to Kraken balance key."""
        _MAP = {"EUR": "ZEUR", "USD": "ZUSD", "BTC": "XXBT", "ETH": "XETH"}
        return _MAP.get(currency, currency)

    @staticmethod
    def _raise_for_error(response: dict) -> None:
        errors = response.get("error", [])
        if errors:
            raise RuntimeError(f"Kraken API error: {errors}")
