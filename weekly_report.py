"""Weekly learning report — posts detailed analysis to Slack every Monday."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SLACK_WEBHOOK  = os.environ["SLACK_WEBHOOK_URL"]
PORTFOLIO_PATH = Path("portfolio.json")
TRADES_PATH    = Path("paper_trades.json")
SIGNALS_PATH   = Path("signals.json")
WALLETS_PATH   = Path("active_wallets.json")


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _fmt(v: float) -> str:
    return ("+" if v >= 0 else "-") + f"${abs(v):,.2f}"


def _pct(v: float) -> str:
    return ("+" if v >= 0 else "") + f"{v:.2f}%"


def _post(text: str) -> None:
    r = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=15)
    r.raise_for_status()


def main() -> None:
    portfolio = _load(PORTFOLIO_PATH, {})
    trades    = _load(TRADES_PATH,    [])
    signals   = _load(SIGNALS_PATH,   [])
    wallets   = _load(WALLETS_PATH,   {})

    now      = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    week_iso = week_ago.isoformat()

    # ── Portfolio ────────────────────────────────────────────────────────────
    history  = portfolio.get("equity_history", [])
    starting = portfolio.get("starting_cash", 10_000.0)
    current  = history[-1]["equity"] if history else portfolio.get("cash", starting)

    eq_week_ago = starting
    for s in history:
        if s["ts"] <= week_iso:
            eq_week_ago = s["equity"]

    week_pnl = current - eq_week_ago
    week_pct = week_pnl / eq_week_ago * 100 if eq_week_ago else 0
    all_pnl  = current - starting
    all_pct  = all_pnl / starting * 100 if starting else 0
    open_pos = len(portfolio.get("open_positions", {}))

    # ── Trades this week ─────────────────────────────────────────────────────
    week_trades = [t for t in trades if (t.get("closed_at") or "") >= week_iso]
    wins        = [t for t in week_trades if t.get("pnl", 0) > 0]
    losses      = [t for t in week_trades if t.get("pnl", 0) <= 0]
    win_rate    = len(wins) / len(week_trades) * 100 if week_trades else 0
    realized_w  = sum(t.get("pnl", 0) for t in week_trades)

    all_wins    = [t for t in trades if t.get("pnl", 0) > 0]
    all_wr      = len(all_wins) / len(trades) * 100 if trades else 0

    # ── Best / worst trades ──────────────────────────────────────────────────
    sorted_w = sorted(week_trades, key=lambda t: t.get("pnl", 0), reverse=True)
    best3    = sorted_w[:3]
    worst3   = sorted_w[-3:][::-1]

    # ── Exit reason breakdown ────────────────────────────────────────────────
    exit_counts: dict[str, int] = defaultdict(int)
    for t in week_trades:
        r = t.get("exit_reason", "trader")
        if r == "trader":            exit_counts["Copy trader"] += 1
        elif r.startswith("SL"):     exit_counts["Stop-loss"] += 1
        elif r.startswith("TP"):     exit_counts["Take-profit"] += 1
        elif r.startswith("time"):   exit_counts["Time-stop"] += 1
        else:                        exit_counts[r] += 1

    # ── Coin performance ─────────────────────────────────────────────────────
    coin_pnl: dict[str, float] = defaultdict(float)
    coin_cnt: dict[str, int]   = defaultdict(int)
    for t in week_trades:
        coin_pnl[t["coin"]] += t.get("pnl", 0)
        coin_cnt[t["coin"]] += 1
    best_coins  = sorted(coin_pnl.items(), key=lambda x: x[1], reverse=True)[:3]
    worst_coins = sorted(coin_pnl.items(), key=lambda x: x[1])[:3]

    # ── Daily PnL last 7 days ────────────────────────────────────────────────
    by_day: dict[str, float] = {}
    for s in history:
        by_day[s["ts"][:10]] = s["equity"]
    days_sorted = sorted(by_day)
    daily_pnl: dict[str, float] = {}
    for i in range(1, len(days_sorted)):
        daily_pnl[days_sorted[i]] = by_day[days_sorted[i]] - by_day[days_sorted[i - 1]]
    last7 = sorted(daily_pnl)[-7:]

    # ── Signals this week ────────────────────────────────────────────────────
    week_sigs   = [s for s in signals if (s.get("ts") or "") >= week_iso]
    new_sigs    = [s for s in week_sigs if s.get("type") == "NEW"]
    closed_sigs = [s for s in week_sigs if s.get("type") == "CLOSED"]

    # ── Trader attribution ───────────────────────────────────────────────────
    trader_pnl: dict[str, float] = defaultdict(float)
    trader_cnt: dict[str, int]   = defaultdict(int)
    for t in week_trades:
        addr = t.get("trader", "unknown")
        trader_pnl[addr] += t.get("pnl", 0)
        trader_cnt[addr] += 1
    best_traders = sorted(trader_pnl.items(), key=lambda x: x[1], reverse=True)[:3]

    # ── Learnings / observations ─────────────────────────────────────────────
    learnings: list[str] = []

    # LONG vs SHORT bias
    long_pnl  = sum(t.get("pnl", 0) for t in week_trades if t.get("side") == "LONG")
    short_pnl = sum(t.get("pnl", 0) for t in week_trades if t.get("side") == "SHORT")
    long_cnt  = sum(1 for t in week_trades if t.get("side") == "LONG")
    short_cnt = sum(1 for t in week_trades if t.get("side") == "SHORT")
    if long_cnt and short_cnt:
        if long_pnl > short_pnl:
            learnings.append(f"LONG trades outperformed SHORT this week ({_fmt(long_pnl)} vs {_fmt(short_pnl)})")
        else:
            learnings.append(f"SHORT trades outperformed LONG this week ({_fmt(short_pnl)} vs {_fmt(long_pnl)})")
    elif long_cnt:
        learnings.append(f"Only LONG positions this week — {_fmt(long_pnl)} total")
    elif short_cnt:
        learnings.append(f"Only SHORT positions this week — {_fmt(short_pnl)} total")

    # Stop-loss analysis
    sl_trades = [t for t in week_trades if str(t.get("exit_reason", "")).startswith("SL")]
    tp_trades = [t for t in week_trades if str(t.get("exit_reason", "")).startswith("TP")]
    ts_trades = [t for t in week_trades if str(t.get("exit_reason", "")).startswith("time")]
    if tp_trades:
        avg_tp = sum(t.get("pnl", 0) for t in tp_trades) / len(tp_trades)
        learnings.append(f"Take-profit fired {len(tp_trades)}x — avg gain {_fmt(avg_tp)} per trade")
    if sl_trades:
        avg_sl = sum(t.get("pnl", 0) for t in sl_trades) / len(sl_trades)
        learnings.append(f"Stop-loss fired {len(sl_trades)}x — avg loss {_fmt(avg_sl)} per trade")
    if ts_trades:
        avg_ts = sum(t.get("pnl", 0) for t in ts_trades) / len(ts_trades)
        learnings.append(f"Time-stop fired {len(ts_trades)}x — avg result {_fmt(avg_ts)} per trade")

    # Confluence
    conf_trades = [t for t in week_trades if t.get("confluence", 1) >= 2]
    if conf_trades:
        conf_wr = sum(1 for t in conf_trades if t.get("pnl", 0) > 0) / len(conf_trades) * 100
        learnings.append(
            f"Confluence (≥2 traders same position): {len(conf_trades)} trades, "
            f"{conf_wr:.0f}% win rate vs {win_rate:.0f}% overall"
        )

    # Win rate trend vs all-time
    if week_trades:
        if win_rate > all_wr + 5:
            learnings.append(f"Win rate improving: this week {win_rate:.0f}% vs all-time {all_wr:.0f}%")
        elif win_rate < all_wr - 5:
            learnings.append(f"Win rate below average: this week {win_rate:.0f}% vs all-time {all_wr:.0f}%")
        else:
            learnings.append(f"Win rate in line with all-time average ({win_rate:.0f}% vs {all_wr:.0f}%)")

    # Best day of the week
    if len(last7) >= 3:
        best_day  = max(last7, key=lambda d: daily_pnl.get(d, 0))
        worst_day = min(last7, key=lambda d: daily_pnl.get(d, 0))
        bd = datetime.fromisoformat(best_day)
        wd = datetime.fromisoformat(worst_day)
        learnings.append(
            f"Best day: {bd.strftime('%A %d %b')} ({_fmt(daily_pnl[best_day])}) | "
            f"Worst day: {wd.strftime('%A %d %b')} ({_fmt(daily_pnl[worst_day])})"
        )

    if not learnings:
        learnings.append("Not enough data for pattern analysis yet — check back next week.")

    # ── Build message ─────────────────────────────────────────────────────────
    L: list[str] = []
    L.append(f"*📊 Copytrade — Weekly Learning Report*")
    L.append(f"_Week ending {now.strftime('%A %d %b %Y, %H:%M UTC')}_")
    L.append("")

    L.append("*Portfolio*")
    L.append(f"• Equity: `${current:,.2f}` | Start: `${starting:,.2f}`")
    L.append(f"• All-time PnL: `{_fmt(all_pnl)}` ({_pct(all_pct)})")
    L.append(f"• Week PnL: `{_fmt(week_pnl)}` ({_pct(week_pct)})")
    L.append(f"• Open positions: `{open_pos}`")
    L.append("")

    L.append("*This week's trading*")
    L.append(f"• Signals: {len(new_sigs)} new · {len(closed_sigs)} closed")
    L.append(f"• Closed trades: `{len(week_trades)}` — {len(wins)}W / {len(losses)}L ({win_rate:.0f}% win rate)")
    L.append(f"• Realized PnL this week: `{_fmt(realized_w)}`")
    L.append(f"• All-time win rate: `{all_wr:.0f}%` ({len(all_wins)}/{len(trades)} trades)")
    L.append("")

    if last7:
        L.append("*Daily PnL — last 7 days*")
        for day in last7:
            pnl = daily_pnl[day]
            emoji = "🟢" if pnl >= 0 else "🔴"
            d = datetime.fromisoformat(day)
            L.append(f"• {emoji} {d.strftime('%a %d %b')}: `{_fmt(pnl)}`")
        L.append("")

    if best3:
        L.append("*Best trades this week*")
        for t in best3:
            reason = t.get("exit_reason", "trader")
            L.append(
                f"• {t.get('side')} {t.get('coin')} x{t.get('leverage','?')} "
                f"→ `{_fmt(t.get('pnl', 0))}` _{reason}_"
            )
        L.append("")

    if worst3:
        L.append("*Worst trades this week*")
        for t in worst3:
            reason = t.get("exit_reason", "trader")
            L.append(
                f"• {t.get('side')} {t.get('coin')} x{t.get('leverage','?')} "
                f"→ `{_fmt(t.get('pnl', 0))}` _{reason}_"
            )
        L.append("")

    if coin_pnl:
        L.append("*Coin performance this week*")
        for coin, pnl in best_coins:
            if pnl > 0:
                L.append(f"• 🏆 {coin}: `{_fmt(pnl)}` ({coin_cnt[coin]} trades)")
        for coin, pnl in worst_coins:
            if pnl < 0:
                L.append(f"• ⚠️  {coin}: `{_fmt(pnl)}` ({coin_cnt[coin]} trades)")
        L.append("")

    if best_traders:
        L.append("*Top traders by contribution*")
        for addr, pnl in best_traders:
            L.append(f"• `{addr[:16]}…` → `{_fmt(pnl)}` ({trader_cnt[addr]} trades)")
        L.append("")

    if exit_counts:
        L.append("*Exit rule breakdown*")
        for reason, count in sorted(exit_counts.items(), key=lambda x: -x[1]):
            L.append(f"• {reason}: {count}×")
        L.append("")

    L.append("*🧠 Learnings & observations*")
    for obs in learnings:
        L.append(f"• {obs}")

    _post("\n".join(L))
    print("Weekly report sent successfully.")


if __name__ == "__main__":
    main()
