"""Mock execution engine for paper-trading copytrade signals."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

STARTING_CASH = 10_000.0
POSITION_PCT = 0.05  # 5% of cash per signal
SLIPPAGE_BPS = 5
MAX_LEVERAGE = 3

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


def apply_slippage(mark: float, side: str) -> float:
    if side == "LONG":
        return mark * (1 + SLIPPAGE_BPS / 10000)
    return mark * (1 - SLIPPAGE_BPS / 10000)


def open_position(portfolio: dict, signal: dict, mark: float) -> None:
    leverage = min(int(signal.get("leverage", 1)), MAX_LEVERAGE)
    cash = portfolio["cash"]
    notional = cash * POSITION_PCT * leverage
    margin = notional / leverage

    if margin > cash:
        return

    side = signal["side"]
    fill_price = apply_slippage(mark, side)
    size = notional / fill_price

    key = _position_key(signal["trader"], signal["coin"], side)
    portfolio["open_positions"][key] = {
        "trader": signal["trader"],
        "coin": signal["coin"],
        "side": side,
        "size": size,
        "entry_price": fill_price,
        "leverage": leverage,
        "margin": margin,
        "notional": notional,
        "opened_at": signal.get("ts"),
    }
    portfolio["cash"] = cash - margin


def close_position(portfolio: dict, signal: dict, mark: float) -> None:
    side = signal["side"]
    key = _position_key(signal["trader"], signal["coin"], side)
    pos = portfolio["open_positions"].pop(key, None)
    if pos is None:
        return

    opposite_side = "SHORT" if side == "LONG" else "LONG"
    exit_price = apply_slippage(mark, opposite_side)

    if side == "LONG":
        pnl = (exit_price - pos["entry_price"]) * pos["size"]
    else:
        pnl = (pos["entry_price"] - exit_price) * pos["size"]

    portfolio["cash"] += pos["margin"] + pnl

    trade = dict(pos)
    trade["exit_price"] = exit_price
    trade["closed_at"] = signal.get("ts")
    trade["pnl"] = pnl
    trade["pnl_pct"] = (pnl / pos["margin"] * 100) if pos["margin"] else 0.0

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
        print(f"  {key}: size={pos['size']:.4f} entry=${pos['entry_price']:.4f} x{pos['leverage']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary()
    else:
        apply_new_signals()
