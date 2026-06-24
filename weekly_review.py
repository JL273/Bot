"""JOB D — weekly self-learning review posted as a GitHub Issue every Sunday."""
from __future__ import annotations

import json
import math
import os
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PORTFOLIO_PATH = Path("portfolio.json")
TRADES_PATH = Path("paper_trades.json")
SIGNALS_PATH = Path("signals.json")
WALLETS_PATH = Path("active_wallets.json")

GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _week_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=7)


def _parse_ts(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_usd(v: float, sign: bool = True) -> str:
    prefix = ("+" if v >= 0 else "") if sign else ""
    return f"{prefix}${v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{'+'if v>=0 else ''}{v:.2f}%"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _analyse(portfolio: dict, trades: list, signals: list, wallets: dict) -> dict:
    cutoff = _week_cutoff()
    starting_cash = portfolio.get("starting_cash", 10_000.0)

    # Equity this week
    history = portfolio.get("equity_history", [])
    week_history = [h for h in history if _parse_ts(h.get("ts", "")) and _parse_ts(h["ts"]) >= cutoff]
    all_time_equity = history[-1]["equity"] if history else starting_cash
    week_start_equity = week_history[0]["equity"] if week_history else starting_cash
    week_pnl = all_time_equity - week_start_equity

    # Max drawdown this week
    if week_history:
        equities = [h["equity"] for h in week_history]
        peak = equities[0]
        max_dd = 0.0
        for e in equities:
            peak = max(peak, e)
            dd = (peak - e) / peak * 100 if peak else 0
            max_dd = max(max_dd, dd)
    else:
        max_dd = 0.0

    # Closed trades this week
    week_trades = []
    for t in trades:
        ts = _parse_ts(t.get("closed_at", ""))
        if ts and ts >= cutoff:
            week_trades.append(t)

    wins = [t for t in week_trades if t.get("pnl", 0) > 0]
    losses = [t for t in week_trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(week_trades) * 100 if week_trades else 0.0
    realized_pnl = sum(t.get("pnl", 0) for t in week_trades)

    best_trades = sorted(week_trades, key=lambda t: t.get("pnl_pct", 0), reverse=True)[:5]
    worst_trades = sorted(week_trades, key=lambda t: t.get("pnl_pct", 0))[:5]

    # Per-trader stats
    trader_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    for t in week_trades:
        addr = t.get("trader", "unknown")[:10] + "..."
        if t.get("pnl", 0) > 0:
            trader_stats[addr]["wins"] += 1
        else:
            trader_stats[addr]["losses"] += 1
        trader_stats[addr]["pnl"] += t.get("pnl", 0)

    # Per-coin stats
    coin_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    for t in week_trades:
        coin = t.get("coin", "?")
        if t.get("pnl", 0) > 0:
            coin_stats[coin]["wins"] += 1
        else:
            coin_stats[coin]["losses"] += 1
        coin_stats[coin]["pnl"] += t.get("pnl", 0)

    # Signals this week
    week_signals = []
    for s in signals:
        ts = _parse_ts(s.get("ts", ""))
        if ts and ts >= cutoff:
            week_signals.append(s)
    new_signals = [s for s in week_signals if s.get("type") == "NEW"]
    closed_signals = [s for s in week_signals if s.get("type") == "CLOSED"]

    return {
        "starting_cash": starting_cash,
        "all_time_equity": all_time_equity,
        "week_pnl": week_pnl,
        "week_pnl_pct": week_pnl / week_start_equity * 100 if week_start_equity else 0.0,
        "all_time_pnl": all_time_equity - starting_cash,
        "all_time_pnl_pct": (all_time_equity - starting_cash) / starting_cash * 100 if starting_cash else 0.0,
        "max_drawdown_pct": max_dd,
        "week_trades_count": len(week_trades),
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "realized_pnl": realized_pnl,
        "best_trades": best_trades,
        "worst_trades": worst_trades,
        "trader_stats": dict(trader_stats),
        "coin_stats": dict(coin_stats),
        "new_signals": len(new_signals),
        "closed_signals": len(closed_signals),
        "open_positions": len(portfolio.get("open_positions", {})),
        "traders_followed": len((wallets or {}).get("top_traders", [])),
    }


def _trade_row(t: dict) -> str:
    side = t.get("side", "?")
    coin = t.get("coin", "?")
    pnl = t.get("pnl", 0)
    pnl_pct = t.get("pnl_pct", 0)
    entry = t.get("entry_price", 0)
    exit_p = t.get("exit_price", 0)
    lev = t.get("leverage", 1)
    trader = (t.get("trader", "") or "")[:10] + "..."
    return (f"| {side} {coin} x{lev} | {_fmt_usd(entry, False)} → {_fmt_usd(exit_p, False)} "
            f"| **{_fmt_usd(pnl)}** ({_fmt_pct(pnl_pct)}) | {trader} |")


# ---------------------------------------------------------------------------
# Suggestions (rule-based)
# ---------------------------------------------------------------------------

def _suggestions(stats: dict, coin_stats: dict, trader_stats: dict) -> list[str]:
    suggestions = []

    wr = stats["win_rate"]
    if stats["week_trades_count"] >= 5:
        if wr < 40:
            suggestions.append(
                f"**Win rate is low ({wr:.0f}%)** — consider tightening trader filters "
                f"(raise `min_30d_pnl` or `min_account_value`) to be more selective."
            )
        elif wr > 65:
            suggestions.append(
                f"**Win rate is strong ({wr:.0f}%)** — bot is selecting well. "
                f"Consider raising `POSITION_PCT` from 5% to 7% to increase exposure."
            )

    dd = stats["max_drawdown_pct"]
    if dd > 5:
        suggestions.append(
            f"**Max drawdown this week was {dd:.1f}%** — consider reducing `POSITION_PCT` "
            f"from 5% to 3% or lowering `MAX_LEVERAGE` from 3 to 2."
        )

    # Flag consistently losing coins
    for coin, cs in coin_stats.items():
        total = cs["wins"] + cs["losses"]
        if total >= 3 and cs["wins"] / total < 0.35:
            suggestions.append(
                f"**{coin} is losing** ({cs['wins']}W / {cs['losses']}L this week, "
                f"PnL {_fmt_usd(cs['pnl'])}) — consider adding a coin blocklist to `job_positions.py`."
            )

    # Flag underperforming traders
    for addr, ts in trader_stats.items():
        total = ts["wins"] + ts["losses"]
        if total >= 3 and ts["wins"] / total < 0.35:
            suggestions.append(
                f"**Trader {addr} is underperforming** ({ts['wins']}W / {ts['losses']}L, "
                f"PnL {_fmt_usd(ts['pnl'])}) — they may be having a bad week or "
                f"their edge has degraded. The daily job will naturally drop them if they "
                f"fall off the leaderboard."
            )

    # Low activity
    if stats["week_trades_count"] == 0:
        suggestions.append(
            "**No closed trades this week** — either positions are still open, or no signals "
            "were generated. Check that `copytrade-positions` is running (cron-job.org dashboard) "
            "and that `active_wallets.json` has live traders."
        )

    if not suggestions:
        suggestions.append(
            "**No urgent changes suggested** — bot is performing within normal parameters. "
            "Continue collecting data; review again next week."
        )

    return suggestions


# ---------------------------------------------------------------------------
# Format issue body
# ---------------------------------------------------------------------------

def _format_issue(stats: dict, wallets: dict) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    week_label = now.strftime("%Y-%m-%d")
    title = f"Weekly review — {week_label}"

    coin_stats = stats["coin_stats"]
    trader_stats = stats["trader_stats"]
    suggestions = _suggestions(stats, coin_stats, trader_stats)

    lines = [
        f"# Copytrade weekly review — {week_label}",
        f"*Generated automatically every Sunday at 09:00 UTC.*",
        "",
        "---",
        "",
        "## Portfolio summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Portfolio equity | **{_fmt_usd(stats['all_time_equity'], False)}** |",
        f"| Weekly PnL | **{_fmt_usd(stats['week_pnl'])} ({_fmt_pct(stats['week_pnl_pct'])})** |",
        f"| All-time PnL | {_fmt_usd(stats['all_time_pnl'])} ({_fmt_pct(stats['all_time_pnl_pct'])}) |",
        f"| Max drawdown this week | {stats['max_drawdown_pct']:.2f}% |",
        f"| Trades closed this week | {stats['week_trades_count']} ({stats['wins']}W / {stats['losses']}L) |",
        f"| Win rate | {stats['win_rate']:.1f}% |",
        f"| Realized PnL this week | {_fmt_usd(stats['realized_pnl'])} |",
        f"| Signals (NEW / CLOSED) | {stats['new_signals']} / {stats['closed_signals']} |",
        f"| Open positions | {stats['open_positions']} |",
        f"| Traders followed | {stats['traders_followed']} |",
        "",
        "---",
        "",
        "## Best trades this week",
        "",
        "| Trade | Entry → Exit | PnL | Trader |",
        "|-------|-------------|-----|--------|",
    ]

    if stats["best_trades"]:
        for t in stats["best_trades"]:
            lines.append(_trade_row(t))
    else:
        lines.append("| — | No closed trades this week | — | — |")

    lines += [
        "",
        "---",
        "",
        "## Worst trades this week",
        "",
        "| Trade | Entry → Exit | PnL | Trader |",
        "|-------|-------------|-----|--------|",
    ]

    if stats["worst_trades"]:
        for t in stats["worst_trades"]:
            lines.append(_trade_row(t))
    else:
        lines.append("| — | No closed trades this week | — | — |")

    lines += [
        "",
        "---",
        "",
        "## Per-trader breakdown",
        "",
        "| Trader | W | L | Win rate | PnL |",
        "|--------|---|---|----------|-----|",
    ]

    if trader_stats:
        for addr, ts in sorted(trader_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            total = ts["wins"] + ts["losses"]
            wr = ts["wins"] / total * 100 if total else 0
            lines.append(f"| `{addr}` | {ts['wins']} | {ts['losses']} | {wr:.0f}% | {_fmt_usd(ts['pnl'])} |")
    else:
        lines.append("| — | — | — | — | No data |")

    lines += [
        "",
        "---",
        "",
        "## Per-coin breakdown",
        "",
        "| Coin | W | L | Win rate | PnL |",
        "|------|---|---|----------|-----|",
    ]

    if coin_stats:
        for coin, cs in sorted(coin_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
            total = cs["wins"] + cs["losses"]
            wr = cs["wins"] / total * 100 if total else 0
            lines.append(f"| {coin} | {cs['wins']} | {cs['losses']} | {wr:.0f}% | {_fmt_usd(cs['pnl'])} |")
    else:
        lines.append("| — | — | — | — | No data |")

    lines += [
        "",
        "---",
        "",
        "## Suggestions",
        "",
        "*Review these and decide whether to act. Close this issue once reviewed.*",
        "",
    ]

    for i, s in enumerate(suggestions, 1):
        lines.append(f"**{i}.** {s}")
        lines.append("")

    lines += [
        "---",
        "",
        "## Current trader shortlist",
        "",
    ]

    top_traders = (wallets or {}).get("top_traders", [])
    if top_traders:
        lines.append("| # | Address | Account | Month PnL | Edge (bps) |")
        lines.append("|---|---------|---------|-----------|-----------|")
        for i, t in enumerate(top_traders, 1):
            addr = t.get("address", "?")[:14] + "..."
            acc = t.get("account_value", 0)
            mpnl = t.get("month_pnl", 0)
            edge = t.get("month_edge_bps", 0)
            lines.append(f"| {i} | `{addr}` | ${acc:,.0f} | ${mpnl:,.0f} | {edge:.0f} |")
    else:
        lines.append("*No active wallets data available.*")

    lines += [
        "",
        "---",
        "*This issue was auto-generated by `weekly_review.py`. "
        "Make your changes to the bot, then close this issue.*",
    ]

    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# Post to GitHub
# ---------------------------------------------------------------------------

def _post_issue(title: str, body: str) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set")

    url = f"{GITHUB_API}/repos/{repo}/issues"
    resp = requests.post(
        url,
        json={"title": title, "body": body, "labels": ["weekly-review"]},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        portfolio = _load_json(PORTFOLIO_PATH, {})
        trades = _load_json(TRADES_PATH, [])
        signals = _load_json(SIGNALS_PATH, [])
        wallets = _load_json(WALLETS_PATH, {})

        stats = _analyse(portfolio, trades, signals, wallets)
        title, body = _format_issue(stats, wallets)

        dry_run = os.environ.get("DRY_RUN", "") == "1"
        if dry_run:
            print(f"DRY RUN — issue title: {title}")
            print(body)
            return 0

        url = _post_issue(title, body)
        print(f"Weekly review posted: {url}")
        return 0
    except Exception:
        print("FATAL: " + traceback.format_exc(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
