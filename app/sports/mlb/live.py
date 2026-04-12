"""Live in-game projection for MLB (after each inning / plate appearance).

The key variable for hitters is *plate appearances remaining*. For pitchers
it's *innings remaining* plus the pitch-count ceiling (manager likely to
pull at 100–110 pitches).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.simulator import Projection
from app.sports.mlb.markets import MLB_MARKETS
from app.sports.mlb.projection import (
    HitterContext, PitcherContext, project_hitter, project_pitcher,
)


@dataclass
class HitterGameState:
    pas_so_far: int
    current_stat: float
    score_differential: int = 0  # used for pinch-hit / bench risk


@dataclass
class PitcherGameState:
    innings_pitched: float
    pitch_count: int
    current_stat: float
    pitch_count_ceiling: int = 100


def project_hitter_live(
    ctx: HitterContext, state: HitterGameState, weights=None
) -> Projection:
    pregame = project_hitter(ctx, weights=weights)
    remaining_pas = max(ctx.projected_pas - state.pas_so_far, 0.0)
    per_pa = pregame.mean / max(ctx.projected_pas, 1.0)

    # In-game observed rate (shrinks to prior early)
    obs_rate = (state.current_stat / state.pas_so_far) if state.pas_so_far > 0 else per_pa
    shrink = state.pas_so_far / (state.pas_so_far + 4.0)
    blended_per_pa = shrink * obs_rate + (1 - shrink) * per_pa

    rest_mean = blended_per_pa * remaining_pas
    final_mean = state.current_stat + rest_mean

    time_left = remaining_pas / max(ctx.projected_pas, 1.0)
    live_sd = pregame.sd * max(time_left ** 0.5, 0.15)

    spec = MLB_MARKETS[ctx.stat]
    return Projection(
        player=ctx.player,
        stat=ctx.stat,
        mean=round(final_mean, 3),
        sd=round(max(live_sd, 0.2), 3),
        dist=spec["dist"],
        floor=state.current_stat,
    )


def project_pitcher_live(
    ctx: PitcherContext, state: PitcherGameState, weights=None
) -> Projection:
    pregame = project_pitcher(ctx, weights=weights)

    # Cap remaining innings by pitch count
    pitches_left = max(state.pitch_count_ceiling - state.pitch_count, 0)
    est_innings_from_pitches = pitches_left / 16.0  # ~16 pitches per inning average
    remaining_ip = min(
        max(ctx.projected_ip - state.innings_pitched, 0.0),
        est_innings_from_pitches,
    )

    per_ip = pregame.mean / max(ctx.projected_ip, 1.0)
    obs_rate = (
        state.current_stat / state.innings_pitched
        if state.innings_pitched > 0 else per_ip
    )
    shrink = state.innings_pitched / (state.innings_pitched + 2.5)
    blended_per_ip = shrink * obs_rate + (1 - shrink) * per_ip

    rest_mean = blended_per_ip * remaining_ip
    final_mean = state.current_stat + rest_mean

    time_left = remaining_ip / max(ctx.projected_ip, 1.0)
    live_sd = pregame.sd * max(time_left ** 0.5, 0.15)

    spec = MLB_MARKETS[ctx.stat]
    return Projection(
        player=ctx.player,
        stat=ctx.stat,
        mean=round(final_mean, 3),
        sd=round(max(live_sd, 0.2), 3),
        dist=spec["dist"],
        floor=state.current_stat,
    )
