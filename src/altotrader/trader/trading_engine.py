"""Main trading engine – fetches prices, generates signals, executes orders.

The engine runs as a daemon thread. Each iteration:
  1. Fetch latest price (c=last, a=ask, b=bid) from the exchange ticker
  2. Feed ``c`` into the SignalGenerator
  3. Check stop-loss if a position is open
  4. Act on BUY / SELL signals
  5. Update risk manager with current portfolio value
  6. Sleep for ``poll_interval`` seconds
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from altotrader.logging_config import setup_logging
from altotrader.trader.broker.base_broker import BaseBroker
from altotrader.trader.config import TradingConfig
from altotrader.trader.position_manager import Position, PositionManager
from altotrader.trader.risk_manager import RiskManager
from altotrader.trader.signal_generator import Signal, SignalGenerator


class TradingEngine(threading.Thread):
    """Runs the live (or paper) trading loop for a single pair on one exchange.

    Args:
        config:       Full TradingConfig for this instance.
        ticker:       Any ticker object that implements ``get_market_query()``
                      returning ``{pair: {c, a, b, v}}``.
        broker:       A BaseBroker implementation (PaperBroker or a live broker).
        position_mgr: Shared PositionManager (can be shared across multiple engines).
        risk_mgr:     RiskManager for this pair.
        log_dir:      Directory for log files.
    """

    def __init__(
        self,
        config: TradingConfig,
        ticker,
        broker: BaseBroker,
        position_mgr: PositionManager,
        risk_mgr: RiskManager,
        log_dir: str = "logs",
    ) -> None:
        super().__init__(name=f"TradingEngine-{config.exchange}-{config.pair}", daemon=False)
        self.config       = config
        self.ticker       = ticker
        self.broker       = broker
        self.position_mgr = position_mgr
        self.risk_mgr     = risk_mgr

        self._stop_flag = threading.Event()
        self._signal_gen = SignalGenerator(
            window_short=config.window_short,
            window_long=config.window_long,
            min_prices=config.min_prices,
        )

        setup_logging(
            log_filename=f"trading_{config.exchange}_{config.pair.replace('-', '')}.log",
            log_dir=log_dir,
        )
        self.logger = logging.getLogger(__name__)
        mode = "PAPER" if config.paper_trading else "LIVE"
        self.logger.info(
            f"[{mode}] TradingEngine started | {config.exchange} {config.pair} | "
            f"SMA({config.window_short}/{config.window_long}) | "
            f"stop_loss={config.stop_loss_pct*100:.1f}% | "
            f"invest={config.initial_invest} {config.quote_currency}"
        )

    # ── Thread entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        while not self._stop_flag.is_set():
            try:
                self._iteration()
            except Exception as exc:
                self.logger.error(f"Unhandled error in trading loop: {exc}", exc_info=True)
            self._stop_flag.wait(timeout=self.config.poll_interval)

        self.logger.info(f"TradingEngine stopped for {self.config.pair}.")

    def stop(self) -> None:
        """Request graceful shutdown."""
        self._stop_flag.set()

    # ── Core loop ─────────────────────────────────────────────────────────────

    def _iteration(self) -> None:
        prices = self._fetch_prices()
        if prices is None:
            return

        last_price = prices["c"]
        ask_price  = prices["a"]
        bid_price  = prices["b"]

        # ── Risk: max drawdown ────────────────────────────────────────────────
        portfolio_val = self._portfolio_value(last_price)
        self.risk_mgr.update_peak(portfolio_val)
        if self.risk_mgr.check_max_drawdown(portfolio_val):
            self.logger.error("Trading halted due to max drawdown. Stop the bot and review.")
            self._stop_flag.set()
            return

        # ── Risk: stop-loss ───────────────────────────────────────────────────
        if self.position_mgr.is_open(self.config.pair):
            pos = self.position_mgr.get(self.config.pair)
            if self.risk_mgr.check_stop_loss(pos, last_price):
                self._execute_sell(bid_price, reason="stop_loss")
                return

        # ── Signal ───────────────────────────────────────────────────────────
        signal = self._signal_gen.update(last_price)

        if signal == Signal.BUY and not self.position_mgr.is_open(self.config.pair):
            balance = self.broker.get_balance(self.config.quote_currency)
            size    = self.risk_mgr.position_size(balance, ask_price)
            if size > 0:
                self._execute_buy(ask_price, size)

        elif signal == Signal.SELL and self.position_mgr.is_open(self.config.pair):
            self._execute_sell(bid_price, reason="signal")

    # ── Order execution ───────────────────────────────────────────────────────

    def _execute_buy(self, ask_price: float, quote_amount: float) -> None:
        try:
            result = self.broker.buy(self.config.pair, quote_amount, ask_price)
            position = Position(
                pair=self.config.pair,
                exchange=self.config.exchange,
                entry_price=result.price,
                base_amount=result.base_amount,
                quote_invested=result.quote_amount,
                entry_time=datetime.now(timezone.utc).isoformat(),
                order_id=result.order_id,
            )
            self.position_mgr.open(position)
        except Exception as exc:
            self.logger.error(f"BUY order failed for {self.config.pair}: {exc}")

    def _execute_sell(self, bid_price: float, reason: str = "signal") -> None:
        pos = self.position_mgr.get(self.config.pair)
        if pos is None:
            return
        try:
            result = self.broker.sell(self.config.pair, pos.base_amount, bid_price)
            summary = self.position_mgr.close(
                self.config.pair, result.price, fee=result.fee
            )
            self.logger.info(
                f"SELL [{reason}] | pnl={summary.get('pnl_abs', 0):+.4f} "
                f"({summary.get('pnl_pct', 0):+.2f}%)"
            )
        except Exception as exc:
            self.logger.error(f"SELL order failed for {self.config.pair}: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fetch_prices(self) -> Optional[dict]:
        """Fetch latest prices from the ticker. Returns None on failure."""
        try:
            market_query = self.ticker.get_market_query()
            prices = market_query.get(self.config.pair)
            if not prices:
                self.logger.warning(f"No price data for {self.config.pair}")
                return None
            return prices
        except Exception as exc:
            self.logger.warning(f"Price fetch failed: {exc}")
            return None

    def _portfolio_value(self, current_price: float) -> float:
        """Total portfolio value in quote currency (cash + open position)."""
        cash = self.broker.get_balance(self.config.quote_currency)
        if self.position_mgr.is_open(self.config.pair):
            pos  = self.position_mgr.get(self.config.pair)
            return cash + pos.base_amount * current_price
        return cash
