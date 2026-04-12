"""NBA player-prop projections.

The projection is a Bayesian blend:

    mean = w_season*season_avg
         + w_recent*last_n_avg
         + w_matchup*(season_avg * opp_def_factor * pace_factor)

Weights are tunable and get updated by the learning loop in
`app/learning/feedback.py` after each game.

This module does NOT fetch data — it consumes a `PlayerContext` dict and
returns a `Projection`. The data layer is responsible for building the
context from real APIs (or mocks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.core.simulator import Projection
from app.sports.nba.markets import NBA_MARKETS


# Default blend weights. These are the values the learning loop tunes.
DEFAULT_WEIGHTS = {
    "w_season": 0.35,
    "w_recent": 0.40,
    "w_matchup": 0.25,
    # Variance multipliers per market (higher = book lines harder to beat)
    "sd_scale": {
        "points":       1.05,
        "rebounds":     1.00,
        "assists":      1.00,
        "threes_made":  1.10,
        "steals":       1.15,
        "blocks":       1.15,
        "pra":          1.05,
        "pr":           1.00,
        "pa":           1.00,
        "ra":           1.00,
    },
}


@dataclass
class PlayerContext:
    """Everything the projection needs for one player, one market."""
    player: str
    stat: str
    season_avg: float
    season_sd: float
    last_n_avg: float
    last_n_sd: float
    opp_def_factor: float   # >1 = opponent ALLOWS more of this stat
    pace_factor: float      # >1 = faster-than-average game total expected
    minutes_projection: float     # baseline expected minutes
    minutes_season_avg: float     # season average minutes

    # Optional injury / lineup adjustment (e.g. star teammate out → +usage)
    usage_bump: float = 1.0


def project_pregame(
    ctx: PlayerContext,
    weights: Dict[str, Any] | None = None,
) -> Projection:
    """Build a pre-game Projection for the simulator."""
    w = weights or DEFAULT_WEIGHTS
    if ctx.stat not in NBA_MARKETS:
        raise ValueError(f"Unknown NBA market: {ctx.stat}")

    matchup_mean = ctx.season_avg * ctx.opp_def_factor * ctx.pace_factor
    blended = (
        w["w_season"] * ctx.season_avg
        + w["w_recent"] * ctx.last_n_avg
        + w["w_matchup"] * matchup_mean
    )
    minutes_ratio = (ctx.minutes_projection / ctx.minutes_season_avg) if ctx.minutes_season_avg > 0 else 1.0
    mean = blended * minutes_ratio * ctx.usage_bump

    # Variance blended, scaled by market-specific factor
    sd = max(ctx.season_sd, ctx.last_n_sd) * w["sd_scale"].get(ctx.stat, 1.0)

    spec = NBA_MARKETS[ctx.stat]
    return Projection(
        player=ctx.player,
        stat=ctx.stat,
        mean=round(mean, 3),
        sd=round(max(sd, 0.5), 3),
        dist=spec["dist"],
        floor=spec["floor"],
    )
