"""SMA crossover signal generator for live trading.

Maintains a rolling price buffer and emits BUY / SELL / HOLD signals based on
the Moving Average Golden Cross / Death Cross pattern.

Signal logic (identical to BacktestEngine, but online/streaming):
- Golden Cross: short SMA crosses *above* long SMA → BUY
- Death  Cross: short SMA crosses *below* long SMA → SELL
- No signal is emitted until ``min_prices`` data points have been collected
  (avoids look-ahead bias on warm-up).
"""
from __future__ import annotations

import logging
from collections import deque
from enum import Enum, auto
from typing import Optional


class Signal(Enum):
    BUY  = auto()
    SELL = auto()
    HOLD = auto()


class SignalGenerator:
    """Online SMA crossover detector.

    Args:
        window_short: Short SMA window (number of price ticks).
        window_long:  Long SMA window (number of price ticks).
        min_prices:   Minimum ticks before a signal can be emitted.
                      Defaults to ``window_long + 10``.
    """

    def __init__(
        self,
        window_short: int,
        window_long: int,
        min_prices: Optional[int] = None,
    ) -> None:
        if window_short >= window_long:
            raise ValueError(
                f"window_short ({window_short}) must be < window_long ({window_long})"
            )
        self.window_short = window_short
        self.window_long  = window_long
        self.min_prices   = min_prices if min_prices is not None else window_long + 10

        # Rolling buffer: keep the last window_long prices for SMA computation
        self._prices: deque[float] = deque(maxlen=window_long)
        # Separate counter for total prices seen (buffer is capped at window_long)
        self._total_seen: int = 0

        # Previous SMA values (needed to detect the cross)
        self._prev_short: Optional[float] = None
        self._prev_long:  Optional[float] = None

        self.logger = logging.getLogger(__name__)

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, price: float) -> Signal:
        """Feed a new price and return the resulting signal.

        Args:
            price: Latest ``c`` (last traded price) from the ticker.

        Returns:
            ``Signal.BUY``, ``Signal.SELL``, or ``Signal.HOLD``.
        """
        self._prices.append(price)
        self._total_seen += 1

        if self._total_seen < self.min_prices:
            self.logger.debug(
                f"Warming up: {len(self._prices)}/{self.min_prices} prices collected"
            )
            return Signal.HOLD

        curr_short = self._sma(self.window_short)
        curr_long  = self._sma(self.window_long)

        signal = Signal.HOLD

        if self._prev_short is not None and self._prev_long is not None:
            golden_cross = (self._prev_short <= self._prev_long) and (curr_short > curr_long)
            death_cross  = (self._prev_short >= self._prev_long) and (curr_short < curr_long)

            if golden_cross:
                signal = Signal.BUY
                self.logger.info(
                    f"GOLDEN CROSS | short_sma={curr_short:.4f} > long_sma={curr_long:.4f}"
                )
            elif death_cross:
                signal = Signal.SELL
                self.logger.info(
                    f"DEATH CROSS  | short_sma={curr_short:.4f} < long_sma={curr_long:.4f}"
                )
            else:
                self.logger.debug(
                    f"HOLD | short_sma={curr_short:.4f}  long_sma={curr_long:.4f}  price={price:.4f}"
                )

        self._prev_short = curr_short
        self._prev_long  = curr_long
        return signal

    @property
    def n_prices(self) -> int:
        """Total number of prices seen (includes prices that rolled off the buffer)."""
        return self._total_seen

    @property
    def is_warmed_up(self) -> bool:
        """True once enough prices have been collected for a reliable signal."""
        return self._total_seen >= self.min_prices

    # ── Internals ─────────────────────────────────────────────────────────────

    def _sma(self, window: int) -> float:
        """Simple moving average of the last ``window`` prices."""
        prices = list(self._prices)
        return sum(prices[-window:]) / window
