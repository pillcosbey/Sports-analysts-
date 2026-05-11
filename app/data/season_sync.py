"""Pull current-season averages from balldontlie and persist to disk.

The halftime projection model uses each player's season half-mean as one
input (`W_SEASON` weight). Those averages are hardcoded in `nba_stats.py`
and drift stale fast — e.g. Mobley listed at 16.0 ppg, actually closer
to 19. This module refreshes them by:

  1. Searching balldontlie for every player in the hardcoded NBA_PLAYERS
     dict to get their balldontlie player_id.
  2. Hitting /v1/season_averages?season=YYYY for those ids.
  3. Writing the merged averages to data/season_averages.json.

The projection code reads from that JSON if it exists, otherwise falls
back to the hardcoded dict. Re-run this sync once a day (a Railway
Cron or the /api/admin/sync-season-averages endpoint).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.data.nba_stats import NBA_PLAYERS

log = logging.getLogger(__name__)

BASE = "https://api.balldontlie.io/v1"
STORE = Path(os.environ.get("SEASON_AVG_PATH", "data/season_averages.json"))

# Standard-deviation defaults when we have a mean but no SD signal.
# Tuned to roughly match historical variance for each stat.
_SD_DEFAULTS = {
    "points": 6.0,
    "rebounds": 2.5,
    "assists": 2.5,
    "threes_made": 1.4,
    "steals": 0.8,
    "blocks": 0.7,
}


def _headers() -> dict[str, str] | None:
    key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    return {"Authorization": key} if key else None


def _current_season() -> int:
    """NBA season runs ~Oct → Jun. Pre-October → previous season's number."""
    now = datetime.utcnow()
    return now.year if now.month >= 10 else now.year - 1


def _resolve_ids(names: Iterable[str], client: httpx.Client, headers: dict) -> dict[str, int]:
    """Map player names → balldontlie ids by searching the API."""
    out: dict[str, int] = {}
    for name in names:
        parts = name.split()
        last = parts[-1] if parts else name
        try:
            r = client.get(f"{BASE}/players", params={"search": last, "per_page": 25}, headers=headers)
            r.raise_for_status()
            data = r.json().get("data", [])
        except httpx.HTTPError as e:
            log.warning("player search failed for %s: %s", name, e)
            continue
        # Find best match by full name
        first = parts[0] if parts else ""
        match = next(
            (p for p in data
             if p.get("first_name", "").lower() == first.lower()
             and p.get("last_name", "").lower() == last.lower()),
            None,
        )
        if match is None and len(data) == 1:
            match = data[0]
        if match is not None:
            out[name] = int(match["id"])
        # Small delay to respect 5 req/min free-tier limits if many players
        time.sleep(0.25)
    return out


def _fetch_averages(player_ids: list[int], season: int, client: httpx.Client, headers: dict) -> list[dict]:
    """Hit /season_averages in batches of 25."""
    out: list[dict] = []
    for i in range(0, len(player_ids), 25):
        batch = player_ids[i:i + 25]
        params = [("season", season)] + [("player_ids[]", pid) for pid in batch]
        try:
            r = client.get(f"{BASE}/season_averages", params=params, headers=headers)
            r.raise_for_status()
            out.extend(r.json().get("data", []))
        except httpx.HTTPError as e:
            log.warning("season_averages batch failed: %s", e)
        time.sleep(1.0)
    return out


def sync_season_averages(season: int | None = None) -> dict[str, Any]:
    """Refresh data/season_averages.json. Returns a summary dict."""
    headers = _headers()
    if headers is None:
        return {"error": "BALLDONTLIE_API_KEY not set", "synced": 0}

    season = season or _current_season()
    names = list(NBA_PLAYERS.keys())

    with httpx.Client(timeout=15.0) as client:
        name_to_id = _resolve_ids(names, client, headers)
        if not name_to_id:
            return {"error": "No player ids could be resolved", "synced": 0}
        id_to_name = {v: k for k, v in name_to_id.items()}
        averages = _fetch_averages(list(name_to_id.values()), season, client, headers)

    merged: dict[str, dict[str, Any]] = {}
    for a in averages:
        pid = int(a.get("player_id") or 0)
        name = id_to_name.get(pid)
        if not name:
            continue
        merged[name] = {
            "team": NBA_PLAYERS.get(name, {}).get("team", ""),
            "points":      (float(a.get("pts", 0) or 0),  _SD_DEFAULTS["points"]),
            "rebounds":    (float(a.get("reb", 0) or 0),  _SD_DEFAULTS["rebounds"]),
            "assists":     (float(a.get("ast", 0) or 0),  _SD_DEFAULTS["assists"]),
            "threes_made": (float(a.get("fg3m", 0) or 0), _SD_DEFAULTS["threes_made"]),
            "steals":      (float(a.get("stl", 0) or 0),  _SD_DEFAULTS["steals"]),
            "blocks":      (float(a.get("blk", 0) or 0),  _SD_DEFAULTS["blocks"]),
            "min":         float(a.get("min", 0) or 0) if isinstance(a.get("min"), (int, float)) else NBA_PLAYERS.get(name, {}).get("min", 30.0),
        }

    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps({
        "season": season,
        "synced_at": time.time(),
        "players": merged,
    }, indent=2))

    return {
        "season": season,
        "resolved": len(name_to_id),
        "synced": len(merged),
        "store": str(STORE),
    }


def load_season_averages() -> dict[str, dict] | None:
    """Return the synced averages dict (player → stats), or None if no file."""
    if not STORE.exists():
        return None
    try:
        data = json.loads(STORE.read_text())
        return data.get("players") or None
    except (json.JSONDecodeError, KeyError):
        return None


def get_player_stats(name: str) -> dict | None:
    """Lookup a player's averages, preferring the synced file over the hardcoded dict."""
    synced = load_season_averages()
    if synced and name in synced:
        return synced[name]
    return NBA_PLAYERS.get(name)
