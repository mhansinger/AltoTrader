"""Binance broker – places real market orders via python-binance.

Market orders are used on Binance because:
- Liquidity is very high → fills are instant at negligible spread
- Taker fee (0.1 %) is low enough that simplicity wins over maker savings
- Avoids complexity of lot-size rounding for limit orders

API keys are read from the environment:
  ``BINANCE_API_KEY`` and ``BINANCE_API_SECRET``
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from altotrader.trader.broker.base_broker import BaseBroker, OrderResult
from altotrader.trader.config import TradingConfig


def _import_binance_client():
    """Lazy import so that missing python-binance doesn't break other code."""
    try:
        from binance.client import Client
        return Client
    except ImportError as exc:
        raise ImportError(
            "python-binance is required for Binance live trading. "
            "Install with: pip install python-binance"
        ) from exc


class BinanceBroker(BaseBroker):
    """Places real market orders on Binance.

    Args:
        config: TradingConfig (fee/slippage parameters + pair info).
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

        api_key    = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")
        if not api_key or not api_secret:
            raise EnvironmentError(
                "BINANCE_API_KEY and BINANCE_API_SECRET must be set for live trading."
            )

        Client = _import_binance_client()
        self._client = Client(api_key, api_secret)

        # Cache exchange info (lot size / step size filters) per pair
        self._filters: dict[str, dict] = {}

    # ── BaseBroker interface ──────────────────────────────────────────────────

    def buy(self, pair: str, quote_amount: float, price: float) -> OrderResult:
        """Place a market buy using ``quoteOrderQty`` (spend exact quote amount)."""
        ex_sym = self._to_binance_symbol(pair)
        # quoteOrderQty lets Binance calculate the base amount automatically
        response = self._client.order_market_buy(
            symbol=ex_sym,
            quoteOrderQty=round(quote_amount, 2),
        )
        return self._parse_response(response, pair, "buy")

    def sell(self, pair: str, base_amount: float, price: float) -> OrderResult:
        """Place a market sell of ``base_amount`` units."""
        ex_sym      = self._to_binance_symbol(pair)
        step_size   = self._get_step_size(ex_sym)
        rounded_qty = self._round_step(base_amount, step_size)

        response = self._client.order_market_sell(
            symbol=ex_sym,
            quantity=rounded_qty,
        )
        return self._parse_response(response, pair, "sell")

    def get_balance(self, currency: str) -> float:
        account = self._client.get_account()
        for asset in account.get("balances", []):
            if asset["asset"] == currency:
                return float(asset["free"])
        return 0.0

    def cancel_order(self, order_id: str) -> bool:
        # Market orders on Binance fill immediately – nothing to cancel
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_response(self, response: dict, pair: str, side: str) -> OrderResult:
        """Convert Binance order response to OrderResult."""
        fills      = response.get("fills", [])
        total_qty  = sum(float(f["qty"])        for f in fills)
        total_quote = sum(float(f["qty"]) * float(f["price"]) for f in fills)
        total_fee  = sum(float(f["commission"]) for f in fills)
        avg_price  = (total_quote / total_qty) if total_qty else float(response.get("price", 0))

        self.logger.info(
            f"Binance {side.upper()} {total_qty:.8f} {self.config.base_currency} "
            f"@ avg {avg_price:.4f} | fee={total_fee:.6f}"
        )
        return OrderResult(
            order_id=str(response.get("orderId", "")),
            pair=pair,
            side=side,
            price=avg_price,
            base_amount=total_qty,
            quote_amount=total_quote,
            fee=total_fee,
            timestamp=datetime.now(timezone.utc),
            raw=response,
        )

    def _get_step_size(self, symbol: str) -> float:
        """Return lot-size step_size for a symbol (cached)."""
        if symbol not in self._filters:
            info = self._client.get_symbol_info(symbol)
            for f in info.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    self._filters[symbol] = f
                    break
        return float(self._filters.get(symbol, {}).get("stepSize", "0.00001"))

    @staticmethod
    def _round_step(qty: float, step: float) -> float:
        """Round qty down to the nearest step_size multiple."""
        if step <= 0:
            return qty
        precision = len(str(step).rstrip("0").split(".")[-1])
        return round(qty - (qty % step), precision)

    @staticmethod
    def _to_binance_symbol(pair: str) -> str:
        """``"BTC-EUR"`` → ``"BTCEUR"``."""
        return pair.replace("-", "").upper()
