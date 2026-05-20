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

from app.data.nba_api_source import fetch_season_averages as nba_api_season_averages
from app.data.nba_api_source import is_available as nba_api_available
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


def _sync_via_balldontlie(season: int) -> dict[str, dict[str, Any]] | None:
    """Pull averages via balldontlie (legacy path). Returns None if no key."""
    headers = _headers()
    if headers is None:
        return None
    names = list(NBA_PLAYERS.keys())
    with httpx.Client(timeout=15.0) as client:
        name_to_id = _resolve_ids(names, client, headers)
        if not name_to_id:
            return {}
        id_to_name = {v: k for k, v in name_to_id.items()}
        averages = _fetch_averages(list(name_to_id.values()), season, client, headers)

    merged: dict[str, dict[str, Any]] = {}
    for a in averages:
        pid = int(a.get("player_id") or 0)
        name = id_to_name.get(pid)
        if not name:
            continue
        merged[name] = _make_entry(
            name=name,
            pts=a.get("pts"), reb=a.get("reb"), ast=a.get("ast"),
            fg3m=a.get("fg3m"), stl=a.get("stl"), blk=a.get("blk"),
            minutes=a.get("min"),
        )
    return merged


def _sync_via_nba_api(season: int) -> dict[str, dict[str, Any]]:
    """Pull averages via nba_api (no key required). Covers EVERY active
    player in the league — not just the ones in NBA_PLAYERS — which closes
    the SAS young-guys gap (Castle, Harper, Champagnie, Vassell, Shannon).
    """
    rows = nba_api_season_averages(season)
    merged: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = (r.get("player_name") or "").strip()
        if not name:
            continue
        merged[name] = _make_entry(
            name=name,
            team_hint=r.get("team_abbr") or "",
            pts=r.get("pts"), reb=r.get("reb"), ast=r.get("ast"),
            fg3m=r.get("fg3m"), stl=r.get("stl"), blk=r.get("blk"),
            minutes=r.get("min"),
        )
    return merged


def _make_entry(
    name: str,
    *,
    pts: Any, reb: Any, ast: Any, fg3m: Any, stl: Any, blk: Any, minutes: Any,
    team_hint: str = "",
) -> dict[str, Any]:
    fallback = NBA_PLAYERS.get(name, {})
    return {
        "team":        team_hint or fallback.get("team", ""),
        "points":      (float(pts or 0),  _SD_DEFAULTS["points"]),
        "rebounds":    (float(reb or 0),  _SD_DEFAULTS["rebounds"]),
        "assists":     (float(ast or 0),  _SD_DEFAULTS["assists"]),
        "threes_made": (float(fg3m or 0), _SD_DEFAULTS["threes_made"]),
        "steals":      (float(stl or 0),  _SD_DEFAULTS["steals"]),
        "blocks":      (float(blk or 0),  _SD_DEFAULTS["blocks"]),
        "min":         float(minutes) if isinstance(minutes, (int, float)) else fallback.get("min", 30.0),
    }


def sync_season_averages(season: int | None = None) -> dict[str, Any]:
    """Refresh data/season_averages.json. Returns a summary dict.

    Tries balldontlie first (if BALLDONTLIE_API_KEY is set), then falls
    back to nba_api (no key required, broader coverage).
    """
    season = season or _current_season()

    merged = _sync_via_balldontlie(season)
    source = "balldontlie"
    if not merged:
        merged = _sync_via_nba_api(season)
        source = "nba_api"

    if not merged:
        return {
            "error": "Both balldontlie and nba_api failed",
            "season": season,
            "synced": 0,
            "nba_api_available": nba_api_available(),
        }

    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps({
        "season": season,
        "synced_at": time.time(),
        "source": source,
        "players": merged,
    }, indent=2))

    return {
        "season": season,
        "source": source,
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
