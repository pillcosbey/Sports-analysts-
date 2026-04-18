"""Core betting math: odds conversions, devigging, Kelly sizing.

These are the primitives every other layer depends on. They are pure
functions, no I/O, no state — easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


# ---------- American odds <-> implied probability ----------

def american_to_prob(odds: int) -> float:
    """Convert American odds to *vig-included* implied probability.

    >>> round(american_to_prob(-110), 4)
    0.5238
    >>> round(american_to_prob(150), 4)
    0.4
    """
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def prob_to_american(p: float) -> int:
    """Convert a probability to American odds (fair, no vig)."""
    if not 0.0 < p < 1.0:
        raise ValueError("Probability must be in (0, 1)")
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def american_to_decimal(odds: int) -> float:
    """American to decimal odds (payout multiplier, includes stake)."""
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / (-odds)


# ---------- Devigging ----------

def devig_two_way(over_odds: int, under_odds: int) -> Tuple[float, float]:
    """Remove the sportsbook margin from a 2-way market (over/under).

    Uses the "multiplicative" (proportional) method, which is the
    most common and is what Pinnacle-style sharp-line estimation assumes.

    Returns (fair_p_over, fair_p_under) that sum to 1.0.

    >>> o, u = devig_two_way(-110, -110)
    >>> round(o, 4), round(u, 4)
    (0.5, 0.5)
    """
    p_over = american_to_prob(over_odds)
    p_under = american_to_prob(under_odds)
    total = p_over + p_under
    if total <= 0:
        raise ValueError("Invalid odds: implied probs sum to 0")
    return p_over / total, p_under / total


def sportsbook_margin(over_odds: int, under_odds: int) -> float:
    """The vig / hold on a 2-way market, as a decimal (0.045 == 4.5%)."""
    return american_to_prob(over_odds) + american_to_prob(under_odds) - 1.0


# ---------- Edge + Kelly ----------

@dataclass(frozen=True)
class EdgeResult:
    side: str                # "OVER" or "UNDER"
    model_prob: float        # simulator's probability for that side
    fair_prob: float         # devigged sportsbook probability for that side
    edge_pct: float          # (model - fair) * 100
    ev_per_dollar: float     # expected value per $1 staked
    kelly_fraction: float    # full-Kelly fraction of bankroll
    recommended_stake_pct: float  # after applying fractional Kelly cap


def edge_and_kelly(
    model_p_over: float,
    over_odds: int,
    under_odds: int,
    kelly_fraction_cap: float = 0.25,
    min_edge_pct: float = 0.0,
) -> EdgeResult | None:
    """Compare a model probability against a 2-way book line.

    Returns an EdgeResult for whichever side has positive EV, or None if
    neither side clears `min_edge_pct`.

    Args:
        model_p_over: simulator's P(over).
        over_odds: American odds on OVER.
        under_odds: American odds on UNDER.
        kelly_fraction_cap: fractional Kelly multiplier (0.25 = quarter-Kelly).
        min_edge_pct: minimum edge over the fair line to consider a play.
    """
    model_p_under = 1.0 - model_p_over
    fair_over, fair_under = devig_two_way(over_odds, under_odds)

    over_edge_pct = (model_p_over - fair_over) * 100.0
    under_edge_pct = (model_p_under - fair_under) * 100.0

    if over_edge_pct >= under_edge_pct:
        side = "OVER"
        p = model_p_over
        fair = fair_over
        odds = over_odds
        edge_pct = over_edge_pct
    else:
        side = "UNDER"
        p = model_p_under
        fair = fair_under
        odds = under_odds
        edge_pct = under_edge_pct

    if edge_pct < min_edge_pct:
        return None

    decimal_odds = american_to_decimal(odds)
    b = decimal_odds - 1.0  # net odds
    q = 1.0 - p
    # Kelly: f* = (bp - q) / b
    kelly = (b * p - q) / b if b > 0 else 0.0
    kelly = max(0.0, kelly)
    stake_pct = kelly * kelly_fraction_cap
    ev = p * b - q  # EV per $1 staked

    return EdgeResult(
        side=side,
        model_prob=round(p, 4),
        fair_prob=round(fair, 4),
        edge_pct=round(edge_pct, 2),
        ev_per_dollar=round(ev, 4),
        kelly_fraction=round(kelly, 4),
        recommended_stake_pct=round(stake_pct * 100.0, 2),
    )
