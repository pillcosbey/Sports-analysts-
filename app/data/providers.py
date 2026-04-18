"""Data provider stubs + abstract interface.

Replace the Mock* implementations with real API clients as you add keys.
The rest of the system depends ONLY on the abstract interfaces, so
swapping providers is a one-file change.

Use ``get_odds_provider()`` to auto-select real or mock based on env.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass
class OddsQuote:
    sport: str
    player: str
    team: str
    stat: str
    line: float
    over_odds: int
    under_odds: int
    book: str
    game_id: str


class OddsProvider(Protocol):
    def player_prop_odds(self, sport: str) -> list[OddsQuote]: ...


class StatsProvider(Protocol):
    def player_context(self, sport: str, player: str, stat: str) -> dict: ...
    def live_game_state(self, sport: str, game_id: str, player: str) -> dict | None: ...
    def final_box(self, sport: str, game_id: str) -> dict: ...


# ----------------------- Mock implementations ------------------------------

class MockOdds:
    def player_prop_odds(self, sport: str) -> list[OddsQuote]:
        if sport == "nba":
            return [
                OddsQuote("nba", "Luka Doncic",    "DAL", "points",  32.5, -115, -105, "mock", "g1"),
                OddsQuote("nba", "Jayson Tatum",   "BOS", "points",  27.5, -110, -110, "mock", "g2"),
                OddsQuote("nba", "Nikola Jokic",   "DEN", "assists",  9.5, -120, +100, "mock", "g3"),
                OddsQuote("nba", "Shai Gilgeous-Alexander", "OKC", "pra", 44.5, -110, -110, "mock", "g4"),
            ]
        if sport == "mlb":
            return [
                OddsQuote("mlb", "Aaron Judge",   "NYY", "total_bases", 1.5, +110, -140, "mock", "m1"),
                OddsQuote("mlb", "Shohei Ohtani", "LAD", "hits",        0.5, -170, +140, "mock", "m2"),
                OddsQuote("mlb", "Gerrit Cole",   "NYY", "strikeouts",  7.5, -115, -105, "mock", "m3"),
                OddsQuote("mlb", "Corbin Burnes", "BAL", "outs_recorded",17.5, -120, +100, "mock", "m4"),
            ]
        return []


class MockStats:
    _NBA = {
        ("Luka Doncic", "points"): {
            "season_avg": 33.1, "season_sd": 8.2,
            "last_n_avg": 34.5, "last_n_sd": 9.0,
            "opp_def_factor": 1.03, "pace_factor": 1.02,
            "minutes_projection": 37.0, "minutes_season_avg": 36.4,
        },
        ("Jayson Tatum", "points"): {
            "season_avg": 26.9, "season_sd": 7.0,
            "last_n_avg": 25.2, "last_n_sd": 6.5,
            "opp_def_factor": 0.97, "pace_factor": 1.00,
            "minutes_projection": 36.5, "minutes_season_avg": 36.0,
        },
        ("Nikola Jokic", "assists"): {
            "season_avg": 9.1, "season_sd": 3.1,
            "last_n_avg": 10.2, "last_n_sd": 3.4,
            "opp_def_factor": 1.05, "pace_factor": 1.01,
            "minutes_projection": 35.0, "minutes_season_avg": 34.6,
        },
        ("Shai Gilgeous-Alexander", "pra"): {
            "season_avg": 42.3, "season_sd": 9.0,
            "last_n_avg": 45.0, "last_n_sd": 8.5,
            "opp_def_factor": 1.02, "pace_factor": 1.03,
            "minutes_projection": 35.5, "minutes_season_avg": 34.8,
        },
    }

    _MLB_HITTERS = {
        ("Aaron Judge", "total_bases"): {
            "season_rate_per_pa": 0.58, "season_sd": 1.1,
            "last_n_rate_per_pa": 0.65, "last_n_sd": 1.2,
            "projected_pas": 4.3, "opp_sp_factor": 1.04, "park_factor": 1.02,
        },
        ("Shohei Ohtani", "hits"): {
            "season_rate_per_pa": 0.24, "season_sd": 0.85,
            "last_n_rate_per_pa": 0.27, "last_n_sd": 0.9,
            "projected_pas": 4.4, "opp_sp_factor": 1.00, "park_factor": 1.01,
        },
    }

    _MLB_PITCHERS = {
        ("Gerrit Cole", "strikeouts"): {
            "season_rate_per_ip": 1.25, "season_sd": 2.1,
            "last_n_rate_per_ip": 1.35, "last_n_sd": 2.2,
            "projected_ip": 6.1, "opp_lineup_factor": 1.05,
            "park_factor": 0.99, "umpire_factor": 1.03,
        },
        ("Corbin Burnes", "outs_recorded"): {
            "season_rate_per_ip": 3.0, "season_sd": 3.0,
            "last_n_rate_per_ip": 3.0, "last_n_sd": 3.0,
            "projected_ip": 6.0, "opp_lineup_factor": 0.98, "park_factor": 1.00,
        },
    }

    def player_context(self, sport: str, player: str, stat: str) -> dict:
        if sport == "nba":
            return self._NBA[(player, stat)]
        if sport == "mlb":
            key = (player, stat)
            if key in self._MLB_HITTERS:
                return {"kind": "hitter", **self._MLB_HITTERS[key]}
            if key in self._MLB_PITCHERS:
                return {"kind": "pitcher", **self._MLB_PITCHERS[key]}
        raise KeyError(f"No mock context for {sport} {player} {stat}")

    def live_game_state(self, sport: str, game_id: str, player: str) -> dict | None:
        # Halftime snapshot example
        if sport == "nba" and player == "Luka Doncic":
            return {
                "minutes_played": 22.0,
                "current_stat": 18,          # points at half
                "on_pace_multiplier": 1.10,
                "blowout_adjust": 1.00,
                "foul_trouble": False,
            }
        if sport == "mlb" and player == "Gerrit Cole":
            return {
                "innings_pitched": 4.0, "pitch_count": 62,
                "current_stat": 5,           # Ks through 4
                "pitch_count_ceiling": 100,
            }
        return None

    def final_box(self, sport: str, game_id: str) -> dict:
        # Fake a final for demo/grading tests
        return {
            "Luka Doncic": {"points": 34, "assists": 9, "rebounds": 7, "pra": 50},
            "Gerrit Cole": {"strikeouts": 8, "outs_recorded": 18},
        }


# ----------------------- Provider factories --------------------------------

def get_odds_provider() -> OddsProvider:
    """Return a real OddsAPIClient if ODDS_API_KEY is set, else MockOdds."""
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        log.info("ODDS_API_KEY not set — using MockOdds")
        return MockOdds()
    from app.data.odds_api import OddsAPIClient
    regions = os.environ.get("ODDS_API_REGIONS", "us")
    books = [
        b.strip()
        for b in os.environ.get("ODDS_API_BOOKS", "draftkings,fanduel").split(",")
        if b.strip()
    ]
    ttl = int(os.environ.get("ODDS_CACHE_TTL", "120"))
    log.info("Using OddsAPIClient (regions=%s, books=%s, cache=%ds)", regions, books, ttl)
    return OddsAPIClient(api_key=key, regions=regions, bookmakers=books, cache_ttl_seconds=ttl)


def get_stats_provider() -> StatsProvider:
    """Return MockStats for now. Swap when real stats APIs are added."""
    return MockStats()
