import pandas as pd
import numpy as np
import logging
from itertools import product
from typing import List, Optional

from altotrader.backtest.dataloader import DataLoader
from altotrader.logging_config import setup_logging


class BacktestEngine:
    def __init__(self, dataloader: DataLoader, backtest_config: dict, log_dir: str = 'logs'):
        self.dataloader = dataloader
        self.maker_fee    = backtest_config.get('maker_fee',    0.0025)
        self.taker_fee    = backtest_config.get('taker_fee',    0.004)
        self.initial_invest = backtest_config.get('initial_invest', 1000)
        self.trading_currency = backtest_config.get("trading_currency")
        self.base_currency    = backtest_config.get("base_currency")
        self.pair = self.trading_currency + self.base_currency
        # Slippage applied on top of ask/bid spread (0.0005 = 0.05%)
        self.slippage_pct = backtest_config.get('slippage_pct', 0.0005)

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

    # ── Main backtest loop ────────────────────────────────────────────────────

    def run(self, window_short: int, window_long: int) -> dict:
        """Run the MA-crossover backtest.

        Look-ahead bias fix: the cross-over signal is detected at bar i, but
        the trade is EXECUTED at bar i+1's prices.  This models a realistic
        market-order placed at the next bar's open.

        Signal logic:
          - Golden cross (short MA crosses above long MA) → queue BUY
          - Death  cross (short MA crosses below long MA) → queue SELL

        Args:
            window_short: short rolling window (minutes)
            window_long:  long rolling window (minutes)

        Returns:
            dict with performance metrics
        """
        self.logger.info(
            f"Starting backtest | short={window_short}min | long={window_long}min | "
            f"slippage={self.slippage_pct*100:.3f}%"
        )
        self._set_portfolio_view_df()
        self.dataloader.compute_rolling_means(window_short, window_long)

        ma_short = self.dataloader.rolling_current_short[self.pair]
        ma_long  = self.dataloader.rolling_current_long[self.pair]

        self.portfolio_view['ma_short'] = ma_short
        self.portfolio_view['ma_long']  = ma_long

        valid = self.portfolio_view.dropna(subset=['ma_short', 'ma_long'])

        pending_action: Optional[str] = None  # 'buy' | 'sell' | None

        for idx, (timestamp, row) in enumerate(valid.iterrows()):
            int_idx = self.portfolio_view.index.get_loc(timestamp)

            # ── STEP 1: Execute any pending order from the PREVIOUS bar ───────
            if pending_action == 'buy':
                self.enter_market(int_idx, row)
            elif pending_action == 'sell':
                self.exit_market(int_idx, row)
            else:
                self.update_portfolio(int_idx, row)
            pending_action = None

            # ── STEP 2: Detect signal on CURRENT bar → queue for NEXT bar ────
            if idx == 0:
                continue

            prev_short = valid['ma_short'].iloc[idx - 1]
            prev_long  = valid['ma_long'].iloc[idx - 1]
            curr_short = row['ma_short']
            curr_long  = row['ma_long']

            curr_position = self.portfolio_view.iloc[int_idx]['market_position']

            golden_cross = (prev_short <= prev_long) and (curr_short > curr_long)
            death_cross  = (prev_short >= prev_long) and (curr_short < curr_long)

            if golden_cross and curr_position == 'out':
                pending_action = 'buy'
            elif death_cross and curr_position == 'in':
                pending_action = 'sell'

        # Force-close any open position at last bar
        last_idx = len(self.portfolio_view) - 1
        last_row = self.portfolio_view.iloc[last_idx]
        if last_row['market_position'] == 'in':
            self.exit_market(last_idx, last_row)
            self.portfolio_view.at[last_row.name, 'action'] = 'sell (end)'

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
    loader_dict = {'export_path': "Examples/ticker_export",
                   "latest_days": 20, "logs_dir": 'logs'}
    testloader = DataLoader(loader_dict)

    backtest_config = {
        "maker_fee":    0.0025,
        "taker_fee":    0.004,
        "slippage_pct": 0.0005,
        "initial_invest": 1000,
        "base_currency":    "ZEUR",
        "trading_currency": "XXBT",
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
