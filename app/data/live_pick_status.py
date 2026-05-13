"""In-flight pick monitor — show each leg's live progress vs. its line.

Auto-grade is for *finished* games. This module is for *mid-game* monitoring:
given a pick whose game is still in progress, pull the current live boxscore,
extract each leg's actual stat-so-far, and report:

  - actual stat value right now
  - amount needed to hit the line
  - projected final value at current pace
  - per-leg status: "winning" / "losing" / "tight" / "won" / "lost" / "void"
  - cash-out signal (if any leg is mathematically near-impossible)

The user can call this any time during Q3/Q4 to decide whether to cash out
or hold.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.data.live_boxscore import NBABoxGame, fetch_nba_boxscore
from app.data.pick_grader import (
    COMBO_STATS,
    _find_player,
    _stat_value,
)

log = logging.getLogger(__name__)


@dataclass
class LiveLegStatus:
    description: str
    player: str
    stat: str
    side: str
    line: float
    actual_now: float
    needed: float                    # how much more to flip the leg's side
    projected_final: float           # at current per-minute pace
    minutes_played: float
    pace_per_min: float              # stat-per-minute so far
    status: str                      # "won"|"lost"|"winning"|"losing"|"tight"|"void"
    cushion: float                   # signed: positive = on track, negative = needs to flip
    note: str = ""


@dataclass
class LivePickStatus:
    pick_id: str
    overall_status: str              # "alive"|"locked_win"|"dead"|"tight"
    cash_out_signal: str             # "hold"|"consider"|"cash_out"
    game_state: str                  # e.g. "Q3 7:42"
    box_score: str                   # "MIN 71, SAS 84"
    legs: list[LiveLegStatus]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _estimate_minutes_remaining(box: NBABoxGame, player_minutes: float) -> float:
    """Rough per-player minutes left. Quarters are 12 min in NBA."""
    quarter = max(1, min(4, box.quarter))
    # Parse remaining seconds in current quarter
    parts = (box.clock or "0:00").split(":")
    try:
        min_left = int(parts[0]) + int(parts[1]) / 60.0 if len(parts) == 2 else 0.0
    except (ValueError, IndexError):
        min_left = 0.0
    game_min_left = (4 - quarter) * 12.0 + min_left

    # A starter typically plays ~80% of remaining game minutes (capped at 12/qtr)
    # A bench guy plays maybe 40%. Heuristic: scale by their pace-so-far.
    if player_minutes >= 14:
        share = 0.78
    elif player_minutes >= 8:
        share = 0.55
    else:
        share = 0.30
    return min(game_min_left * share, game_min_left)


def live_status(pick: dict) -> LivePickStatus | None:
    """Re-pull the live boxscore for `pick.game_id` and report progress per leg."""
    game_id = pick.get("game_id") or ""
    if not game_id:
        return None
    box = fetch_nba_boxscore(game_id)
    if box is None:
        return None

    leg_statuses: list[LiveLegStatus] = []
    n_locked_wins = 0
    n_locked_losses = 0
    n_tight = 0

    for leg in (pick.get("legs") or []):
        player_name = leg.get("player", "") or ""
        team_hint = (leg.get("team") or "").upper()
        stat = (leg.get("stat", "") or "").lower()
        side = (leg.get("side", "") or "").upper()
        line = leg.get("line")

        if not player_name or not stat or line is None or side not in ("OVER", "UNDER"):
            leg_statuses.append(LiveLegStatus(
                description=leg.get("description", ""), player=player_name,
                stat=stat, side=side, line=line or 0.0,
                actual_now=0.0, needed=0.0, projected_final=0.0,
                minutes_played=0.0, pace_per_min=0.0,
                status="void", cushion=0.0,
                note="Leg missing structured fields",
            ))
            continue

        found = _find_player(box, player_name, team_hint=team_hint)
        if found is None:
            leg_statuses.append(LiveLegStatus(
                description=leg.get("description", ""), player=player_name,
                stat=stat, side=side, line=float(line),
                actual_now=0.0, needed=0.0, projected_final=0.0,
                minutes_played=0.0, pace_per_min=0.0,
                status="void", cushion=0.0,
                note=f"Could not find {player_name} in live box",
            ))
            continue

        actual = _stat_value(found, stat)
        if actual is None:
            leg_statuses.append(LiveLegStatus(
                description=leg.get("description", ""), player=player_name,
                stat=stat, side=side, line=float(line),
                actual_now=0.0, needed=0.0, projected_final=0.0,
                minutes_played=found.minutes, pace_per_min=0.0,
                status="void", cushion=0.0,
                note=f"Stat '{stat}' not recognized",
            ))
            continue

        actual_f = float(actual)
        line_f = float(line)
        mins = float(found.minutes)
        pace = (actual_f / mins) if mins > 0 else 0.0
        mins_left = _estimate_minutes_remaining(box, mins)
        projected_final = actual_f + (pace * mins_left)

        if side == "OVER":
            needed = max(0.0, line_f + 0.5 - actual_f)  # need to exceed
            cushion = actual_f - line_f
        else:
            needed = max(0.0, actual_f - line_f + 0.5)  # need to stay under
            cushion = line_f - actual_f

        # Status classification
        if box.is_final:
            status = "won" if (
                (side == "OVER" and actual_f > line_f)
                or (side == "UNDER" and actual_f < line_f)
            ) else ("push" if actual_f == line_f else "lost")
        elif side == "OVER" and actual_f > line_f:
            status = "won"  # already cleared the line
            n_locked_wins += 1
        elif side == "UNDER" and actual_f >= line_f + 1:
            # under can still push, but more than +1 past the line in basketball
            # stats (counting) means OVER hit
            status = "lost"
            n_locked_losses += 1
        elif (side == "OVER" and projected_final >= line_f * 1.1) or \
             (side == "UNDER" and projected_final <= line_f * 0.9):
            status = "winning"
        elif (side == "OVER" and projected_final < line_f * 0.85) or \
             (side == "UNDER" and projected_final > line_f * 1.15):
            status = "losing"
        else:
            status = "tight"
            n_tight += 1

        leg_statuses.append(LiveLegStatus(
            description=leg.get("description", ""),
            player=found.player,
            stat=stat, side=side, line=line_f,
            actual_now=actual_f,
            needed=round(needed, 1),
            projected_final=round(projected_final, 1),
            minutes_played=mins,
            pace_per_min=round(pace, 3),
            status=status,
            cushion=round(cushion, 1),
        ))

    total = len(leg_statuses)
    losses = sum(1 for l in leg_statuses if l.status == "lost")
    voids = sum(1 for l in leg_statuses if l.status == "void")
    losings = sum(1 for l in leg_statuses if l.status == "losing")

    if losses > 0:
        overall = "dead"
        cash = "cash_out"
    elif voids == total:
        overall = "dead"
        cash = "cash_out"
        note = "Could not resolve any legs"
    elif all(l.status == "won" for l in leg_statuses):
        overall = "locked_win"
        cash = "hold"
    elif losings + n_tight >= max(1, total - 1):
        overall = "tight"
        cash = "consider"
    else:
        overall = "alive"
        cash = "hold"

    quarter_label = "Final" if box.is_final else f"Q{box.quarter} {box.clock}"
    score = f"{box.away_team} {box.away_score}, {box.home_team} {box.home_score}"
    return LivePickStatus(
        pick_id=pick.get("id", ""),
        overall_status=overall,
        cash_out_signal=cash,
        game_state=quarter_label,
        box_score=score,
        legs=leg_statuses,
    )
