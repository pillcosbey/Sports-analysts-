"""FastAPI backend for the Halftime Parlay Analyzer.

This used to host a full pregame research board (NBA + MLB props, parlay
builder, backtest). That surface was retired — this app's job now is:

  1. Pull live box-scores from ESPN (NBA) and MLB StatsAPI mid-game,
  2. Project second-half / remaining-innings stat lines per player,
  3. Suggest +EV bet-builder combos for the current game,
  4. Let the user log placed bets — manually or via a Claude-Vision parse
     of a bet365 screenshot — and roll those into real ROI.

Run:
    uvicorn app.api.main:app --reload
or:
    python -m app.api.main
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

from fastapi import Body, FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.math_utils import american_to_decimal

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="PropEdge Halftime Parlay Analyzer",
    version="0.3.0",
    description="Live halftime / in-game projections, +EV parlay builder suggestions, and an AI-parsed bet log.",
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


# ---------- Halftime / In-game analyzer ----------

@app.get("/api/halftime/games")
def halftime_games(sport: str = Query("nba", pattern="^(nba|mlb)$")):
    """Return a list of games eligible for halftime / mid-game analysis."""
    from app.data.live_scores import LiveScoresFeed

    feed = LiveScoresFeed()
    if sport == "nba":
        try:
            games = feed.nba_scoreboard()
        except Exception:
            games = []
        out = []
        for g in games:
            eligible = g.is_halftime or (g.quarter == 2) or (g.quarter == 3 and g.clock != "0:00")
            if not eligible:
                continue
            out.append({
                "game_id": g.game_id,
                "home": g.home_team,
                "away": g.away_team,
                "home_score": g.home_score,
                "away_score": g.away_score,
                "quarter": g.quarter,
                "clock": g.clock,
                "is_halftime": g.is_halftime,
            })
        return {"sport": "nba", "games": out}

    # MLB — anything in-progress and past the 4th inning
    sched = feed.mlb_schedule_today()
    out = []
    for g in sched:
        status = (g.get("status") or "").lower()
        if "progress" not in status and "in progress" not in status:
            continue
        out.append({
            "game_id": g.get("game_id", ""),
            "home": g.get("home", ""),
            "away": g.get("away", ""),
            "status": g.get("status", ""),
        })
    return {"sport": "mlb", "games": out}


@app.get("/api/halftime/nba/{game_id}")
def halftime_nba(game_id: str):
    """Halftime projection for one NBA game."""
    from app.data.live_boxscore import fetch_nba_boxscore
    from app.sports.halftime_projection import project_nba_halftime

    box = fetch_nba_boxscore(game_id)
    if box is None:
        return JSONResponse({"error": "Could not fetch live box score"}, status_code=502)

    ht = project_nba_halftime(box)
    return {
        "game_id": ht.game_id,
        "home_team": ht.home_team,
        "away_team": ht.away_team,
        "home_team_name": box.home_team_name,
        "away_team_name": box.away_team_name,
        "home_score": ht.home_score,
        "away_score": ht.away_score,
        "quarter": ht.quarter,
        "clock": ht.clock,
        "is_halftime": ht.is_halftime,
        "home_quarters": box.home_quarters,
        "away_quarters": box.away_quarters,
        "pace_factor": ht.pace_factor,
        "legs": [asdict(l) for l in ht.legs],
    }


@app.get("/api/halftime/mlb/{game_id}")
def halftime_mlb(game_id: str):
    """Mid-game projection for one MLB game (5th inning onward)."""
    from app.data.live_scores import LiveScoresFeed

    g = LiveScoresFeed().mlb_live_game(game_id)
    if g is None:
        return JSONResponse({"error": "Could not fetch MLB live feed"}, status_code=502)

    # Lightweight in-game view — we expose what the user can see in
    # the bet365 in-play menu (current hitter/pitcher splits). Full
    # remaining-innings projection is a follow-up.
    return {
        "game_id": g.game_id,
        "home_team": g.home_team,
        "away_team": g.away_team,
        "inning": g.inning,
        "is_top": g.is_top,
        "home_score": g.home_score,
        "away_score": g.away_score,
        "is_final": g.is_final,
        "players": [asdict(p) for p in g.players],
    }


# ---------- Suggested bet builder ----------

@app.post("/api/builder/suggest")
def suggest_builder(
    body: dict = Body(...),
):
    """Given a list of halftime legs (from /api/halftime/...), return the
    best +EV 2/3/4-leg combos sorted by correlated EV.

    Request body:
      {
        "sport": "nba",
        "game_id": "...",
        "legs": [
          {"player": "...", "team": "...", "stat": "points", "side": "OVER",
           "line": 11.5, "model_prob": 0.62, "american_odds": -110,
           "decimal_odds": 1.91},
          ...
        ],
        "sizes": [2, 3, 4],   // optional
        "min_leg_prob": 0.55,  // optional
        "min_ev": 0.0,         // optional
        "top_k": 6             // optional
      }
    """
    from app.core.builder import CandidateLeg, suggest_builders

    sport = body.get("sport", "nba")
    game_id = body.get("game_id", "")
    raw_legs = body.get("legs") or []
    if not raw_legs:
        return JSONResponse({"error": "legs is required"}, status_code=400)

    candidates: list[CandidateLeg] = []
    for l in raw_legs:
        try:
            american = int(l.get("american_odds", -110))
            decimal = float(l.get("decimal_odds") or american_to_decimal(american))
            candidates.append(CandidateLeg(
                player=l["player"],
                team=l.get("team", ""),
                stat=l["stat"],
                side=l["side"],
                line=float(l["line"]),
                model_prob=float(l["model_prob"]),
                american_odds=american,
                decimal_odds=decimal,
                game_id=game_id,
                sport=sport,
            ))
        except (KeyError, ValueError, TypeError) as e:
            return JSONResponse({"error": f"Invalid leg: {e}"}, status_code=400)

    sizes = tuple(body.get("sizes") or (2, 3, 4))
    suggestions = suggest_builders(
        candidates,
        sizes=sizes,
        min_leg_prob=float(body.get("min_leg_prob", 0.55)),
        min_ev=float(body.get("min_ev", 0.0)),
        top_k=int(body.get("top_k", 6)),
    )
    return {
        "sport": sport,
        "game_id": game_id,
        "suggestions": [
            {
                "size": len(s.legs),
                "naive_prob": s.naive_prob,
                "correlated_prob": s.correlated_prob,
                "combined_decimal_odds": s.combined_decimal_odds,
                "combined_american": s.combined_american,
                "ev_per_dollar": s.ev_per_dollar,
                "legs": [
                    {
                        "player": l.player,
                        "team": l.team,
                        "stat": l.stat,
                        "side": l.side,
                        "line": l.line,
                        "model_prob": l.model_prob,
                        "american_odds": l.american_odds,
                    }
                    for l in s.legs
                ],
            }
            for s in suggestions
        ],
    }


# ---------- Parlay pricer (kept for ad-hoc pricing) ----------

@app.post("/api/parlay")
def build_parlay_endpoint(legs: list[dict] = Body(...)):
    """Price an ad-hoc parlay. Each leg: {player, stat, side, model_prob, game_id, sport, odds}."""
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


# ---------- Bet log ----------

@app.get("/api/bets")
def list_bets():
    from app.data.bet_log import BetStore
    store = BetStore()
    return {"bets": store.all(), "stats": store.stats()}


@app.get("/api/bets/stats")
def bet_stats():
    from app.data.bet_log import BetStore
    return BetStore().stats()


@app.post("/api/bets")
def add_bet(body: dict = Body(...)):
    """Manually add a bet.

    Body: {sport, book, stake, american_odds, legs:[{description,player,stat,side,line,status}], note}
    """
    from app.data.bet_log import BetLeg, BetStore, make_bet

    try:
        legs = [BetLeg(**l) for l in (body.get("legs") or [])]
        bet = make_bet(
            sport=body.get("sport", "other"),
            book=body.get("book", "bet365"),
            stake=float(body["stake"]),
            american_odds=int(body.get("american_odds") or 0) or None,
            legs=legs,
            source="manual",
            note=body.get("note", ""),
        )
    except (KeyError, ValueError, TypeError) as e:
        return JSONResponse({"error": f"Invalid bet: {e}"}, status_code=400)

    return BetStore().add(bet)


@app.post("/api/bets/upload")
async def upload_bet(image: UploadFile = File(...), note: str = Form("")):
    """Parse a bet-slip screenshot via Claude Vision and log it."""
    from app.data.bet_log import BetLeg, BetStore, make_bet
    from app.data.bet_parser import parse_bet_screenshot

    try:
        image_bytes = await image.read()
    except Exception as e:
        return JSONResponse({"error": f"Could not read image: {e}"}, status_code=400)
    if not image_bytes:
        return JSONResponse({"error": "Empty image"}, status_code=400)

    media_type = image.content_type or "image/png"
    try:
        parsed = parse_bet_screenshot(image_bytes, media_type=media_type)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    legs = [BetLeg(**{
        "description": l.get("description", ""),
        "player": l.get("player", ""),
        "stat": l.get("stat", ""),
        "side": l.get("side", ""),
        "line": l.get("line"),
        "status": l.get("status", "open"),
    }) for l in (parsed.get("legs") or [])]

    odds = parsed.get("american_odds")
    try:
        odds_int = int(odds) if odds is not None else None
    except (TypeError, ValueError):
        odds_int = None

    bet = make_bet(
        sport=parsed.get("sport", "other"),
        book=parsed.get("book", "other"),
        stake=float(parsed.get("stake", 0) or 0),
        american_odds=odds_int,
        legs=legs,
        source="image",
        note=note,
    )
    bet.status = parsed.get("status", "open")
    bet.returned = float(parsed.get("returned", 0) or 0)
    return BetStore().add(bet)


@app.post("/api/bets/{bet_id}/settle")
def settle_bet(bet_id: str, body: dict = Body(...)):
    """Mark a logged bet as won/lost/push/void."""
    from app.data.bet_log import BetStore

    status = body.get("status")
    if status not in ("won", "lost", "push", "void", "open"):
        return JSONResponse({"error": "status must be won/lost/push/void/open"}, status_code=400)
    returned = body.get("returned")
    returned_f = float(returned) if returned is not None else None
    res = BetStore().update_status(bet_id, status, returned=returned_f)
    if res is None:
        return JSONResponse({"error": "Bet not found"}, status_code=404)
    return res


@app.delete("/api/bets/{bet_id}")
def delete_bet(bet_id: str):
    from app.data.bet_log import BetStore
    ok = BetStore().delete(bet_id)
    if not ok:
        return JSONResponse({"error": "Bet not found"}, status_code=404)
    return {"deleted": bet_id}


# ---------- Claude pick log ----------

@app.get("/api/picks")
def list_picks():
    """Every parlay Claude has suggested + W/L track record."""
    from app.data.pick_log import PickStore
    store = PickStore()
    return {"picks": store.all(), "stats": store.stats()}


@app.get("/api/picks/stats")
def pick_stats():
    from app.data.pick_log import PickStore
    return PickStore().stats()


@app.post("/api/picks")
def add_pick(body: dict = Body(...)):
    """Log a Claude-suggested parlay.

    Body:
      {
        "sport": "nba",
        "game_id": "401705234",
        "confidence": "high",       // optional
        "rationale": "Pace running 1.18x, ...",
        "american_odds": 650,        // combined parlay odds
        "model_prob": 0.18,
        "ev_per_dollar": 0.34,
        "legs": [
          {"description":"Player X Over 21.5 Points",
           "player":"X","team":"BOS","stat":"points","side":"OVER",
           "line":21.5,"model_prob":0.62,"american_odds":-110},
          ...
        ]
      }
    """
    from app.data.pick_log import PickLeg, PickStore, make_pick

    try:
        legs_in = body.get("legs") or []
        if not legs_in:
            return JSONResponse({"error": "legs is required"}, status_code=400)
        legs = [PickLeg(**{
            "description": l.get("description", ""),
            "player": l.get("player", ""),
            "team": l.get("team", ""),
            "stat": l.get("stat", ""),
            "side": l.get("side", ""),
            "line": l.get("line"),
            "model_prob": l.get("model_prob"),
            "american_odds": l.get("american_odds"),
            "status": l.get("status", "open"),
        }) for l in legs_in]

        odds = body.get("american_odds")
        odds_int = int(odds) if odds is not None else None
        pick = make_pick(
            sport=body.get("sport", "other"),
            legs=legs,
            american_odds=odds_int,
            model_prob=body.get("model_prob"),
            ev_per_dollar=body.get("ev_per_dollar"),
            rationale=body.get("rationale", ""),
            confidence=body.get("confidence", "medium"),
            game_id=body.get("game_id", ""),
            source=body.get("source", "claude"),
        )
    except (KeyError, ValueError, TypeError) as e:
        return JSONResponse({"error": f"Invalid pick: {e}"}, status_code=400)

    return PickStore().add(pick)


@app.post("/api/picks/{pick_id}/settle")
def settle_pick(pick_id: str, body: dict = Body(...)):
    """Mark a logged pick as won/lost/push/void."""
    from app.data.pick_log import PickStore

    status = body.get("status")
    if status not in ("won", "lost", "push", "void", "open"):
        return JSONResponse({"error": "status must be won/lost/push/void/open"}, status_code=400)
    res = PickStore().update_status(pick_id, status)
    if res is None:
        return JSONResponse({"error": "Pick not found"}, status_code=404)
    return res


@app.post("/api/picks/{pick_id}/promote")
def promote_pick(pick_id: str, body: dict = Body(...)):
    """Copy a Claude pick into the real Bets log at a chosen stake.

    Body: {"stake": 10, "book": "bet365"}  (both optional)
    """
    from app.data.bet_log import BetLeg, BetStore, make_bet
    from app.data.pick_log import PickStore

    picks = PickStore()
    pick = picks.get(pick_id)
    if pick is None:
        return JSONResponse({"error": "Pick not found"}, status_code=404)
    if pick.get("promoted_to_bet_id"):
        return JSONResponse({"error": "Already promoted", "bet_id": pick["promoted_to_bet_id"]}, status_code=409)

    stake = float(body.get("stake", 10))
    book = body.get("book", "bet365")
    legs = [BetLeg(
        description=l.get("description", ""),
        player=l.get("player", ""),
        stat=l.get("stat", ""),
        side=l.get("side", ""),
        line=l.get("line"),
        status="open",
    ) for l in pick.get("legs", [])]

    bet = make_bet(
        sport=pick.get("sport", "other"),
        book=book,
        stake=stake,
        american_odds=pick.get("american_odds"),
        legs=legs,
        source="claude_promoted",
        note=f"From pick {pick_id}",
    )
    stored = BetStore().add(bet)
    picks.set_promoted(pick_id, stored["id"])
    return {"pick_id": pick_id, "bet": stored}


@app.delete("/api/picks/{pick_id}")
def delete_pick(pick_id: str):
    from app.data.pick_log import PickStore
    ok = PickStore().delete(pick_id)
    if not ok:
        return JSONResponse({"error": "Pick not found"}, status_code=404)
    return {"deleted": pick_id}


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
        "halftime_provider": "espn",
        "vision_enabled": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=port, reload=False)
