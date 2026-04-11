"""Risk manager – stop-loss, position sizing, and drawdown protection."""
from __future__ import annotations

import logging
from typing import Optional

from altotrader.trader.config import TradingConfig
from altotrader.trader.position_manager import Position


class RiskManager:
    """Centralises all risk checks for a single trading pair.

    Args:
        config: TradingConfig with stop_loss_pct, max_drawdown_pct,
                max_position_pct parameters.
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

        self._peak_portfolio_value: Optional[float] = None
        self._trading_halted: bool = False

    # ── Public API ────────────────────────────────────────────────────────────

    def check_stop_loss(self, position: Position, current_price: float) -> bool:
        """Return True if the stop-loss threshold has been breached.

        Stop-loss fires when:
            (current_price - entry_price) / entry_price < -stop_loss_pct
        """
        loss_pct = (current_price - position.entry_price) / position.entry_price
        if loss_pct < -self.config.stop_loss_pct:
            self.logger.warning(
                f"STOP-LOSS triggered for {position.pair} | "
                f"entry={position.entry_price:.4f} current={current_price:.4f} "
                f"loss={loss_pct*100:.2f}% (limit={self.config.stop_loss_pct*100:.1f}%)"
            )
            return True
        return False

    def position_size(self, available_capital: float, price: float) -> float:
        """Calculate how much quote currency to invest in the next trade.

        Respects ``max_position_pct`` and leaves a small buffer for fees.

        Args:
            available_capital: Available quote balance (e.g. EUR).
            price:             Current ask price (used only for logging).

        Returns:
            Quote amount to invest (≤ available_capital * max_position_pct).
        """
        invest = available_capital * self.config.max_position_pct
        self.logger.debug(
            f"Position size: {invest:.4f} {self.config.quote_currency} "
            f"({self.config.max_position_pct*100:.0f}% of {available_capital:.4f})"
        )
        return invest

    def update_peak(self, portfolio_value: float) -> None:
        """Track the portfolio peak for drawdown calculation.

        Call this once per trading loop iteration with the current total
        portfolio value (cash + holdings at market price).
        """
        if self._peak_portfolio_value is None or portfolio_value > self._peak_portfolio_value:
            self._peak_portfolio_value = portfolio_value

    def check_max_drawdown(self, portfolio_value: float) -> bool:
        """Return True if the portfolio has drawn down beyond the configured limit.

        When triggered, sets an internal flag that halts all trading until the
        bot is restarted (fail-safe behaviour).
        """
        if self._trading_halted:
            return True

        if self._peak_portfolio_value is None or self._peak_portfolio_value <= 0:
            return False

        drawdown = (self._peak_portfolio_value - portfolio_value) / self._peak_portfolio_value
        if drawdown > self.config.max_drawdown_pct:
            self.logger.error(
                f"MAX DRAWDOWN exceeded! drawdown={drawdown*100:.2f}% "
                f"(limit={self.config.max_drawdown_pct*100:.1f}%) – HALTING TRADING."
            )
            self._trading_halted = True
            return True
        return False

    @property
    def is_halted(self) -> bool:
        """True if trading has been halted due to max drawdown."""
        return self._trading_halted
