"""Monte Carlo simulator for player props.

We don't try to model every player stat with one distribution. Different
stats have different shapes:

    counting, rare         -> Poisson           (steals, blocks, HRs, SBs)
    counting, over-dispersed -> Negative Binomial (points, assists, K's)
    bounded continuous     -> truncated Normal   (minutes, yards)

The `Projection` is the model's (mean, sd, dist) for a player stat. The
simulator runs `trials` draws, counts how many land over the book line,
and returns P(over) with a tiny Laplace smoothing so we never report 0 or 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


DistName = Literal["poisson", "negbin", "normal"]


@dataclass
class Projection:
    """A player-stat projection consumable by the simulator."""
    player: str
    stat: str                 # e.g. "points", "assists", "strikeouts"
    mean: float
    sd: float
    dist: DistName = "negbin"
    floor: float = 0.0        # truncate draws below this
    ceiling: float | None = None

    def __post_init__(self) -> None:
        if self.mean < 0:
            raise ValueError("mean must be >= 0")
        if self.sd <= 0:
            raise ValueError("sd must be > 0")


def _draw(proj: Projection, trials: int, rng: np.random.Generator) -> np.ndarray:
    m, s = proj.mean, proj.sd
    if proj.dist == "poisson":
        samples = rng.poisson(lam=max(m, 1e-6), size=trials).astype(float)
    elif proj.dist == "negbin":
        # Parameterize NegBin by mean m and variance v = m + m^2/r
        v = max(s * s, m * 1.01 + 1e-6)  # must exceed mean for NegBin
        r = m * m / (v - m)
        p = r / (r + m)
        samples = rng.negative_binomial(n=max(r, 1e-6), p=p, size=trials).astype(float)
    elif proj.dist == "normal":
        samples = rng.normal(loc=m, scale=s, size=trials)
    else:
        raise ValueError(f"Unknown dist: {proj.dist}")

    samples = np.clip(samples, proj.floor, proj.ceiling if proj.ceiling is not None else np.inf)
    return samples


@dataclass
class SimResult:
    player: str
    stat: str
    line: float
    trials: int
    mean: float
    p10: float
    p50: float
    p90: float
    p_over: float
    p_under: float


def simulate_prop(
    projection: Projection,
    line: float,
    trials: int = 1000,
    seed: int | None = None,
) -> SimResult:
    """Run Monte Carlo on a single player prop.

    `line` is the sportsbook line (e.g. 24.5 points). Ties (== line) are
    split 50/50, matching sportsbook push rules for half-point lines.
    """
    if trials < 100:
        trials = 100  # the user requested 100+ runs minimum
    rng = np.random.default_rng(seed)
    draws = _draw(projection, trials, rng)

    over = float(np.mean(draws > line))
    push = float(np.mean(draws == line))
    p_over = over + 0.5 * push

    # Laplace smoothing to keep probs strictly in (0,1)
    p_over = max(min(p_over, 1.0 - 1.0 / (trials + 2)), 1.0 / (trials + 2))

    return SimResult(
        player=projection.player,
        stat=projection.stat,
        line=line,
        trials=trials,
        mean=float(np.mean(draws)),
        p10=float(np.percentile(draws, 10)),
        p50=float(np.percentile(draws, 50)),
        p90=float(np.percentile(draws, 90)),
        p_over=round(p_over, 4),
        p_under=round(1.0 - p_over, 4),
    )
