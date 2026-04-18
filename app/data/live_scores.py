"""Live game state feed for NBA and MLB.

Pulls real-time scores, player stats, and game clock from free APIs.
Falls back to a polling simulator for development.

NBA live: ESPN has a public scoreboard endpoint.
MLB live: MLB StatsAPI /game/{gamePk}/feed/live is free and official.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

ESPN_NBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
MLB_LIVE_FEED = "https://statsapi.mlb.com/api/v1"


@dataclass
class NBALivePlayer:
    player: str
    team: str
    minutes_played: float
    points: int
    rebounds: int
    assists: int
    threes_made: int
    steals: int
    blocks: int
    fouls: int

    @property
    def pra(self) -> int:
        return self.points + self.rebounds + self.assists

    @property
    def foul_trouble(self) -> bool:
        return self.fouls >= 4


@dataclass
class NBALiveGame:
    game_id: str
    home_team: str
    away_team: str
    quarter: int
    clock: str
    home_score: int
    away_score: int
    is_halftime: bool
    is_final: bool
    players: list[NBALivePlayer] = field(default_factory=list)

    @property
    def elapsed_minutes(self) -> float:
        if self.is_final:
            return 48.0
        base = (self.quarter - 1) * 12.0
        try:
            parts = self.clock.split(":")
            mins_left = int(parts[0]) + int(parts[1]) / 60.0 if len(parts) == 2 else 0.0
        except (ValueError, IndexError):
            mins_left = 0.0
        return min(base + (12.0 - mins_left), 48.0)

    @property
    def is_blowout(self) -> bool:
        return abs(self.home_score - self.away_score) > 25 and self.quarter >= 3


@dataclass
class MLBLivePlayer:
    player: str
    team: str
    is_pitcher: bool
    # Hitter fields
    at_bats: int = 0
    plate_appearances: int = 0
    hits: int = 0
    total_bases: int = 0
    runs: int = 0
    rbis: int = 0
    home_runs: int = 0
    walks: int = 0
    stolen_bases: int = 0
    # Pitcher fields
    innings_pitched: float = 0.0
    pitch_count: int = 0
    strikeouts: int = 0
    hits_allowed: int = 0
    earned_runs: int = 0
    walks_allowed: int = 0


@dataclass
class MLBLiveGame:
    game_id: str
    home_team: str
    away_team: str
    inning: int
    is_top: bool
    home_score: int
    away_score: int
    is_final: bool
    players: list[MLBLivePlayer] = field(default_factory=list)


class LiveScoresFeed:
    """Fetches live game state from ESPN (NBA) and MLB StatsAPI."""

    def __init__(self, timeout: float = 10.0):
        self._timeout = timeout

    # ---------- NBA ----------

    def nba_scoreboard(self) -> list[NBALiveGame]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.get(ESPN_NBA_SCOREBOARD)
                r.raise_for_status()
                data = r.json()
            return self._parse_espn_nba(data)
        except httpx.HTTPError as e:
            log.warning("ESPN NBA scoreboard fetch failed: %s", e)
            return []

    def _parse_espn_nba(self, data: dict) -> list[NBALiveGame]:
        games: list[NBALiveGame] = []
        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            status = event.get("status", {}).get("type", {})
            period = int(status.get("period", 1) or 1)
            clock = status.get("displayClock", "0:00")
            state = status.get("state", "")

            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            game = NBALiveGame(
                game_id=event.get("id", ""),
                home_team=home.get("team", {}).get("abbreviation", ""),
                away_team=away.get("team", {}).get("abbreviation", ""),
                quarter=period,
                clock=clock,
                home_score=int(home.get("score", 0)),
                away_score=int(away.get("score", 0)),
                is_halftime=state == "in" and period == 2 and clock == "0:00",
                is_final=state == "post",
            )
            games.append(game)
        return games

    def nba_player_live(self, game_id: str, player_name: str) -> dict | None:
        """Build a LiveGameState dict for the pipeline from ESPN box score.

        ESPN's free endpoint doesn't always include live player stats during
        the game. This returns None if unavailable; the pipeline treats
        None as 'use pregame projection instead'.
        """
        return None  # ESPN free tier doesn't expose live box; upgrade to Sportradar for this

    # ---------- MLB ----------

    def mlb_schedule_today(self) -> list[dict]:
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            with httpx.Client(timeout=self._timeout) as client:
                r = client.get(
                    f"{MLB_LIVE_FEED}/schedule",
                    params={"sportId": 1, "date": today},
                )
                r.raise_for_status()
                data = r.json()
            games = []
            for date_entry in data.get("dates", []):
                for g in date_entry.get("games", []):
                    games.append({
                        "game_id": str(g.get("gamePk", "")),
                        "home": g.get("teams", {}).get("home", {}).get("team", {}).get("abbreviation", ""),
                        "away": g.get("teams", {}).get("away", {}).get("team", {}).get("abbreviation", ""),
                        "status": g.get("status", {}).get("detailedState", ""),
                    })
            return games
        except httpx.HTTPError as e:
            log.warning("MLB schedule fetch failed: %s", e)
            return []

    def mlb_live_game(self, game_pk: str) -> MLBLiveGame | None:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                r = client.get(f"{MLB_LIVE_FEED}/game/{game_pk}/feed/live")
                r.raise_for_status()
                data = r.json()
            return self._parse_mlb_live(data, game_pk)
        except httpx.HTTPError as e:
            log.warning("MLB live feed failed for %s: %s", game_pk, e)
            return None

    def _parse_mlb_live(self, data: dict, game_pk: str) -> MLBLiveGame:
        game_data = data.get("gameData", {})
        live_data = data.get("liveData", {})
        linescore = live_data.get("linescore", {})

        teams = game_data.get("teams", {})
        home_abbr = teams.get("home", {}).get("abbreviation", "")
        away_abbr = teams.get("away", {}).get("abbreviation", "")

        status = game_data.get("status", {}).get("detailedState", "")
        inning = int(linescore.get("currentInning", 1) or 1)
        is_top = linescore.get("isTopInning", True)

        home_runs = int(linescore.get("teams", {}).get("home", {}).get("runs", 0) or 0)
        away_runs = int(linescore.get("teams", {}).get("away", {}).get("runs", 0) or 0)

        players: list[MLBLivePlayer] = []
        boxscore = live_data.get("boxscore", {})
        for side in ("home", "away"):
            team_box = boxscore.get("teams", {}).get(side, {})
            team_abbr = home_abbr if side == "home" else away_abbr
            for pid, pdata in team_box.get("players", {}).items():
                person = pdata.get("person", {})
                name = person.get("fullName", "")
                stats = pdata.get("stats", {})

                batting = stats.get("batting", {})
                pitching = stats.get("pitching", {})

                if pitching:
                    ip_str = pitching.get("inningsPitched", "0")
                    try:
                        ip = float(ip_str)
                    except ValueError:
                        ip = 0.0
                    players.append(MLBLivePlayer(
                        player=name, team=team_abbr, is_pitcher=True,
                        innings_pitched=ip,
                        pitch_count=int(pitching.get("pitchesThrown", 0) or 0),
                        strikeouts=int(pitching.get("strikeOuts", 0) or 0),
                        hits_allowed=int(pitching.get("hits", 0) or 0),
                        earned_runs=int(pitching.get("earnedRuns", 0) or 0),
                        walks_allowed=int(pitching.get("baseOnBalls", 0) or 0),
                    ))
                if batting:
                    players.append(MLBLivePlayer(
                        player=name, team=team_abbr, is_pitcher=False,
                        at_bats=int(batting.get("atBats", 0) or 0),
                        plate_appearances=int(batting.get("plateAppearances", 0) or 0),
                        hits=int(batting.get("hits", 0) or 0),
                        total_bases=int(batting.get("totalBases", 0) or 0),
                        runs=int(batting.get("runs", 0) or 0),
                        rbis=int(batting.get("rbi", 0) or 0),
                        home_runs=int(batting.get("homeRuns", 0) or 0),
                        walks=int(batting.get("baseOnBalls", 0) or 0),
                        stolen_bases=int(batting.get("stolenBases", 0) or 0),
                    ))

        return MLBLiveGame(
            game_id=game_pk,
            home_team=home_abbr,
            away_team=away_abbr,
            inning=inning,
            is_top=is_top,
            home_score=home_runs,
            away_score=away_runs,
            is_final="Final" in status,
            players=players,
        )
