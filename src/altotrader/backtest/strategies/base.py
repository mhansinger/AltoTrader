"""Abstract base class for all backtest strategies.

Every strategy must implement three methods:

* ``setup``          – called once before the backtest loop with the pair name and
                       user-supplied parameters; store anything that on_bar will need.
* ``add_indicators`` – attach all required indicator columns to ``portfolio_view``.
* ``on_bar``         – called bar-by-bar during the loop; returns a ('buy'/'sell'/None)
                       signal and an updated state dict for cross-bar memory.

The engine handles all order execution (enter_market / exit_market); strategies only
decide *when* to signal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseStrategy(ABC):
    """Abstract base for every backtest strategy."""

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short human-readable identifier, e.g. 'ema_crossover'."""
        ...

    # ── Columns that must be non-NaN before the loop starts ──────────────────

    @property
    def required_dropna_cols(self) -> list[str]:
        """List of indicator column names that serve as the warm-up guard.

        The backtest loop skips all rows where *any* of these columns is NaN,
        so the strategy never sees incomplete indicator values.  Override this
        to list whatever your strategy adds in add_indicators().
        """
        return []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def setup(self, pair: str, **kwargs) -> None:
        """Store run-level config before add_indicators is called.

        Args:
            pair:    Unified pair string, e.g. ``'BTC-EUR'``.
            **kwargs: Strategy-specific parameters passed by the caller.
        """
        self.pair = pair

    @abstractmethod
    def add_indicators(
        self,
        pv: pd.DataFrame,
        dataloader,
        **kwargs,
    ) -> pd.DataFrame:
        """Compute indicators and attach them as columns to *pv*.

        Args:
            pv:         The portfolio_view DataFrame (already contains price +
                        ask/bid/volume columns).  Add indicator columns directly
                        and return the modified DataFrame.
            dataloader: DataLoader instance; use its ticker_* attributes for
                        raw price data.
            **kwargs:   Strategy-specific parameters (e.g. periods, thresholds).

        Returns:
            The modified ``pv`` DataFrame.
        """
        ...

    @abstractmethod
    def on_bar(
        self,
        idx: int,
        row: pd.Series,
        pv: pd.DataFrame,
        current_position: str,
        state: dict,
    ) -> tuple[Optional[str], dict]:
        """Generate a trading signal for the current bar.

        Called *after* the pending order from the previous bar has been
        executed, so ``current_position`` reflects the live state.

        Args:
            idx:              Integer row position within the valid (dropna'd)
                              slice of portfolio_view.
            row:              The current bar as a Series (pv.iloc[idx]).
            pv:               The full (valid) portfolio_view slice; use
                              ``pv.iloc[idx-1]`` etc. for lookback.
            current_position: ``'in'`` or ``'out'`` after today's execution.
            state:            Mutable dict for cross-bar memory (e.g. trailing
                              stop level, entry price, peak).

        Returns:
            ``(signal, state)`` where *signal* is ``'buy'``, ``'sell'``, or
            ``None``, and *state* is the (possibly updated) state dict.
        """
        ...
