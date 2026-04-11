"""Option B – Time-Series Momentum strategy.

The core idea: an asset that has been rising over the past N hours/days is more
likely to keep rising than to reverse.  This is the single-asset (time-series)
flavour of momentum – appropriate when data for only one pair is available.

Mechanics
---------
* **Entry signal**: the rolling N-period return is above a minimum threshold,
  confirming a meaningful upswing (not just noise).
* **Exit signal**: the rolling return drops below a (possibly negative) exit
  threshold, meaning the momentum has stalled or reversed.  An ATR trailing
  stop provides an additional hard-floor exit to cap losses.
* **Rebalance cooldown**: after entering or exiting, a minimum holding period
  prevents rapid in-and-out flipping on volatile but trendless price action.

Why it works in crypto
----------------------
Crypto markets exhibit strong momentum over multi-hour to multi-day windows.
When Bitcoin or a major altcoin builds a sustained positive return over several
hours, it tends to attract further buying (retail FOMO, breakout traders),
reinforcing the trend.  The strategy harvests this by staying long only when
the evidence for an ongoing trend is clear.

Parameters
----------
lookback_period : int
    Window in minutes over which the return is measured.  Default 240 (4 h).
entry_threshold : float
    Minimum return (as a decimal fraction) required to enter.
    Default 0.02 (= 2 %).
exit_threshold : float
    Return level below which the position is closed.
    Default -0.005 (= -0.5 %).
atr_period : int
    ATR estimation window in minutes.  Default 60.
atr_multiplier : float
    Trailing-stop distance in ATR multiples.  Default 2.5.
min_holding_bars : int
    Minimum number of bars to hold after a trade before signalling again.
    Default 60 (= 1 h).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Time-series momentum: go long when N-period return exceeds threshold.

    Grid-search parameters::

        param_grid = {
            "lookback_period":  [120, 240, 480],
            "entry_threshold":  [0.01, 0.02, 0.03],
            "atr_multiplier":   [2.0, 2.5, 3.0],
        }
    """

    @property
    def name(self) -> str:
        return "momentum"

    @property
    def required_dropna_cols(self) -> list[str]:
        return ["_momentum", "_atr"]

    # ── Setup ─────────────────────────────────────────────────────────────────

    def setup(self, pair: str, **kwargs) -> None:
        super().setup(pair)
        self._atr_multiplier:   float = float(kwargs.get("atr_multiplier",  2.5))
        self._min_holding_bars: int   = int(kwargs.get("min_holding_bars",  60))

    # ── Indicators ────────────────────────────────────────────────────────────

    def add_indicators(
        self,
        pv: pd.DataFrame,
        dataloader,
        **kwargs,
    ) -> pd.DataFrame:
        lookback_period = int(kwargs.get("lookback_period", 240))
        atr_period      = int(kwargs.get("atr_period",       60))

        close = dataloader.ticker_current[self.pair]

        # ── Momentum: rolling N-bar return ────────────────────────────────────
        # shift(N) gives us the price N minutes ago; the result is the
        # percentage return over that window.
        shifted = close.shift(lookback_period)
        pv["_momentum"] = (close - shifted) / shifted

        # ── ATR approximation (same as ImprovedMACrossover) ───────────────────
        returns = close.pct_change()
        atr_pct = returns.abs().rolling(f"{atr_period}min").mean()
        pv["_atr"] = (atr_pct * close).bfill()

        # ── 200-period daily EMA for structural trend context (optional) ──────
        close_1h     = close.resample("1h").last()
        ema_200_1h   = close_1h.ewm(span=200, adjust=False).mean()
        pv["_trend_ema"] = ema_200_1h.reindex(pv.index, method="ffill")

        return pv

    # ── Per-bar signal logic ──────────────────────────────────────────────────

    def on_bar(
        self,
        idx: int,
        row: pd.Series,
        pv: pd.DataFrame,
        current_position: str,
        state: dict,
    ) -> tuple[Optional[str], dict]:
        if idx == 0:
            return None, state

        momentum       = row.get("_momentum")
        current_price  = row[self.pair]
        atr_val        = row.get("_atr", 0) or 0
        atr_multiplier = state.get("atr_multiplier", self._atr_multiplier)

        if pd.isna(momentum) or pd.isna(current_price):
            return None, state

        # Respect minimum holding period after any trade
        bars_since_trade = state.get("bars_since_trade", self._min_holding_bars)
        if bars_since_trade < self._min_holding_bars:
            state["bars_since_trade"] = bars_since_trade + 1

            # Still check the trailing stop even during cooldown
            if current_position == "in":
                trailing_stop    = state.get("trailing_stop", 0.0)
                peak_since_entry = state.get("peak_since_entry", current_price)

                if current_price > peak_since_entry:
                    peak_since_entry = current_price
                if atr_val > 0:
                    candidate = peak_since_entry - atr_multiplier * atr_val
                    trailing_stop = max(trailing_stop, candidate)
                state["trailing_stop"]    = trailing_stop
                state["peak_since_entry"] = peak_since_entry

                if trailing_stop > 0 and current_price < trailing_stop:
                    state["trailing_stop"]    = 0.0
                    state["peak_since_entry"] = 0.0
                    state["bars_since_trade"] = 0
                    return "sell", state

            return None, state

        # ── Retrieve thresholds (allow per-run override) ──────────────────────
        entry_threshold = state.get("entry_threshold", 0.02)
        exit_threshold  = state.get("exit_threshold", -0.005)

        # ── EXIT ──────────────────────────────────────────────────────────────
        if current_position == "in":
            trailing_stop    = state.get("trailing_stop", 0.0)
            peak_since_entry = state.get("peak_since_entry", current_price)

            if current_price > peak_since_entry:
                peak_since_entry = current_price
            if atr_val > 0:
                candidate     = peak_since_entry - atr_multiplier * atr_val
                trailing_stop = max(trailing_stop, candidate)
            state["trailing_stop"]    = trailing_stop
            state["peak_since_entry"] = peak_since_entry

            stop_hit     = (trailing_stop > 0 and current_price < trailing_stop)
            momentum_off = (momentum < exit_threshold)

            if stop_hit or momentum_off:
                state["trailing_stop"]    = 0.0
                state["peak_since_entry"] = 0.0
                state["bars_since_trade"] = 0
                return "sell", state

        # ── ENTRY ─────────────────────────────────────────────────────────────
        if current_position == "out" and momentum > entry_threshold:
            state["atr_multiplier"]   = atr_multiplier
            state["entry_threshold"]  = entry_threshold
            state["exit_threshold"]   = exit_threshold
            state["peak_since_entry"] = current_price
            state["trailing_stop"] = (
                current_price - atr_multiplier * atr_val
                if atr_val > 0 else 0.0
            )
            state["bars_since_trade"] = 0
            return "buy", state

        return None, state
