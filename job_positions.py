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

        for trader in top_traders:
            addr = trader["address"]
            try:
                curr_data = fetch_positions.get_open_positions(addr)
            except Exception as exc:
                log(f"Failed to fetch positions for {addr}: {exc}")
                continue

            curr_positions = curr_data["positions"]
            curr_map = {_key(p): p for p in curr_positions}

            prev_positions = []
            state_path = _state_path(addr)
            if state_path.exists():
                try:
                    prev_positions = json.loads(state_path.read_text()).get("positions", [])
                except Exception:
                    prev_positions = []
            prev_map = {_key(p): p for p in prev_positions}

            opened_keys = set(curr_map) - set(prev_map)
            closed_keys = set(prev_map) - set(curr_map)

            for k in opened_keys:
                p = curr_map[k]
                signal = {"ts": now_iso, "trader": addr, "type": "NEW", **p}
                signals.append(signal)
                new_signal_lines.append(f"NEW {p['side']} {p['coin']} ({addr})")

            for k in closed_keys:
                p = prev_map[k]
                signal = {"ts": now_iso, "trader": addr, "type": "CLOSED", **p}
                signals.append(signal)
                new_signal_lines.append(f"CLOSED {p['side']} {p['coin']} ({addr})")

            state_path.write_text(json.dumps(curr_data, indent=2))

        if new_signal_lines:
            SIGNALS_PATH.write_text(json.dumps(signals, indent=2))

        portfolio = paper_engine.apply_new_signals()

        if new_signal_lines:
            equity = portfolio["equity_history"][-1]["equity"] if portfolio["equity_history"] else portfolio["cash"]
            starting = portfolio["starting_cash"]
            pnl_pct = ((equity - starting) / starting * 100) if starting else 0.0
            lines = [f"{len(new_signal_lines)} signal(s) detected:"]
            lines.extend(new_signal_lines)
            lines.append(f"Portfolio equity: ${equity:,.2f} ({pnl_pct:+.2f}%)")
            notes.append_entry("Position poll (Job B)", lines)
            log(f"{len(new_signal_lines)} signals processed.")
        else:
            log("No position changes.")

        return 0
    except Exception:
        log("FATAL: " + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
