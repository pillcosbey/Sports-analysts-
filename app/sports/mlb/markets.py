"""MLB prop market definitions and their recommended distributions."""

from __future__ import annotations

MLB_MARKETS = {
    # Hitter props
    "hits":            {"dist": "poisson", "floor": 0, "side": "hitter"},
    "total_bases":     {"dist": "negbin",  "floor": 0, "side": "hitter"},
    "runs":            {"dist": "poisson", "floor": 0, "side": "hitter"},
    "rbis":            {"dist": "poisson", "floor": 0, "side": "hitter"},
    "home_runs":       {"dist": "poisson", "floor": 0, "side": "hitter"},
    "stolen_bases":    {"dist": "poisson", "floor": 0, "side": "hitter"},
    "walks":           {"dist": "poisson", "floor": 0, "side": "hitter"},
    # Pitcher props
    "strikeouts":      {"dist": "negbin",  "floor": 0, "side": "pitcher"},
    "outs_recorded":   {"dist": "negbin",  "floor": 0, "side": "pitcher"},
    "hits_allowed":    {"dist": "poisson", "floor": 0, "side": "pitcher"},
    "earned_runs":     {"dist": "poisson", "floor": 0, "side": "pitcher"},
    "walks_allowed":   {"dist": "poisson", "floor": 0, "side": "pitcher"},
}

MLB_REG_INNINGS = 9
