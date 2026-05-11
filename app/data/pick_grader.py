"""Auto-grader — settle a Claude pick against the final ESPN box score.

Given a pick's `game_id` and its legs (player + stat + side + line), this
fetches the final NBA box from ESPN, looks up each player's stat, and
returns the leg outcomes (won/lost/push) plus an overall pick status.

Player-name matching is case-insensitive and tolerates "Last" / "F. Last"
forms (handy for parsed bet365 slips that abbreviate first names).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.data.box_score import fetch_final_box
from app.data.live_boxscore import NBABoxGame, NBABoxPlayer

log = logging.getLogger(__name__)


COMBO_STATS = {
    "pra": ("points", "rebounds", "assists"),
    "pr":  ("points", "rebounds"),
    "pa":  ("points", "assists"),
    "ra":  ("rebounds", "assists"),
}


def _stat_value(p: NBABoxPlayer, stat: str) -> float | None:
    """Return the player's value for `stat`, summing components for combo stats."""
    if stat in COMBO_STATS:
        return float(sum(getattr(p, c, 0) for c in COMBO_STATS[stat]))
    if hasattr(p, stat):
        return float(getattr(p, stat))
    aliases = {
        "threes": "threes_made", "3pm": "threes_made", "3s": "threes_made",
        "stl": "steals", "blk": "blocks",
        "pts": "points", "reb": "rebounds", "ast": "assists",
    }
    s = aliases.get(stat.lower())
    return float(getattr(p, s)) if s and hasattr(p, s) else None


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _find_player(box: NBABoxGame, name: str) -> NBABoxPlayer | None:
    """Match by full name first, then by last name, then by initial+last."""
    n = _normalize_name(name)
    if not n:
        return None
    # Exact normalized match
    for p in box.players:
        if _normalize_name(p.player) == n:
            return p
    # Last-name only
    parts = name.split()
    if not parts:
        return None
    last = _normalize_name(parts[-1])
    candidates = [p for p in box.players if _normalize_name(p.player).endswith(last)]
    if len(candidates) == 1:
        return candidates[0]
    # First-initial + last (e.g. "K.Johnson" → matches "Keldon Johnson")
    if len(parts) >= 2 and len(parts[0]) <= 2:
        first_initial = _normalize_name(parts[0])[:1]
        narrowed = [
            p for p in candidates
            if _normalize_name(p.player).startswith(first_initial)
        ]
        if len(narrowed) == 1:
            return narrowed[0]
    return None


@dataclass
class LegOutcome:
    description: str
    player: str
    stat: str
    side: str
    line: float | None
    actual: float | None
    status: str             # "won" | "lost" | "push" | "void"
    note: str = ""


@dataclass
class PickGrade:
    pick_id: str
    overall: str            # "won" | "lost" | "push" | "void"
    legs: list[LegOutcome]
    game_final: bool
    box_score: str          # short summary like "MIN 114, SAS 109"


def grade_leg(leg: dict, box: NBABoxGame) -> LegOutcome:
    desc = leg.get("description", "")
    player = leg.get("player", "") or ""
    stat = (leg.get("stat", "") or "").lower()
    side = (leg.get("side", "") or "").upper()
    line = leg.get("line")

    if not player or not stat or line is None or side not in ("OVER", "UNDER"):
        return LegOutcome(
            description=desc, player=player, stat=stat, side=side,
            line=line, actual=None, status="void",
            note="Leg is missing structured fields (player/stat/side/line)",
        )

    found = _find_player(box, player)
    if found is None:
        return LegOutcome(
            description=desc, player=player, stat=stat, side=side,
            line=line, actual=None, status="void",
            note=f"Could not find {player} in box score",
        )

    actual = _stat_value(found, stat)
    if actual is None:
        return LegOutcome(
            description=desc, player=player, stat=stat, side=side,
            line=line, actual=None, status="void",
            note=f"Stat '{stat}' not recognized",
        )

    line_f = float(line)
    if actual == line_f:
        status = "push"
    elif (side == "OVER" and actual > line_f) or (side == "UNDER" and actual < line_f):
        status = "won"
    else:
        status = "lost"

    return LegOutcome(
        description=desc, player=found.player, stat=stat, side=side,
        line=line_f, actual=actual, status=status,
    )


def grade_pick(pick: dict, box: NBABoxGame) -> PickGrade:
    """Grade a Pick dict against a final NBABoxGame.

    Parlay rules: any leg LOST → pick LOST. All WON → pick WON.
    Any leg PUSH (with rest won) → pick WON at reduced odds, but we
    simplify to PUSH for the parlay's status; the user can manually
    override if their book pushes the leg out of the parlay.
    Any leg VOID → return overall VOID with a note (manual review).
    """
    leg_outcomes = [grade_leg(l, box) for l in (pick.get("legs") or [])]

    if any(l.status == "void" for l in leg_outcomes):
        overall = "void"
    elif any(l.status == "lost" for l in leg_outcomes):
        overall = "lost"
    elif any(l.status == "push" for l in leg_outcomes):
        overall = "push"
    else:
        overall = "won"

    score = f"{box.away_team} {box.away_score}, {box.home_team} {box.home_score}"
    return PickGrade(
        pick_id=pick.get("id", ""),
        overall=overall,
        legs=leg_outcomes,
        game_final=box.is_final,
        box_score=score,
    )


def fetch_and_grade(pick: dict) -> PickGrade | None:
    """One-shot: fetch the box (from any available source), grade.

    Uses `game_id` first (ESPN), falls back to (`game_date`, `home_team`,
    `away_team`) via balldontlie. Returns None only if every source fails.
    """
    box = fetch_final_box(
        espn_game_id=pick.get("game_id") or None,
        game_date=pick.get("game_date") or None,
        home_team=pick.get("home_team") or None,
        away_team=pick.get("away_team") or None,
    )
    if box is None:
        return None
    return grade_pick(pick, box)
