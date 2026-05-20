"""NBA.com data source via the open-source `nba_api` package.

A third provider alongside ESPN (`live_boxscore`) and balldontlie. Unlike
those two, this one needs **no API key** — it hits stats.nba.com and
cdn.nba.com directly. Lives behind the same `NBABoxGame` / `NBABoxPlayer`
shapes so the grader and projection code stay source-agnostic.

Coverage:
  - `fetch_live_box_by_date_teams(date, home, away)` — live or final box
    by (date, home, away). Used by `box_score.py` as a fallback.
  - `fetch_season_averages(season)` — pull every player's season line in
    one call (LeagueDashPlayerStats). Used by `season_sync.py` when no
    BALLDONTLIE_API_KEY is set.
  - `resolve_player_static(name, team_abbr)` — search the library's
    embedded player list. No network needed.

`nba_api` is an optional import — if the package isn't available the
module's public functions return None / [] so existing fallbacks still work.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.data.live_boxscore import NBABoxGame, NBABoxPlayer

log = logging.getLogger(__name__)

try:
    from nba_api.live.nba.endpoints import boxscore as _live_boxscore
    from nba_api.live.nba.endpoints import scoreboard as _live_scoreboard
    from nba_api.stats.endpoints import leaguedashplayerstats as _league_dash
    from nba_api.stats.endpoints import scoreboardv2 as _stats_scoreboard
    from nba_api.stats.endpoints import boxscoretraditionalv2 as _stats_box
    from nba_api.stats.static import players as _static_players
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _live_boxscore = _live_scoreboard = None
    _league_dash = _stats_scoreboard = _stats_box = None
    _static_players = None
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


_ISO_MIN = re.compile(r"PT(?:(\d+)M)?(?:([\d.]+)S)?")


def _parse_iso_minutes(s: str | None) -> float:
    """NBA live returns minutes as ISO-8601, e.g. 'PT12M30.00S'."""
    if not s:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if not s:
        return 0.0
    m = _ISO_MIN.fullmatch(s)
    if m:
        mins = float(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        return mins + secs / 60.0
    # bare "34" or "34:12"
    if ":" in s:
        a, b = s.split(":", 1)
        try:
            return float(a) + float(b) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _season_str(season_start_year: int) -> str:
    """2025 → '2025-26' (the format stats.nba.com expects)."""
    return f"{season_start_year}-{str(season_start_year + 1)[-2:]}"


def _find_live_game_id(date: str, home_abbr: str, away_abbr: str) -> str | None:
    """Look up a stats.nba.com game id for (date, home, away).

    `date` is YYYY-MM-DD. Tries the live scoreboard first (today's games),
    then falls back to the stats scoreboard (any date).
    """
    if not _AVAILABLE:
        return None
    home_u = home_abbr.upper()
    away_u = away_abbr.upper()

    # Live scoreboard: only carries games for the current day, but the
    # cheapest call (single HTTP hit, no per-game lookup).
    try:
        games = _live_scoreboard.ScoreBoard().games.get_dict() or []
    except Exception as e:  # noqa: BLE001 — third-party network errors
        log.debug("live scoreboard failed: %s", e)
        games = []
    for g in games:
        gh = (g.get("homeTeam") or {}).get("teamTricode", "").upper()
        ga = (g.get("awayTeam") or {}).get("teamTricode", "").upper()
        if {gh, ga} == {home_u, away_u}:
            return str(g.get("gameId") or "")

    # Stats scoreboard: works for any date.
    try:
        sb = _stats_scoreboard.ScoreboardV2(game_date=date).get_normalized_dict()
        line = sb.get("LineScore", [])
        # LineScore has one row per team — group by GAME_ID.
        by_game: dict[str, set[str]] = {}
        for row in line:
            gid = str(row.get("GAME_ID", "") or "")
            tri = (row.get("TEAM_ABBREVIATION") or "").upper()
            by_game.setdefault(gid, set()).add(tri)
        for gid, abbrs in by_game.items():
            if {home_u, away_u} <= abbrs:
                return gid
    except Exception as e:  # noqa: BLE001
        log.debug("stats scoreboard failed (%s): %s", date, e)

    return None


def _parse_live_box(game: dict, espn_game_id: str = "") -> NBABoxGame:
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    status_n = int(game.get("gameStatus") or 0)  # 1=upcoming 2=live 3=final
    period = int(game.get("period") or 0)
    clock = str(game.get("gameClock") or "")
    is_final = status_n == 3
    # nba_api drops the leading "PT" from clock too — empty at half is fine.
    is_halftime = status_n == 2 and period == 2 and clock in ("", "PT00M00.00S", "0:00")

    def _players(team: dict) -> list[NBABoxPlayer]:
        out: list[NBABoxPlayer] = []
        tri = (team.get("teamTricode") or "").upper()
        for p in team.get("players", []) or []:
            st = p.get("statistics") or {}
            name = (p.get("name") or
                    f"{p.get('firstName','')} {p.get('familyName','')}".strip())
            # NBA Live emits `starter` as "1"/"0" sometimes, bool other times.
            starter_raw = p.get("starter")
            starter = (str(starter_raw).strip() in {"1", "true", "True"})
            out.append(NBABoxPlayer(
                player=name,
                team=tri,
                starter=starter,
                minutes=_parse_iso_minutes(st.get("minutes")),
                points=int(st.get("points") or 0),
                rebounds=int(st.get("reboundsTotal") or st.get("rebounds") or 0),
                assists=int(st.get("assists") or 0),
                threes_made=int(st.get("threePointersMade") or 0),
                steals=int(st.get("steals") or 0),
                blocks=int(st.get("blocks") or 0),
                turnovers=int(st.get("turnovers") or 0),
                fouls=int(st.get("foulsPersonal") or 0),
                fg_made=int(st.get("fieldGoalsMade") or 0),
                fg_att=int(st.get("fieldGoalsAttempted") or 0),
                ft_made=int(st.get("freeThrowsMade") or 0),
                ft_att=int(st.get("freeThrowsAttempted") or 0),
            ))
        return out

    def _q_scores(team: dict) -> list[int]:
        return [int((p or {}).get("score") or 0) for p in team.get("periods", []) or []]

    return NBABoxGame(
        game_id=espn_game_id or str(game.get("gameId") or ""),
        home_team=(home.get("teamTricode") or "").upper(),
        away_team=(away.get("teamTricode") or "").upper(),
        home_team_name=home.get("teamName") or home.get("teamCity") or "",
        away_team_name=away.get("teamName") or away.get("teamCity") or "",
        home_score=int(home.get("score") or 0),
        away_score=int(away.get("score") or 0),
        quarter=period,
        clock=clock or ("0:00" if is_final else ""),
        is_halftime=is_halftime,
        is_final=is_final,
        home_quarters=_q_scores(home),
        away_quarters=_q_scores(away),
        players=_players(home) + _players(away),
    )


def fetch_live_box_by_date_teams(
    date: str,
    home_abbr: str,
    away_abbr: str,
    espn_game_id: str = "",
) -> NBABoxGame | None:
    """Fetch a live or final box from NBA.com by (date, home, away).

    Returns None on any failure or when nba_api isn't installed.
    """
    if not _AVAILABLE:
        return None
    nba_game_id = _find_live_game_id(date, home_abbr, away_abbr)
    if not nba_game_id:
        return None

    # Prefer the live endpoint (cdn.nba.com — no auth headers, low latency).
    try:
        bs = _live_boxscore.BoxScore(game_id=nba_game_id).game.get_dict()
        return _parse_live_box(bs, espn_game_id=espn_game_id)
    except Exception as e:  # noqa: BLE001
        log.debug("live boxscore failed (%s): %s", nba_game_id, e)

    # Final-only games sometimes only resolve via the stats endpoint.
    try:
        nd = _stats_box.BoxScoreTraditionalV2(game_id=nba_game_id).get_normalized_dict()
        return _parse_stats_box(nd, nba_game_id=nba_game_id, espn_game_id=espn_game_id)
    except Exception as e:  # noqa: BLE001
        log.warning("stats boxscore failed (%s): %s", nba_game_id, e)
        return None


def _parse_stats_box(nd: dict, nba_game_id: str, espn_game_id: str = "") -> NBABoxGame:
    """Parse the BoxScoreTraditionalV2 normalized response."""
    player_rows = nd.get("PlayerStats", []) or []
    team_rows = nd.get("TeamStats", []) or []

    teams_by_id: dict[int, dict] = {}
    for t in team_rows:
        teams_by_id[int(t.get("TEAM_ID") or 0)] = t

    # Pick home/away by team-stat order if available (TeamStats is [away, home]
    # in some responses, [home, away] in others — fall back to first/last).
    if len(team_rows) >= 2:
        away_t, home_t = team_rows[0], team_rows[-1]
    else:
        away_t, home_t = {}, team_rows[0] if team_rows else {}

    def _min(s: str | None) -> float:
        if not s:
            return 0.0
        s = str(s).strip()
        if ":" in s:
            a, b = s.split(":", 1)
            try:
                return float(a) + float(b) / 60.0
            except ValueError:
                return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    players: list[NBABoxPlayer] = []
    for r in player_rows:
        tri = (r.get("TEAM_ABBREVIATION") or "").upper()
        # Stats endpoint marks starters via START_POSITION ('G'/'F'/'C' vs '')
        starter = bool((r.get("START_POSITION") or "").strip())
        players.append(NBABoxPlayer(
            player=r.get("PLAYER_NAME") or "",
            team=tri,
            starter=starter,
            minutes=_min(r.get("MIN")),
            points=int(r.get("PTS") or 0),
            rebounds=int(r.get("REB") or 0),
            assists=int(r.get("AST") or 0),
            threes_made=int(r.get("FG3M") or 0),
            steals=int(r.get("STL") or 0),
            blocks=int(r.get("BLK") or 0),
            turnovers=int(r.get("TO") or 0),
            fouls=int(r.get("PF") or 0),
            fg_made=int(r.get("FGM") or 0),
            fg_att=int(r.get("FGA") or 0),
            ft_made=int(r.get("FTM") or 0),
            ft_att=int(r.get("FTA") or 0),
        ))

    return NBABoxGame(
        game_id=espn_game_id or nba_game_id,
        home_team=(home_t.get("TEAM_ABBREVIATION") or "").upper(),
        away_team=(away_t.get("TEAM_ABBREVIATION") or "").upper(),
        home_team_name=home_t.get("TEAM_NAME") or home_t.get("TEAM_CITY_NAME") or "",
        away_team_name=away_t.get("TEAM_NAME") or away_t.get("TEAM_CITY_NAME") or "",
        home_score=int(home_t.get("PTS") or 0),
        away_score=int(away_t.get("PTS") or 0),
        quarter=4,
        clock="0:00",
        is_halftime=False,
        is_final=True,
        home_quarters=[],
        away_quarters=[],
        players=players,
    )


def fetch_season_averages(season_start_year: int) -> list[dict[str, Any]]:
    """Pull every active player's season averages in one call.

    Returns a list of dicts with at least:
      player_id, player_name, team_abbr, games_played,
      min, pts, reb, ast, fg3m, stl, blk, fgm, fga, ftm, fta.

    Returns [] when nba_api isn't installed or the call fails.
    """
    if not _AVAILABLE:
        return []
    try:
        rows = _league_dash.LeagueDashPlayerStats(
            season=_season_str(season_start_year),
            season_type_all_star="Regular Season",
            per_mode_detailed="PerGame",
        ).get_normalized_dict().get("LeagueDashPlayerStats", [])
    except Exception as e:  # noqa: BLE001
        log.warning("LeagueDashPlayerStats failed (%s): %s", season_start_year, e)
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "player_id":  int(r.get("PLAYER_ID") or 0),
            "player_name": r.get("PLAYER_NAME") or "",
            "team_abbr":   (r.get("TEAM_ABBREVIATION") or "").upper(),
            "games_played": int(r.get("GP") or 0),
            "min":  float(r.get("MIN") or 0),
            "pts":  float(r.get("PTS") or 0),
            "reb":  float(r.get("REB") or 0),
            "ast":  float(r.get("AST") or 0),
            "fg3m": float(r.get("FG3M") or 0),
            "stl":  float(r.get("STL") or 0),
            "blk":  float(r.get("BLK") or 0),
            "fgm":  float(r.get("FGM") or 0),
            "fga":  float(r.get("FGA") or 0),
            "ftm":  float(r.get("FTM") or 0),
            "fta":  float(r.get("FTA") or 0),
        })
    return out


def resolve_player_static(name: str, team_abbr: str = "") -> dict[str, Any] | None:
    """Look up a player in nba_api's embedded static roster.

    No network call — the package ships a list of every NBA player. Good
    enough for fuzzy resolution when balldontlie has no key.
    """
    if not _AVAILABLE or _static_players is None:
        return None
    n = (name or "").strip()
    if not n:
        return None

    try:
        hits = _static_players.find_players_by_full_name(n) or []
    except Exception:  # noqa: BLE001
        hits = []
    if not hits:
        # Try last-name only.
        parts = n.split()
        if len(parts) >= 2:
            try:
                hits = _static_players.find_players_by_last_name(parts[-1]) or []
            except Exception:  # noqa: BLE001
                hits = []
    if not hits:
        return None

    # Static data has no team info; if a team was requested we can only
    # return the single-result case to avoid wrong-team guesses.
    if team_abbr and len(hits) > 1:
        return None

    p = hits[0]
    return {
        "id": int(p.get("id") or 0),
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "team_abbreviation": team_abbr.upper(),
        "display_name": p.get("full_name", "").strip() or n,
    }
