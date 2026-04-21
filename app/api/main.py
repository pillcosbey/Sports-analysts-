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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import build_board
from app.core.math_utils import american_to_decimal

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Sports Prop Research", version="0.2.0")
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
    # MLB live is disabled — only pregame research is offered for baseball.
    if sport == "mlb" and phase == "live":
        return JSONResponse(
            {"error": "MLB live research is disabled. Use pregame for baseball."},
            status_code=400,
        )
    # NBA live is only open when a playoff game is at halftime.
    if sport == "nba" and phase == "live":
        from app.data.live_scores import LiveScoresFeed
        from app.data.nba_stats import NBA_PLAYOFF_TEAMS

        try:
            games = LiveScoresFeed().nba_scoreboard()
        except Exception:  # pragma: no cover
            games = []
        halftime = any(
            g.is_halftime
            and g.home_team in NBA_PLAYOFF_TEAMS
            and g.away_team in NBA_PLAYOFF_TEAMS
            for g in games
        )
        if not halftime:
            return JSONResponse(
                {
                    "sport": sport,
                    "phase": phase,
                    "cards": [],
                    "gated": True,
                    "message": "NBA Live research opens at halftime of playoff games.",
                }
            )

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


# ---------- Player game log (PropsMadness-style graph) ----------

@app.get("/api/player/{player_name}/gamelog")
def player_gamelog(
    player_name: str,
    stat: str = Query("points"),
    line: Optional[float] = Query(None),
    n: int = Query(12, ge=4, le=20),
):
    """Recent game-by-game log for a player/stat used by the graph view.

    Only NBA is supported for now (playoffs-in-progress). Response includes
    season avg, graph avg, hit rate vs the line, and per-game bars.
    """
    from app.data.gamelog import build_nba_gamelog
    from app.data.nba_stats import NBA_PLAYERS

    if player_name not in NBA_PLAYERS:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)

    p = NBA_PLAYERS[player_name]
    if stat not in p and stat not in ("pra", "pr", "pa", "ra"):
        return JSONResponse({"error": f"Stat '{stat}' not available for {player_name}"}, status_code=400)

    try:
        return build_nba_gamelog(player_name, stat, line=line, n_games=n)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/player/{player_name}/teammates")
def player_teammates(
    player_name: str,
    stat: str = Query("points"),
    n: int = Query(6, ge=1, le=10),
):
    """Teammates of the given NBA player for the 'Suggested' strip in the graph modal."""
    from app.data.nba_stats import NBA_PLAYERS, COMBO_STATS

    if player_name not in NBA_PLAYERS:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)
    team = NBA_PLAYERS[player_name]["team"]

    def mean_for(p: dict, s: str) -> Optional[float]:
        if s in COMBO_STATS:
            try:
                return sum(p[c][0] for c in COMBO_STATS[s])
            except KeyError:
                return None
        v = p.get(s)
        if isinstance(v, tuple):
            return v[0]
        return None

    mates = []
    for name, p in NBA_PLAYERS.items():
        if name == player_name or p["team"] != team:
            continue
        m = mean_for(p, stat)
        if m is None:
            continue
        mates.append({"name": name, "team": team, "mean": round(m, 1)})

    mates.sort(key=lambda x: x["mean"], reverse=True)
    return {"player": player_name, "team": team, "stat": stat, "teammates": mates[:n]}


# ---------- Playoffs ----------

@app.get("/api/playoffs/nba")
def nba_playoffs():
    """Current NBA playoff bracket with team rosters."""
    from app.data.nba_stats import (
        NBA_PLAYOFF_BRACKET,
        NBA_PLAYOFF_TEAMS,
        NBA_TEAM_NAMES,
        NBA_PLAYERS,
    )

    teams = {}
    for team, meta in NBA_PLAYOFF_TEAMS.items():
        roster = sorted([name for name, p in NBA_PLAYERS.items() if p["team"] == team])
        teams[team] = {
            "name": NBA_TEAM_NAMES.get(team, team),
            "seed": meta["seed"],
            "conference": meta["conference"],
            "opp": meta["opp"],
            "series": meta["series"],
            "roster": roster,
        }
    return {"bracket": NBA_PLAYOFF_BRACKET, "teams": teams}


@app.get("/api/nba/live_availability")
def nba_live_availability():
    """NBA Live research is only available during halftime of a playoff game.

    Returns { available, games: [...] } where each game has teams/score/clock.
    If there's no live playoff halftime, the UI hides the NBA Live tab.
    """
    from app.data.live_scores import LiveScoresFeed
    from app.data.nba_stats import NBA_PLAYOFF_TEAMS

    try:
        feed = LiveScoresFeed()
        games = feed.nba_scoreboard()
    except Exception:  # pragma: no cover - network failure
        games = []

    halftime_games = [
        g for g in games
        if g.is_halftime
        and g.home_team in NBA_PLAYOFF_TEAMS
        and g.away_team in NBA_PLAYOFF_TEAMS
    ]
    return {
        "available": bool(halftime_games),
        "games": [
            {
                "game_id": g.game_id,
                "home": g.home_team,
                "away": g.away_team,
                "score": f"{g.away_score}-{g.home_score}",
                "series": NBA_PLAYOFF_TEAMS[g.home_team]["series"],
            }
            for g in halftime_games
        ],
    }


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
