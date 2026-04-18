"""Historical backtest engine.

Runs the full pipeline against past game data to measure model accuracy
before trusting it with real stakes. Outputs:
  - overall win rate
  - ROI (flat-bet and Kelly-weighted)
  - calibration chart data (predicted P(over) vs actual hit rate in bins)
  - per-stat and per-sport breakdown

Usage:
    from app.backtest.engine import run_backtest, generate_synthetic_history
    history = generate_synthetic_history(n_games=200)
    report = run_backtest(history)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.math_utils import edge_and_kelly, devig_two_way, american_to_decimal
from app.core.simulator import Projection, simulate_prop


@dataclass
class HistoricalGame:
    sport: str
    player: str
    stat: str
    line: float
    over_odds: int
    under_odds: int
    actual: float             # what actually happened
    proj_mean: float          # what the model projected
    proj_sd: float
    dist: str = "negbin"


@dataclass
class BacktestReport:
    total_games: int
    picks_made: int           # games where edge > threshold
    wins: int
    losses: int
    pushes: int
    win_rate: float
    flat_roi_pct: float       # ROI if flat-betting $100 on every pick
    kelly_roi_pct: float      # ROI using Kelly-weighted stakes
    mean_edge_pct: float
    calibration: list[dict]   # [{bin, predicted, actual, count}]
    by_sport: dict[str, dict[str, Any]]
    by_stat: dict[str, dict[str, Any]]


def run_backtest(
    history: list[HistoricalGame],
    min_edge_pct: float = 3.0,
    kelly_cap: float = 0.25,
    sim_trials: int = 1000,
    seed: int = 42,
) -> BacktestReport:
    """Run the model against a historical dataset and measure performance."""
    rng = np.random.default_rng(seed)

    picks_made = 0
    wins = 0
    losses = 0
    pushes = 0
    flat_pnl = 0.0
    kelly_pnl = 0.0
    kelly_bankroll = 1000.0
    edges: list[float] = []
    predicted_probs: list[float] = []
    actual_outcomes: list[int] = []  # 1 = over hit, 0 = under hit

    by_sport: dict[str, dict[str, Any]] = {}
    by_stat: dict[str, dict[str, Any]] = {}

    for game in history:
        proj = Projection(
            player=game.player, stat=game.stat,
            mean=game.proj_mean, sd=game.proj_sd, dist=game.dist,
        )
        sim = simulate_prop(proj, game.line, trials=sim_trials, seed=int(rng.integers(1_000_000)))
        edge = edge_and_kelly(
            model_p_over=sim.p_over,
            over_odds=game.over_odds,
            under_odds=game.under_odds,
            kelly_fraction_cap=kelly_cap,
            min_edge_pct=min_edge_pct,
        )
        if edge is None:
            continue

        picks_made += 1
        edges.append(edge.edge_pct)

        side = edge.side
        predicted_probs.append(edge.model_prob)

        did_hit_over = game.actual > game.line
        actual_outcomes.append(1 if did_hit_over else 0)

        if side == "OVER":
            won = game.actual > game.line
        else:
            won = game.actual < game.line

        if game.actual == game.line:
            pushes += 1
            continue

        dec_odds = american_to_decimal(game.over_odds if side == "OVER" else game.under_odds)
        stake_pct = edge.recommended_stake_pct / 100.0

        if won:
            wins += 1
            flat_pnl += (dec_odds - 1) * 100
            kelly_pnl += kelly_bankroll * stake_pct * (dec_odds - 1)
        else:
            losses += 1
            flat_pnl -= 100
            kelly_pnl -= kelly_bankroll * stake_pct

        # Update sport/stat trackers
        for key_dict, key_val in [(by_sport, game.sport), (by_stat, game.stat)]:
            entry = key_dict.setdefault(key_val, {"w": 0, "l": 0, "pnl": 0.0})
            if won:
                entry["w"] += 1
                entry["pnl"] += (dec_odds - 1) * 100
            else:
                entry["l"] += 1
                entry["pnl"] -= 100

    total_decided = wins + losses
    flat_invested = total_decided * 100 if total_decided > 0 else 1

    # Calibration bins
    calibration = _calibrate(predicted_probs, actual_outcomes)

    return BacktestReport(
        total_games=len(history),
        picks_made=picks_made,
        wins=wins,
        losses=losses,
        pushes=pushes,
        win_rate=round(wins / max(total_decided, 1), 4),
        flat_roi_pct=round(flat_pnl / flat_invested * 100, 2),
        kelly_roi_pct=round(kelly_pnl / 1000.0 * 100, 2),
        mean_edge_pct=round(float(np.mean(edges)) if edges else 0.0, 2),
        calibration=calibration,
        by_sport={k: {**v, "wr": round(v["w"] / max(v["w"] + v["l"], 1), 3)} for k, v in by_sport.items()},
        by_stat={k: {**v, "wr": round(v["w"] / max(v["w"] + v["l"], 1), 3)} for k, v in by_stat.items()},
    )


def _calibrate(predicted: list[float], actual: list[int], n_bins: int = 10) -> list[dict]:
    if not predicted:
        return []
    bins = np.linspace(0, 1, n_bins + 1)
    result = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = [(lo <= p < hi) for p in predicted]
        n = sum(mask)
        if n == 0:
            continue
        avg_pred = float(np.mean([p for p, m in zip(predicted, mask) if m]))
        avg_actual = float(np.mean([a for a, m in zip(actual, mask) if m]))
        result.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "predicted": round(avg_pred, 3),
            "actual": round(avg_actual, 3),
            "count": n,
        })
    return result


def generate_synthetic_history(
    n_games: int = 200,
    seed: int = 123,
) -> list[HistoricalGame]:
    """Generate realistic synthetic game history for backtesting.

    Uses player stat distributions to simulate both projections and actuals
    with realistic noise so the backtest measures the model's edge detection.
    """
    rng = np.random.default_rng(seed)

    players_nba = [
        ("Luka Doncic", "points", 33.5, 8.0, 32.5),
        ("Jayson Tatum", "points", 27.0, 7.0, 26.5),
        ("Nikola Jokic", "assists", 9.0, 3.0, 8.5),
        ("Shai Gilgeous-Alexander", "points", 31.5, 6.5, 30.5),
        ("Giannis Antetokounmpo", "rebounds", 11.5, 3.5, 11.5),
        ("Stephen Curry", "threes_made", 4.5, 2.2, 4.5),
        ("Anthony Edwards", "points", 25.5, 6.5, 25.5),
        ("LeBron James", "assists", 8.0, 3.0, 7.5),
    ]

    players_mlb = [
        ("Aaron Judge", "total_bases", 2.5, 1.1, 1.5),
        ("Gerrit Cole", "strikeouts", 8.0, 2.2, 7.5),
        ("Shohei Ohtani", "hits", 1.2, 0.85, 0.5),
        ("Bobby Witt Jr.", "stolen_bases", 0.26, 0.45, 0.5),
        ("Corbin Burnes", "strikeouts", 7.0, 2.1, 6.5),
    ]

    history: list[HistoricalGame] = []

    for _ in range(n_games):
        if rng.random() < 0.55:
            name, stat, mean, sd, line = players_nba[rng.integers(len(players_nba))]
            sport = "nba"
            dist = "negbin"
        else:
            name, stat, mean, sd, line = players_mlb[rng.integers(len(players_mlb))]
            sport = "mlb"
            dist = "poisson" if stat in ("stolen_bases", "hits", "home_runs") else "negbin"

        # Actual outcome: draw from a slightly different distribution (reality ≠ model)
        noise = rng.normal(0, sd * 0.15)
        actual_mean = mean + noise
        if dist == "poisson":
            actual = float(rng.poisson(max(actual_mean, 0.1)))
        elif dist == "negbin":
            v = max(sd * sd, actual_mean * 1.01 + 0.01)
            r = actual_mean ** 2 / (v - actual_mean) if v > actual_mean else 10
            p = r / (r + actual_mean) if (r + actual_mean) > 0 else 0.5
            actual = float(rng.negative_binomial(max(r, 0.1), min(max(p, 0.01), 0.99)))
        else:
            actual = float(max(0, rng.normal(actual_mean, sd)))

        over_odds = rng.choice([-115, -110, -120, -105, +100])
        under_odds = rng.choice([-105, -110, -100, -115, +100])

        history.append(HistoricalGame(
            sport=sport, player=name, stat=stat,
            line=line, over_odds=int(over_odds), under_odds=int(under_odds),
            actual=round(actual, 1), proj_mean=mean, proj_sd=sd, dist=dist,
        ))

    return history
