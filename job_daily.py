"""JOB A — once a day: fetch leaderboard, produce the fresh shortlist."""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import time

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


def _is_live_on_clearinghouse(address: str) -> bool:
    """Return True if the trader has a non-zero perp account OR recent standard perp fills.

    Traders whose PnL comes from HyperEVM / vaults show account_value == 0 in
    clearinghouseState — our polling can never see their positions. Skip them.
    """
    try:
        data = fetch_positions.get_open_positions(address)
        if data["account_value"] > 0:
            return True
        # Fall back: check for any fill in the last 7 days on a standard perp coin
        import requests as _req
        r = _req.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "userFills", "user": address},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        fills = r.json() if isinstance(r.json(), list) else []
        cutoff_ms = (time.time() - 7 * 86400) * 1000
        for f in fills:
            # Standard perp coins have no prefix; spot = '@', HyperEVM = 'xyz:'
            coin = f.get("coin", "")
            if not coin.startswith("@") and not coin.startswith("xyz:") and f.get("time", 0) >= cutoff_ms:
                return True
        return False
    except Exception as exc:
        log(f"Liveness check failed for {address}: {exc} — excluding")
        return False


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

        # Score a wider candidate pool so we can drop HyperEVM/vault wallets
        result = analyze_wallets.main(top_n=20)
        candidates = result["top_traders"]
        log(f"Scored {len(candidates)} candidates, running liveness checks…")

        live_traders = []
        for t in candidates:
            if len(live_traders) >= 5:
                break
            addr = t["address"]
            if _is_live_on_clearinghouse(addr):
                live_traders.append(t)
                log(f"  ✓ {addr} — active on clearinghouse")
            else:
                log(f"  ✗ {addr} — no clearinghouse activity (HyperEVM/vault), skipping")

        # Overwrite active_wallets.json with the filtered live shortlist
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        live_result = {
            "generated_at": _dt.now(_tz.utc).isoformat(),
            "filters": result["filters"],
            "top_traders": live_traders,
        }
        analyze_wallets.OUTPUT_PATH.write_text(_json.dumps(live_result, indent=2))

        top_traders = live_traders
        new_addresses = {t["address"] for t in top_traders}
        log(f"Shortlist updated: {len(top_traders)} live traders")

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
