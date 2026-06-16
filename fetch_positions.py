"""Wrappers around Hyperliquid's /info endpoint for open positions and fills."""
from __future__ import annotations

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(payload: dict) -> dict:
    resp = requests.post(
        INFO_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_open_positions(address: str) -> dict:
    """Return account value + open positions (szi == 0 entries are skipped)."""
    data = _post({"type": "clearinghouseState", "user": address})

    positions = []
    for entry in data.get("assetPositions", []):
        p = entry["position"]
        szi = float(p["szi"])
        if szi == 0:
            continue
        positions.append(
            {
                "coin": p["coin"],
                "side": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry_price": float(p["entryPx"]),
                "position_value_usd": float(p["positionValue"]),
                "leverage": p["leverage"]["value"],
                "unrealized_pnl": float(p["unrealizedPnl"]),
                "liquidation_price": float(p["liquidationPx"] or 0),
            }
        )

    return {
        "account_value": float(data["marginSummary"]["accountValue"]),
        "positions": positions,
        "timestamp_ms": data["time"],
    }


def get_recent_fills(address: str, limit: int = 50) -> list[dict]:
    """Optional helper, not used by the current jobs."""
    side_map = {"B": "BUY", "A": "SELL"}
    data = _post({"type": "userFills", "user": address})
    fills = data if isinstance(data, list) else data.get("fills", [])
    out = []
    for f in fills[:limit]:
        f = dict(f)
        f["side"] = side_map.get(f.get("side"), f.get("side"))
        out.append(f)
    return out
