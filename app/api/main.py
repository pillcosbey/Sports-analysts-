"""FastAPI backend. Serves the web UI and JSON endpoints.

Run:
    uvicorn app.api.main:app --reload
or:
    python -m app.api.main
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import build_board

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Sports Prop Research", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/board")
def board(
    sport: str = Query("nba", pattern="^(nba|mlb)$"),
    phase: str = Query("pregame", pattern="^(pregame|live)$"),
):
    cards = build_board(sport, phase=phase)
    return JSONResponse({"sport": sport, "phase": phase, "cards": cards})


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    """Show which providers are active so the frontend can display a badge."""
    return {
        "odds_provider": "live" if os.environ.get("ODDS_API_KEY", "").strip() else "mock",
        "stats_provider": "mock",
        "ai_enabled": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=8000, reload=False)
