"""Trading configuration dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TradingConfig:
    """All parameters for one trading engine instance (one pair on one exchange).

    Args:
        pair:             Unified pair format, e.g. ``"BTC-EUR"``.
        exchange:         ``"kraken"`` or ``"binance"``.
        window_short:     Short SMA window in price-ticks (= poll cycles), e.g. 50.
        window_long:      Long SMA window in price-ticks, e.g. 200.
        initial_invest:   Starting capital in quote currency (EUR / USDT …).
        maker_fee:        Maker fee fraction, e.g. 0.0025 for 0.25 %.
        taker_fee:        Taker fee fraction, e.g. 0.004 for 0.40 %.
        slippage_pct:     Additional slippage fraction applied to order price,
                          e.g. 0.0005 for 0.05 %.
        stop_loss_pct:    Fraction below entry price that triggers stop-loss,
                          e.g. 0.05 for 5 %.
        max_drawdown_pct: Portfolio drawdown from peak that halts all trading,
                          e.g. 0.20 for 20 %.
        max_position_pct: Maximum fraction of available capital to invest per trade,
                          e.g. 0.95 (keep 5 % as buffer for fees).
        paper_trading:    If True, no real orders are placed.
        min_prices:       Minimum price ticks before the first signal is emitted
                          (must be > window_long to avoid look-ahead bias).
        poll_interval:    Seconds between price fetches. Default 60.
    """

    pair: str
    exchange: str

    window_short: int = 50
    window_long: int = 200

    initial_invest: float = 1000.0
    maker_fee: float = 0.0025
    taker_fee: float = 0.004
    slippage_pct: float = 0.0005

    stop_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.20
    max_position_pct: float = 0.95

    paper_trading: bool = True
    min_prices: int = field(init=False)
    poll_interval: int = 60

    def __post_init__(self) -> None:
        if self.window_short >= self.window_long:
            raise ValueError(
                f"window_short ({self.window_short}) must be < window_long ({self.window_long})"
            )
        self.min_prices = self.window_long + 10  # safety buffer

    @property
    def base_currency(self) -> str:
        """e.g. 'BTC' from 'BTC-EUR'."""
        return self.pair.split("-")[0]

    @property
    def quote_currency(self) -> str:
        """e.g. 'EUR' from 'BTC-EUR'."""
        return self.pair.split("-")[1]
