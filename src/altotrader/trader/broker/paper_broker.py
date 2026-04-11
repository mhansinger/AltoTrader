"""Paper trading broker – no real orders, simulates execution locally."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from altotrader.trader.broker.base_broker import BaseBroker, OrderResult
from altotrader.trader.config import TradingConfig


class PaperBroker(BaseBroker):
    """Simulates buy/sell orders using live prices.

    Fees and slippage are applied identically to the real brokers so that
    paper trading results are directly comparable.

    Args:
        config: TradingConfig with fee/slippage parameters and initial_invest.
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Virtual balances: quote currency starts with initial_invest, base with 0
        self._balance: dict[str, float] = {
            config.quote_currency: config.initial_invest,
            config.base_currency: 0.0,
        }
        self.logger.info(
            f"[PAPER] PaperBroker initialised | "
            f"{config.quote_currency}={config.initial_invest:.2f}"
        )

    # ── BaseBroker interface ──────────────────────────────────────────────────

    def buy(self, pair: str, quote_amount: float, price: float) -> OrderResult:
        """Simulate a market buy. Uses taker fee + slippage.

        Args:
            pair:         e.g. ``"BTC-EUR"``
            quote_amount: EUR/USDT to spend (before fees).
            price:        Ask price used for execution.
        """
        exec_price   = price * (1 + self.config.slippage_pct)
        fee          = quote_amount * self.config.taker_fee
        net_spend    = quote_amount - fee
        base_bought  = net_spend / exec_price

        available = self._balance.get(self.config.quote_currency, 0.0)
        if quote_amount > available:
            raise ValueError(
                f"[PAPER] Insufficient {self.config.quote_currency}: "
                f"need {quote_amount:.4f}, have {available:.4f}"
            )

        self._balance[self.config.quote_currency] -= quote_amount
        self._balance[self.config.base_currency]  = (
            self._balance.get(self.config.base_currency, 0.0) + base_bought
        )

        result = OrderResult(
            order_id=str(uuid.uuid4()),
            pair=pair,
            side="buy",
            price=exec_price,
            base_amount=base_bought,
            quote_amount=quote_amount,
            fee=fee,
            timestamp=datetime.now(timezone.utc),
        )
        self.logger.info(
            f"[PAPER] BUY  {base_bought:.6f} {self.config.base_currency} "
            f"@ {exec_price:.4f} | fee={fee:.4f} | "
            f"balance: {self.config.quote_currency}={self._balance[self.config.quote_currency]:.4f}"
        )
        return result

    def sell(self, pair: str, base_amount: float, price: float) -> OrderResult:
        """Simulate a market sell. Uses maker fee + slippage.

        Args:
            pair:        e.g. ``"BTC-EUR"``
            base_amount: BTC/ETH amount to sell.
            price:       Bid price used for execution.
        """
        exec_price   = price * (1 - self.config.slippage_pct)
        gross_quote  = base_amount * exec_price
        fee          = gross_quote * self.config.maker_fee
        net_quote    = gross_quote - fee

        available = self._balance.get(self.config.base_currency, 0.0)
        if base_amount > available + 1e-10:
            raise ValueError(
                f"[PAPER] Insufficient {self.config.base_currency}: "
                f"need {base_amount:.8f}, have {available:.8f}"
            )

        self._balance[self.config.base_currency]  -= base_amount
        self._balance[self.config.quote_currency]  = (
            self._balance.get(self.config.quote_currency, 0.0) + net_quote
        )

        result = OrderResult(
            order_id=str(uuid.uuid4()),
            pair=pair,
            side="sell",
            price=exec_price,
            base_amount=base_amount,
            quote_amount=net_quote,
            fee=fee,
            timestamp=datetime.now(timezone.utc),
        )
        self.logger.info(
            f"[PAPER] SELL {base_amount:.6f} {self.config.base_currency} "
            f"@ {exec_price:.4f} | fee={fee:.4f} | "
            f"balance: {self.config.quote_currency}={self._balance[self.config.quote_currency]:.4f}"
        )
        return result

    def get_balance(self, currency: str) -> float:
        return self._balance.get(currency, 0.0)

    def cancel_order(self, order_id: str) -> bool:
        # Paper broker has no open orders
        return True
