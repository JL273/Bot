"""Mock execution engine for paper-trading copytrade signals."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

STARTING_CASH = 10_000.0
POSITION_PCT = 0.05  # 5% of cash per signal
MAX_LEVERAGE = 3
SLIPPAGE_BPS_FALLBACK = 10  # used only when L2 book fetch fails

PORTFOLIO_PATH = Path("portfolio.json")
SIGNALS_PATH = Path("signals.json")
TRADES_PATH = Path("paper_trades.json")

INFO_URL = "https://api.hyperliquid.xyz/info"


def get_mark_prices() -> dict[str, float]:
    resp = requests.post(
        INFO_URL,
        json={"type": "allMids"},
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return {coin: float(px) for coin, px in data.items()}


def _fallback_fill(mark: float, side: str) -> float:
    """Fixed-slippage fallback when the order book is unavailable."""
    if side == "LONG":
        return mark * (1 + SLIPPAGE_BPS_FALLBACK / 10_000)
    return mark * (1 - SLIPPAGE_BPS_FALLBACK / 10_000)


def get_fill_price(coin: str, side: str, notional_usd: float, mark: float) -> tuple[float, str]:
    """
    Simulate a market order fill by walking the real L2 order book.

    Returns (fill_price, method) where method is 'book' or 'fallback'.
    - LONG  = buying  → walk asks (index 1, lowest price first)
    - SHORT = selling → walk bids (index 0, highest price first)
    """
    try:
        resp = requests.post(
            INFO_URL,
            json={"type": "l2Book", "coin": coin},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        book = resp.json()
        levels = book.get("levels", [[], []])

        # bids = levels[0] (sorted high→low), asks = levels[1] (sorted low→high)
        side_levels = levels[1] if side == "LONG" else levels[0]

        remaining_usd = notional_usd
        total_cost = 0.0
        total_size = 0.0

        for level in side_levels:
            px = float(level["px"])
            sz = float(level["sz"])
            level_usd = px * sz

            if remaining_usd <= level_usd:
                fill_sz = remaining_usd / px
                total_cost += remaining_usd
                total_size += fill_sz
                remaining_usd = 0.0
                break
            else:
                total_cost += level_usd
                total_size += sz
                remaining_usd -= level_usd

        if total_size > 0:
            return total_cost / total_size, "book"

    except Exception:
        pass

    return _fallback_fill(mark, side), "fallback"


def load_portfolio() -> dict:
    if PORTFOLIO_PATH.exists():
        return json.loads(PORTFOLIO_PATH.read_text())
    return {
        "cash": STARTING_CASH,
        "starting_cash": STARTING_CASH,
        "open_positions": {},
        "equity_history": [],
        "last_processed_signal_index": -1,
    }


def save_portfolio(portfolio: dict) -> None:
    PORTFOLIO_PATH.write_text(json.dumps(portfolio, indent=2))


def _position_key(trader: str, coin: str, side: str) -> str:
    return f"{trader}:{coin}:{side}"


def open_position(portfolio: dict, signal: dict, mark: float) -> None:
    leverage = min(int(signal.get("leverage", 1)), MAX_LEVERAGE)
    cash = portfolio["cash"]
    notional = cash * POSITION_PCT * leverage
    margin = notional / leverage

    if margin > cash:
        return

    side = signal["side"]
    coin = signal["coin"]
    fill_price, fill_method = get_fill_price(coin, side, notional, mark)
    size = notional / fill_price

    # Slippage vs mid for logging
    slippage_bps = abs(fill_price - mark) / mark * 10_000 if mark else 0.0

    key = _position_key(signal["trader"], coin, side)
    portfolio["open_positions"][key] = {
        "trader": signal["trader"],
        "coin": coin,
        "side": side,
        "size": size,
        "entry_price": fill_price,
        "entry_slippage_bps": round(slippage_bps, 2),
        "entry_fill_method": fill_method,
        "leverage": leverage,
        "margin": margin,
        "notional": notional,
        "opened_at": signal.get("ts"),
    }
    portfolio["cash"] = cash - margin


def close_position(portfolio: dict, signal: dict, mark: float) -> None:
    side = signal["side"]
    coin = signal["coin"]
    key = _position_key(signal["trader"], coin, side)
    pos = portfolio["open_positions"].pop(key, None)
    if pos is None:
        return

    # Closing a LONG = selling → use SHORT side of book; vice versa
    exit_side = "SHORT" if side == "LONG" else "LONG"
    close_notional = pos["size"] * mark  # approximate notional to walk the book
    exit_price, exit_method = get_fill_price(coin, exit_side, close_notional, mark)

    if side == "LONG":
        pnl = (exit_price - pos["entry_price"]) * pos["size"]
    else:
        pnl = (pos["entry_price"] - exit_price) * pos["size"]

    portfolio["cash"] += pos["margin"] + pnl

    exit_slippage_bps = abs(exit_price - mark) / mark * 10_000 if mark else 0.0

    trade = dict(pos)
    trade["exit_price"] = exit_price
    trade["exit_slippage_bps"] = round(exit_slippage_bps, 2)
    trade["exit_fill_method"] = exit_method
    trade["closed_at"] = signal.get("ts")
    trade["pnl"] = pnl
    trade["pnl_pct"] = (pnl / pos["margin"] * 100) if pos["margin"] else 0.0
    trade["total_slippage_bps"] = round(
        pos.get("entry_slippage_bps", 0) + exit_slippage_bps, 2
    )

    trades = []
    if TRADES_PATH.exists():
        trades = json.loads(TRADES_PATH.read_text())
    trades.append(trade)
    TRADES_PATH.write_text(json.dumps(trades, indent=2))


def _compute_equity(portfolio: dict, marks: dict[str, float]) -> float:
    equity = portfolio["cash"]
    for pos in portfolio["open_positions"].values():
        mark = marks.get(pos["coin"])
        if mark is None:
            equity += pos["margin"]
            continue
        if pos["side"] == "LONG":
            unrealized = (mark - pos["entry_price"]) * pos["size"]
        else:
            unrealized = (pos["entry_price"] - mark) * pos["size"]
        equity += pos["margin"] + unrealized
    return equity


def apply_new_signals() -> dict:
    portfolio = load_portfolio()

    signals = []
    if SIGNALS_PATH.exists():
        signals = json.loads(SIGNALS_PATH.read_text())

    start = portfolio["last_processed_signal_index"] + 1
    new_signals = signals[start:]

    if new_signals:
        marks = get_mark_prices()
        for signal in new_signals:
            mark = marks.get(signal["coin"])
            if mark is None:
                continue
            if signal["type"] == "NEW":
                open_position(portfolio, signal, mark)
            elif signal["type"] == "CLOSED":
                close_position(portfolio, signal, mark)

        portfolio["last_processed_signal_index"] = len(signals) - 1

    try:
        marks_for_equity = get_mark_prices()
    except Exception:
        marks_for_equity = {}
    equity = _compute_equity(portfolio, marks_for_equity)
    portfolio["equity_history"].append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": equity,
            "cash": portfolio["cash"],
        }
    )

    save_portfolio(portfolio)
    return portfolio


def summary() -> None:
    portfolio = load_portfolio()
    try:
        marks = get_mark_prices()
    except Exception:
        marks = {}
    equity = _compute_equity(portfolio, marks)
    starting = portfolio["starting_cash"]
    pnl = equity - starting
    pnl_pct = (pnl / starting * 100) if starting else 0.0
    print(f"Cash: ${portfolio['cash']:,.2f}")
    print(f"Equity: ${equity:,.2f}")
    print(f"All-time PnL: {pnl:+,.2f} ({pnl_pct:+.2f}%)")
    print(f"Open positions: {len(portfolio['open_positions'])}")
    for key, pos in portfolio["open_positions"].items():
        print(
            f"  {key}: size={pos['size']:.4f} entry=${pos['entry_price']:.4f} "
            f"x{pos['leverage']} entry_slip={pos.get('entry_slippage_bps', '?')}bps"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary()
    else:
        apply_new_signals()
