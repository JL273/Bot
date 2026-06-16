"""Fetch the Hyperliquid public leaderboard and snapshot it to disk."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DATA_DIR = Path("data")


def fetch() -> dict:
    """GET the leaderboard payload. Returns the parsed JSON."""
    resp = requests.get(
        LEADERBOARD_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def save_snapshot(payload: dict) -> Path:
    """Write data/leaderboard_<YYYY-MM-DD>.json (UTC today). Returns the path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DATA_DIR / f"leaderboard_{today}.json"
    path.write_text(json.dumps(payload))
    return path


if __name__ == "__main__":
    data = fetch()
    p = save_snapshot(data)
    print(f"Saved leaderboard snapshot to {p}")
