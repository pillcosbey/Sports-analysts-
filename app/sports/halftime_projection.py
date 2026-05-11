"""Halftime / in-game projections for the live analyzer.

NBA (real halftime):
  - We have Q1+Q2 player stats. Project Q3+Q4 by blending three signals:
    (a) the rate the player is on so far (carried forward),
    (b) their season half-pace (season mean / 2),
    (c) a pace adjustment based on the actual halftime game total vs.
        the expected halftime total.
  - Players with foul trouble (4+ PF) get their projection trimmed.
  - Players already at >= 25 actual minutes get a slight cap because the
    coach is more likely to manage their workload in the second half.

MLB (in-game, mid-5th onward):
  - For hitters we project remaining ABs and remaining hits/RBIs.
  - For pitchers we project remaining IP based on pitch count.

Outputs are `Projection` objects ready for the Monte Carlo simulator, plus
fair / live lines so the API can surface a halftime-O/U for each stat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.simulator import Projection
from app.data.live_boxscore import NBABoxGame, NBABoxPlayer
from app.data.nba_stats import NBA_PLAYERS, COMBO_STATS


# Stats we project for halftime
NBA_HALFTIME_STATS = (
    "points",
    "rebounds",
    "assists",
    "threes_made",
    "steals",
    "blocks",
    "pra",
    "pr",
    "pa",
)

# Blend weights for the 2nd-half mean.
# Heavier on actual-rate-so-far since the user is reacting to a real game.
W_RATE = 0.55
W_SEASON = 0.30
W_PACE = 0.15

# Dist per stat — matches the pregame projection assumptions.
_DIST = {
    "points": "negbin",
    "rebounds": "negbin",
    "assists": "negbin",
    "threes_made": "poisson",
    "steals": "poisson",
    "blocks": "poisson",
    "pra": "negbin",
    "pr": "negbin",
    "pa": "negbin",
}

# Variance scale per stat for the 2nd-half projection.
# Halftime has half the time → variance shrinks by ~sqrt(0.5).
_SD_SCALE = 0.72


@dataclass
class HalftimeLeg:
    player: str
    team: str
    stat: str
    so_far: float          # actual 1st-half stat
    projection: float      # projected final game value
    second_half: float     # projected second-half only
    sd: float              # second-half SD
    line: float            # suggested halftime O/U line (over the second half)
    p_over: float          # model probability the player goes over the line in 2H
    minutes_so_far: float
    foul_trouble: bool


@dataclass
class HalftimeGame:
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    quarter: int
    clock: str
    is_halftime: bool
    pace_factor: float        # >1 = game running hot vs. expected
    legs: list[HalftimeLeg]


def _stat_value(p: NBABoxPlayer, stat: str) -> int:
    if stat == "pra":
        return p.points + p.rebounds + p.assists
    if stat == "pr":
        return p.points + p.rebounds
    if stat == "pa":
        return p.points + p.assists
    return getattr(p, stat, 0)


def _season_half_mean(player_name: str, stat: str) -> tuple[float, float] | None:
    """Return (half_mean, half_sd) for the player, or None if not in db."""
    p = NBA_PLAYERS.get(player_name)
    if not p:
        return None
    if stat in COMBO_STATS:
        try:
            mean = sum(p[c][0] for c in COMBO_STATS[stat])
            sd = sum(p[c][1] for c in COMBO_STATS[stat]) * 0.75
        except (KeyError, TypeError):
            return None
        return mean / 2.0, sd * 0.72
    val = p.get(stat)
    if not isinstance(val, tuple):
        return None
    return val[0] / 2.0, val[1] * 0.72


def _line_round(stat: str, value: float) -> float:
    """Half-point line that's closest to `value` (matches sportsbook conventions)."""
    if stat in ("steals", "blocks", "threes_made"):
        # rare counting stats — use 0.5 granularity, but anchor near integers
        return round(value * 2) / 2.0
    return round(value * 2) / 2.0


def project_nba_halftime(game: NBABoxGame) -> HalftimeGame:
    """Project second-half lines for every meaningful player in the game.

    "Meaningful" = at least 8 minutes played in the first half. Bench guys
    who only saw garbage time aren't worth modeling.
    """
    # Game-level pace: expected halftime total for an average game is ~110.
    # Compare to actual halftime total.
    total = game.home_score + game.away_score
    pace_factor = max(0.80, min(1.25, total / 110.0))

    legs: list[HalftimeLeg] = []
    for p in game.players:
        if p.minutes < 8.0:
            continue
        foul_trouble = p.fouls >= 4
        for stat in NBA_HALFTIME_STATS:
            so_far = float(_stat_value(p, stat))
            half_mean = _season_half_mean(p.player, stat)
            if half_mean is None:
                # Unknown player → fall back to rate-only projection.
                # Players not in our dataset still get analyzed using the rate they're on.
                base_mean = so_far
                base_sd = max(1.0, so_far * 0.6)
                second_half_mean = base_mean * pace_factor
                second_half_sd = base_sd * _SD_SCALE
            else:
                season_half, season_sd = half_mean
                rate_projection = so_far  # what they'd produce in the 2H if they kept their 1H rate
                pace_term = season_half * pace_factor
                second_half_mean = (
                    W_RATE * rate_projection
                    + W_SEASON * season_half
                    + W_PACE * pace_term
                )
                second_half_sd = season_sd * _SD_SCALE

            # Foul-trouble haircut
            if foul_trouble:
                second_half_mean *= 0.78
            # Heavy minutes already → mild taper
            if p.minutes >= 22:
                second_half_mean *= 0.94

            second_half_mean = max(0.0, second_half_mean)
            second_half_sd = max(0.4, second_half_sd)

            line = _line_round(stat, second_half_mean)
            # Quick p_over via the simulator
            proj = Projection(
                player=p.player,
                stat=stat,
                mean=round(second_half_mean, 3),
                sd=round(second_half_sd, 3),
                dist=_DIST.get(stat, "negbin"),
                floor=0.0,
            )
            from app.core.simulator import simulate_prop
            sim = simulate_prop(proj, line, trials=600)

            legs.append(HalftimeLeg(
                player=p.player,
                team=p.team,
                stat=stat,
                so_far=so_far,
                projection=round(so_far + second_half_mean, 1),
                second_half=round(second_half_mean, 1),
                sd=round(second_half_sd, 2),
                line=line,
                p_over=sim.p_over,
                minutes_so_far=p.minutes,
                foul_trouble=foul_trouble,
            ))

    return HalftimeGame(
        game_id=game.game_id,
        home_team=game.home_team,
        away_team=game.away_team,
        home_score=game.home_score,
        away_score=game.away_score,
        quarter=game.quarter,
        clock=game.clock,
        is_halftime=game.is_halftime,
        pace_factor=round(pace_factor, 3),
        legs=legs,
    )
