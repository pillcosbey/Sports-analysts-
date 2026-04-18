"""Parlay builder with same-game correlation adjustment.

Naive parlay math multiplies independent probabilities, but same-game
player props are correlated: if the game goes high-scoring, points AND
assists AND rebounds all rise. Ignoring this overestimates parlay EVs.

We handle this with a simple correlation matrix and Gaussian copula.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Pairwise correlation between same-game stats (NBA).
# Positive = tend to move together. Zero = independent.
NBA_CORRELATION = {
    ("points", "rebounds"):  0.15,
    ("points", "assists"):   0.20,
    ("rebounds", "assists"):  0.05,
    ("points", "threes_made"): 0.45,
    ("points", "steals"):    0.10,
    ("points", "blocks"):    0.05,
    ("rebounds", "blocks"):   0.30,
    ("assists", "steals"):    0.10,
}

MLB_CORRELATION = {
    ("hits", "total_bases"):    0.60,
    ("hits", "runs"):           0.35,
    ("hits", "rbis"):           0.30,
    ("total_bases", "runs"):    0.40,
    ("total_bases", "rbis"):    0.50,
    ("runs", "rbis"):           0.25,
    ("home_runs", "total_bases"): 0.55,
    ("home_runs", "rbis"):       0.45,
    ("strikeouts", "outs_recorded"): 0.20,
}


def _get_corr(sport: str, stat_a: str, stat_b: str) -> float:
    table = NBA_CORRELATION if sport == "nba" else MLB_CORRELATION
    key = (stat_a, stat_b)
    rev = (stat_b, stat_a)
    return table.get(key, table.get(rev, 0.0))


@dataclass
class ParlayLeg:
    player: str
    stat: str
    side: str             # "OVER" or "UNDER"
    model_prob: float     # from simulator
    game_id: str
    sport: str
    decimal_odds: float   # payout multiplier


@dataclass
class ParlayResult:
    legs: list[ParlayLeg]
    naive_prob: float           # product of individual probs (ignores correlation)
    correlated_prob: float      # adjusted for same-game correlation
    combined_decimal_odds: float
    ev_per_dollar: float        # correlated EV
    is_positive_ev: bool
    correlation_penalty: float  # how much correlation shaved off


def build_parlay(legs: Sequence[ParlayLeg]) -> ParlayResult:
    """Price a parlay with same-game correlation adjustment.

    For legs from different games, correlation = 0 (independent).
    For legs from the same game, correlation is looked up from the table.
    """
    if len(legs) < 2:
        raise ValueError("A parlay needs at least 2 legs")

    # Naive: multiply individual probs
    naive = 1.0
    for leg in legs:
        naive *= leg.model_prob
    naive = max(naive, 1e-12)

    # Combined decimal odds
    combined_odds = 1.0
    for leg in legs:
        combined_odds *= leg.decimal_odds

    # Correlation adjustment via Gaussian copula approximation
    corr_adj = _copula_adjustment(list(legs))
    correlated = naive * corr_adj
    correlated = max(min(correlated, 0.99), 1e-12)

    ev = correlated * combined_odds - 1.0

    return ParlayResult(
        legs=list(legs),
        naive_prob=round(naive, 6),
        correlated_prob=round(correlated, 6),
        combined_decimal_odds=round(combined_odds, 3),
        ev_per_dollar=round(ev, 4),
        is_positive_ev=ev > 0,
        correlation_penalty=round(1.0 - corr_adj, 4),
    )


def _copula_adjustment(legs: list[ParlayLeg]) -> float:
    """Approximate the joint probability adjustment from pairwise correlations.

    For n legs, we adjust the naive product by the average pairwise
    correlation between same-game legs. This is a first-order approximation;
    a full copula simulation would be more accurate but slower.
    """
    n = len(legs)
    if n < 2:
        return 1.0

    total_corr = 0.0
    pair_count = 0

    for i in range(n):
        for j in range(i + 1, n):
            if legs[i].game_id == legs[j].game_id and legs[i].sport == legs[j].sport:
                rho = _get_corr(legs[i].sport, legs[i].stat, legs[j].stat)
                # Same-player same-game props are more correlated
                if legs[i].player == legs[j].player:
                    rho = min(rho * 1.5, 0.80)
                total_corr += rho
                pair_count += 1

    if pair_count == 0:
        return 1.0

    avg_corr = total_corr / pair_count

    # Directional: if both legs are the same direction (both OVER or both UNDER),
    # positive correlation HELPS the parlay. If opposite, it hurts.
    same_dir = all(l.side == legs[0].side for l in legs)
    if same_dir:
        # Correlated outcomes move together — slight boost
        return 1.0 + avg_corr * 0.15
    else:
        # Anti-directional legs hurt by correlation
        return 1.0 - avg_corr * 0.20
