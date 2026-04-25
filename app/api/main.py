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


@app.get("/api/player/{player_name}/shooting")
def player_shooting(player_name: str):
    """Deterministic shooting profile derived from the player's season means.

    We don't have real play-by-play archives wired up, so we back out a
    plausible shot chart from points / threes_made / minutes using stable
    per-player seeded efficiencies.
    """
    import hashlib
    from app.data.nba_stats import NBA_PLAYERS

    if player_name not in NBA_PLAYERS:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)

    p = NBA_PLAYERS[player_name]
    pts = p["points"][0]
    three_pm = p["threes_made"][0]
    minutes = p.get("min", 28.0)

    # Stable seeds from name so the profile doesn't flicker between refreshes.
    seed = int(hashlib.md5(player_name.encode()).hexdigest()[:8], 16)

    def jitter(base: float, spread: float, offset: int) -> float:
        frac = ((seed >> (offset * 3)) & 0xFF) / 255.0  # 0..1
        return base + (frac - 0.5) * 2 * spread

    three_pct = max(0.25, min(0.45, jitter(0.355, 0.06, 0)))
    two_pct = max(0.42, min(0.62, jitter(0.515, 0.05, 1)))
    ft_pct = max(0.55, min(0.95, jitter(0.78, 0.12, 2)))
    ft_rate = max(0.10, min(0.40, jitter(0.22, 0.08, 3)))  # FTA per FGA

    three_pa = three_pm / three_pct if three_pct > 0 else 0.0
    # points from 3s + 2s + FTs  =>  2*2PM + 3*3PM + FTM = pts
    # solve for 2PM assuming FTM/FGA ≈ ft_rate * ft_pct.
    # Use iteration: assume FGA ≈ 3PA + 2PA. Start with 2PA guess.
    two_pa = max(1.0, (pts - 3 * three_pm) / max(0.6, 2 * two_pct))
    fga = two_pa + three_pa
    fta = fga * ft_rate
    ftm = fta * ft_pct
    # re-solve 2PM to balance points exactly
    two_pm_needed = max(0.0, (pts - 3 * three_pm - ftm) / 2)
    two_pa = max(two_pm_needed / two_pct, 0.5) if two_pct > 0 else 0.0
    two_pm = two_pa * two_pct
    fga = two_pa + three_pa
    fgm = two_pm + three_pm
    fg_pct = fgm / fga if fga > 0 else 0.0
    efg_pct = (fgm + 0.5 * three_pm) / fga if fga > 0 else 0.0
    ts_pct = pts / (2 * (fga + 0.44 * fta)) if (fga + fta) > 0 else 0.0

    # Zone breakdown — again, deterministic shares.
    rim_share = max(0.15, min(0.55, jitter(0.35, 0.1, 4)))   # at-rim
    mid_share = max(0.10, min(0.35, jitter(0.18, 0.06, 5)))  # mid-range
    three_share = three_pa / fga if fga > 0 else 0.0
    # normalize so rim + mid + three ≈ 1
    remaining = max(0.0, 1 - three_share)
    total_2 = rim_share + mid_share
    if total_2 > 0:
        rim_share = rim_share / total_2 * remaining
        mid_share = mid_share / total_2 * remaining

    return {
        "player": player_name,
        "team": p["team"],
        "minutes": round(minutes, 1),
        "fg": {"made": round(fgm, 1), "att": round(fga, 1), "pct": round(fg_pct * 100, 1)},
        "three": {"made": round(three_pm, 1), "att": round(three_pa, 1), "pct": round(three_pct * 100, 1)},
        "ft": {"made": round(ftm, 1), "att": round(fta, 1), "pct": round(ft_pct * 100, 1)},
        "ts_pct": round(ts_pct * 100, 1),
        "efg_pct": round(efg_pct * 100, 1),
        "zones": [
            {"name": "At Rim", "share": round(rim_share * 100, 1), "pct": round(min(0.75, two_pct + 0.12) * 100, 1)},
            {"name": "Mid-Range", "share": round(mid_share * 100, 1), "pct": round(max(0.30, two_pct - 0.08) * 100, 1)},
            {"name": "3-Point", "share": round(three_share * 100, 1), "pct": round(three_pct * 100, 1)},
        ],
    }


@app.get("/api/player/{player_name}/similar")
def player_similar(player_name: str, n: int = Query(6, ge=1, le=10)):
    """Players with the closest stat profile (Euclidean distance on normalized means)."""
    from app.data.nba_stats import NBA_PLAYERS, NBA_TEAM_NAMES

    if player_name not in NBA_PLAYERS:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)

    keys = ("points", "rebounds", "assists", "threes_made", "steals", "blocks")

    # League-wide scales for normalization so no stat dominates the distance.
    scales = {}
    for k in keys:
        vals = [pl[k][0] for pl in NBA_PLAYERS.values() if isinstance(pl.get(k), tuple)]
        scales[k] = max(vals) if vals else 1.0

    def vec(p):
        return [p[k][0] / scales[k] for k in keys]

    base = vec(NBA_PLAYERS[player_name])

    distances = []
    for name, p in NBA_PLAYERS.items():
        if name == player_name:
            continue
        v = vec(p)
        d2 = sum((a - b) ** 2 for a, b in zip(base, v))
        distances.append((d2, name, p))

    distances.sort(key=lambda x: x[0])
    results = []
    for d2, name, p in distances[:n]:
        sim_pct = max(0, round((1 - min(1.0, d2 ** 0.5 / 1.5)) * 100))
        results.append({
            "name": name,
            "team": p["team"],
            "team_name": NBA_TEAM_NAMES.get(p["team"], p["team"]),
            "points": p["points"][0],
            "rebounds": p["rebounds"][0],
            "assists": p["assists"][0],
            "threes_made": p["threes_made"][0],
            "similarity": sim_pct,
        })
    return {"player": player_name, "similar": results}


@app.get("/api/player/{player_name}/types")
def player_types(player_name: str):
    """Summary across all prop types available for this player."""
    from app.data.gamelog import build_nba_gamelog
    from app.data.nba_stats import NBA_PLAYERS, COMBO_STATS

    if player_name not in NBA_PLAYERS:
        return JSONResponse({"error": f"Player not found: {player_name}"}, status_code=404)

    p = NBA_PLAYERS[player_name]
    stat_keys = [k for k in ("points", "rebounds", "assists", "threes_made", "steals", "blocks") if k in p]
    stat_keys += list(COMBO_STATS.keys())

    out = []
    for stat in stat_keys:
        try:
            g = build_nba_gamelog(player_name, stat, n_games=12)
        except KeyError:
            continue
        out.append({
            "stat": stat,
            "season_avg": g["season_avg"],
            "graph_avg": g["graph_avg"],
            "line": g["line"],
            "hit_rate": g["hit_rate"],
            "hits": g["hits"],
            "games": g["games_played"],
        })
    # sort by hit rate desc so the best-performing markets float to the top
    out.sort(key=lambda r: r["hit_rate"], reverse=True)
    return {"player": player_name, "team": p["team"], "types": out}


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
