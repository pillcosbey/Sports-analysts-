"""Auto-generate +EV bet-builder suggestions from a halftime board.

Given a list of priced legs (each with model probability and assumed payout
odds), search for 2-, 3-, and 4-leg parlays from the SAME game with the
highest correlated EV. Same-game legs get correlation handled by parlay.py.

This isn't a full combinatorial search — that would explode. We cap each
combo size at the top N strongest individual legs by model probability,
then enumerate combinations within that pool.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Sequence

from app.core.math_utils import decimal_to_american
from app.core.parlay import ParlayLeg, build_parlay


@dataclass
class CandidateLeg:
    player: str
    team: str
    stat: str
    side: str
    line: float
    model_prob: float
    american_odds: int
    decimal_odds: float
    game_id: str
    sport: str


@dataclass
class BuilderSuggestion:
    legs: list[CandidateLeg]
    naive_prob: float
    correlated_prob: float
    combined_decimal_odds: float
    combined_american: int
    ev_per_dollar: float
    correlation_score: float = 0.0   # avg pairwise correlation across same-game pairs
    correlation_warning: str = ""    # set when legs are uncorrelated (parlay-risk)


def _to_parlay_leg(c: CandidateLeg) -> ParlayLeg:
    return ParlayLeg(
        player=c.player,
        stat=c.stat,
        side=c.side,
        model_prob=c.model_prob,
        game_id=c.game_id,
        sport=c.sport,
        decimal_odds=c.decimal_odds,
    )


def suggest_builders(
    candidates: Sequence[CandidateLeg],
    *,
    sizes: Iterable[int] = (2, 3, 4),
    pool_size: int = 14,
    top_k: int = 6,
    min_ev: float = 0.0,
    min_leg_prob: float = 0.50,
) -> list[BuilderSuggestion]:
    """Return up to `top_k` best parlays sorted by correlated EV.

    - `sizes`: combo sizes to enumerate (default 2/3/4 legs).
    - `pool_size`: only consider this many strongest individual legs.
    - `min_leg_prob`: drop legs below this model probability before combining.
    - `min_ev`: only keep parlays whose correlated EV per $ exceeds this.
    """
    pool = [c for c in candidates if c.model_prob >= min_leg_prob]
    # Rank pool by per-leg edge (model_prob * decimal_odds - 1)
    pool.sort(key=lambda c: c.model_prob * c.decimal_odds - 1, reverse=True)
    pool = pool[:pool_size]

    seen: set[tuple] = set()
    suggestions: list[BuilderSuggestion] = []
    for size in sizes:
        if size > len(pool):
            continue
        for combo in itertools.combinations(pool, size):
            # No double-up on same player+stat
            keys = {(c.player, c.stat) for c in combo}
            if len(keys) != size:
                continue
            # Dedup by sorted (player, stat, side) tuple
            sig = tuple(sorted((c.player, c.stat, c.side) for c in combo))
            if sig in seen:
                continue
            seen.add(sig)

            result = build_parlay([_to_parlay_leg(c) for c in combo])
            if result.ev_per_dollar < min_ev:
                continue
            # correlation_penalty is 1 - copula_adjustment; positive means
            # legs hurt each other, negative means they help. Translate into
            # a 0-1 "how much do these legs move together" score for the UI.
            corr_score = max(0.0, -result.correlation_penalty + 0.0)
            warning = ""
            if size >= 3 and corr_score <= 0.02:
                warning = (
                    "Low same-game correlation: every leg must hit independently. "
                    "Consider smaller stake or splitting into single bets."
                )
            suggestions.append(BuilderSuggestion(
                legs=list(combo),
                naive_prob=result.naive_prob,
                correlated_prob=result.correlated_prob,
                combined_decimal_odds=result.combined_decimal_odds,
                combined_american=decimal_to_american(result.combined_decimal_odds),
                ev_per_dollar=result.ev_per_dollar,
                correlation_score=round(corr_score, 4),
                correlation_warning=warning,
            ))

    suggestions.sort(key=lambda s: s.ev_per_dollar, reverse=True)
    return suggestions[:top_k]
