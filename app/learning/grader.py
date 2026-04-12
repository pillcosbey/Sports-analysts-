"""Post-game grading: compare each pick against final-game actuals."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.data.store import (
    insert_residual, mark_graded, ungraded_picks,
)


def grade_pick(pick: dict, actual: float) -> dict:
    """Grade one pick. Returns an update dict for logging."""
    line = float(pick["line"])
    side = pick["side"]
    if side == "OVER":
        won = actual > line
    elif side == "UNDER":
        won = actual < line
    else:
        raise ValueError(f"Unknown side: {side}")

    residual = float(pick["projected_mean"]) - actual
    insert_residual({
        "pick_id": pick["id"],
        "sport": pick["sport"],
        "stat": pick["stat"],
        "projected": pick["projected_mean"],
        "actual": actual,
        "residual": residual,
        "phase": pick["phase"],
    })
    mark_graded(pick["id"], won)
    return {
        "pick_id": pick["id"],
        "player": pick["player"],
        "stat": pick["stat"],
        "line": line,
        "side": side,
        "actual": actual,
        "won": won,
        "residual": residual,
        "graded_at": datetime.utcnow().isoformat(),
    }


def grade_batch(actuals_by_key: dict[tuple[str, str, str], float]) -> list[dict]:
    """Grade all ungraded picks that have an actual available.

    `actuals_by_key` maps (sport, player, stat) -> final actual value.
    """
    results: list[dict] = []
    for pick in ungraded_picks():
        key = (pick["sport"], pick["player"], pick["stat"])
        if key in actuals_by_key:
            results.append(grade_pick(pick, actuals_by_key[key]))
    return results
