"""JOB B — every 5 min: poll trader positions, diff, generate signals, paper trade."""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import fetch_positions
import notes
import paper_engine

LOG_PATH = Path("logs/job_positions.log")
ACTIVE_WALLETS_PATH = Path("active_wallets.json")
SIGNALS_PATH = Path("signals.json")
STATE_DIR = Path("state")

# Exit thresholds (as % of margin)
STOP_LOSS_PCT   = 20.0  # close if position is down >20% of margin
TAKE_PROFIT_PCT = 40.0  # close if position is up  >40% of margin
TIME_STOP_DAYS  = 5     # close if open >5 days and PnL is flat (within ±2%)

# Confluence: minimum number of followed traders holding the same coin+side
# before we open a paper position. Set to 1 to disable (open on any signal).
CONFLUENCE_MIN = 2


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _key(p: dict) -> str:
    return f"{p['coin']}:{p['side']}"


def _state_path(address: str) -> Path:
    return STATE_DIR / f"{address}.json"


def _check_exits(portfolio: dict, signals: list, now_iso: str) -> list[str]:
    """Check all open paper positions for SL/TP/time-stop and inject CLOSED signals."""
    open_positions = portfolio.get("open_positions", {})
    if not open_positions:
        return []

    try:
        marks = paper_engine.get_mark_prices()
    except Exception as exc:
        log(f"Exit check: failed to fetch mark prices: {exc}")
        return []

    exit_lines = []
    now_dt = datetime.now(timezone.utc)

    for key, pos in list(open_positions.items()):
        coin = pos["coin"]
        side = pos["side"]
        mark = marks.get(coin)
        if mark is None:
            continue

        entry = pos["entry_price"]
        size = pos["size"]
        margin = pos["margin"]

        # Unrealized PnL
        if side == "LONG":
            unrealized = (mark - entry) * size
        else:
            unrealized = (entry - mark) * size

        pnl_pct = (unrealized / margin * 100) if margin else 0.0

        # Determine exit reason
        reason = None
        if pnl_pct <= -STOP_LOSS_PCT:
            reason = f"SL hit ({pnl_pct:.1f}% of margin)"
        elif pnl_pct >= TAKE_PROFIT_PCT:
            reason = f"TP hit (+{pnl_pct:.1f}% of margin)"
        else:
            # Time-stop: position open >N days and flat
            opened_at = pos.get("opened_at")
            if opened_at:
                try:
                    age_days = (now_dt - datetime.fromisoformat(opened_at.replace("Z", "+00:00"))).days
                    if age_days >= TIME_STOP_DAYS and abs(pnl_pct) < 2.0:
                        reason = f"time-stop ({age_days}d open, flat)"
                except Exception:
                    pass

        if reason:
            signal = {
                "ts": now_iso,
                "trader": pos["trader"],
                "type": "CLOSED",
                "coin": coin,
                "side": side,
                "size": size,
                "entry_price": entry,
                "position_value_usd": pos.get("position_value_usd", 0),
                "leverage": pos.get("leverage", 1),
                "unrealized_pnl": unrealized,
                "liquidation_price": pos.get("liquidation_price", 0),
                "exit_reason": reason,
            }
            signals.append(signal)
            log(f"Exit triggered — {side} {coin}: {reason}")
            exit_lines.append(f"EXIT {side} {coin} [{reason}]")

    return exit_lines


def main() -> int:
    try:
        if not ACTIVE_WALLETS_PATH.exists():
            log("active_wallets.json missing — Job A hasn't run yet, skipping")
            return 0

        active = json.loads(ACTIVE_WALLETS_PATH.read_text())
        top_traders = active.get("top_traders", [])
        log(f"Polling {len(top_traders)} traders")

        signals = []
        if SIGNALS_PATH.exists():
            signals = json.loads(SIGNALS_PATH.read_text())

        now_iso = datetime.now(timezone.utc).isoformat()
        new_signal_lines = []
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        # Pass 1: fetch all current positions, build confluence map
        # confluence_map[coin:side] = number of traders currently holding it
        fetch_results: dict[str, tuple[dict, dict]] = {}  # addr -> (curr_data, prev_map)
        confluence_map: dict[str, int] = {}

        for trader in top_traders:
            addr = trader["address"]
            try:
                curr_data = fetch_positions.get_open_positions(addr)
            except Exception as exc:
                log(f"Failed to fetch positions for {addr}: {exc}")
                continue

            curr_map = {_key(p): p for p in curr_data["positions"]}

            prev_positions = []
            state_path = _state_path(addr)
            if state_path.exists():
                try:
                    prev_positions = json.loads(state_path.read_text()).get("positions", [])
                except Exception:
                    prev_positions = []
            prev_map = {_key(p): p for p in prev_positions}

            fetch_results[addr] = (curr_data, curr_map, prev_map)

            for k in curr_map:
                confluence_map[k] = confluence_map.get(k, 0) + 1

        log(f"Confluence map: {confluence_map}")

        # Pass 2: diff per trader, apply confluence filter to opens
        skipped_confluence = []
        for addr, (curr_data, curr_map, prev_map) in fetch_results.items():
            opened_keys = set(curr_map) - set(prev_map)
            closed_keys = set(prev_map) - set(curr_map)

            for k in opened_keys:
                p = curr_map[k]
                count = confluence_map.get(k, 0)
                if count >= CONFLUENCE_MIN:
                    signal = {"ts": now_iso, "trader": addr, "type": "NEW",
                              "confluence": count, **p}
                    signals.append(signal)
                    new_signal_lines.append(
                        f"NEW {p['side']} {p['coin']} ({addr}) [{count}/{len(top_traders)} traders]")
                else:
                    skipped_confluence.append(
                        f"SKIPPED {p['side']} {p['coin']} ({addr}) — only {count}/{len(top_traders)} traders")
                    log(f"Confluence miss: {p['side']} {p['coin']} — {count} trader(s), need {CONFLUENCE_MIN}")

            for k in closed_keys:
                p = prev_map[k]
                signal = {"ts": now_iso, "trader": addr, "type": "CLOSED", **p}
                signals.append(signal)
                new_signal_lines.append(f"CLOSED {p['side']} {p['coin']} ({addr})")

            _state_path(addr).write_text(json.dumps(curr_data, indent=2))

        if new_signal_lines:
            SIGNALS_PATH.write_text(json.dumps(signals, indent=2))

        portfolio = paper_engine.apply_new_signals()

        # ── Independent exits: stop-loss / take-profit / time-stop ──────────
        exit_lines = _check_exits(portfolio, signals, now_iso)
        if exit_lines:
            SIGNALS_PATH.write_text(json.dumps(signals, indent=2))
            portfolio = paper_engine.apply_new_signals()
            new_signal_lines.extend(exit_lines)

        if new_signal_lines or skipped_confluence:
            equity = portfolio["equity_history"][-1]["equity"] if portfolio["equity_history"] else portfolio["cash"]
            starting = portfolio["starting_cash"]
            pnl_pct = ((equity - starting) / starting * 100) if starting else 0.0
            lines = [f"{len(new_signal_lines)} signal(s) acted on, {len(skipped_confluence)} skipped (confluence):"]
            lines.extend(new_signal_lines)
            if skipped_confluence:
                lines.extend(skipped_confluence)
            lines.append(f"Portfolio equity: ${equity:,.2f} ({pnl_pct:+.2f}%)")
            notes.append_entry("Position poll (Job B)", lines)
            log(f"{len(new_signal_lines)} signals processed, {len(skipped_confluence)} skipped.")
        else:
            log("No position changes.")

        return 0
    except Exception:
        log("FATAL: " + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
