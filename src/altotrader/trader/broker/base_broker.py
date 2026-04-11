"""Abstract broker interface.

All exchange brokers and the paper broker implement this interface so that the
TradingEngine can swap between them without any code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OrderResult:
    """Normalised result of a placed order."""
    order_id: str
    pair: str
    side: str            # "buy" or "sell"
    price: float         # actual execution price
    base_amount: float   # base asset quantity (e.g. BTC)
    quote_amount: float  # quote cost including fees (e.g. EUR)
    fee: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    raw: dict = field(default_factory=dict)   # raw exchange response


class BaseBroker(ABC):
    """Abstract base class for all broker implementations."""

    @abstractmethod
    def buy(self, pair: str, quote_amount: float, price: float) -> OrderResult:
        """Place a buy order.

        Args:
            pair:         Unified pair, e.g. ``"BTC-EUR"``.
            quote_amount: How much quote currency (EUR/USDT) to spend.
            price:        Reference price (ask). Used for limit orders or
                          slippage calculation.

        Returns:
            ``OrderResult`` with execution details.
        """

    @abstractmethod
    def sell(self, pair: str, base_amount: float, price: float) -> OrderResult:
        """Place a sell order.

        Args:
            pair:        Unified pair, e.g. ``"BTC-EUR"``.
            base_amount: How much base currency (BTC/ETH) to sell.
            price:       Reference price (bid).

        Returns:
            ``OrderResult`` with execution details.
        """

    @abstractmethod
    def get_balance(self, currency: str) -> float:
        """Return available balance for ``currency`` (e.g. ``"EUR"``, ``"BTC"``)."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled successfully."""
