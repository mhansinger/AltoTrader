"""Option C – Bollinger Bands + RSI mean-reversion strategy.

Philosophy
----------
Prices do not move in a straight line.  Even in an uptrend, a coin periodically
pulls back toward its mean.  This strategy identifies those pull-backs using two
complementary indicators:

* **Bollinger Bands** – a statistical envelope around a rolling mean.  When the
  price falls *below the lower band* it has moved more than 2 standard deviations
  away from its average, statistically an unusual event.

* **RSI (Relative Strength Index)** – a momentum oscillator (0–100).  A reading
  below ~35 signals the market has been selling aggressively and is likely
  over-extended to the downside.

Using both together dramatically reduces false signals: price can briefly dip
below the lower Bollinger Band without the RSI confirming extreme selling, and
vice versa.

Safety filter
-------------
Mean reversion *against* a structural downtrend is dangerous ("catching a
falling knife").  The optional ``trend_filter`` checks that the current price
is above the 200-period EMA of 4-hour bars before allowing a buy.  This
ensures we only fade pull-backs in bull-market conditions.

Entry  : close < lower_BB **and** RSI < ``rsi_oversold``
         (**and** close > 4h-200 EMA if ``trend_filter=True``)
Exit   : close > middle_BB (back to mean)  **or**  RSI > ``rsi_overbought``

Parameters
----------
bb_period : int
    Rolling window (minutes) for Bollinger Band SMA and std.  Default 120 (2 h).
bb_std : float
    Number of standard deviations for the bands.  Default 2.0.
rsi_period : int
    Look-back window (minutes) for RSI.  Default 60.
rsi_oversold : float
    RSI threshold to trigger entry.  Default 35.
rsi_overbought : float
    RSI threshold to trigger exit.  Default 65.
trend_filter : bool
    Apply the 4h 200-EMA trend guard.  Default True.
trend_ema_period : int
    Number of 4h bars for the trend EMA.  Default 200.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import numpy as np

from .base import BaseStrategy


def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI using EWM smoothing (alpha = 1/period)."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    # Avoid division by zero
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


class BollingerRSIStrategy(BaseStrategy):
    """Mean-reversion: buy oversold pull-backs within an uptrend.

    Grid-search parameters::

        param_grid = {
            "bb_period":     [60, 120, 240],
            "rsi_period":    [30, 60, 120],
            "rsi_oversold":  [30, 35, 40],
            "bb_std":        [1.5, 2.0, 2.5],
        }
    """

    @property
    def name(self) -> str:
        return "bollinger_rsi"

    @property
    def required_dropna_cols(self) -> list[str]:
        return ["_bb_lower", "_bb_middle", "_rsi", "_ema_trend"]

    # ── Setup ─────────────────────────────────────────────────────────────────

    def setup(self, pair: str, **kwargs) -> None:
        super().setup(pair)
        self._trend_filter:   bool  = bool(kwargs.get("trend_filter", True))
        self._rsi_overbought: float = float(kwargs.get("rsi_overbought", 65.0))
        self._rsi_oversold:   float = float(kwargs.get("rsi_oversold",   35.0))

    # ── Indicators ────────────────────────────────────────────────────────────

    def add_indicators(
        self,
        pv: pd.DataFrame,
        dataloader,
        **kwargs,
    ) -> pd.DataFrame:
        bb_period        = int(kwargs.get("bb_period",       120))
        bb_std_factor    = float(kwargs.get("bb_std",        2.0))
        rsi_period       = int(kwargs.get("rsi_period",       60))
        rsi_overbought   = float(kwargs.get("rsi_overbought", self._rsi_overbought))
        rsi_oversold     = float(kwargs.get("rsi_oversold",   self._rsi_oversold))
        trend_filter     = bool(kwargs.get("trend_filter",    self._trend_filter))
        trend_ema_period = int(kwargs.get("trend_ema_period", 200))

        # Store in pv attrs so on_bar can read them via state
        self._bb_std_factor  = bb_std_factor
        self._rsi_overbought = rsi_overbought
        self._rsi_oversold   = rsi_oversold

        close = dataloader.ticker_current[self.pair]

        # ── Bollinger Bands ───────────────────────────────────────────────────
        bb_sma    = close.rolling(f"{bb_period}min").mean()
        bb_stddev = close.rolling(f"{bb_period}min").std()

        pv["_bb_middle"] = bb_sma
        pv["_bb_upper"]  = bb_sma + bb_std_factor * bb_stddev
        pv["_bb_lower"]  = bb_sma - bb_std_factor * bb_stddev

        # ── RSI ───────────────────────────────────────────────────────────────
        pv["_rsi"] = _compute_rsi(close, rsi_period)

        # ── Trend filter (4h 200 EMA) ─────────────────────────────────────────
        if trend_filter:
            close_4h     = close.resample("4h").last()
            ema_trend_4h = close_4h.ewm(span=trend_ema_period, adjust=False).mean()
            pv["_ema_trend"] = ema_trend_4h.reindex(pv.index, method="ffill")
        else:
            pv["_ema_trend"] = 0.0  # always pass

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
        current_price  = row[self.pair]
        bb_lower       = row.get("_bb_lower")
        bb_middle      = row.get("_bb_middle")
        rsi            = row.get("_rsi")
        ema_trend      = row.get("_ema_trend", 0)

        rsi_overbought = state.get("rsi_overbought", self._rsi_overbought)
        rsi_oversold   = state.get("rsi_oversold",   self._rsi_oversold)

        if any(pd.isna(x) for x in [current_price, bb_lower, bb_middle, rsi]):
            return None, state

        # ── EXIT ──────────────────────────────────────────────────────────────
        if current_position == "in":
            # Exit when price reverts to the mean OR RSI signals overbought
            mean_reversion = current_price >= bb_middle
            rsi_exit       = rsi > rsi_overbought

            if mean_reversion or rsi_exit:
                return "sell", state

        # ── ENTRY ─────────────────────────────────────────────────────────────
        if current_position == "out":
            below_lower_band = current_price < bb_lower
            rsi_oversold_ok  = rsi < rsi_oversold

            # Trend filter: only buy in confirmed uptrend
            trend_ok = True
            if pd.notna(ema_trend) and ema_trend > 0 and pd.notna(current_price):
                trend_ok = current_price > ema_trend

            if below_lower_band and rsi_oversold_ok and trend_ok:
                state["rsi_overbought"] = rsi_overbought
                state["rsi_oversold"]   = rsi_oversold
                return "buy", state

        return None, state
