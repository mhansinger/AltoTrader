import pandas as pd
import numpy as np
import logging
from itertools import product
from typing import List, Optional

from altotrader.backtest.dataloader import DataLoader
from altotrader.logging_config import setup_logging

# Imported lazily inside methods to avoid circular imports at module load time.
# Use: from altotrader.backtest.strategies import BaseStrategy


class BacktestEngine:
    def __init__(self, dataloader: DataLoader, backtest_config: dict, log_dir: str = 'logs'):
        self.dataloader = dataloader
        self.maker_fee    = backtest_config.get('maker_fee',    0.0025)
        self.taker_fee    = backtest_config.get('taker_fee',    0.004)
        self.initial_invest = backtest_config.get('initial_invest', 1000)
        self.trading_currency = backtest_config.get("trading_currency")
        self.base_currency    = backtest_config.get("base_currency")
        # Unified pair format: "BTC-EUR", matching exported CSV column names
        self.pair = f"{self.trading_currency}-{self.base_currency}"
        # Slippage applied on top of ask/bid spread (0.0005 = 0.05%)
        self.slippage_pct = backtest_config.get('slippage_pct', 0.0005)
        # Optional volume filter: only enter if volume >= rolling mean over this window (minutes)
        self.volume_filter_window: Optional[int] = backtest_config.get('volume_filter_window', None)

        setup_logging(log_filename='backtest.logs', log_dir=log_dir)
        self.logger = logging.getLogger(__name__)

        self.portfolio_view = pd.DataFrame()
        self.trade_log: list[dict] = []

        self.dataloader.load_csv_export()
        self._set_portfolio_view_df()

    # ── State reset ───────────────────────────────────────────────────────────

    def _set_portfolio_view_df(self):
        """Initialise (or reset) portfolio_view for a new run."""
        self.portfolio_view = pd.DataFrame(index=self.dataloader.ticker_current.index)

        self.portfolio_view[self.pair]           = self.dataloader.ticker_current[self.pair]
        self.portfolio_view[self.pair + '_ask']  = self.dataloader.ticker_ask[self.pair]
        self.portfolio_view[self.pair + '_bid']  = self.dataloader.ticker_bid[self.pair]
        if self.dataloader.ticker_volume is not None and self.pair in self.dataloader.ticker_volume.columns:
            self.portfolio_view[self.pair + '_volume'] = self.dataloader.ticker_volume[self.pair]

        self.portfolio_view[self.base_currency]              = float(self.initial_invest)
        self.portfolio_view[self.trading_currency]           = 0.0
        self.portfolio_view['portfolio_in_' + self.base_currency] = float(self.initial_invest)
        self.portfolio_view["market_position"] = "out"
        self.portfolio_view["action"]          = None

        self.trade_log = []

    # ── Trade execution ───────────────────────────────────────────────────────

    def enter_market(self, idx: int, row: pd.Series):
        """Buy trading currency at ask + slippage using all available base currency.

        Args:
            idx: integer position into portfolio_view
            row: the bar on which the trade is EXECUTED (next bar after signal)
        """
        base_balance = (
            self.portfolio_view.iloc[idx - 1][self.base_currency] if idx > 0
            else self.initial_invest
        )
        # ask price with slippage
        ask_price = row[self.pair + '_ask'] * (1 + self.slippage_pct)

        if base_balance <= 0 or ask_price <= 0:
            return

        fee            = base_balance * self.taker_fee
        amount_bought  = (base_balance - fee) / ask_price
        portfolio_val  = amount_bought * ask_price   # value right after buy

        self.portfolio_view.at[row.name, self.base_currency]             = 0.0
        self.portfolio_view.at[row.name, self.trading_currency]          = amount_bought
        self.portfolio_view.at[row.name, 'market_position']              = 'in'
        self.portfolio_view.at[row.name, 'action']                       = 'buy'
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = portfolio_val

        self.trade_log.append({
            'timestamp':       row.name,
            'action':          'buy',
            'price':           ask_price,
            'amount':          amount_bought,
            'fee':             fee,
            'fee_type':        'taker',
            self.base_currency:    0.0,
            self.trading_currency: amount_bought,
        })
        self.logger.info(
            f"BUY  @ {ask_price:.2f} (slip={self.slippage_pct*100:.3f}%) | "
            f"amount: {amount_bought:.6f} | taker fee: {fee:.4f}"
        )

    def exit_market(self, idx: int, row: pd.Series):
        """Sell all trading currency at bid - slippage.

        Args:
            idx: integer position into portfolio_view
            row: the bar on which the trade is EXECUTED (next bar after signal)
        """
        trading_balance = (
            self.portfolio_view.iloc[idx - 1][self.trading_currency] if idx > 0
            else 0.0
        )
        # bid price with slippage (adverse)
        bid_price = row[self.pair + '_bid'] * (1 - self.slippage_pct)

        if trading_balance <= 0 or bid_price <= 0:
            return

        gross_proceeds = trading_balance * bid_price
        fee            = gross_proceeds * self.maker_fee
        net_proceeds   = gross_proceeds - fee

        self.portfolio_view.at[row.name, self.base_currency]             = net_proceeds
        self.portfolio_view.at[row.name, self.trading_currency]          = 0.0
        self.portfolio_view.at[row.name, 'market_position']              = 'out'
        self.portfolio_view.at[row.name, 'action']                       = 'sell'
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = net_proceeds

        self.trade_log.append({
            'timestamp':       row.name,
            'action':          'sell',
            'price':           bid_price,
            'amount':          trading_balance,
            'fee':             fee,
            'fee_type':        'maker',
            self.base_currency:    net_proceeds,
            self.trading_currency: 0.0,
        })
        self.logger.info(
            f"SELL @ {bid_price:.2f} (slip={self.slippage_pct*100:.3f}%) | "
            f"amount: {trading_balance:.6f} | proceeds: {net_proceeds:.4f} | maker fee: {fee:.4f}"
        )

    def update_portfolio(self, idx: int, row: pd.Series):
        """Carry forward balances and mark portfolio to current price."""
        if idx == 0:
            return

        prev         = self.portfolio_view.iloc[idx - 1]
        base_bal     = prev[self.base_currency]
        trading_bal  = prev[self.trading_currency]
        current_price = row[self.pair]

        self.portfolio_view.at[row.name, self.base_currency]    = base_bal
        self.portfolio_view.at[row.name, self.trading_currency] = trading_bal
        self.portfolio_view.at[row.name, 'market_position']     = prev['market_position']

        portfolio_value = base_bal + trading_bal * current_price
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = portfolio_value

    # ── Core numpy loop ───────────────────────────────────────────────────────

    def _apply_loop_results(
        self,
        valid: pd.DataFrame,
        base_arr: np.ndarray,
        trading_arr: np.ndarray,
        pv_val_arr: np.ndarray,
        pos_arr: np.ndarray,
        action_arr: np.ndarray,
    ) -> None:
        """Write numpy state arrays back to portfolio_view in one vectorised pass.

        Using a single iloc slice assignment is ~240× faster than per-bar
        .at[] writes, because it bypasses label lookup overhead entirely.

        The valid slice is always a contiguous tail of portfolio_view (after
        the rolling-window warm-up period), so a slice assignment is safe.
        """
        pv    = self.portfolio_view
        vi    = valid.index
        start = pv.index.get_loc(vi[0])
        end   = pv.index.get_loc(vi[-1]) + 1

        col = pv.columns.get_loc

        pv.iloc[start:end, col(self.base_currency)]                           = base_arr
        pv.iloc[start:end, col(self.trading_currency)]                        = trading_arr
        pv.iloc[start:end, col('portfolio_in_' + self.base_currency)]         = pv_val_arr
        pv.iloc[start:end, col('market_position')]                            = np.where(
            pos_arr == 1, 'in', 'out'
        )
        pv.iloc[start:end, col('action')]                                     = action_arr

    # ── Main backtest loop ────────────────────────────────────────────────────

    def run(self, window_short: int, window_long: int) -> dict:
        """Run the MA-crossover backtest.

        Look-ahead bias fix: the cross-over signal is detected at bar i, but
        the trade is EXECUTED at bar i+1's prices.  This models a realistic
        market-order placed at the next bar's open.

        Signal logic:
          - Golden cross (short MA crosses above long MA) → queue BUY
          - Death  cross (short MA crosses below long MA) → queue SELL

        Performance: all hot-path operations use pre-extracted numpy arrays.
        Signal checking (golden/death cross) runs at numpy speed; portfolio
        state is tracked in numpy arrays and written back to portfolio_view
        in a single vectorised assignment at the end.  This avoids both the
        per-bar overhead of iterrows() *and* the per-bar .at[] write cost.

        Args:
            window_short: short rolling window (minutes)
            window_long:  long rolling window (minutes)

        Returns:
            dict with performance metrics
        """
        vol_filter_active = (
            self.volume_filter_window is not None
            and self.dataloader.ticker_volume is not None
            and self.pair in self.dataloader.ticker_volume.columns
        )
        self.logger.info(
            f"Starting backtest | short={window_short}min | long={window_long}min | "
            f"slippage={self.slippage_pct*100:.3f}% | "
            f"volume_filter={'on (' + str(self.volume_filter_window) + 'min)' if vol_filter_active else 'off'}"
        )
        self._set_portfolio_view_df()
        self.dataloader.compute_rolling_means(window_short, window_long)

        ma_short = self.dataloader.rolling_current_short[self.pair]
        ma_long  = self.dataloader.rolling_current_long[self.pair]

        self.portfolio_view['ma_short'] = ma_short
        self.portfolio_view['ma_long']  = ma_long

        if vol_filter_active:
            vol_ma = self.dataloader.ticker_volume[self.pair].rolling(
                f'{self.volume_filter_window}min'
            ).mean()
            self.portfolio_view['_vol_ma'] = vol_ma

        valid = self.portfolio_view.dropna(subset=['ma_short', 'ma_long'])
        n     = len(valid)

        # ── Pre-extract all arrays (one-time cost) ────────────────────────────
        ma_short_arr = valid['ma_short'].values
        ma_long_arr  = valid['ma_long'].values
        close_arr    = valid[self.pair].values
        ask_arr      = valid[self.pair + '_ask'].values
        bid_arr      = valid[self.pair + '_bid'].values
        vol_arr      = valid[self.pair + '_volume'].values if vol_filter_active else None
        vol_ma_arr   = valid['_vol_ma'].values             if vol_filter_active else None

        # ── Output arrays (written to portfolio_view at the end) ──────────────
        base_arr    = np.empty(n)
        trading_arr = np.empty(n)
        pv_val_arr  = np.empty(n)
        pos_arr     = np.zeros(n, dtype=np.uint8)   # 0 = 'out', 1 = 'in'
        action_arr  = np.empty(n, dtype=object)

        # First bar: carry forward warm-up defaults (cash = initial_invest)
        base_arr[0]    = float(self.initial_invest)
        trading_arr[0] = 0.0
        pv_val_arr[0]  = float(self.initial_invest)
        action_arr[0]  = None

        pending_action: Optional[str] = None
        position = 0  # local tracker avoids per-bar DataFrame reads

        for i in range(n):
            action_arr[i] = None  # default: no action this bar

            if i == 0:
                # Nothing to execute on the very first bar
                continue

            prev_base    = base_arr[i - 1]
            prev_trading = trading_arr[i - 1]
            prev_pos     = int(pos_arr[i - 1])

            # ── Execute pending order from previous bar ───────────────────────
            if pending_action == 'buy':
                ask = ask_arr[i] * (1 + self.slippage_pct)
                if prev_base > 0 and ask > 0:
                    fee    = prev_base * self.taker_fee
                    amount = (prev_base - fee) / ask
                    base_arr[i]    = 0.0
                    trading_arr[i] = amount
                    pv_val_arr[i]  = amount * ask
                    pos_arr[i]     = 1
                    action_arr[i]  = 'buy'
                    position       = 1
                    self.trade_log.append({
                        'timestamp':           valid.index[i],
                        'action':              'buy',
                        'price':               ask,
                        'amount':              amount,
                        'fee':                 fee,
                        'fee_type':            'taker',
                        self.base_currency:    0.0,
                        self.trading_currency: amount,
                    })
                else:
                    # Can't enter – carry forward
                    base_arr[i]    = prev_base
                    trading_arr[i] = prev_trading
                    pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                    pos_arr[i]     = prev_pos

            elif pending_action == 'sell':
                bid = bid_arr[i] * (1 - self.slippage_pct)
                if prev_trading > 0 and bid > 0:
                    gross = prev_trading * bid
                    fee   = gross * self.maker_fee
                    net   = gross - fee
                    base_arr[i]    = net
                    trading_arr[i] = 0.0
                    pv_val_arr[i]  = net
                    pos_arr[i]     = 0
                    action_arr[i]  = 'sell'
                    position       = 0
                    self.trade_log.append({
                        'timestamp':           valid.index[i],
                        'action':              'sell',
                        'price':               bid,
                        'amount':              prev_trading,
                        'fee':                 fee,
                        'fee_type':            'maker',
                        self.base_currency:    net,
                        self.trading_currency: 0.0,
                    })
                else:
                    base_arr[i]    = prev_base
                    trading_arr[i] = prev_trading
                    pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                    pos_arr[i]     = prev_pos

            else:
                # No pending order – carry forward balances, mark to market
                base_arr[i]    = prev_base
                trading_arr[i] = prev_trading
                pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                pos_arr[i]     = prev_pos

            pending_action = None

            # ── Signal detection on current bar (numpy – no Series objects) ───
            ps, pl = ma_short_arr[i - 1], ma_long_arr[i - 1]
            cs, cl = ma_short_arr[i],     ma_long_arr[i]

            golden_cross = bool((ps <= pl) and (cs > cl))
            death_cross  = bool((ps >= pl) and (cs < cl))

            volume_ok = True
            if vol_filter_active and golden_cross and vol_arr is not None:
                vm = vol_ma_arr[i]
                vc = vol_arr[i]
                volume_ok = (
                    not np.isnan(vm) and not np.isnan(vc) and vc >= vm
                )

            if golden_cross and position == 0 and volume_ok:
                pending_action = 'buy'
            elif death_cross and position == 1:
                pending_action = 'sell'

        # ── Force-close any open position at last bar ─────────────────────────
        if pos_arr[-1] == 1:
            bid = bid_arr[-1] * (1 - self.slippage_pct)
            prev_trading = trading_arr[-1]
            if prev_trading > 0 and bid > 0:
                gross = prev_trading * bid
                fee   = gross * self.maker_fee
                net   = gross - fee
                base_arr[-1]    = net
                trading_arr[-1] = 0.0
                pv_val_arr[-1]  = net
                pos_arr[-1]     = 0
                action_arr[-1]  = 'sell (end)'
                self.trade_log.append({
                    'timestamp':           valid.index[-1],
                    'action':              'sell',
                    'price':               bid,
                    'amount':              prev_trading,
                    'fee':                 fee,
                    'fee_type':            'maker',
                    self.base_currency:    net,
                    self.trading_currency: 0.0,
                })

        # ── Single vectorised write-back ──────────────────────────────────────
        self._apply_loop_results(valid, base_arr, trading_arr, pv_val_arr,
                                 pos_arr, action_arr)

        metrics = self.compute_metrics()
        self.logger.info(f"Backtest complete | return: {metrics['total_return_pct']:.2f}%")
        return metrics

    # ── Metrics ───────────────────────────────────────────────────────────────

    def compute_metrics(self) -> dict:
        """Compute performance metrics after a completed run.

        Returns:
            dict with keys:
              total_return_pct, buy_and_hold_return_pct,
              n_trades, win_rate,
              max_drawdown_pct, max_drawdown_duration_hrs,
              sharpe_ratio (annualised, from daily portfolio returns),
              total_fees, taker_fees, maker_fees,
              final_portfolio_value
        """
        pv_col = 'portfolio_in_' + self.base_currency
        pv = self.portfolio_view[pv_col].dropna()

        initial = float(self.initial_invest)
        final   = float(pv.iloc[-1]) if len(pv) > 0 else initial
        total_return_pct = (final - initial) / initial * 100

        # ── Buy & Hold benchmark ──────────────────────────────────────────────
        first_ask = self.portfolio_view[self.pair + '_ask'].dropna().iloc[0]
        last_bid  = self.portfolio_view[self.pair + '_bid'].dropna().iloc[-1]
        bh_amount = (initial * (1 - self.taker_fee)) / first_ask
        bh_final  = bh_amount * last_bid * (1 - self.maker_fee)
        bh_return_pct = (bh_final - initial) / initial * 100

        # ── Trade statistics ──────────────────────────────────────────────────
        trades_df = pd.DataFrame(self.trade_log)
        n_trades  = 0
        win_rate  = 0.0

        if not trades_df.empty:
            sell_mask = trades_df['action'].str.startswith('sell')
            n_trades  = int(sell_mask.sum())

            if n_trades > 0:
                buy_prices  = trades_df[trades_df['action'] == 'buy']['price'].values
                sell_prices = trades_df[sell_mask]['price'].values
                pairs       = min(len(buy_prices), len(sell_prices))
                wins        = int(np.sum(sell_prices[:pairs] > buy_prices[:pairs]))
                win_rate    = wins / pairs * 100 if pairs > 0 else 0.0

        # ── Max drawdown + duration ───────────────────────────────────────────
        rolling_max   = pv.cummax()
        drawdown_pct  = (pv - rolling_max) / rolling_max * 100
        max_drawdown_pct = float(drawdown_pct.min())

        # Duration of the worst drawdown in hours
        in_drawdown = drawdown_pct < 0
        max_dd_dur_hrs = 0.0
        if in_drawdown.any():
            # Find the longest consecutive run of drawdown bars
            groups = (in_drawdown != in_drawdown.shift()).cumsum()
            dd_runs = in_drawdown.groupby(groups).sum()  # bar counts
            longest_bars = int(dd_runs[in_drawdown.groupby(groups).any()].max())
            max_dd_dur_hrs = round(longest_bars / 60, 2)  # 1-min bars → hours

        # ── Sharpe ratio (annualised from daily returns) ──────────────────────
        # Resample to daily to avoid the noise of 525k 1-min bars
        pv_daily = pv.resample('1D').last().dropna()
        daily_returns = pv_daily.pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365)
        else:
            sharpe = 0.0

        # ── Fee breakdown ─────────────────────────────────────────────────────
        total_fees  = 0.0
        taker_fees  = 0.0
        maker_fees  = 0.0
        if not trades_df.empty:
            total_fees = float(trades_df['fee'].sum())
            if 'fee_type' in trades_df.columns:
                taker_fees = float(trades_df.loc[trades_df['fee_type'] == 'taker', 'fee'].sum())
                maker_fees = float(trades_df.loc[trades_df['fee_type'] == 'maker', 'fee'].sum())

        return {
            'total_return_pct':           round(total_return_pct, 4),
            'buy_and_hold_return_pct':    round(bh_return_pct, 4),
            'n_trades':                   n_trades,
            'win_rate':                   round(win_rate, 2),
            'max_drawdown_pct':           round(max_drawdown_pct, 4),
            'max_drawdown_duration_hrs':  max_dd_dur_hrs,
            'sharpe_ratio':               round(sharpe, 4),
            'total_fees':                 round(total_fees, 4),
            'taker_fees':                 round(taker_fees, 4),
            'maker_fees':                 round(maker_fees, 4),
            'final_portfolio_value':      round(final, 4),
        }

    # ── Pluggable strategy runner ─────────────────────────────────────────────

    def run_strategy(self, strategy, **strategy_params) -> dict:
        """Run a backtest with any strategy that implements BaseStrategy.

        This is the main entry point for the three new strategies (Options A–C).
        The original ``run(window_short, window_long)`` method is kept unchanged
        for the classic SMA crossover.

        How it works
        ------------
        1. Reset portfolio state.
        2. Call ``strategy.setup(pair, **strategy_params)`` – stores pair name
           and any static config the strategy needs inside the strategy object.
        3. Call ``strategy.add_indicators(portfolio_view, dataloader, ...)`` –
           the strategy attaches all indicator columns it needs (EMAs, ATR,
           Bollinger Bands, RSI, …).
        4. Drop warm-up rows where required indicators are still NaN.
        5. Iterate bar-by-bar: execute any pending order from the previous bar,
           then ask the strategy for a signal on the current bar.
        6. Force-close any open position at the last bar.
        7. Compute and return performance metrics.

        The ``state`` dict is passed to the strategy on every bar so it can
        carry cross-bar memory (trailing stop levels, peak prices, cooldown
        counters, …) without needing instance variables.

        Args:
            strategy:         An instance of a BaseStrategy subclass.
            **strategy_params: Forwarded to both ``setup`` and
                               ``add_indicators``.  These are the tunable
                               parameters (e.g. ``ema_short=50``).

        Returns:
            dict of performance metrics (same keys as ``compute_metrics()``).

        Example::

            from altotrader.backtest.strategies import get_strategy

            strategy = get_strategy("ema")
            metrics  = engine.run_strategy(strategy, ema_short=50, ema_long=200,
                                           atr_multiplier=2.0)
        """
        from altotrader.backtest.strategies.base import BaseStrategy as _BaseStrategy  # noqa

        self._set_portfolio_view_df()
        strategy.setup(self.pair, **strategy_params)
        strategy.add_indicators(self.portfolio_view, self.dataloader, **strategy_params)

        dropna_cols = [
            c for c in strategy.required_dropna_cols
            if c in self.portfolio_view.columns
        ]
        valid = (
            self.portfolio_view.dropna(subset=dropna_cols)
            if dropna_cols
            else self.portfolio_view.copy()
        )

        self.logger.info(
            f"run_strategy | strategy={strategy.name} | "
            f"params={strategy_params} | bars={len(valid)}"
        )

        n = len(valid)

        if n == 0:
            self.logger.info("run_strategy: no valid bars after warm-up, returning zero metrics")
            return self.compute_metrics()

        # ── Pre-extract price arrays ──────────────────────────────────────────
        close_arr = valid[self.pair].values
        ask_arr   = valid[self.pair + '_ask'].values
        bid_arr   = valid[self.pair + '_bid'].values

        # ── Output arrays ─────────────────────────────────────────────────────
        base_arr    = np.empty(n)
        trading_arr = np.empty(n)
        pv_val_arr  = np.empty(n)
        pos_arr     = np.zeros(n, dtype=np.uint8)
        action_arr  = np.empty(n, dtype=object)

        base_arr[0]    = float(self.initial_invest)
        trading_arr[0] = 0.0
        pv_val_arr[0]  = float(self.initial_invest)
        action_arr[0]  = None

        pending_action: Optional[str] = None
        position = 0  # 0 = 'out', 1 = 'in'
        state: dict = {**strategy_params}

        for i in range(n):
            action_arr[i] = None

            # Strategies need indicator values → build a lightweight row only
            # when on_bar is called.  Price/portfolio ops use numpy arrays.
            row = valid.iloc[i]

            if i == 0:
                current_position = 'out'
                signal, state = strategy.on_bar(0, row, valid, current_position, state)
                if signal in ('buy', 'sell'):
                    pending_action = signal
                continue

            prev_base    = base_arr[i - 1]
            prev_trading = trading_arr[i - 1]
            prev_pos     = int(pos_arr[i - 1])

            # ── Execute pending order ─────────────────────────────────────────
            if pending_action == 'buy':
                ask = ask_arr[i] * (1 + self.slippage_pct)
                if prev_base > 0 and ask > 0:
                    fee    = prev_base * self.taker_fee
                    amount = (prev_base - fee) / ask
                    base_arr[i]    = 0.0
                    trading_arr[i] = amount
                    pv_val_arr[i]  = amount * ask
                    pos_arr[i]     = 1
                    action_arr[i]  = 'buy'
                    position       = 1
                    self.trade_log.append({
                        'timestamp':           valid.index[i],
                        'action':              'buy',
                        'price':               ask,
                        'amount':              amount,
                        'fee':                 fee,
                        'fee_type':            'taker',
                        self.base_currency:    0.0,
                        self.trading_currency: amount,
                    })
                else:
                    base_arr[i]    = prev_base
                    trading_arr[i] = prev_trading
                    pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                    pos_arr[i]     = prev_pos

            elif pending_action == 'sell':
                bid = bid_arr[i] * (1 - self.slippage_pct)
                if prev_trading > 0 and bid > 0:
                    gross = prev_trading * bid
                    fee   = gross * self.maker_fee
                    net   = gross - fee
                    base_arr[i]    = net
                    trading_arr[i] = 0.0
                    pv_val_arr[i]  = net
                    pos_arr[i]     = 0
                    action_arr[i]  = 'sell'
                    position       = 0
                    self.trade_log.append({
                        'timestamp':           valid.index[i],
                        'action':              'sell',
                        'price':               bid,
                        'amount':              prev_trading,
                        'fee':                 fee,
                        'fee_type':            'maker',
                        self.base_currency:    net,
                        self.trading_currency: 0.0,
                    })
                else:
                    base_arr[i]    = prev_base
                    trading_arr[i] = prev_trading
                    pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                    pos_arr[i]     = prev_pos

            else:
                base_arr[i]    = prev_base
                trading_arr[i] = prev_trading
                pv_val_arr[i]  = prev_base + prev_trading * close_arr[i]
                pos_arr[i]     = prev_pos

            pending_action = None

            # ── Ask strategy for signal (still uses pd.Series row for ─────────
            # indicator access; portfolio ops above are already numpy-fast)
            current_position = 'in' if position == 1 else 'out'
            signal, state = strategy.on_bar(i, row, valid, current_position, state)
            if signal in ('buy', 'sell'):
                pending_action = signal

        # ── Force-close ───────────────────────────────────────────────────────
        if pos_arr[-1] == 1:
            bid = bid_arr[-1] * (1 - self.slippage_pct)
            prev_trading = trading_arr[-1]
            if prev_trading > 0 and bid > 0:
                gross = prev_trading * bid
                fee   = gross * self.maker_fee
                net   = gross - fee
                base_arr[-1]    = net
                trading_arr[-1] = 0.0
                pv_val_arr[-1]  = net
                pos_arr[-1]     = 0
                action_arr[-1]  = 'sell (end)'
                self.trade_log.append({
                    'timestamp':           valid.index[-1],
                    'action':              'sell',
                    'price':               bid,
                    'amount':              prev_trading,
                    'fee':                 fee,
                    'fee_type':            'maker',
                    self.base_currency:    net,
                    self.trading_currency: 0.0,
                })

        # ── Single vectorised write-back ──────────────────────────────────────
        self._apply_loop_results(valid, base_arr, trading_arr, pv_val_arr,
                                 pos_arr, action_arr)

        metrics = self.compute_metrics()
        self.logger.info(
            f"run_strategy done | return={metrics['total_return_pct']:+.2f}% | "
            f"sharpe={metrics['sharpe_ratio']:.2f} | trades={metrics['n_trades']}"
        )
        return metrics

    def run_strategy_grid_search(
        self,
        strategy,
        param_grid: dict,
        sort_by: str = "sharpe_ratio",
    ) -> "pd.DataFrame":
        """Parameter sweep for any pluggable strategy.

        Works exactly like ``run_grid_search()`` for the SMA crossover but
        accepts an arbitrary ``param_grid`` dict so you can tune any set of
        parameters for any strategy.

        Args:
            strategy:   A BaseStrategy instance (will be reused across runs –
                        state is reset by ``run_strategy`` on every call).
            param_grid: Dict mapping parameter names to lists of values.
                        All combinations are tested.  Example::

                            {
                                "ema_short":      [30, 50, 100],
                                "ema_long":       [200, 500, 1000],
                                "atr_multiplier": [1.5, 2.0, 2.5],
                            }

            sort_by:    Metric column to sort results by (descending).
                        Default ``'sharpe_ratio'``.

        Returns:
            DataFrame sorted by *sort_by* (descending) with one row per
            parameter combination.

        Example::

            from altotrader.backtest.strategies import get_strategy
            from altotrader.backtest.backtest_engine import BacktestEngine

            strategy = get_strategy("ema")
            results  = engine.run_strategy_grid_search(
                strategy,
                param_grid={
                    "ema_short":      [50, 100],
                    "ema_long":       [200, 500],
                    "atr_multiplier": [1.5, 2.0],
                },
            )
            print(results.head())
        """
        keys   = list(param_grid.keys())
        combos = list(product(*[param_grid[k] for k in keys]))
        self.logger.info(
            f"Strategy grid search: strategy={strategy.name} | "
            f"{len(combos)} combinations"
        )

        rows = []
        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                metrics = self.run_strategy(strategy, **params)
                metrics.update(params)
                rows.append(metrics)
                self.logger.debug(
                    f"  {params}  →  "
                    f"return={metrics['total_return_pct']:+.2f}%  "
                    f"sharpe={metrics['sharpe_ratio']:.3f}  "
                    f"trades={metrics['n_trades']}"
                )
            except Exception as exc:
                self.logger.warning(f"  {params} failed: {exc}")

        if not rows:
            return pd.DataFrame()

        df = (
            pd.DataFrame(rows)
            .sort_values(sort_by, ascending=False)
            .reset_index(drop=True)
        )
        best = df.iloc[0]
        self.logger.info(
            f"Best: {dict(best[keys].items())}  "
            f"→  {sort_by}={best[sort_by]:.3f}  "
            f"return={best['total_return_pct']:+.2f}%"
        )
        return df

    # ── Visualisation ─────────────────────────────────────────────────────────

    def plot_results(self, show: bool = True, save_path: str = None):
        """Plot equity curve, buy/sell markers and drawdown after a run().

        Requires matplotlib (pip install matplotlib).

        Args:
            show:      Display the interactive figure (default True).
            save_path: Optional path to save the figure (e.g. 'out.png').
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            self.logger.error(
                "matplotlib is required for plotting. "
                "Install it with: pip install matplotlib"
            )
            return

        pv_col = f"portfolio_in_{self.base_currency}"
        pv         = self.portfolio_view[pv_col].dropna()
        timestamps = pv.index

        buys  = self.portfolio_view[self.portfolio_view["action"] == "buy"]
        sells = self.portfolio_view[
            self.portfolio_view["action"].str.startswith("sell", na=False)
        ]

        rolling_max = pv.cummax()
        drawdown    = (pv - rolling_max) / rolling_max * 100

        metrics = self.compute_metrics()
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8), sharex=True,
            gridspec_kw={"height_ratios": [3, 1]},
        )
        fig.suptitle(
            f"Backtest: {self.pair}  |  "
            f"Return {metrics['total_return_pct']:+.2f}%  |  "
            f"Sharpe {metrics['sharpe_ratio']:.2f}  |  "
            f"MaxDD {metrics['max_drawdown_pct']:.2f}%",
            fontsize=12,
        )

        ax1.plot(timestamps, pv, color="steelblue", linewidth=1.2, label="Portfolio")
        ax1.axhline(self.initial_invest, color="grey", linewidth=0.8,
                    linestyle="--", label="Initial invest")
        if not buys.empty:
            ax1.scatter(buys.index, buys[pv_col], marker="^", color="green",
                        s=80, zorder=5, label="Buy")
        if not sells.empty:
            ax1.scatter(sells.index, sells[pv_col], marker="v", color="red",
                        s=80, zorder=5, label="Sell")
        ax1.set_ylabel(f"Portfolio value ({self.base_currency})")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.3)

        ax2.fill_between(timestamps, drawdown, 0, color="salmon", alpha=0.6)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        plt.tight_layout()
        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            self.logger.info(f"Plot saved to {save_path}")
        if show:
            plt.show()
        plt.close(fig)


# ── Grid search ───────────────────────────────────────────────────────────────

def run_grid_search(
    engine: "BacktestEngine",
    short_windows: List[int],
    long_windows: List[int],
) -> pd.DataFrame:
    """Parameter sweep over MA window combinations.

    Only valid combinations where short < long are tested.

    Args:
        engine:        A configured BacktestEngine instance.
        short_windows: List of short MA window sizes (minutes).
        long_windows:  List of long MA window sizes (minutes).

    Returns:
        DataFrame sorted by total_return_pct (descending).

    Example::

        results = run_grid_search(engine, [10, 20, 50], [100, 200, 500])
        print(results.head())
    """
    logger = logging.getLogger(__name__)
    rows   = []

    combos = [(ws, wl) for ws, wl in product(short_windows, long_windows) if ws < wl]
    logger.info(f"Grid search: {len(combos)} combinations")

    for ws, wl in combos:
        try:
            metrics = engine.run(window_short=ws, window_long=wl)
            metrics["window_short"] = ws
            metrics["window_long"]  = wl
            rows.append(metrics)
            logger.debug(
                f"  ws={ws:>4} wl={wl:>4}  "
                f"return={metrics['total_return_pct']:+.2f}%  "
                f"trades={metrics['n_trades']}"
            )
        except Exception as e:
            logger.warning(f"  ws={ws} wl={wl} failed: {e}")

    if not rows:
        return pd.DataFrame()

    results = (
        pd.DataFrame(rows)
        .sort_values("total_return_pct", ascending=False)
        .reset_index(drop=True)
    )

    best = results.iloc[0]
    logger.info(
        f"Best: ws={best['window_short']} wl={best['window_long']}  "
        f"return={best['total_return_pct']:+.2f}%"
    )
    return results


if __name__ == '__main__':
    loader_dict = {
        'export_path': "Examples/ticker_export",
        "latest_days": 20,
        "file_prefix": "altotrader",  # must match InfluxDB bucket name
        "logs_dir":    'logs',
    }
    testloader = DataLoader(loader_dict)

    backtest_config = {
        "maker_fee":        0.0025,
        "taker_fee":        0.004,
        "slippage_pct":     0.0005,
        "initial_invest":   1000,
        "base_currency":    "EUR",   # pair will be "BTC-EUR"
        "trading_currency": "BTC",
    }

    backtest = BacktestEngine(testloader, backtest_config)
    metrics  = backtest.run(window_short=50, window_long=200)

    print("\n=== Backtest Results ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    backtest.plot_results(show=False, save_path="Examples/backtest_result.png")

    print("\n=== Grid Search ===")
    results = run_grid_search(backtest, short_windows=[20, 50, 100], long_windows=[100, 200, 500])
    print(results[["window_short", "window_long", "total_return_pct",
                   "n_trades", "sharpe_ratio", "max_drawdown_pct"]].to_string())
