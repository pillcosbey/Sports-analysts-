"""Tests for The Odds API client — parsing logic only (no HTTP calls)."""

import pytest

from app.data.odds_api import _parse_event, NBA_MARKET_TO_STAT, MLB_MARKET_TO_STAT
from app.data.providers import OddsQuote, get_odds_provider, MockOdds


# ---------- realistic sample payloads from The Odds API docs ----------

SAMPLE_NBA_EVENT = {
    "id": "abc123",
    "sport_key": "basketball_nba",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -115, "point": 25.5},
                        {"name": "Under", "description": "LeBron James", "price": -105, "point": 25.5},
                        {"name": "Over", "description": "Jayson Tatum", "price": -110, "point": 27.5},
                        {"name": "Under", "description": "Jayson Tatum", "price": -110, "point": 27.5},
                    ],
                },
                {
                    "key": "player_assists",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -120, "point": 7.5},
                        {"name": "Under", "description": "LeBron James", "price": 100, "point": 7.5},
                    ],
                },
            ],
        },
        {
            "key": "fanduel",
            "markets": [
                {
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "LeBron James", "price": -110, "point": 25.5},
                        {"name": "Under", "description": "LeBron James", "price": -110, "point": 25.5},
                    ],
                },
            ],
        },
    ],
}

SAMPLE_MLB_EVENT = {
    "id": "mlb456",
    "sport_key": "baseball_mlb",
    "home_team": "New York Yankees",
    "away_team": "Houston Astros",
    "bookmakers": [
        {
            "key": "draftkings",
            "markets": [
                {
                    "key": "pitcher_strikeouts",
                    "outcomes": [
                        {"name": "Over", "description": "Gerrit Cole", "price": -115, "point": 7.5},
                        {"name": "Under", "description": "Gerrit Cole", "price": -105, "point": 7.5},
                    ],
                },
                {
                    "key": "batter_hits",
                    "outcomes": [
                        {"name": "Over", "description": "Aaron Judge", "price": +140, "point": 1.5},
                        {"name": "Under", "description": "Aaron Judge", "price": -170, "point": 1.5},
                    ],
                },
            ],
        },
    ],
}


class TestParseNBAEvent:
    def test_returns_correct_count(self):
        quotes = _parse_event(SAMPLE_NBA_EVENT, "nba", NBA_MARKET_TO_STAT)
        # LeBron points, Tatum points, LeBron assists = 3
        assert len(quotes) == 3

    def test_best_over_price_selected(self):
        quotes = _parse_event(SAMPLE_NBA_EVENT, "nba", NBA_MARKET_TO_STAT)
        lebron_pts = [q for q in quotes if q.player == "LeBron James" and q.stat == "points"][0]
        # DraftKings has -115 over, FanDuel has -110 over => best is -110 (higher payout)
        assert lebron_pts.over_odds == -110

    def test_matchup_formatted(self):
        quotes = _parse_event(SAMPLE_NBA_EVENT, "nba", NBA_MARKET_TO_STAT)
        assert quotes[0].team == "Boston Celtics @ Los Angeles Lakers"

    def test_game_id_preserved(self):
        quotes = _parse_event(SAMPLE_NBA_EVENT, "nba", NBA_MARKET_TO_STAT)
        assert all(q.game_id == "abc123" for q in quotes)

    def test_stat_names_mapped(self):
        quotes = _parse_event(SAMPLE_NBA_EVENT, "nba", NBA_MARKET_TO_STAT)
        stats = {q.stat for q in quotes}
        assert stats == {"points", "assists"}


class TestParseMLBEvent:
    def test_returns_correct_count(self):
        quotes = _parse_event(SAMPLE_MLB_EVENT, "mlb", MLB_MARKET_TO_STAT)
        assert len(quotes) == 2

    def test_pitcher_market_mapped(self):
        quotes = _parse_event(SAMPLE_MLB_EVENT, "mlb", MLB_MARKET_TO_STAT)
        cole = [q for q in quotes if q.player == "Gerrit Cole"][0]
        assert cole.stat == "strikeouts"
        assert cole.line == 7.5

    def test_hitter_market_mapped(self):
        quotes = _parse_event(SAMPLE_MLB_EVENT, "mlb", MLB_MARKET_TO_STAT)
        judge = [q for q in quotes if q.player == "Aaron Judge"][0]
        assert judge.stat == "hits"
        assert judge.over_odds == 140
        assert judge.under_odds == -170


class TestIncompleteData:
    def test_missing_under_skips_outcome(self):
        event = {
            "id": "x",
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [{
                "key": "dk",
                "markets": [{
                    "key": "player_points",
                    "outcomes": [
                        {"name": "Over", "description": "Player X", "price": -110, "point": 20.5},
                        # no Under
                    ],
                }],
            }],
        }
        quotes = _parse_event(event, "nba", NBA_MARKET_TO_STAT)
        assert len(quotes) == 0

    def test_unknown_market_ignored(self):
        event = {
            "id": "x",
            "bookmakers": [{
                "key": "dk",
                "markets": [{
                    "key": "player_fantasy_score",
                    "outcomes": [
                        {"name": "Over", "description": "P", "price": -110, "point": 30},
                        {"name": "Under", "description": "P", "price": -110, "point": 30},
                    ],
                }],
            }],
        }
        quotes = _parse_event(event, "nba", NBA_MARKET_TO_STAT)
        assert len(quotes) == 0

    def test_empty_bookmakers_ok(self):
        event = {"id": "x", "bookmakers": []}
        assert _parse_event(event, "nba", NBA_MARKET_TO_STAT) == []


class TestProviderFactory:
    def test_no_key_returns_mock(self, monkeypatch):
        monkeypatch.delenv("ODDS_API_KEY", raising=False)
        provider = get_odds_provider()
        assert isinstance(provider, MockOdds)

    def test_with_key_returns_real_client(self, monkeypatch):
        monkeypatch.setenv("ODDS_API_KEY", "test_key_123")
        provider = get_odds_provider()
        from app.data.odds_api import OddsAPIClient
        assert isinstance(provider, OddsAPIClient)
