"""Unit tests for the betting math primitives."""

import math
import pytest

from app.core.math_utils import (
    american_to_prob, prob_to_american, american_to_decimal,
    devig_two_way, sportsbook_margin, edge_and_kelly,
)


def test_american_to_prob_minus_110():
    assert math.isclose(american_to_prob(-110), 0.5238, abs_tol=0.001)


def test_american_to_prob_plus_150():
    assert math.isclose(american_to_prob(150), 0.4, abs_tol=0.001)


def test_prob_to_american_roundtrip_favorite():
    assert prob_to_american(american_to_prob(-200)) == -200


def test_prob_to_american_roundtrip_dog():
    assert prob_to_american(american_to_prob(200)) == 200


def test_decimal_conversion():
    assert math.isclose(american_to_decimal(-110), 1.909, abs_tol=0.001)
    assert math.isclose(american_to_decimal(150), 2.5, abs_tol=0.001)


def test_devig_symmetric_market():
    o, u = devig_two_way(-110, -110)
    assert math.isclose(o, 0.5, abs_tol=1e-9)
    assert math.isclose(u, 0.5, abs_tol=1e-9)


def test_devig_asymmetric_market_sums_to_one():
    o, u = devig_two_way(-140, +120)
    assert math.isclose(o + u, 1.0, abs_tol=1e-9)
    assert o > u  # favorite


def test_hold_minus_110_both_sides():
    # Classic -110/-110 market has ~4.76% vig
    h = sportsbook_margin(-110, -110)
    assert math.isclose(h, 0.0476, abs_tol=0.001)


def test_edge_and_kelly_positive_edge_over():
    # Simulator says 60% but market-fair is 50% at -110/-110
    result = edge_and_kelly(model_p_over=0.6, over_odds=-110, under_odds=-110)
    assert result is not None
    assert result.side == "OVER"
    assert result.edge_pct > 9.0
    assert result.kelly_fraction > 0
    assert result.recommended_stake_pct > 0


def test_edge_and_kelly_no_edge_returns_none():
    result = edge_and_kelly(
        model_p_over=0.51, over_odds=-110, under_odds=-110, min_edge_pct=3.0,
    )
    assert result is None


def test_edge_and_kelly_picks_under_when_model_low():
    result = edge_and_kelly(model_p_over=0.35, over_odds=-110, under_odds=-110)
    assert result is not None
    assert result.side == "UNDER"


# ---- Simulator smoke test ----

def test_simulator_runs_and_returns_probs():
    from app.core.simulator import Projection, simulate_prop
    p = Projection(player="Test", stat="points", mean=25.0, sd=7.0, dist="negbin")
    sim = simulate_prop(p, line=24.5, trials=1000, seed=42)
    assert sim.trials == 1000
    assert 0.0 < sim.p_over < 1.0
    assert 0.0 < sim.p_under < 1.0
    assert math.isclose(sim.p_over + sim.p_under, 1.0, abs_tol=0.02)


def test_simulator_minimum_100_trials():
    from app.core.simulator import Projection, simulate_prop
    p = Projection(player="Test", stat="hits", mean=0.9, sd=1.0, dist="poisson")
    sim = simulate_prop(p, line=0.5, trials=50)  # requested too few
    assert sim.trials >= 100
