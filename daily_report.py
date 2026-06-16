"""JOB C — Slack daily/30-min report. Read-only, never mutates state."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PORTFOLIO_PATH = Path("portfolio.json")
TRADES_PATH = Path("paper_trades.json")
SIGNALS_PATH = Path("signals.json")
ACTIVE_WALLETS_PATH = Path("active_wallets.json")


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _humanize_age(ts: str, now: datetime) -> str:
    delta = now - _parse_ts(ts)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    rem_minutes = minutes % 60
    return f"{hours}h {rem_minutes}m ago"


def build_message() -> str:
    now = datetime.now(timezone.utc)
    portfolio = _load(PORTFOLIO_PATH, {"cash": 10000.0, "starting_cash": 10000.0, "open_positions": {}, "equity_history": []})
    trades = _load(TRADES_PATH, [])
    signals = _load(SIGNALS_PATH, [])
    active = _load(ACTIVE_WALLETS_PATH, {"top_traders": []})

    starting_cash = portfolio.get("starting_cash", 10000.0)
    equity_history = portfolio.get("equity_history", [])
    current_equity = equity_history[-1]["equity"] if equity_history else portfolio.get("cash", starting_cash)

    cutoff_24h = now - timedelta(hours=24)
    equity_24h_ago = starting_cash
    for snap in equity_history:
        snap_ts = _parse_ts(snap["ts"])
        if snap_ts <= cutoff_24h:
            equity_24h_ago = snap["equity"]
        else:
            break

    pnl_24h = current_equity - equity_24h_ago
    pnl_24h_pct = (pnl_24h / equity_24h_ago * 100) if equity_24h_ago else 0.0

    all_time_pnl = current_equity - starting_cash
    all_time_pct = (all_time_pnl / starting_cash * 100) if starting_cash else 0.0

    trades_24h = [t for t in trades if "closed_at" in t and _parse_ts(t["closed_at"]) >= cutoff_24h]
    realized_pnl_24h = sum(t.get("pnl", 0) for t in trades_24h)

    signals_24h = [s for s in signals if _parse_ts(s["ts"]) >= cutoff_24h]
    new_count = sum(1 for s in signals_24h if s["type"] == "NEW")
    closed_count = sum(1 for s in signals_24h if s["type"] == "CLOSED")

    open_positions = list(portfolio.get("open_positions", {}).values())

    last_signal = signals[-1] if signals else None
    last_trade = trades[-1] if trades else None

    lines = []
    lines.append(f"*📈 Copytrade daily report — {now.strftime('%Y-%m-%d')}*")
    lines.append("")
    lines.append(
        f"*Portfolio:* `${current_equity:,.2f}`  (yesterday: `${equity_24h_ago:,.2f}`)"
    )
    lines.append(f"*24h PnL:* `{pnl_24h:+,.2f}` USD  (`{pnl_24h_pct:+.2f}%`)")
    lines.append(
        f"*All-time:* `{all_time_pnl:+,.2f}` USD  (`{all_time_pct:+.2f}%`)  — start `${starting_cash:,.0f}`"
    )
    lines.append("")
    lines.append("*Last 24h activity:*")
    lines.append(f"• Signals: {new_count} NEW, {closed_count} CLOSED")
    lines.append(f"• Closed paper trades: {len(trades_24h)}  (realized PnL: `{realized_pnl_24h:+,.2f}` USD)")
    lines.append(f"• Open positions: {len(open_positions)}")
    lines.append("")
    lines.append("*Last activity:*")
    if last_signal:
        age = _humanize_age(last_signal["ts"], now)
        lines.append(
            f"• Last signal: {age} — {last_signal['type']} {last_signal['side']} {last_signal['coin']} "
            f"({last_signal['trader'][:10]}...)"
        )
    else:
        lines.append("• Last signal: none yet")
    if last_trade:
        age = _humanize_age(last_trade["closed_at"], now)
        lines.append(
            f"• Last paper trade closed: {age} — {last_trade['side']} {last_trade['coin']} "
            f"PnL `{last_trade['pnl']:+,.2f}` USD"
        )
    else:
        lines.append("• Last paper trade closed: none yet")
    lines.append("")
    lines.append(f"*Following:* {len(active.get('top_traders', []))} traders")
    lines.append("")
    lines.append("*Open positions:*")
    if open_positions:
        for p in open_positions[:10]:
            lines.append(
                f"• {p['side']} {p['coin']}  size=`{p['size']:.4f}`  entry=`${p['entry_price']:,.4f}`  x{p['leverage']}"
            )
    else:
        lines.append("• none")

    return "\n".join(lines)


def main() -> int:
    message = build_message()

    if os.environ.get("DRY_RUN") == "1":
        print(message)
        return 0

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    resp = requests.post(webhook_url, json={"text": message}, timeout=20)
    resp.raise_for_status()
    print("Report posted to Slack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
