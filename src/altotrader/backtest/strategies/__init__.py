"""Strategy registry for the AltoTrader backtest engine.

Available strategies
--------------------
``sma``            – Classic SMA crossover (original, via BacktestEngine.run())
``ema``            – Option A: EMA crossover + ATR trailing stop + multi-timeframe filter
``momentum``       – Option B: Time-series momentum + ATR trailing stop
``bollinger_rsi``  – Option C: Bollinger Bands + RSI mean-reversion

Usage::

    from altotrader.backtest.strategies import get_strategy

    strategy = get_strategy("ema")
    metrics  = engine.run_strategy(strategy, ema_short=50, ema_long=200)
"""

from altotrader.backtest.strategies.base import BaseStrategy
from altotrader.backtest.strategies.ma_improved import ImprovedMACrossover
from altotrader.backtest.strategies.momentum import MomentumStrategy
from altotrader.backtest.strategies.bollinger_rsi import BollingerRSIStrategy

_REGISTRY: dict[str, type[BaseStrategy]] = {
    "ema":           ImprovedMACrossover,
    "momentum":      MomentumStrategy,
    "bollinger_rsi": BollingerRSIStrategy,
}


def get_strategy(name: str) -> BaseStrategy:
    """Instantiate a strategy by its short name.

    Args:
        name: One of ``'ema'``, ``'momentum'``, ``'bollinger_rsi'``.

    Returns:
        A fresh strategy instance.

    Raises:
        ValueError: if the name is not in the registry.
    """
    if name not in _REGISTRY:
        available = ", ".join(f"'{k}'" for k in _REGISTRY)
        raise ValueError(
            f"Unknown strategy '{name}'.  Available: {available}"
        )
    return _REGISTRY[name]()


AVAILABLE_STRATEGIES = list(_REGISTRY.keys())

__all__ = [
    "BaseStrategy",
    "ImprovedMACrossover",
    "MomentumStrategy",
    "BollingerRSIStrategy",
    "get_strategy",
    "AVAILABLE_STRATEGIES",
]
