"""Bot status overview – prices, balances, open positions.

Shows at a glance:
  - Current prices for configured pairs (no API key required)
  - Exchange balances (requires API keys)
  - Open positions from positions.json + unrealised P&L

Usage:
    # Prices only (no API key needed):
    python Examples/status.py --exchange kraken --pairs BTC-EUR,ETH-EUR

    # Full status with balances (API keys via env or .env):
    KRAKEN_API_KEY=... KRAKEN_API_SECRET=... \\
    python Examples/status.py --exchange kraken --pairs BTC-EUR,ETH-EUR

    # Binance:
    BINANCE_API_KEY=... BINANCE_API_SECRET=... \\
    python Examples/status.py --exchange binance --pairs BTC-USDT,ETH-USDT

    # Custom positions file:
    python Examples/status.py --positions logs/positions.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _color(text: str, code: str) -> str:
    """ANSI color if stdout is a terminal."""
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def green(t):  return _color(t, "32")
def red(t):    return _color(t, "31")
def yellow(t): return _color(t, "33")
def bold(t):   return _color(t, "1")
def dim(t):    return _color(t, "2")


def _pnl_str(pnl: float) -> str:
    s = f"{pnl:+.2f}"
    return green(s) if pnl >= 0 else red(s)


def _build_ticker(exchange: str, pairs: list[str]):
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump({"items": pairs}, tmp)
    tmp.close()
    if exchange == "kraken":
        from altotrader.ticker.krakenticker import KrakenTicker
        return KrakenTicker(pairs_yaml=tmp.name)
    elif exchange == "binance":
        from altotrader.ticker.binanceticker import BinanceTicker
        return BinanceTicker(pairs_yaml=tmp.name)
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")


def _build_broker(exchange: str, pair: str):
    """Return a broker if API keys are set, else None."""
    from altotrader.trader.config import TradingConfig
    cfg = TradingConfig(pair=pair, exchange=exchange, paper_trading=False)

    if exchange == "kraken":
        if not (os.environ.get("KRAKEN_API_KEY") and os.environ.get("KRAKEN_API_SECRET")):
            return None
        from altotrader.trader.broker.kraken_broker import KrakenBroker
        try:
            return KrakenBroker(cfg)
        except Exception:
            return None
    elif exchange == "binance":
        if not (os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET")):
            return None
        from altotrader.trader.broker.binance_broker import BinanceBroker
        try:
            return BinanceBroker(cfg)
        except Exception:
            return None
    return None


def _load_positions(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            data = json.load(f)
        return data.get("positions", {})
    except (json.JSONDecodeError, OSError):
        return {}


# ── Sections ──────────────────────────────────────────────────────────────────

def print_prices(exchange: str, pairs: list[str]) -> dict:
    """Fetch and print current prices. Returns market_query dict."""
    print(bold(f"\n{'─'*50}"))
    print(bold(f"  PRICES  ({exchange.upper()})"))
    print(bold(f"{'─'*50}"))

    try:
        ticker = _build_ticker(exchange, pairs)
        mq = ticker.get_market_query()
    except Exception as exc:
        print(red(f"  Price fetch failed: {exc}"))
        return {}

    for pair in pairs:
        data = mq.get(pair)
        if not data:
            print(f"  {pair:<12} {yellow('no data')}")
            continue
        # Kraken returns ask/bid as [price, wholeLotVolume, lotVolume] – take first element
        c = float(data["c"][0]) if isinstance(data["c"], list) else float(data["c"])
        a = float(data["a"][0]) if isinstance(data["a"], list) else float(data["a"])
        b = float(data["b"][0]) if isinstance(data["b"], list) else float(data["b"])
        spread = a - b
        print(
            f"  {bold(pair):<20}  "
            f"last={c:>12,.2f}  "
            f"ask={a:>12,.2f}  "
            f"bid={b:>12,.2f}  "
            f"spread={dim(f'{spread:.2f}')}"
        )
    return mq


def print_balances(exchange: str, pairs: list[str]) -> None:
    """Fetch and print exchange balances (requires API keys)."""
    print(bold(f"\n{'─'*50}"))
    print(bold(f"  BALANCE  ({exchange.upper()})"))
    print(bold(f"{'─'*50}"))

    # Use the first pair's broker to query balance
    broker = _build_broker(exchange, pairs[0])
    if broker is None:
        print(dim(f"  No API keys set – skipping balance."))
        print(dim(f"  Set {exchange.upper()}_API_KEY and {exchange.upper()}_API_SECRET to see balances."))
        return

    # Collect unique currencies from all pairs
    currencies: list[str] = []
    for pair in pairs:
        base, quote = pair.split("-")
        if base not in currencies:
            currencies.append(base)
        if quote not in currencies:
            currencies.append(quote)

    for currency in currencies:
        try:
            bal = broker.get_balance(currency)
            marker = dim("  ") if bal < 0.0001 else "  "
            print(f"{marker}{currency:<8}  {bal:>16.6f}")
        except Exception as exc:
            print(f"  {currency:<8}  {red(str(exc))}")


def print_positions(positions: dict, mq: dict) -> None:
    """Print open positions with unrealised P&L."""
    print(bold(f"\n{'─'*50}"))
    print(bold(f"  OPEN POSITIONS"))
    print(bold(f"{'─'*50}"))

    if not positions:
        print(dim("  No open positions."))
        return

    for pair, pos in positions.items():
        entry_price   = pos.get("entry_price", 0)
        base_amount   = pos.get("base_amount", 0)
        quote_invested = pos.get("quote_invested", 0)
        entry_time    = pos.get("entry_time", "–")
        order_id      = pos.get("order_id", "–")[:12]

        # Unrealised P&L
        raw_c = mq.get(pair, {}).get("c")
        current_price = float(raw_c[0]) if isinstance(raw_c, list) else (float(raw_c) if raw_c else None)
        if current_price:
            current_value = base_amount * current_price
            pnl_abs = current_value - quote_invested
            pnl_pct = (pnl_abs / quote_invested * 100) if quote_invested else 0
            pnl_display = f"{_pnl_str(pnl_abs)}  ({_pnl_str(pnl_pct)}%)"
        else:
            pnl_display = dim("(no current price)")

        print(f"  {bold(pair)}")
        print(f"    Entry:     {entry_price:>12,.2f}  ×  {base_amount:.6f} {pair.split('-')[0]}")
        print(f"    Invested:  {quote_invested:>12,.2f} {pair.split('-')[1]}")
        if current_price:
            print(f"    Current:   {current_price:>12,.2f}")
        print(f"    P&L:       {pnl_display}")
        print(f"    Since:     {entry_time[:19].replace('T', ' ')}")
        print(f"    Order ID:  {dim(order_id)}…")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="AltoTrader – bot status")
    p.add_argument("--exchange", default=os.environ.get("EXCHANGE", "kraken"),
                   choices=["kraken", "binance"])
    p.add_argument("--pairs",    default=os.environ.get("TRADER_PAIR", "BTC-EUR"),
                   help="Comma-separated pairs, e.g. BTC-EUR,ETH-EUR")
    p.add_argument("--positions", default="logs/positions.json",
                   help="Path to positions.json")
    args = p.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(bold(f"\n{'═'*50}"))
    print(bold(f"  AltoTrader Status  –  {now}"))
    print(bold(f"{'═'*50}"))

    mq        = print_prices(args.exchange, pairs)
    _          = print_balances(args.exchange, pairs)
    positions  = _load_positions(args.positions)
    print_positions(positions, mq)

    print(bold(f"\n{'═'*50}\n"))


if __name__ == "__main__":
    main()
