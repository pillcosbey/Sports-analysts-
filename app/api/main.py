"""FastAPI backend. Serves the web UI and JSON endpoints.

Run:
    uvicorn app.api.main:app --reload
or:
    python -m app.api.main
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import build_board
from app.core.math_utils import american_to_decimal, edge_and_kelly

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="PropEdge Sports Research API",
    version="0.3.0",
    description="AI-powered sports betting research API with Monte Carlo simulations, live odds, player projections, parlay pricing, and backtesting for NBA and MLB props.",
    servers=[{"url": os.environ.get("PUBLIC_URL", ""), "description": "Production"}] if os.environ.get("PUBLIC_URL") else [],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chat.openai.com", "https://chatgpt.com", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


# ---------- Core board ----------

@app.get("/api/board")
def board(
    sport: str = Query("nba", pattern="^(nba|mlb)$"),
    phase: str = Query("pregame", pattern="^(pregame|live)$"),
):
    cards = build_board(sport, phase=phase)
    return JSONResponse({"sport": sport, "phase": phase, "cards": cards})


# ---------- Player search ----------

@app.get("/api/search")
def search_players(q: str = Query("", min_length=1), sport: str = Query("nba", pattern="^(nba|mlb)$")):
    """Search for players by name fragment. Returns matching names."""
    q_lower = q.lower()
    if sport == "nba":
        from app.data.nba_stats import NBA_PLAYERS
        matches = [name for name in NBA_PLAYERS if q_lower in name.lower()]
    else:
        from app.data.mlb_stats import MLB_HITTERS, MLB_PITCHERS
        all_names = list(MLB_HITTERS.keys()) + list(MLB_PITCHERS.keys())
        matches = [name for name in all_names if q_lower in name.lower()]
    return {"sport": sport, "query": q, "results": sorted(set(matches))[:20]}


@app.get("/api/player/{player_name}")
def player_detail(player_name: str, sport: str = Query("nba", pattern="^(nba|mlb)$")):
    """Get all available stats and projections for a specific player."""
    from app.data.providers import get_stats_provider
    from app.core.simulator import Projection, simulate_prop
    from app.sports.nba.markets import NBA_MARKETS
    from app.sports.mlb.markets import MLB_MARKETS

    stats_provider = get_stats_provider()
    markets = NBA_MARKETS if sport == "nba" else MLB_MARKETS
    trials = int(os.environ.get("SIM_TRIALS", "1000"))

    props = []
    for stat_name in markets:
        try:
            ctx = stats_provider.player_context(sport, player_name, stat_name)
        except KeyError:
            continue

        if sport == "nba":
            from app.sports.nba.projection import PlayerContext, project_pregame
            proj = project_pregame(PlayerContext(player=player_name, stat=stat_name, **ctx))
        else:
            kind = ctx.pop("kind", "hitter")
            if kind == "hitter":
                from app.sports.mlb.projection import HitterContext, project_hitter
                proj = project_hitter(HitterContext(player=player_name, stat=stat_name, **ctx))
            else:
                from app.sports.mlb.projection import PitcherContext, project_pitcher
                proj = project_pitcher(PitcherContext(player=player_name, stat=stat_name, **ctx))

        props.append({
            "stat": stat_name,
            "mean": proj.mean,
            "sd": proj.sd,
            "dist": proj.dist,
        })

    if not props:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)
    return {"player": player_name, "sport": sport, "props": props}


# ---------- Parlay builder ----------

@app.post("/api/parlay")
def build_parlay_endpoint(legs: list[dict] = Body(...)):
    """Price a parlay. Each leg: {player, stat, side, model_prob, game_id, sport, odds}."""
    from app.core.parlay import ParlayLeg, build_parlay

    parlay_legs = []
    for leg in legs:
        try:
            parlay_legs.append(ParlayLeg(
                player=leg["player"],
                stat=leg["stat"],
                side=leg["side"],
                model_prob=float(leg["model_prob"]),
                game_id=leg.get("game_id", ""),
                sport=leg.get("sport", "nba"),
                decimal_odds=american_to_decimal(int(leg["odds"])),
            ))
        except (KeyError, ValueError) as e:
            return JSONResponse({"error": f"Invalid leg: {e}"}, status_code=400)

    if len(parlay_legs) < 2:
        return JSONResponse({"error": "Need at least 2 legs"}, status_code=400)

    result = build_parlay(parlay_legs)
    return {
        "naive_prob": result.naive_prob,
        "correlated_prob": result.correlated_prob,
        "combined_odds": result.combined_decimal_odds,
        "ev_per_dollar": result.ev_per_dollar,
        "is_positive_ev": result.is_positive_ev,
        "correlation_penalty": result.correlation_penalty,
        "legs": len(result.legs),
    }


# ---------- Backtest ----------

@app.get("/api/backtest")
def run_backtest_endpoint(
    n_games: int = Query(200, ge=50, le=2000),
    min_edge: float = Query(3.0, ge=0.0),
):
    """Run a backtest on synthetic history."""
    from app.backtest.engine import generate_synthetic_history, run_backtest

    history = generate_synthetic_history(n_games=n_games)
    report = run_backtest(history, min_edge_pct=min_edge)
    return {
        "total_games": report.total_games,
        "picks_made": report.picks_made,
        "wins": report.wins,
        "losses": report.losses,
        "win_rate": report.win_rate,
        "flat_roi_pct": report.flat_roi_pct,
        "kelly_roi_pct": report.kelly_roi_pct,
        "mean_edge_pct": report.mean_edge_pct,
        "calibration": report.calibration,
        "by_sport": report.by_sport,
        "by_stat": report.by_stat,
    }


# ---------- Live scores ----------

@app.get("/api/live/nba")
def live_nba():
    """Get live NBA scoreboard from ESPN."""
    from app.data.live_scores import LiveScoresFeed
    feed = LiveScoresFeed()
    games = feed.nba_scoreboard()
    return {
        "games": [
            {
                "game_id": g.game_id,
                "home": g.home_team,
                "away": g.away_team,
                "score": f"{g.away_score}-{g.home_score}",
                "quarter": g.quarter,
                "clock": g.clock,
                "is_halftime": g.is_halftime,
                "is_final": g.is_final,
                "is_blowout": g.is_blowout,
            }
            for g in games
        ]
    }


@app.get("/api/live/mlb")
def live_mlb():
    """Get today's MLB schedule and live status."""
    from app.data.live_scores import LiveScoresFeed
    feed = LiveScoresFeed()
    return {"games": feed.mlb_schedule_today()}


# ---------- ChatGPT-friendly endpoints ----------

@app.get("/api/top-picks")
def top_picks(
    sport: str = Query("nba", pattern="^(nba|mlb)$"),
    limit: int = Query(10, ge=1, le=25),
):
    """Get the top player prop picks ranked by edge. Perfect for ChatGPT to summarize."""
    cards = build_board(sport, phase="pregame")
    plays = [c for c in cards if c.get("edge")]
    top = plays[:limit]
    return {
        "sport": sport,
        "total_props_scanned": len(cards),
        "plays_found": len(plays),
        "top_picks": [
            {
                "rank": i + 1,
                "player": c["player"],
                "team": c.get("team", ""),
                "stat": c["stat"],
                "line": c["line"],
                "side": c["edge"]["side"],
                "edge_pct": c["edge"]["edge_pct"],
                "model_probability": round(c["edge"]["model_prob"] * 100, 1),
                "ev_per_dollar": round(c["edge"]["ev_per_dollar"], 3),
                "recommended_stake_pct": c["edge"]["recommended_stake_pct"],
                "projected_mean": c["projection"]["mean"],
                "projected_sd": c["projection"]["sd"],
                "p10": c["simulation"]["p10"],
                "p50": c["simulation"]["p50"],
                "p90": c["simulation"]["p90"],
                "over_odds": c["odds"]["over"],
                "under_odds": c["odds"]["under"],
                "book": c.get("book", ""),
                "trials": c["simulation"]["trials"],
            }
            for i, c in enumerate(top)
        ],
    }


@app.get("/api/player-projection/{player_name}")
def player_projection(
    player_name: str,
    sport: str = Query("nba", pattern="^(nba|mlb)$"),
    stat: str = Query("points"),
    line: float = Query(20.5, ge=0.0),
):
    """Get a full projection + simulation for a specific player/stat/line. ChatGPT can ask for any combo."""
    from app.data.providers import get_stats_provider
    from app.core.simulator import simulate_prop

    stats_provider = get_stats_provider()
    trials = int(os.environ.get("SIM_TRIALS", "1000"))

    try:
        ctx = stats_provider.player_context(sport, player_name, stat)
    except KeyError:
        return JSONResponse({"error": f"Player or stat not found: {player_name} / {stat}"}, status_code=404)

    if sport == "nba":
        from app.sports.nba.projection import PlayerContext, project_pregame
        proj = project_pregame(PlayerContext(player=player_name, stat=stat, **ctx))
    else:
        kind = ctx.pop("kind", "hitter")
        if kind == "hitter":
            from app.sports.mlb.projection import HitterContext, project_hitter
            proj = project_hitter(HitterContext(player=player_name, stat=stat, **ctx))
        else:
            from app.sports.mlb.projection import PitcherContext, project_pitcher
            proj = project_pitcher(PitcherContext(player=player_name, stat=stat, **ctx))

    sim = simulate_prop(proj, line, trials=trials)
    edge_result = edge_and_kelly(
        model_p_over=sim.p_over,
        over_odds=-110,
        under_odds=-110,
        kelly_fraction_cap=0.25,
        min_edge_pct=3.0,
    )

    return {
        "player": player_name,
        "sport": sport,
        "stat": stat,
        "line": line,
        "projection": {"mean": proj.mean, "sd": proj.sd, "distribution": proj.dist},
        "simulation": {
            "trials": sim.trials,
            "p_over": round(sim.p_over * 100, 1),
            "p_under": round(sim.p_under * 100, 1),
            "p10": sim.p10,
            "p50": sim.p50,
            "p90": sim.p90,
        },
        "edge": {
            "side": edge_result.side,
            "edge_pct": edge_result.edge_pct,
            "ev_per_dollar": round(edge_result.ev_per_dollar, 3),
            "recommended_stake_pct": edge_result.recommended_stake_pct,
        } if edge_result else None,
    }


@app.get("/api/all-players")
def all_players(sport: str = Query("nba", pattern="^(nba|mlb)$")):
    """List all available players and their teams."""
    if sport == "nba":
        from app.data.nba_stats import NBA_PLAYERS
        return {"sport": sport, "players": [
            {"name": name, "team": data["team"]}
            for name, data in sorted(NBA_PLAYERS.items())
        ]}
    else:
        from app.data.mlb_stats import MLB_HITTERS, MLB_PITCHERS
        players = []
        for name, data in sorted(MLB_HITTERS.items()):
            players.append({"name": name, "team": data.get("team", ""), "type": "hitter"})
        for name, data in sorted(MLB_PITCHERS.items()):
            players.append({"name": name, "team": data.get("team", ""), "type": "pitcher"})
        return {"sport": sport, "players": players}


@app.get("/privacy")
def privacy_policy():
    """Privacy policy for ChatGPT GPT Actions."""
    return JSONResponse({
        "name": "PropEdge Sports Research",
        "privacy_policy": "This API provides sports betting research data. No personal data is collected or stored. All data is for research and entertainment purposes only. Users must be 21+. Not gambling advice.",
        "contact": "propedge@research.app",
    })


# ---------- Status ----------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    return {
        "odds_provider": "live" if os.environ.get("ODDS_API_KEY", "").strip() else "mock",
        "stats_provider": "database",
        "nba_players": _count_nba(),
        "mlb_players": _count_mlb(),
        "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    }


def _count_nba() -> int:
    try:
        from app.data.nba_stats import NBA_PLAYERS
        return len(NBA_PLAYERS)
    except Exception:
        return 0


def _count_mlb() -> int:
    try:
        from app.data.mlb_stats import MLB_HITTERS, MLB_PITCHERS
        return len(MLB_HITTERS) + len(MLB_PITCHERS)
    except Exception:
        return 0


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=port, reload=False)
