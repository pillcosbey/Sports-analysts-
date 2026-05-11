"""Auto-backtest: replay the halftime projection against a finished game.

Given a finished NBA game's ESPN id, fetch the summary, reconstruct the
halftime per-player box from play-by-play, run the halftime projection
model on it, and compare each projection to the player's actual
second-half result.

Returns a per-player report (predicted 2H mean, actual 2H value, hit/miss
for the implied O/U line) plus aggregate metrics (% calls correct,
average miss magnitude per stat).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.data.live_boxscore import _parse_nba_summary, NBABoxGame, NBABoxPlayer
from app.data.play_by_play import fetch_summary, halftime_box_from_summary
from app.sports.halftime_projection import (
    NBA_HALFTIME_STATS,
    _stat_value,
    project_nba_halftime,
)


@dataclass
class BacktestLeg:
    player: str
    team: str
    stat: str
    halftime: float
    projected_2h: float          # what the model said the 2H would be
    actual_2h: float             # what actually happened in the 2H
    projected_total: float       # halftime + projected_2h
    actual_total: float          # halftime + actual_2h
    line: float                  # the O/U line the model would have set
    model_side: str              # "OVER" or "UNDER" — whichever side has model edge vs line
    call_correct: bool           # did the actual 2H value land on the side the model favored
    error: float                 # actual_2h - projected_2h


@dataclass
class BacktestReport:
    game_id: str
    away_team: str
    home_team: str
    halftime: str
    final: str
    legs: list[BacktestLeg]
    accuracy_by_stat: dict[str, dict[str, float]]
    overall_accuracy: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "halftime": self.halftime,
            "final": self.final,
            "accuracy_by_stat": self.accuracy_by_stat,
            "overall_accuracy": self.overall_accuracy,
            "legs": [asdict(l) for l in self.legs],
        }


def _find(box: NBABoxGame, name: str) -> NBABoxPlayer | None:
    for p in box.players:
        if p.player.lower() == name.lower():
            return p
    return None


def backtest_game(game_id: str) -> BacktestReport | None:
    """Run a halftime backtest on a finished NBA game."""
    summary = fetch_summary(game_id)
    if summary is None:
        return None

    ht_box = halftime_box_from_summary(summary, espn_game_id=game_id)
    if ht_box is None or not ht_box.players:
        return None

    try:
        final_box = _parse_nba_summary(summary, game_id)
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    if not final_box.is_final:
        return None

    halftime_proj = project_nba_halftime(ht_box)

    legs: list[BacktestLeg] = []
    for proj_leg in halftime_proj.legs:
        # Find the player's *final* stats to compute actual 2H value
        final_p = _find(final_box, proj_leg.player)
        if final_p is None:
            continue
        actual_total = float(_stat_value(final_p, proj_leg.stat))
        actual_2h = actual_total - proj_leg.so_far
        # The model line was set at the rounded second_half mean; over/under
        # is decided by which side the model thinks is more likely.
        # We use p_over from the simulator: >= 0.5 → OVER bias.
        model_side = "OVER" if proj_leg.p_over >= 0.5 else "UNDER"
        if model_side == "OVER":
            call_correct = actual_2h > proj_leg.line
        else:
            call_correct = actual_2h < proj_leg.line
        legs.append(BacktestLeg(
            player=proj_leg.player,
            team=proj_leg.team,
            stat=proj_leg.stat,
            halftime=proj_leg.so_far,
            projected_2h=proj_leg.second_half,
            actual_2h=round(actual_2h, 1),
            projected_total=proj_leg.projection,
            actual_total=actual_total,
            line=proj_leg.line,
            model_side=model_side,
            call_correct=call_correct,
            error=round(actual_2h - proj_leg.second_half, 1),
        ))

    # Aggregate accuracy
    by_stat: dict[str, dict[str, Any]] = {s: {"n": 0, "correct": 0, "err_sum": 0.0} for s in NBA_HALFTIME_STATS}
    for l in legs:
        b = by_stat.setdefault(l.stat, {"n": 0, "correct": 0, "err_sum": 0.0})
        b["n"] += 1
        b["err_sum"] += abs(l.error)
        if l.call_correct:
            b["correct"] += 1
    accuracy_by_stat: dict[str, dict[str, float]] = {}
    for s, b in by_stat.items():
        if b["n"] == 0:
            continue
        accuracy_by_stat[s] = {
            "n": b["n"],
            "hit_pct": round(100.0 * b["correct"] / b["n"], 1),
            "avg_abs_error": round(b["err_sum"] / b["n"], 2),
        }

    n_total = sum(b["n"] for b in by_stat.values())
    n_correct = sum(b["correct"] for b in by_stat.values())
    overall = round(100.0 * n_correct / n_total, 1) if n_total else 0.0

    return BacktestReport(
        game_id=game_id,
        away_team=final_box.away_team,
        home_team=final_box.home_team,
        halftime=f"{ht_box.away_team} {ht_box.away_score}, {ht_box.home_team} {ht_box.home_score}",
        final=f"{final_box.away_team} {final_box.away_score}, {final_box.home_team} {final_box.home_score}",
        legs=legs,
        accuracy_by_stat=accuracy_by_stat,
        overall_accuracy=overall,
    )
