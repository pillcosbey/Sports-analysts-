"""Tests for the parlay builder."""

import pytest

from app.core.parlay import ParlayLeg, build_parlay


def _leg(player="A", stat="points", side="OVER", prob=0.55, game="g1", sport="nba", odds=1.91):
    return ParlayLeg(player=player, stat=stat, side=side, model_prob=prob, game_id=game, sport=sport, decimal_odds=odds)


class TestParlay:
    def test_two_leg_independent(self):
        legs = [_leg(game="g1"), _leg(player="B", game="g2")]
        result = build_parlay(legs)
        assert result.naive_prob == pytest.approx(0.3025, abs=0.001)
        assert result.correlation_penalty == 0.0  # different games

    def test_same_game_has_correlation(self):
        legs = [
            _leg(stat="points", game="g1"),
            _leg(player="B", stat="rebounds", game="g1"),
        ]
        result = build_parlay(legs)
        assert result.correlation_penalty != 0.0

    def test_combined_odds_multiply(self):
        legs = [_leg(odds=2.0), _leg(player="B", game="g2", odds=2.0)]
        result = build_parlay(legs)
        assert result.combined_decimal_odds == pytest.approx(4.0, abs=0.01)

    def test_positive_ev_flag(self):
        legs = [_leg(prob=0.7, odds=2.0), _leg(player="B", game="g2", prob=0.7, odds=2.0)]
        result = build_parlay(legs)
        assert result.is_positive_ev is True

    def test_negative_ev_flag(self):
        legs = [_leg(prob=0.4, odds=1.5), _leg(player="B", game="g2", prob=0.4, odds=1.5)]
        result = build_parlay(legs)
        assert result.is_positive_ev is False

    def test_minimum_two_legs(self):
        with pytest.raises(ValueError):
            build_parlay([_leg()])

    def test_three_leg_parlay(self):
        legs = [_leg(game="g1"), _leg(player="B", game="g2"), _leg(player="C", game="g3")]
        result = build_parlay(legs)
        assert len(result.legs) == 3
        assert result.naive_prob < 0.55 ** 3 + 0.01
