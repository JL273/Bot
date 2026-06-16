"""Filter + score Hyperliquid leaderboard traders, write active_wallets.json."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("data")
OUTPUT_PATH = Path("active_wallets.json")

FILTERS = {
    "min_account_value": 100_000,
    "min_30d_volume": 5_000_000,
    "min_30d_pnl": 50_000,
}

TOP_N = 5


def _latest_snapshot_path() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_path = DATA_DIR / f"leaderboard_{today}.json"
    if today_path.exists():
        return today_path
    candidates = sorted(DATA_DIR.glob("leaderboard_*.json"))
    if not candidates:
        raise FileNotFoundError("No leaderboard snapshot found in data/")
    return candidates[-1]


def _window_map(row: dict) -> dict:
    return {name: stats for name, stats in row.get("windowPerformances", [])}


def score_trader(row: dict) -> dict | None:
    windows = _window_map(row)
    day = windows.get("day")
    week = windows.get("week")
    month = windows.get("month")
    if not day or not week or not month:
        return None

    account_value = float(row.get("accountValue", 0))
    day_pnl = float(day["pnl"])
    day_roi = float(day["roi"])
    week_pnl = float(week["pnl"])
    week_roi = float(week["roi"])
    month_pnl = float(month["pnl"])
    month_roi = float(month["roi"])
    month_volume = float(month["vlm"])
    week_volume = float(week["vlm"])

    if account_value < FILTERS["min_account_value"]:
        return None
    if month_volume < FILTERS["min_30d_volume"]:
        return None
    if month_pnl < FILTERS["min_30d_pnl"]:
        return None
    if not (day_pnl > 0):
        return None
    if not (week_pnl > 0):
        return None
    if not (day_pnl < 0.8 * month_pnl):
        return None
    if abs(day_roi) > 5.0:
        return None

    month_edge_bps = (month_pnl / month_volume) * 10000 if month_volume else 0.0
    week_edge_bps = (week_pnl / week_volume) * 10000 if week_volume else 0.0
    score = month_edge_bps * 2.0 + week_edge_bps * 1.0 + math.log10(max(month_pnl, 1))

    return {
        "address": row.get("ethAddress") or row.get("address"),
        "account_value": account_value,
        "day_pnl": day_pnl,
        "day_roi": day_roi,
        "week_pnl": week_pnl,
        "week_roi": week_roi,
        "month_pnl": month_pnl,
        "month_roi": month_roi,
        "month_volume": month_volume,
        "month_edge_bps": month_edge_bps,
        "week_edge_bps": week_edge_bps,
        "score": score,
    }


def main() -> dict:
    snapshot_path = _latest_snapshot_path()
    payload = json.loads(snapshot_path.read_text())
    rows = payload.get("leaderboardRows", payload if isinstance(payload, list) else [])

    scored = []
    for row in rows:
        result = score_trader(row)
        if result is not None:
            scored.append(result)

    scored.sort(key=lambda t: t["score"], reverse=True)
    top_traders = scored[:TOP_N]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": FILTERS,
        "top_traders": top_traders,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    result = main()
    print(f"Shortlist updated: {len(result['top_traders'])} traders")
