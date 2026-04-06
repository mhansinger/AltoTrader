import pandas as pd
import numpy as np
import logging
from itertools import product
from typing import List

from altotrader.backtest.dataloader import DataLoader
from altotrader.logging_config import setup_logging


class BacktestEngine:
    def __init__(self, dataloader: DataLoader, backtest_config: dict, log_dir: str = 'logs'):
        self.dataloader = dataloader
        self.maker_fee = backtest_config.get('maker_fee', 0.0025)
        self.taker_fee = backtest_config.get('taker_fee', 0.004)
        self.initial_invest = backtest_config.get('initial_invest', 1000)
        self.trading_currency = backtest_config.get("trading_currency")
        self.base_currency = backtest_config.get("base_currency")
        self.pair = self.trading_currency + self.base_currency

        setup_logging(log_filename='backtest.logs', log_dir=log_dir)
        self.logger = logging.getLogger(__name__)

        self.portfolio_view = pd.DataFrame()
        self.trade_log: list[dict] = []

        # load crypto ticker data
        self.dataloader.load_csv_export()

        self._set_portfolio_view_df()

    def _set_portfolio_view_df(self):
        """Creates a dataframe (portfolio_view) that stores all relevant information such as
        current, ask, bid prices, market position etc.
        Resets state for every new run."""

        self.portfolio_view = pd.DataFrame(index=self.dataloader.ticker_current.index)

        self.portfolio_view[self.pair] = self.dataloader.ticker_current[self.pair]
        self.portfolio_view[self.pair + '_ask'] = self.dataloader.ticker_ask[self.pair]
        self.portfolio_view[self.pair + '_bid'] = self.dataloader.ticker_bid[self.pair]

        self.portfolio_view[self.base_currency] = float(self.initial_invest)
        self.portfolio_view[self.trading_currency] = 0.0
        self.portfolio_view['portfolio_in_' + self.base_currency] = float(self.initial_invest)
        self.portfolio_view["market_position"] = "out"
        self.portfolio_view["action"] = None

        self.trade_log = []

    def enter_market(self, idx: int, row: pd.Series):
        """Buy trading currency at ask price using all available base currency.

        Args:
            idx: integer index into portfolio_view
            row: current row of portfolio_view
        """
        base_balance = self.portfolio_view.iloc[idx - 1][self.base_currency] if idx > 0 else self.initial_invest
        ask_price = row[self.pair + '_ask']

        if base_balance <= 0 or ask_price <= 0:
            return

        # Buy amount after taker fee
        trade_cost = base_balance
        fee = trade_cost * self.taker_fee
        amount_bought = (trade_cost - fee) / ask_price

        self.portfolio_view.at[row.name, self.base_currency] = 0.0
        self.portfolio_view.at[row.name, self.trading_currency] = amount_bought
        self.portfolio_view.at[row.name, 'market_position'] = 'in'
        self.portfolio_view.at[row.name, 'action'] = 'buy'
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = amount_bought * ask_price

        self.trade_log.append({
            'timestamp': row.name,
            'action': 'buy',
            'price': ask_price,
            'amount': amount_bought,
            'fee': fee,
            self.base_currency: 0.0,
            self.trading_currency: amount_bought,
        })
        self.logger.info(f"BUY  @ {ask_price:.2f} | amount: {amount_bought:.6f} | fee: {fee:.4f}")

    def exit_market(self, idx: int, row: pd.Series):
        """Sell all trading currency at bid price.

        Args:
            idx: integer index into portfolio_view
            row: current row of portfolio_view
        """
        trading_balance = self.portfolio_view.iloc[idx - 1][self.trading_currency] if idx > 0 else 0.0
        bid_price = row[self.pair + '_bid']

        if trading_balance <= 0 or bid_price <= 0:
            return

        # Sell amount after maker fee
        gross_proceeds = trading_balance * bid_price
        fee = gross_proceeds * self.maker_fee
        net_proceeds = gross_proceeds - fee

        self.portfolio_view.at[row.name, self.base_currency] = net_proceeds
        self.portfolio_view.at[row.name, self.trading_currency] = 0.0
        self.portfolio_view.at[row.name, 'market_position'] = 'out'
        self.portfolio_view.at[row.name, 'action'] = 'sell'
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = net_proceeds

        self.trade_log.append({
            'timestamp': row.name,
            'action': 'sell',
            'price': bid_price,
            'amount': trading_balance,
            'fee': fee,
            self.base_currency: net_proceeds,
            self.trading_currency: 0.0,
        })
        self.logger.info(f"SELL @ {bid_price:.2f} | amount: {trading_balance:.6f} | proceeds: {net_proceeds:.4f} | fee: {fee:.4f}")

    def update_portfolio(self, idx: int, row: pd.Series):
        """Carry forward balances and update portfolio value when no trade occurs.

        Args:
            idx: integer index into portfolio_view
            row: current row of portfolio_view
        """
        if idx == 0:
            return

        prev = self.portfolio_view.iloc[idx - 1]
        base_bal = prev[self.base_currency]
        trading_bal = prev[self.trading_currency]
        current_price = row[self.pair]

        self.portfolio_view.at[row.name, self.base_currency] = base_bal
        self.portfolio_view.at[row.name, self.trading_currency] = trading_bal
        self.portfolio_view.at[row.name, 'market_position'] = prev['market_position']

        portfolio_value = base_bal + trading_bal * current_price
        self.portfolio_view.at[row.name, 'portfolio_in_' + self.base_currency] = portfolio_value

    def run(self, window_short: int, window_long: int) -> dict:
        """Run the backtest using a moving-average crossover strategy.

        Signal:
          - BUY  when short MA crosses above long MA (golden cross)
          - SELL when short MA crosses below long MA (death cross)

        Buy is executed at ask price, sell at bid price.

        Args:
            window_short: short rolling window in minutes
            window_long: long rolling window in minutes

        Returns:
            dict with performance metrics
        """
        self.logger.info(f"Starting backtest | short={window_short}min | long={window_long}min")
        self._set_portfolio_view_df()

        self.dataloader.compute_rolling_means(window_short, window_long)

        ma_short = self.dataloader.rolling_current_short[self.pair]
        ma_long = self.dataloader.rolling_current_long[self.pair]

        # Align indices
        self.portfolio_view['ma_short'] = ma_short
        self.portfolio_view['ma_long'] = ma_long

        # Drop rows where MAs are NaN (warm-up period)
        valid = self.portfolio_view.dropna(subset=['ma_short', 'ma_long'])

        for idx, (timestamp, row) in enumerate(valid.iterrows()):
            int_idx = self.portfolio_view.index.get_loc(timestamp)

            if idx == 0:
                self.update_portfolio(int_idx, row)
                continue

            prev_short = valid['ma_short'].iloc[idx - 1]
            prev_long = valid['ma_long'].iloc[idx - 1]
            curr_short = row['ma_short']
            curr_long = row['ma_long']

            prev_position = self.portfolio_view.iloc[int_idx - 1]['market_position']

            golden_cross = (prev_short <= prev_long) and (curr_short > curr_long)
            death_cross = (prev_short >= prev_long) and (curr_short < curr_long)

            if golden_cross and prev_position == 'out':
                self.enter_market(int_idx, row)
            elif death_cross and prev_position == 'in':
                self.exit_market(int_idx, row)
            else:
                self.update_portfolio(int_idx, row)

        # Force-close any open position at the last bid price
        last_idx = len(self.portfolio_view) - 1
        last_row = self.portfolio_view.iloc[last_idx]
        if last_row['market_position'] == 'in':
            self.exit_market(last_idx, last_row)
            self.portfolio_view.at[last_row.name, 'action'] = 'sell (end)'

        metrics = self.compute_metrics()
        self.logger.info(f"Backtest complete | return: {metrics['total_return_pct']:.2f}%")
        return metrics

    def compute_metrics(self) -> dict:
        """Compute performance metrics after a completed run.

        Returns:
            dict with keys: total_return_pct, buy_and_hold_return_pct,
                            n_trades, win_rate, max_drawdown_pct,
                            sharpe_ratio, total_fees
        """
        portfolio_col = 'portfolio_in_' + self.base_currency
        pv = self.portfolio_view[portfolio_col].dropna()

        initial = float(self.initial_invest)
        final = float(pv.iloc[-1]) if len(pv) > 0 else initial

        total_return_pct = (final - initial) / initial * 100

        # Buy & Hold: buy at first ask, sell at last bid
        first_ask = self.portfolio_view[self.pair + '_ask'].dropna().iloc[0]
        last_bid = self.portfolio_view[self.pair + '_bid'].dropna().iloc[-1]
        bh_amount = (initial * (1 - self.taker_fee)) / first_ask
        bh_final = bh_amount * last_bid * (1 - self.maker_fee)
        bh_return_pct = (bh_final - initial) / initial * 100

        # Trade stats
        trades_df = pd.DataFrame(self.trade_log)
        n_trades = len(trades_df[trades_df['action'] == 'sell']) if not trades_df.empty else 0

        wins = 0
        if not trades_df.empty and n_trades > 0:
            buys = trades_df[trades_df['action'] == 'buy']['price'].values
            sells = trades_df[trades_df['action'].str.startswith('sell')]['price'].values
            pairs = min(len(buys), len(sells))
            wins = int(np.sum(sells[:pairs] > buys[:pairs]))
            win_rate = wins / pairs * 100 if pairs > 0 else 0.0
        else:
            win_rate = 0.0

        # Max drawdown
        rolling_max = pv.cummax()
        drawdown = (pv - rolling_max) / rolling_max * 100
        max_drawdown_pct = float(drawdown.min())

        # Sharpe ratio (annualised, assuming 1-minute bars)
        returns = pv.pct_change().dropna()
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(525_600)  # minutes per year
        else:
            sharpe = 0.0

        total_fees = float(trades_df['fee'].sum()) if not trades_df.empty else 0.0

        return {
            'total_return_pct': round(total_return_pct, 4),
            'buy_and_hold_return_pct': round(bh_return_pct, 4),
            'n_trades': n_trades,
            'win_rate': round(win_rate, 2),
            'max_drawdown_pct': round(max_drawdown_pct, 4),
            'sharpe_ratio': round(sharpe, 4),
            'total_fees': round(total_fees, 4),
            'final_portfolio_value': round(final, 4),
        }


    def plot_results(self, show: bool = True, save_path: str = None):
        """Plot equity curve, buy/sell markers and drawdown after a run().

        Requires matplotlib.  Install with: pip install matplotlib

        Args:
            show:      Display the interactive figure (default True).
            save_path: Optional file path to save the figure (e.g. 'out.png').
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
        pv = self.portfolio_view[pv_col].dropna()
        timestamps = pv.index

        buys  = self.portfolio_view[self.portfolio_view["action"] == "buy"]
        sells = self.portfolio_view[
            self.portfolio_view["action"].str.startswith("sell", na=False)
        ]

        # Drawdown
        rolling_max = pv.cummax()
        drawdown    = (pv - rolling_max) / rolling_max * 100

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8), sharex=True,
            gridspec_kw={"height_ratios": [3, 1]},
        )
        fig.suptitle(
            f"Backtest: {self.pair}  |  "
            f"Return {self.compute_metrics()['total_return_pct']:.2f}%",
            fontsize=13,
        )

        # ── Equity curve ──────────────────────────────────────────────────────
        ax1.plot(timestamps, pv, color="steelblue", linewidth=1.2, label="Portfolio")
        ax1.axhline(self.initial_invest, color="grey", linewidth=0.8,
                    linestyle="--", label="Initial invest")

        if not buys.empty:
            ax1.scatter(
                buys.index, buys[pv_col], marker="^", color="green",
                s=80, zorder=5, label="Buy",
            )
        if not sells.empty:
            ax1.scatter(
                sells.index, sells[pv_col], marker="v", color="red",
                s=80, zorder=5, label="Sell",
            )

        ax1.set_ylabel(f"Portfolio value ({self.base_currency})")
        ax1.legend(loc="upper left", fontsize=9)
        ax1.grid(True, alpha=0.3)

        # ── Drawdown ──────────────────────────────────────────────────────────
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


def run_grid_search(
    engine: "BacktestEngine",
    short_windows: List[int],
    long_windows: List[int],
) -> pd.DataFrame:
    """Run a parameter sweep over MA window combinations.

    Only valid combinations (short < long) are tested.

    Args:
        engine:        A configured BacktestEngine instance.
        short_windows: List of short MA window sizes (minutes).
        long_windows:  List of long MA window sizes (minutes).

    Returns:
        DataFrame sorted by total_return_pct (descending), with one row per
        valid (window_short, window_long) combination.

    Example::

        results = run_grid_search(engine, [10, 20, 50], [100, 200, 500])
        print(results.head())
    """
    logger = logging.getLogger(__name__)
    rows = []

    combos = [(ws, wl) for ws, wl in product(short_windows, long_windows) if ws < wl]
    logger.info(f"Grid search: {len(combos)} combinations to test")

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
        "maker_fee": 0.0025,
        "taker_fee": 0.004,
        "initial_invest": 1000,
        "base_currency": "ZEUR",
        "trading_currency": "XXBT"
    }

    backtest = BacktestEngine(testloader, backtest_config)
    metrics = backtest.run(window_short=50, window_long=200)

    print("\n=== Backtest Results ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    backtest.plot_results(show=False, save_path="Examples/backtest_result.png")

    print("\n=== Grid Search ===")
    results = run_grid_search(backtest, short_windows=[20, 50, 100], long_windows=[100, 200, 500])
    print(results[["window_short", "window_long", "total_return_pct", "n_trades", "sharpe_ratio"]].to_string())
