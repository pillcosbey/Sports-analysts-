"""balldontlie.io NBA data source.

Free public API used as a backup to ESPN. Auth via the BALLDONTLIE_API_KEY
env var. Their game IDs differ from ESPN's, so we look up games by
(date, home_abbr, away_abbr) then pull the per-player stats for that game.

Returns the same NBABoxGame shape `live_boxscore` produces so the
auto-grader and any consumer code is source-agnostic.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.data.live_boxscore import NBABoxGame, NBABoxPlayer

log = logging.getLogger(__name__)

BASE = "https://api.balldontlie.io/v1"


def _headers() -> dict[str, str] | None:
    key = os.environ.get("BALLDONTLIE_API_KEY", "").strip()
    if not key:
        return None
    return {"Authorization": key}


def _team_abbr(team: dict[str, Any]) -> str:
    return (team.get("abbreviation") or team.get("triCode") or "").upper()


def _find_game_id(
    date: str,
    home_abbr: str,
    away_abbr: str,
    timeout: float = 8.0,
) -> int | None:
    """Look up the balldontlie game_id for a given (date, home, away).

    `date` should be YYYY-MM-DD. Returns None if not found / network fails.
    """
    headers = _headers()
    if headers is None:
        return None
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(
                f"{BASE}/games",
                params={"dates[]": date, "per_page": 100},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        log.warning("balldontlie games fetch failed (%s): %s", date, e)
        return None

    home_u = home_abbr.upper()
    away_u = away_abbr.upper()
    for g in data.get("data", []):
        gh = _team_abbr(g.get("home_team", {}))
        ga = _team_abbr(g.get("visitor_team", {}))
        if (gh == home_u and ga == away_u) or (gh == away_u and ga == home_u):
            return int(g["id"])
    return None


def fetch_final_box_by_date_teams(
    date: str,
    home_abbr: str,
    away_abbr: str,
    espn_game_id: str = "",
    timeout: float = 10.0,
) -> NBABoxGame | None:
    """Fetch a final box from balldontlie by (date, home, away).

    `espn_game_id` is optional metadata stamped on the returned NBABoxGame
    so callers that already pass an ESPN id around can keep doing so.
    """
    bdl_id = _find_game_id(date, home_abbr, away_abbr, timeout=timeout)
    if bdl_id is None:
        return None

    headers = _headers()
    if headers is None:
        return None

    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(
                f"{BASE}/stats",
                params={"game_ids[]": bdl_id, "per_page": 100},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            # Also pull the game itself for the score / status fields
            rg = client.get(f"{BASE}/games/{bdl_id}", headers=headers)
            rg.raise_for_status()
            game = rg.json().get("data", rg.json())
    except httpx.HTTPError as e:
        log.warning("balldontlie stats fetch failed (game %s): %s", bdl_id, e)
        return None

    return _parse_box(data.get("data", []), game, espn_game_id=espn_game_id)


def _parse_min(m: Any) -> float:
    """balldontlie returns minutes as a string like '34' or '34:12'."""
    if m is None:
        return 0.0
    if isinstance(m, (int, float)):
        return float(m)
    s = str(m).strip()
    if not s:
        return 0.0
    if ":" in s:
        mm, ss = s.split(":", 1)
        try:
            return float(mm) + float(ss) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_box(stats: list[dict], game: dict, espn_game_id: str = "") -> NBABoxGame:
    home = game.get("home_team", {})
    away = game.get("visitor_team", {})
    home_abbr = _team_abbr(home)
    away_abbr = _team_abbr(away)

    players: list[NBABoxPlayer] = []
    for s in stats:
        p = s.get("player", {})
        t = s.get("team", {})
        first = p.get("first_name", "")
        last = p.get("last_name", "")
        full = f"{first} {last}".strip()
        players.append(NBABoxPlayer(
            player=full,
            team=_team_abbr(t),
            starter=bool(s.get("starter", False)),
            minutes=_parse_min(s.get("min")),
            points=int(s.get("pts") or 0),
            rebounds=int(s.get("reb") or 0),
            assists=int(s.get("ast") or 0),
            threes_made=int(s.get("fg3m") or 0),
            steals=int(s.get("stl") or 0),
            blocks=int(s.get("blk") or 0),
            turnovers=int(s.get("turnover") or 0),
            fouls=int(s.get("pf") or 0),
            fg_made=int(s.get("fgm") or 0),
            fg_att=int(s.get("fga") or 0),
            ft_made=int(s.get("ftm") or 0),
            ft_att=int(s.get("fta") or 0),
        ))

    status = (game.get("status") or "").lower()
    is_final = "final" in status or game.get("period", 0) >= 4 and not status.startswith("q")
    period = int(game.get("period") or 4)

    return NBABoxGame(
        game_id=espn_game_id or str(game.get("id", "")),
        home_team=home_abbr,
        away_team=away_abbr,
        home_team_name=home.get("full_name", home_abbr),
        away_team_name=away.get("full_name", away_abbr),
        home_score=int(game.get("home_team_score") or 0),
        away_score=int(game.get("visitor_team_score") or 0),
        quarter=period,
        clock="0:00" if is_final else (game.get("time") or ""),
        is_halftime=False,
        is_final=is_final,
        home_quarters=[],
        away_quarters=[],
        players=players,
    )
