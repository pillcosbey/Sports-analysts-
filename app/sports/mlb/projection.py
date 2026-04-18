"""MLB player-prop projections.

Hitters: per-plate-appearance rate * projected PAs
Pitchers: per-inning rate * projected innings
Both adjusted for opponent park, handedness splits, and umpire (strikeouts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from app.core.simulator import Projection
from app.sports.mlb.markets import MLB_MARKETS


DEFAULT_WEIGHTS = {
    "w_season": 0.40,
    "w_recent": 0.35,
    "w_matchup": 0.25,
    "sd_scale": {
        "hits":          1.05,
        "total_bases":   1.10,
        "runs":          1.15,
        "rbis":          1.20,
        "home_runs":     1.20,
        "stolen_bases":  1.15,
        "walks":         1.10,
        "strikeouts":    1.00,
        "outs_recorded": 0.95,
        "hits_allowed":  1.05,
        "earned_runs":   1.20,
        "walks_allowed": 1.15,
    },
}


@dataclass
class HitterContext:
    player: str
    stat: str
    season_rate_per_pa: float   # e.g. hits/PA
    season_sd: float
    last_n_rate_per_pa: float
    last_n_sd: float
    projected_pas: float         # usually 4.1-4.5
    opp_sp_factor: float         # >1 = opp starter gives up more of this
    park_factor: float           # >1 = hitter-friendly park
    lineup_slot_factor: float = 1.0


@dataclass
class PitcherContext:
    player: str
    stat: str
    season_rate_per_ip: float    # e.g. K/IP
    season_sd: float
    last_n_rate_per_ip: float
    last_n_sd: float
    projected_ip: float          # projected innings pitched
    opp_lineup_factor: float     # >1 = opp lineup prone to this stat
    park_factor: float
    umpire_factor: float = 1.0   # matters for K props


def project_hitter(
    ctx: HitterContext,
    weights: Dict[str, Any] | None = None,
) -> Projection:
    w = weights or DEFAULT_WEIGHTS
    if ctx.stat not in MLB_MARKETS or MLB_MARKETS[ctx.stat]["side"] != "hitter":
        raise ValueError(f"Not a hitter market: {ctx.stat}")

    matchup_rate = ctx.season_rate_per_pa * ctx.opp_sp_factor * ctx.park_factor
    blended_rate = (
        w["w_season"] * ctx.season_rate_per_pa
        + w["w_recent"] * ctx.last_n_rate_per_pa
        + w["w_matchup"] * matchup_rate
    )
    mean = blended_rate * ctx.projected_pas * ctx.lineup_slot_factor
    sd = max(ctx.season_sd, ctx.last_n_sd) * w["sd_scale"].get(ctx.stat, 1.0)

    spec = MLB_MARKETS[ctx.stat]
    return Projection(
        player=ctx.player,
        stat=ctx.stat,
        mean=round(mean, 3),
        sd=round(max(sd, 0.35), 3),
        dist=spec["dist"],
        floor=spec["floor"],
    )


def project_pitcher(
    ctx: PitcherContext,
    weights: Dict[str, Any] | None = None,
) -> Projection:
    w = weights or DEFAULT_WEIGHTS
    if ctx.stat not in MLB_MARKETS or MLB_MARKETS[ctx.stat]["side"] != "pitcher":
        raise ValueError(f"Not a pitcher market: {ctx.stat}")

    matchup_rate = ctx.season_rate_per_ip * ctx.opp_lineup_factor * ctx.park_factor
    blended_rate = (
        w["w_season"] * ctx.season_rate_per_ip
        + w["w_recent"] * ctx.last_n_rate_per_ip
        + w["w_matchup"] * matchup_rate
    )
    ump_bump = ctx.umpire_factor if ctx.stat == "strikeouts" else 1.0
    mean = blended_rate * ctx.projected_ip * ump_bump
    sd = max(ctx.season_sd, ctx.last_n_sd) * w["sd_scale"].get(ctx.stat, 1.0)

    spec = MLB_MARKETS[ctx.stat]
    return Projection(
        player=ctx.player,
        stat=ctx.stat,
        mean=round(mean, 3),
        sd=round(max(sd, 0.35), 3),
        dist=spec["dist"],
        floor=spec["floor"],
    )
