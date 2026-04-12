"""Live in-game projection for NBA (halftime, end Q3, etc.).

Idea: at time T of a 48-minute game, the player has `current_stat` already
banked. The question is: what's the distribution of their *final* stat?

    final = current_stat + rest_of_game_stat

We model `rest_of_game_stat` as a scaled pre-game projection, where the
scale factor is the fraction of minutes the player has left, adjusted for
their current per-minute rate and game flow (foul trouble, blowout).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.simulator import Projection
from app.sports.nba.markets import NBA_GAME_MINUTES, NBA_MARKETS
from app.sports.nba.projection import PlayerContext, project_pregame


@dataclass
class LiveGameState:
    """Snapshot of a player's in-game state."""
    minutes_played: float
    current_stat: float          # e.g. points scored so far
    on_pace_multiplier: float = 1.0  # >1 if outperforming baseline
    blowout_adjust: float = 1.0      # <1 if game is a blowout (bench likely)
    foul_trouble: bool = False       # if True, shave projected minutes


def project_live(
    ctx: PlayerContext,
    state: LiveGameState,
    weights=None,
) -> tuple[Projection, float]:
    """Return a Projection for the *final* game total and the current stat.

    The caller then hands the Projection to the simulator with the same
    sportsbook line to get an updated P(over).
    """
    if ctx.stat not in NBA_MARKETS:
        raise ValueError(f"Unknown NBA market: {ctx.stat}")

    pregame = project_pregame(ctx, weights=weights)

    minutes_remaining = max(NBA_GAME_MINUTES - state.minutes_played, 0.0)
    # Adjust projected minutes: start from pre-game minutes projection
    projected_remaining_minutes = min(
        minutes_remaining,
        max(ctx.minutes_projection - state.minutes_played, 0.0),
    )
    if state.foul_trouble:
        projected_remaining_minutes *= 0.85
    projected_remaining_minutes *= state.blowout_adjust

    # Per-minute rate from the pre-game projection
    per_min = pregame.mean / max(ctx.minutes_projection, 1.0)
    # Blend pre-game per-minute with in-game per-minute rate
    in_game_per_min = (
        state.current_stat / state.minutes_played
        if state.minutes_played > 0 else per_min
    )
    # 60/40 blend: trust the model but let live evidence move it
    blended_per_min = 0.4 * per_min + 0.6 * in_game_per_min * state.on_pace_multiplier

    rest_of_game_mean = blended_per_min * projected_remaining_minutes
    final_mean = state.current_stat + rest_of_game_mean

    # Variance shrinks as game progresses: less unknown left
    time_remaining_frac = max(minutes_remaining / NBA_GAME_MINUTES, 0.01)
    live_sd = pregame.sd * (time_remaining_frac ** 0.5)

    return (
        Projection(
            player=ctx.player,
            stat=ctx.stat,
            mean=round(final_mean, 3),
            sd=round(max(live_sd, 0.25), 3),
            dist=pregame.dist,
            floor=state.current_stat,  # can't go below what's already banked
        ),
        state.current_stat,
    )
