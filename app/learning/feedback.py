"""Feedback loop: use graded residuals to tune projection weights.

Simple approach: compute the mean residual per (sport, stat). If the
projection is systematically high, shrink the mean. If systematically
low, bump it. Over time, the blend weights in projection.DEFAULT_WEIGHTS
are nudged toward whichever signal (season / recent / matchup) is
predicting best.

For a real production system you'd replace this with ridge regression or
gradient boosting over a richer feature set. This is the hook where that
plugs in.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev

from app.data.store import residuals_for


@dataclass
class BiasReport:
    sport: str
    stat: str
    n: int
    mean_residual: float        # >0 = projection too high
    std_residual: float
    suggested_mean_adjust: float   # multiplicative factor to apply to new projections
    suggested_sd_scale: float


def analyze_bias(sport: str, stat: str) -> BiasReport | None:
    res = residuals_for(sport, stat)
    if len(res) < 10:
        return None
    m = mean(res)
    s = pstdev(res) if len(res) > 1 else 1.0

    # If the model is biased high by X units on a stat with average Y,
    # shrink the multiplier. We apply a gentle 50% correction to avoid
    # oscillation.
    #
    # This is a hook — replace with a proper regression.
    adjust = 1.0 - 0.5 * (m / max(s, 1e-6)) * 0.01
    adjust = max(0.9, min(1.1, adjust))  # clamp
    sd_scale = 1.0 + 0.2 * max(0.0, (s - 1.0))  # widen SD if residuals noisy
    sd_scale = max(0.9, min(1.3, sd_scale))
    return BiasReport(
        sport=sport, stat=stat, n=len(res),
        mean_residual=round(m, 3), std_residual=round(s, 3),
        suggested_mean_adjust=round(adjust, 4),
        suggested_sd_scale=round(sd_scale, 4),
    )


def apply_bias(projection_mean: float, report: BiasReport | None) -> float:
    if report is None:
        return projection_mean
    return projection_mean * report.suggested_mean_adjust
