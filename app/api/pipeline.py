"""End-to-end pipeline: odds -> projection -> simulation -> edge -> card.

This is what the web routes call. It takes a sport and returns a list of
`PickCard` dicts ready for JSON serialization.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from app.core.math_utils import (
    edge_and_kelly, sportsbook_margin, devig_two_way,
)
from app.core.simulator import simulate_prop
from app.data.providers import MockOdds, MockStats
from app.sports.nba.projection import PlayerContext, project_pregame
from app.sports.nba.live import LiveGameState, project_live
from app.sports.mlb.projection import (
    HitterContext, PitcherContext, project_hitter, project_pitcher,
)
from app.sports.mlb.live import (
    HitterGameState, PitcherGameState,
    project_hitter_live, project_pitcher_live,
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def build_board(sport: str, phase: str = "pregame") -> list[dict[str, Any]]:
    """Run the full pipeline for one sport and return pick cards.

    `phase` is 'pregame' or 'live'.
    """
    odds_provider = MockOdds()
    stats_provider = MockStats()

    trials = _env_int("SIM_TRIALS", 1000)
    kelly_cap = _env_float("KELLY_FRACTION", 0.25)
    min_edge = _env_float("MIN_EDGE_PCT", 3.0)

    cards: list[dict[str, Any]] = []

    for quote in odds_provider.player_prop_odds(sport):
        try:
            ctx_raw = stats_provider.player_context(sport, quote.player, quote.stat)
        except KeyError:
            continue

        if sport == "nba":
            ctx = PlayerContext(
                player=quote.player, stat=quote.stat, **ctx_raw,
            )
            projection = project_pregame(ctx)

            if phase == "live":
                live = stats_provider.live_game_state(sport, quote.game_id, quote.player)
                if live is not None:
                    state = LiveGameState(**live)
                    projection, _ = project_live(ctx, state)

        elif sport == "mlb":
            kind = ctx_raw.pop("kind")
            if kind == "hitter":
                hctx = HitterContext(player=quote.player, stat=quote.stat, **ctx_raw)
                projection = project_hitter(hctx)
                if phase == "live":
                    live = stats_provider.live_game_state(sport, quote.game_id, quote.player)
                    if live is not None and "pas_so_far" in live:
                        projection = project_hitter_live(hctx, HitterGameState(**live))
            else:
                pctx = PitcherContext(player=quote.player, stat=quote.stat, **ctx_raw)
                projection = project_pitcher(pctx)
                if phase == "live":
                    live = stats_provider.live_game_state(sport, quote.game_id, quote.player)
                    if live is not None and "innings_pitched" in live:
                        projection = project_pitcher_live(pctx, PitcherGameState(**live))
        else:
            continue

        sim = simulate_prop(projection, quote.line, trials=trials)
        edge = edge_and_kelly(
            model_p_over=sim.p_over,
            over_odds=quote.over_odds,
            under_odds=quote.under_odds,
            kelly_fraction_cap=kelly_cap,
            min_edge_pct=min_edge,
        )
        hold = round(sportsbook_margin(quote.over_odds, quote.under_odds) * 100, 2)
        fair_over, fair_under = devig_two_way(quote.over_odds, quote.under_odds)

        card = {
            "sport": sport,
            "phase": phase,
            "player": quote.player,
            "team": quote.team,
            "stat": quote.stat,
            "line": quote.line,
            "book": quote.book,
            "odds": {"over": quote.over_odds, "under": quote.under_odds, "hold_pct": hold},
            "projection": {
                "mean": projection.mean,
                "sd": projection.sd,
                "dist": projection.dist,
            },
            "simulation": {
                "trials": sim.trials,
                "p_over": sim.p_over,
                "p_under": sim.p_under,
                "p10": round(sim.p10, 2),
                "p50": round(sim.p50, 2),
                "p90": round(sim.p90, 2),
            },
            "fair": {
                "p_over": round(fair_over, 4),
                "p_under": round(fair_under, 4),
            },
            "edge": edge.__dict__ if edge else None,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        cards.append(card)

    # Sort by edge desc (None at bottom)
    cards.sort(
        key=lambda c: (c["edge"]["edge_pct"] if c["edge"] else -999),
        reverse=True,
    )
    return cards
