"""Live box-score fetcher for the halftime analyzer.

NBA: ESPN's public summary endpoint exposes a per-player boxscore even mid-game.
MLB: StatsAPI exposes a live boxscore (already wired in live_scores.py — we
reuse `LiveScoresFeed.mlb_live_game` for that).

The shapes returned here are intentionally simple — projection code consumes
plain dicts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

import httpx

log = logging.getLogger(__name__)

ESPN_NBA_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


@dataclass
class NBABoxPlayer:
    player: str
    team: str
    starter: bool
    minutes: float
    points: int
    rebounds: int
    assists: int
    threes_made: int
    steals: int
    blocks: int
    turnovers: int
    fouls: int
    fg_made: int
    fg_att: int
    ft_made: int
    ft_att: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NBABoxGame:
    game_id: str
    home_team: str
    away_team: str
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int
    quarter: int
    clock: str
    is_halftime: bool
    is_final: bool
    home_quarters: list[int]
    away_quarters: list[int]
    players: list[NBABoxPlayer]


def fetch_nba_boxscore(game_id: str, timeout: float = 8.0) -> NBABoxGame | None:
    """Fetch the live ESPN summary for a single NBA game and parse the box.

    Returns None on any network/parsing failure so callers can fall back gracefully.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(ESPN_NBA_SUMMARY, params={"event": game_id})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        log.warning("ESPN NBA summary fetch failed (%s): %s", game_id, e)
        return None

    try:
        return _parse_nba_summary(data, game_id)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("ESPN NBA summary parse failed (%s): %s", game_id, e)
        return None


def _parse_nba_summary(data: dict, game_id: str) -> NBABoxGame:
    header = data.get("header", {}) or data.get("gameInfo", {})
    competitions = (header.get("competitions") or [{}])
    comp = competitions[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    status = comp.get("status", {}).get("type", {})
    period = int(status.get("period", 1) or 1)
    clock = status.get("displayClock", "0:00") or "0:00"
    state = status.get("state", "")
    is_halftime = state == "in" and period == 2 and clock in ("0:00", "0.0")
    is_final = state == "post"

    home_q = [int(ls.get("displayValue", 0) or 0) for ls in home.get("linescores", [])]
    away_q = [int(ls.get("displayValue", 0) or 0) for ls in away.get("linescores", [])]

    home_abbr = home.get("team", {}).get("abbreviation", "")
    away_abbr = away.get("team", {}).get("abbreviation", "")
    home_name = home.get("team", {}).get("displayName", home_abbr)
    away_name = away.get("team", {}).get("displayName", away_abbr)

    players = _parse_box_players(data.get("boxscore", {}))

    return NBABoxGame(
        game_id=game_id,
        home_team=home_abbr,
        away_team=away_abbr,
        home_team_name=home_name,
        away_team_name=away_name,
        home_score=int(home.get("score", 0) or 0),
        away_score=int(away.get("score", 0) or 0),
        quarter=period,
        clock=clock,
        is_halftime=is_halftime,
        is_final=is_final,
        home_quarters=home_q,
        away_quarters=away_q,
        players=players,
    )


# Index of the box-score stat columns ESPN returns. Order matters.
# Example labels: ["MIN","FG","3PT","FT","OREB","DREB","REB","AST","STL","BLK","TO","PF","+/-","PTS"]
_STAT_KEYS = ("MIN", "FG", "3PT", "FT", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "+/-", "PTS")


def _parse_made_att(val: str) -> tuple[int, int]:
    if not val or "-" not in val:
        return 0, 0
    a, b = val.split("-", 1)
    try:
        return int(a), int(b)
    except ValueError:
        return 0, 0


def _parse_box_players(boxscore: dict) -> list[NBABoxPlayer]:
    out: list[NBABoxPlayer] = []
    for team_block in boxscore.get("players", []):
        team_abbr = team_block.get("team", {}).get("abbreviation", "")
        statistics = team_block.get("statistics", []) or [{}]
        labels = statistics[0].get("labels", _STAT_KEYS)
        idx = {label: i for i, label in enumerate(labels)}
        athletes = statistics[0].get("athletes", [])
        for ath in athletes:
            person = ath.get("athlete", {})
            stats = ath.get("stats", [])
            if not stats:
                continue
            def s(key: str) -> str:
                i = idx.get(key)
                return stats[i] if i is not None and i < len(stats) else ""
            min_str = s("MIN")
            try:
                minutes = float(min_str) if min_str else 0.0
            except ValueError:
                minutes = 0.0
            fgm, fga = _parse_made_att(s("FG"))
            tpm, _ = _parse_made_att(s("3PT"))
            ftm, fta = _parse_made_att(s("FT"))
            try:
                pts = int(s("PTS") or 0)
            except ValueError:
                pts = 0
            try:
                reb = int(s("REB") or 0)
            except ValueError:
                reb = 0
            try:
                ast = int(s("AST") or 0)
            except ValueError:
                ast = 0
            try:
                stl = int(s("STL") or 0)
            except ValueError:
                stl = 0
            try:
                blk = int(s("BLK") or 0)
            except ValueError:
                blk = 0
            try:
                to = int(s("TO") or 0)
            except ValueError:
                to = 0
            try:
                pf = int(s("PF") or 0)
            except ValueError:
                pf = 0
            out.append(NBABoxPlayer(
                player=person.get("displayName", ""),
                team=team_abbr,
                starter=ath.get("starter", False),
                minutes=minutes,
                points=pts,
                rebounds=reb,
                assists=ast,
                threes_made=tpm,
                steals=stl,
                blocks=blk,
                turnovers=to,
                fouls=pf,
                fg_made=fgm,
                fg_att=fga,
                ft_made=ftm,
                ft_att=fta,
            ))
    return out
