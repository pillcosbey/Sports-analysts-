"""Auto-grading scheduler: runs after games end, grades picks, updates weights.

Usage:
    python -m app.learning.scheduler          # one-shot grade
    python -m app.learning.scheduler --loop   # poll every 30 minutes
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

from app.data.live_scores import LiveScoresFeed
from app.data.store import ungraded_picks
from app.learning.grader import grade_pick
from app.learning.feedback import analyze_bias

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _collect_nba_finals(feed: LiveScoresFeed) -> dict[tuple[str, str, str], float]:
    """Pull final box scores for completed NBA games."""
    actuals: dict[tuple, float] = {}
    games = feed.nba_scoreboard()
    for game in games:
        if not game.is_final:
            continue
        for p in game.players:
            for stat_name in ("points", "rebounds", "assists", "threes_made", "steals", "blocks"):
                val = getattr(p, stat_name, None)
                if val is not None:
                    actuals[("nba", p.player, stat_name)] = float(val)
            actuals[("nba", p.player, "pra")] = float(p.pra)
    return actuals


def _collect_mlb_finals(feed: LiveScoresFeed) -> dict[tuple[str, str, str], float]:
    """Pull final box scores for completed MLB games."""
    actuals: dict[tuple, float] = {}
    schedule = feed.mlb_schedule_today()
    for entry in schedule:
        if "Final" not in entry.get("status", ""):
            continue
        game = feed.mlb_live_game(entry["game_id"])
        if game is None or not game.is_final:
            continue
        for p in game.players:
            if p.is_pitcher:
                for stat_name in ("strikeouts", "outs_recorded", "hits_allowed", "earned_runs", "walks_allowed"):
                    actuals[("mlb", p.player, stat_name)] = float(getattr(p, stat_name, 0))
            else:
                for stat_name in ("hits", "total_bases", "runs", "rbis", "home_runs", "walks", "stolen_bases"):
                    actuals[("mlb", p.player, stat_name)] = float(getattr(p, stat_name, 0))
    return actuals


def grade_all() -> list[dict]:
    """Grade all ungraded picks against available final results."""
    feed = LiveScoresFeed()
    actuals = {}
    actuals.update(_collect_nba_finals(feed))
    actuals.update(_collect_mlb_finals(feed))

    if not actuals:
        log.info("No final game data available to grade against.")
        return []

    pending = ungraded_picks()
    if not pending:
        log.info("No ungraded picks to process.")
        return []

    results = []
    for pick in pending:
        key = (pick["sport"], pick["player"], pick["stat"])
        if key in actuals:
            result = grade_pick(pick, actuals[key])
            emoji = "W" if result["won"] else "L"
            log.info(
                "%s %s %s %s line=%.1f actual=%.1f residual=%.2f",
                emoji, pick["player"], pick["stat"], pick["side"],
                pick["line"], actuals[key], result["residual"],
            )
            results.append(result)

    log.info("Graded %d / %d pending picks.", len(results), len(pending))

    # Run bias analysis for stats that just got graded
    graded_combos = {(r["stat"],) for r in results}
    for (stat,) in graded_combos:
        for sport in ("nba", "mlb"):
            report = analyze_bias(sport, stat)
            if report:
                log.info(
                    "Bias %s/%s: n=%d mean_res=%.2f adjust=%.4f",
                    sport, stat, report.n, report.mean_residual, report.suggested_mean_adjust,
                )

    return results


def run_loop(interval_minutes: int = 30) -> None:
    """Continuously poll and grade until interrupted."""
    log.info("Starting grading loop (every %d minutes). Ctrl+C to stop.", interval_minutes)
    while True:
        try:
            grade_all()
        except Exception:
            log.exception("Grading cycle failed")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade picks against final box scores")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=30, help="Minutes between runs (with --loop)")
    args = parser.parse_args()

    if args.loop:
        run_loop(args.interval)
    else:
        results = grade_all()
        print(f"Graded {len(results)} picks.")
