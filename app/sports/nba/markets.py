"""NBA prop market definitions and their recommended distributions."""

from __future__ import annotations

# Markets the system prices. Each entry maps to the simulator distribution
# that fits the stat's shape best.
NBA_MARKETS = {
    "points":         {"dist": "negbin",  "floor": 0},
    "rebounds":       {"dist": "negbin",  "floor": 0},
    "assists":        {"dist": "negbin",  "floor": 0},
    "threes_made":    {"dist": "poisson", "floor": 0},
    "steals":         {"dist": "poisson", "floor": 0},
    "blocks":         {"dist": "poisson", "floor": 0},
    "pra":            {"dist": "negbin",  "floor": 0},   # points+rebounds+assists
    "pr":             {"dist": "negbin",  "floor": 0},
    "pa":             {"dist": "negbin",  "floor": 0},
    "ra":             {"dist": "negbin",  "floor": 0},
}

NBA_GAME_MINUTES = 48.0
NBA_HALFTIME_MINUTES = 24.0
