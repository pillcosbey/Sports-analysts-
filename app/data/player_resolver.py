"""Resolve fuzzy / abbreviated player names via balldontlie.

The pick-grader matches a player's name against the box score by string
equality / last-name / first-initial+last. That works for clean names
but bet365 sometimes prints abbreviated forms ("K.Johnson", "Ant",
"PJ Tucker") that don't map cleanly to the official displayName.

This module asks balldontlie's /players?search= endpoint to disambiguate,
optionally narrowing by team. Results are cached in-process for the
session — a player only needs one lookup.

Returns None if no key is set or no match is found.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import httpx

from app.data.nba_api_source import resolve_player_static

log = logging.getLogger(__name__)

BASE = "https://api.balldontlie.io/v1"

# Common nicknames / abbreviations that don't search well via the API.
# Map them to the canonical first/last for the API search.
NICKNAMES: dict[str, str] = {
    "ant": "Anthony Edwards",
    "the beard": "James Harden",
    "dame": "Damian Lillard",
    "luka": "Luka Doncic",
    "kd": "Kevin Durant",
    "kawhi": "Kawhi Leonard",
    "giannis": "Giannis Antetokounmpo",
    "wemby": "Victor Wembanyama",
    "the joker": "Nikola Jokic",
    "jokic": "Nikola Jokic",
    "tatum": "Jayson Tatum",
    "trae": "Trae Young",
    "shai": "Shai Gilgeous-Alexander",
    "sga": "Shai Gilgeous-Alexander",
    "klay": "Klay Thompson",
    "steph": "Stephen Curry",
    "lebron": "LeBron James",
    "lbj": "LeBron James",
    "ad": "Anthony Davis",
    "the brow": "Anthony Davis",
    "cp3": "Chris Paul",
    "pg13": "Paul George",
    "jrue": "Jrue Holiday",
}


def _headers() -> dict[str, str] | None:
    key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    if not key:
        return None
    return {"Authorization": key}


def _expand_nickname(name: str) -> str:
    """If `name` is a known nickname, return its full canonical form."""
    return NICKNAMES.get(name.strip().lower(), name)


def _search_term(name: str) -> str:
    """Best search term for balldontlie's `search` parameter.

    The API matches on the player's last name. For abbreviated forms like
    "K.Johnson" we strip the initial and search the last name.
    """
    name = _expand_nickname(name)
    if "." in name:
        # "K.Johnson" → "Johnson"
        parts = name.split(".", 1)
        if len(parts[0].strip()) <= 2:
            return parts[1].strip()
    parts = name.split()
    if len(parts) >= 2:
        return parts[-1]  # last name
    return name


@lru_cache(maxsize=512)
def resolve_player(name: str, team_abbr: str = "") -> dict[str, Any] | None:
    """Search balldontlie for a player. If multiple results, narrow by team.

    Returns a dict like
      {"id": 237, "first_name": "Keldon", "last_name": "Johnson",
       "team_abbreviation": "SAS", "display_name": "Keldon Johnson"}
    or None on miss / no key / network failure.
    """
    term = _search_term(name)
    if not term:
        return None

    headers = _headers()
    if headers is None:
        # No balldontlie key — fall straight to the nba_api static roster.
        return resolve_player_static(_expand_nickname(name), team_abbr)

    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(
                f"{BASE}/players",
                params={"search": term, "per_page": 25},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        log.warning("balldontlie player search failed (%s): %s", term, e)
        return resolve_player_static(_expand_nickname(name), team_abbr)

    results = data.get("data", []) or []
    if not results:
        return resolve_player_static(_expand_nickname(name), team_abbr)

    team_u = team_abbr.upper().strip()

    def _hit(p: dict) -> dict[str, Any]:
        team = (p.get("team") or {}).get("abbreviation", "")
        return {
            "id": int(p["id"]),
            "first_name": p.get("first_name", ""),
            "last_name": p.get("last_name", ""),
            "team_abbreviation": team,
            "display_name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
        }

    # If a team is given, filter to it first
    if team_u:
        for p in results:
            if (p.get("team") or {}).get("abbreviation", "") == team_u:
                return _hit(p)

    # If name contains a first-initial pattern, narrow by first letter
    expanded = _expand_nickname(name)
    if "." in expanded:
        prefix = expanded.split(".", 1)[0].strip().upper()
        if prefix:
            for p in results:
                if p.get("first_name", "")[:1].upper() == prefix[:1]:
                    return _hit(p)

    # Single hit on the last-name search → use it
    if len(results) == 1:
        return _hit(results[0])

    # Ambiguous and we have no disambiguator — refuse to guess
    log.info("Ambiguous player lookup for '%s' (%d results)", name, len(results))
    return None
