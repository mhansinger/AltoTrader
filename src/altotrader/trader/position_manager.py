"""Position manager – tracks open positions and computes P&L.

Positions are persisted to a JSON file so they survive a process restart.
Only one position per pair at a time (no pyramiding in v1).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    """An open trading position."""
    pair: str
    exchange: str
    entry_price: float
    base_amount: float      # e.g. BTC quantity we hold
    quote_invested: float   # EUR/USDT we spent (including fees)
    entry_time: str         # ISO-8601 string
    order_id: str


class PositionManager:
    """Manages open positions and historical trade records.

    Args:
        persist_path: File path to JSON file for position persistence.
                      Parent directory must exist.
    """

    def __init__(self, persist_path: str = "logs/positions.json") -> None:
        self.persist_path = persist_path
        self.logger = logging.getLogger(__name__)

        # {pair: Position}
        self._positions: dict[str, Position] = {}
        self._trade_history: list[dict] = []

        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def open(self, position: Position) -> None:
        """Record a new open position."""
        if self.is_open(position.pair):
            self.logger.warning(
                f"Position for {position.pair} already open – ignoring duplicate open."
            )
            return
        self._positions[position.pair] = position
        self._save()
        self.logger.info(
            f"POSITION OPENED | {position.pair} | "
            f"entry={position.entry_price:.4f} | qty={position.base_amount:.8f} | "
            f"invested={position.quote_invested:.4f}"
        )

    def close(self, pair: str, exit_price: float, fee: float = 0.0) -> dict:
        """Close an open position and return a P&L summary dict.

        Args:
            pair:       Unified pair, e.g. ``"BTC-EUR"``.
            exit_price: Execution price of the sell order.
            fee:        Fee paid on the sell order.

        Returns:
            Dict with trade summary including ``pnl_abs`` and ``pnl_pct``.
        """
        pos = self._positions.pop(pair, None)
        if pos is None:
            self.logger.warning(f"close() called but no open position for {pair}")
            return {}

        gross_return  = pos.base_amount * exit_price
        net_return    = gross_return - fee
        pnl_abs       = net_return - pos.quote_invested
        pnl_pct       = (pnl_abs / pos.quote_invested) * 100.0

        summary = {
            "pair":            pair,
            "exchange":        pos.exchange,
            "entry_price":     pos.entry_price,
            "exit_price":      exit_price,
            "base_amount":     pos.base_amount,
            "quote_invested":  pos.quote_invested,
            "net_return":      net_return,
            "pnl_abs":         pnl_abs,
            "pnl_pct":         pnl_pct,
            "entry_time":      pos.entry_time,
            "exit_time":       datetime.now(timezone.utc).isoformat(),
        }
        self._trade_history.append(summary)
        self._save()

        self.logger.info(
            f"POSITION CLOSED | {pair} | "
            f"pnl={pnl_abs:+.4f} ({pnl_pct:+.2f}%) | "
            f"exit={exit_price:.4f}"
        )
        return summary

    def is_open(self, pair: str) -> bool:
        """True if there is an open position for this pair."""
        return pair in self._positions

    def get(self, pair: str) -> Optional[Position]:
        """Return the open position for ``pair``, or None."""
        return self._positions.get(pair)

    def get_pnl(self, pair: str, current_price: float) -> float:
        """Unrealised P&L in quote currency at ``current_price``."""
        pos = self._positions.get(pair)
        if pos is None:
            return 0.0
        return (pos.base_amount * current_price) - pos.quote_invested

    @property
    def trade_history(self) -> list[dict]:
        return list(self._trade_history)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
        data = {
            "positions":     {k: asdict(v) for k, v in self._positions.items()},
            "trade_history": self._trade_history,
        }
        try:
            with open(self.persist_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self.logger.error(f"Failed to persist positions: {exc}")

    def _load(self) -> None:
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path) as f:
                data = json.load(f)
            self._positions = {
                k: Position(**v) for k, v in data.get("positions", {}).items()
            }
            self._trade_history = data.get("trade_history", [])
            if self._positions:
                self.logger.info(
                    f"Restored {len(self._positions)} open position(s) from {self.persist_path}"
                )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            self.logger.error(f"Failed to load positions from {self.persist_path}: {exc}")
