"""JOB A — once a day: fetch leaderboard, produce the fresh shortlist."""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import analyze_wallets
import fetch_leaderboard
import fetch_positions
import notes

LOG_PATH = Path("logs/job_daily.log")
ACTIVE_WALLETS_PATH = Path("active_wallets.json")


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _load_prior_addresses() -> set[str]:
    if not ACTIVE_WALLETS_PATH.exists():
        return set()
    try:
        prior = json.loads(ACTIVE_WALLETS_PATH.read_text())
        return {t["address"] for t in prior.get("top_traders", [])}
    except Exception:
        return set()


def main() -> int:
    try:
        prior_addresses = _load_prior_addresses()
        had_prior = ACTIVE_WALLETS_PATH.exists()

        log("Fetching leaderboard...")
        payload = fetch_leaderboard.fetch()
        snapshot_path = fetch_leaderboard.save_snapshot(payload)
        leaderboard_count = len(payload.get("leaderboardRows", payload if isinstance(payload, list) else []))
        log(f"Leaderboard snapshot saved to {snapshot_path} ({leaderboard_count} traders)")

        result = analyze_wallets.main()
        top_traders = result["top_traders"]
        new_addresses = {t["address"] for t in top_traders}
        log(f"Shortlist updated: {len(top_traders)} traders")

        position_lines = []
        for trader in top_traders:
            addr = trader["address"]
            try:
                pos_data = fetch_positions.get_open_positions(addr)
                positions = pos_data["positions"]
                if not positions:
                    position_lines.append(f"  {addr}... no open positions")
                else:
                    detail = ", ".join(f"{p['side']} {p['coin']} x{p['leverage']}" for p in positions)
                    position_lines.append(f"  {addr}... {len(positions)} positions: {detail}")
            except Exception as exc:
                log(f"Failed to fetch positions for {addr}: {exc}")
                position_lines.append(f"  {addr}... failed to fetch positions")

        added = new_addresses - prior_addresses
        removed = prior_addresses - new_addresses

        lines = [f"Leaderboard: {leaderboard_count} traders fetched, {len(top_traders)} shortlisted"]
        if not had_prior:
            lines.append("First shortlist (no prior run)")
        else:
            lines.append(f"Shortlist change: +{len(added)} new, -{len(removed)} dropped")

        for i, trader in enumerate(top_traders, start=1):
            lines.append(
                f"#{i} {trader['address']} acc=${trader['account_value']:,.0f} "
                f"month=${trader['month_pnl']:,.0f} edge={trader['month_edge_bps']:.0f}bps"
            )

        lines.append("Current positions across the shortlist:")
        lines.extend(position_lines)

        notes.append_entry("Daily refresh (Job A)", lines)
        log("NOTES.md updated.")
        return 0
    except Exception:
        log("FATAL: " + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
