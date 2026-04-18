"""Tests for NBA and MLB stats providers."""

import pytest

from app.data.nba_stats import NBAStatsProvider, NBA_PLAYERS, NBA_DEFENSE
from app.data.mlb_stats import MLBStatsProvider, MLB_HITTERS, MLB_PITCHERS
from app.data.providers import get_stats_provider


class TestNBAStatsProvider:
    def setup_method(self):
        self.p = NBAStatsProvider()

    def test_player_context_returns_required_keys(self):
        ctx = self.p.player_context("nba", "LeBron James", "points")
        assert "season_avg" in ctx
        assert "season_sd" in ctx
        assert "minutes_projection" in ctx

    def test_combo_stat_pra(self):
        ctx = self.p.player_context("nba", "Luka Doncic", "pra")
        assert ctx["season_avg"] > 40  # points + rebounds + assists

    def test_unknown_player_raises(self):
        with pytest.raises(KeyError):
            self.p.player_context("nba", "Fake Player", "points")

    def test_defense_factor_range(self):
        f = self.p.defense_factor("OKC", "points")
        assert 0.85 <= f <= 1.15

    def test_pace_factor_range(self):
        f = self.p.pace_factor("IND", "MIA")
        assert 0.9 <= f <= 1.1

    def test_all_players_have_required_stats(self):
        for name, data in NBA_PLAYERS.items():
            assert "team" in data, f"{name} missing team"
            assert "points" in data, f"{name} missing points"
            assert "min" in data, f"{name} missing minutes"

    def test_all_teams_have_defense(self):
        teams = {p["team"] for p in NBA_PLAYERS.values()}
        for team in teams:
            assert team in NBA_DEFENSE, f"No defense data for {team}"

    def test_player_count(self):
        assert len(NBA_PLAYERS) >= 50


class TestMLBStatsProvider:
    def setup_method(self):
        self.p = MLBStatsProvider()

    def test_hitter_context(self):
        ctx = self.p.player_context("mlb", "Aaron Judge", "total_bases")
        assert ctx["kind"] == "hitter"
        assert "season_rate_per_pa" in ctx

    def test_pitcher_context(self):
        ctx = self.p.player_context("mlb", "Gerrit Cole", "strikeouts")
        assert ctx["kind"] == "pitcher"
        assert "season_rate_per_ip" in ctx

    def test_unknown_player_raises(self):
        with pytest.raises(KeyError):
            self.p.player_context("mlb", "Fake Pitcher", "strikeouts")

    def test_park_factor_range(self):
        f = self.p.park_factor("COL")
        assert f > 1.0  # Coors is hitter-friendly

    def test_player_count(self):
        assert len(MLB_HITTERS) + len(MLB_PITCHERS) >= 30


class TestMultiProvider:
    def test_routes_nba(self):
        sp = get_stats_provider()
        ctx = sp.player_context("nba", "Stephen Curry", "threes_made")
        assert ctx["season_avg"] > 3

    def test_routes_mlb(self):
        sp = get_stats_provider()
        ctx = sp.player_context("mlb", "Shohei Ohtani", "hits")
        assert ctx["kind"] == "hitter"

    def test_unknown_sport_raises(self):
        sp = get_stats_provider()
        with pytest.raises(KeyError):
            sp.player_context("nfl", "Someone", "points")
