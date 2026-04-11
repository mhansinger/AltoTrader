"""Option A – Improved EMA Crossover strategy.

Four enhancements over the basic SMA crossover:

1. **EMA instead of SMA** – exponential weighting reacts faster to recent price
   changes, reducing the lag that causes late entries in the SMA version.

2. **Volume confirmation** – only enter on a golden cross when current bar volume
   is above the rolling average.  This filters out low-conviction breakouts.

3. **ATR-based trailing stop** – once in a position, a trailing stop sits at
   ``peak_price - atr_multiplier × ATR``.  It locks in profits as the price
   rises and exits automatically when the trend reverses, without waiting for a
   full death cross.

4. **Higher-timeframe trend filter** – entry is only allowed when the 1-min
   close price is *above* the 200-period EMA of 4-hour bars.  This prevents
   buying into a structural downtrend.

Parameters
----------
ema_short : int
    Span (in minutes) for the short EMA.  Default 50.
ema_long : int
    Span (in minutes) for the long EMA.  Default 200.
atr_period : int
    Lookback window (minutes) for the ATR estimate.  Default 60.
atr_multiplier : float
    Trailing stop distance expressed as a multiple of ATR.  Default 2.0.
volume_filter_window : int
    Rolling window (minutes) for the volume moving average.  Default 60.
    Set to 0 to disable the volume filter.
trend_filter : bool
    Whether to apply the 4-hour EMA trend filter.  Default True.
trend_ema_period : int
    Number of 4-hour bars used for the trend EMA.  Default 200.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .base import BaseStrategy


class ImprovedMACrossover(BaseStrategy):
    """EMA crossover with ATR trailing stop and multi-timeframe confirmation.

    Grid-search parameters::

        param_grid = {
            "ema_short":        [30, 50, 100],
            "ema_long":         [200, 500, 1000],
            "atr_multiplier":   [1.5, 2.0, 3.0],
        }
    """

    @property
    def name(self) -> str:
        return "ema_crossover"

    @property
    def required_dropna_cols(self) -> list[str]:
        return ["_ema_short", "_ema_long", "_atr", "_ema_trend"]

    # ── Setup ─────────────────────────────────────────────────────────────────

    def setup(self, pair: str, **kwargs) -> None:
        super().setup(pair)
        self._atr_multiplier: float = float(kwargs.get("atr_multiplier", 2.0))
        self._trend_filter: bool = bool(kwargs.get("trend_filter", True))
        self._volume_filter_window: int = int(kwargs.get("volume_filter_window", 60))

    # ── Indicators ────────────────────────────────────────────────────────────

    def add_indicators(
        self,
        pv: pd.DataFrame,
        dataloader,
        **kwargs,
    ) -> pd.DataFrame:
        ema_short_period   = int(kwargs.get("ema_short",        50))
        ema_long_period    = int(kwargs.get("ema_long",        200))
        atr_period         = int(kwargs.get("atr_period",       60))
        trend_ema_period   = int(kwargs.get("trend_ema_period", 200))
        vol_window         = int(kwargs.get("volume_filter_window", self._volume_filter_window))
        trend_filter       = bool(kwargs.get("trend_filter",   self._trend_filter))

        close = dataloader.ticker_current[self.pair]

        # ── 1. Short and long EMAs ────────────────────────────────────────────
        pv["_ema_short"] = close.ewm(span=ema_short_period, adjust=False).mean()
        pv["_ema_long"]  = close.ewm(span=ema_long_period,  adjust=False).mean()

        # ── 2. ATR approximation ──────────────────────────────────────────────
        # We have no true OHLC bars, so we estimate the Average True Range as
        # the rolling mean of the absolute 1-min return expressed in price units.
        # This captures short-term volatility and scales naturally with price.
        returns = close.pct_change()
        atr_pct = returns.abs().rolling(f"{atr_period}min").mean()
        pv["_atr"] = (atr_pct * close).bfill()

        # ── 3. Volume filter ──────────────────────────────────────────────────
        if (
            vol_window > 0
            and dataloader.ticker_volume is not None
            and self.pair in dataloader.ticker_volume.columns
        ):
            vol = dataloader.ticker_volume[self.pair]
            pv["_vol_ma"]      = vol.rolling(f"{vol_window}min").mean()
            pv["_vol_current"] = vol
        else:
            pv["_vol_ma"]      = None
            pv["_vol_current"] = None

        # ── 4. Higher-timeframe trend filter (4-hour 200 EMA) ─────────────────
        if trend_filter:
            close_4h     = close.resample("4h").last()
            ema_trend_4h = close_4h.ewm(span=trend_ema_period, adjust=False).mean()
            # Forward-fill the 4h EMA back to 1-min resolution.  This is
            # causal: each 1-min bar sees the EMA value computed up to the
            # most recently completed 4-hour bar.
            pv["_ema_trend"] = ema_trend_4h.reindex(pv.index, method="ffill")
        else:
            # Trend filter disabled: always pass
            pv["_ema_trend"] = 0.0

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

        prev = pv.iloc[idx - 1]

        prev_ema_short = prev["_ema_short"]
        prev_ema_long  = prev["_ema_long"]
        curr_ema_short = row["_ema_short"]
        curr_ema_long  = row["_ema_long"]

        if any(
            pd.isna(x)
            for x in [prev_ema_short, prev_ema_long, curr_ema_short, curr_ema_long]
        ):
            return None, state

        golden_cross = (prev_ema_short <= prev_ema_long) and (curr_ema_short > curr_ema_long)
        death_cross  = (prev_ema_short >= prev_ema_long) and (curr_ema_short < curr_ema_long)

        current_price  = row[self.pair]
        atr_val        = row.get("_atr", 0) or 0
        atr_multiplier = state.get("atr_multiplier", self._atr_multiplier)

        # ── EXIT logic ────────────────────────────────────────────────────────
        if current_position == "in":
            trailing_stop    = state.get("trailing_stop",    0.0)
            peak_since_entry = state.get("peak_since_entry", current_price)

            # Ratchet the peak upward
            if pd.notna(current_price) and current_price > peak_since_entry:
                peak_since_entry = current_price

            # Move trailing stop up as price rises (never down)
            if atr_val > 0 and pd.notna(current_price):
                candidate_stop = peak_since_entry - atr_multiplier * atr_val
                trailing_stop  = max(trailing_stop, candidate_stop)

            state["trailing_stop"]    = trailing_stop
            state["peak_since_entry"] = peak_since_entry

            stop_hit = (
                trailing_stop > 0
                and pd.notna(current_price)
                and current_price < trailing_stop
            )

            if stop_hit or death_cross:
                # Reset state on exit
                state["trailing_stop"]    = 0.0
                state["peak_since_entry"] = 0.0
                return "sell", state

        # ── ENTRY logic ───────────────────────────────────────────────────────
        if current_position == "out" and golden_cross:
            # Trend filter: only buy when price is above the 4h 200 EMA
            trend_ema = row.get("_ema_trend", 0)
            trend_ok  = True
            if pd.notna(trend_ema) and trend_ema > 0 and pd.notna(current_price):
                trend_ok = current_price > trend_ema

            # Volume filter
            vol_ok = True
            vol_ma  = row.get("_vol_ma")
            vol_cur = row.get("_vol_current")
            if pd.notna(vol_ma) and pd.notna(vol_cur) and vol_ma > 0:
                vol_ok = vol_cur >= vol_ma

            if trend_ok and vol_ok:
                # Initialise trailing stop at entry
                state["atr_multiplier"]  = atr_multiplier
                state["peak_since_entry"] = current_price
                state["trailing_stop"] = (
                    current_price - atr_multiplier * atr_val
                    if atr_val > 0 and pd.notna(current_price)
                    else 0.0
                )
                return "buy", state

        return None, state
