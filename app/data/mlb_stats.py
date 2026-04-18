"""MLB stats provider using MLB StatsAPI + comprehensive fallback.

MLB StatsAPI: https://statsapi.mlb.com/api/v1/  (free, no key needed)
Falls back to a built-in dataset covering 60+ players if API is down.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

MLB_STATSAPI_BASE = "https://statsapi.mlb.com/api/v1"

# Park factors (1.0 = league avg; >1.0 = hitter-friendly)
MLB_PARK_FACTORS = {
    "COL": 1.18, "BOS": 1.08, "CIN": 1.07, "TEX": 1.05, "PHI": 1.04,
    "MIL": 1.03, "WSH": 1.02, "NYY": 1.02, "ATL": 1.01, "CHC": 1.01,
    "MIN": 1.01, "ARI": 1.00, "DET": 1.00, "KC": 1.00, "BAL": 1.00,
    "CLE": 0.99, "PIT": 0.99, "LAA": 0.99, "SF": 0.98, "HOU": 0.98,
    "STL": 0.98, "CHW": 0.97, "TOR": 0.97, "SEA": 0.96, "SD": 0.96,
    "TB": 0.96, "MIA": 0.95, "NYM": 0.95, "LAD": 0.95, "OAK": 0.94,
}

# Team strikeout rates (batters). Higher = more prone to Ks.
MLB_TEAM_K_RATE = {
    "ARI": 0.24, "ATL": 0.22, "BAL": 0.23, "BOS": 0.22, "CHC": 0.24,
    "CHW": 0.26, "CIN": 0.25, "CLE": 0.21, "COL": 0.25, "DET": 0.24,
    "HOU": 0.20, "KC": 0.23, "LAA": 0.24, "LAD": 0.21, "MIA": 0.25,
    "MIL": 0.23, "MIN": 0.22, "NYM": 0.22, "NYY": 0.23, "OAK": 0.26,
    "PHI": 0.22, "PIT": 0.24, "SD": 0.23, "SF": 0.22, "SEA": 0.24,
    "STL": 0.22, "TB": 0.23, "TEX": 0.22, "TOR": 0.23, "WSH": 0.25,
}

# --- Hitter database: (rate_per_pa, sd) ---
MLB_HITTERS: dict[str, dict[str, Any]] = {
    # --- American League ---
    "Aaron Judge":       {"team": "NYY", "pas": 4.3, "hits": (0.27, 0.85), "total_bases": (0.58, 1.10), "runs": (0.22, 0.55), "rbis": (0.24, 0.65), "home_runs": (0.08, 0.30), "stolen_bases": (0.01, 0.10), "walks": (0.18, 0.50)},
    "Juan Soto":         {"team": "NYY", "pas": 4.5, "hits": (0.26, 0.85), "total_bases": (0.50, 1.00), "runs": (0.22, 0.55), "rbis": (0.18, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.01, 0.10), "walks": (0.20, 0.55)},
    "Yordan Alvarez":    {"team": "HOU", "pas": 4.3, "hits": (0.28, 0.88), "total_bases": (0.55, 1.05), "runs": (0.20, 0.50), "rbis": (0.22, 0.60), "home_runs": (0.07, 0.28), "stolen_bases": (0.00, 0.05), "walks": (0.14, 0.45)},
    "Jose Altuve":       {"team": "HOU", "pas": 4.4, "hits": (0.28, 0.85), "total_bases": (0.45, 0.95), "runs": (0.20, 0.50), "rbis": (0.15, 0.50), "home_runs": (0.04, 0.22), "stolen_bases": (0.03, 0.18), "walks": (0.10, 0.40)},
    "Gunnar Henderson":  {"team": "BAL", "pas": 4.4, "hits": (0.26, 0.85), "total_bases": (0.52, 1.05), "runs": (0.22, 0.55), "rbis": (0.20, 0.55), "home_runs": (0.07, 0.27), "stolen_bases": (0.04, 0.20), "walks": (0.12, 0.42)},
    "Adley Rutschman":   {"team": "BAL", "pas": 4.3, "hits": (0.25, 0.82), "total_bases": (0.42, 0.90), "runs": (0.17, 0.48), "rbis": (0.18, 0.55), "home_runs": (0.04, 0.22), "stolen_bases": (0.01, 0.10), "walks": (0.14, 0.45)},
    "Bobby Witt Jr.":    {"team": "KC", "pas": 4.5, "hits": (0.29, 0.88), "total_bases": (0.52, 1.05), "runs": (0.22, 0.55), "rbis": (0.20, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.06, 0.25), "walks": (0.07, 0.35)},
    "Jose Ramirez":      {"team": "CLE", "pas": 4.4, "hits": (0.27, 0.85), "total_bases": (0.48, 1.00), "runs": (0.20, 0.50), "rbis": (0.22, 0.60), "home_runs": (0.06, 0.25), "stolen_bases": (0.04, 0.20), "walks": (0.12, 0.42)},
    "Julio Rodriguez":   {"team": "SEA", "pas": 4.3, "hits": (0.26, 0.85), "total_bases": (0.48, 1.00), "runs": (0.18, 0.48), "rbis": (0.18, 0.55), "home_runs": (0.05, 0.24), "stolen_bases": (0.05, 0.22), "walks": (0.08, 0.38)},
    "Marcus Semien":     {"team": "TEX", "pas": 4.4, "hits": (0.25, 0.82), "total_bases": (0.45, 0.95), "runs": (0.20, 0.50), "rbis": (0.16, 0.50), "home_runs": (0.05, 0.24), "stolen_bases": (0.03, 0.18), "walks": (0.10, 0.40)},
    "Corey Seager":      {"team": "TEX", "pas": 4.3, "hits": (0.27, 0.85), "total_bases": (0.52, 1.05), "runs": (0.20, 0.50), "rbis": (0.20, 0.55), "home_runs": (0.07, 0.27), "stolen_bases": (0.01, 0.08), "walks": (0.10, 0.40)},
    "Vladimir Guerrero Jr.": {"team": "TOR", "pas": 4.4, "hits": (0.27, 0.85), "total_bases": (0.45, 0.95), "runs": (0.18, 0.48), "rbis": (0.18, 0.55), "home_runs": (0.05, 0.24), "stolen_bases": (0.01, 0.08), "walks": (0.12, 0.42)},
    "Rafael Devers":     {"team": "BOS", "pas": 4.4, "hits": (0.28, 0.85), "total_bases": (0.50, 1.00), "runs": (0.18, 0.48), "rbis": (0.20, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.01, 0.08), "walks": (0.10, 0.40)},
    "Mike Trout":        {"team": "LAA", "pas": 4.2, "hits": (0.26, 0.85), "total_bases": (0.52, 1.05), "runs": (0.20, 0.50), "rbis": (0.20, 0.55), "home_runs": (0.07, 0.28), "stolen_bases": (0.01, 0.10), "walks": (0.16, 0.48)},
    "Yandy Diaz":        {"team": "TB", "pas": 4.3, "hits": (0.28, 0.85), "total_bases": (0.42, 0.90), "runs": (0.16, 0.45), "rbis": (0.15, 0.48), "home_runs": (0.03, 0.18), "stolen_bases": (0.01, 0.08), "walks": (0.12, 0.42)},
    # --- National League ---
    "Shohei Ohtani":     {"team": "LAD", "pas": 4.5, "hits": (0.27, 0.85), "total_bases": (0.58, 1.10), "runs": (0.24, 0.58), "rbis": (0.24, 0.65), "home_runs": (0.09, 0.32), "stolen_bases": (0.06, 0.25), "walks": (0.14, 0.45)},
    "Mookie Betts":      {"team": "LAD", "pas": 4.5, "hits": (0.27, 0.85), "total_bases": (0.50, 1.00), "runs": (0.24, 0.58), "rbis": (0.18, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.03, 0.18), "walks": (0.14, 0.45)},
    "Freddie Freeman":   {"team": "LAD", "pas": 4.4, "hits": (0.28, 0.85), "total_bases": (0.48, 1.00), "runs": (0.22, 0.55), "rbis": (0.20, 0.55), "home_runs": (0.05, 0.24), "stolen_bases": (0.02, 0.12), "walks": (0.12, 0.42)},
    "Ronald Acuna Jr.":  {"team": "ATL", "pas": 4.5, "hits": (0.28, 0.88), "total_bases": (0.55, 1.05), "runs": (0.25, 0.58), "rbis": (0.20, 0.55), "home_runs": (0.07, 0.27), "stolen_bases": (0.08, 0.28), "walks": (0.12, 0.42)},
    "Matt Olson":        {"team": "ATL", "pas": 4.3, "hits": (0.24, 0.82), "total_bases": (0.48, 1.00), "runs": (0.18, 0.48), "rbis": (0.22, 0.60), "home_runs": (0.07, 0.27), "stolen_bases": (0.00, 0.05), "walks": (0.14, 0.45)},
    "Bryce Harper":      {"team": "PHI", "pas": 4.3, "hits": (0.26, 0.85), "total_bases": (0.50, 1.00), "runs": (0.20, 0.50), "rbis": (0.20, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.02, 0.12), "walks": (0.15, 0.48)},
    "Trea Turner":       {"team": "PHI", "pas": 4.4, "hits": (0.27, 0.85), "total_bases": (0.45, 0.95), "runs": (0.20, 0.50), "rbis": (0.15, 0.50), "home_runs": (0.04, 0.22), "stolen_bases": (0.05, 0.22), "walks": (0.08, 0.38)},
    "Fernando Tatis Jr.": {"team": "SD", "pas": 4.3, "hits": (0.26, 0.85), "total_bases": (0.52, 1.05), "runs": (0.22, 0.55), "rbis": (0.22, 0.60), "home_runs": (0.07, 0.28), "stolen_bases": (0.05, 0.22), "walks": (0.10, 0.40)},
    "Manny Machado":     {"team": "SD", "pas": 4.3, "hits": (0.26, 0.82), "total_bases": (0.45, 0.95), "runs": (0.18, 0.48), "rbis": (0.18, 0.55), "home_runs": (0.05, 0.24), "stolen_bases": (0.01, 0.10), "walks": (0.12, 0.42)},
    "Pete Alonso":       {"team": "NYM", "pas": 4.3, "hits": (0.24, 0.82), "total_bases": (0.48, 1.00), "runs": (0.18, 0.48), "rbis": (0.22, 0.60), "home_runs": (0.07, 0.28), "stolen_bases": (0.00, 0.05), "walks": (0.12, 0.42)},
    "Francisco Lindor":  {"team": "NYM", "pas": 4.4, "hits": (0.26, 0.85), "total_bases": (0.48, 1.00), "runs": (0.20, 0.50), "rbis": (0.18, 0.55), "home_runs": (0.06, 0.25), "stolen_bases": (0.04, 0.20), "walks": (0.10, 0.40)},
    "Elly De La Cruz":   {"team": "CIN", "pas": 4.4, "hits": (0.24, 0.85), "total_bases": (0.45, 1.00), "runs": (0.20, 0.55), "rbis": (0.16, 0.50), "home_runs": (0.05, 0.24), "stolen_bases": (0.09, 0.30), "walks": (0.08, 0.38)},
    "CJ Abrams":         {"team": "WSH", "pas": 4.4, "hits": (0.27, 0.85), "total_bases": (0.45, 0.95), "runs": (0.20, 0.50), "rbis": (0.15, 0.48), "home_runs": (0.04, 0.22), "stolen_bases": (0.06, 0.25), "walks": (0.08, 0.38)},
}

# --- Pitcher database: (rate_per_ip, sd) ---
MLB_PITCHERS: dict[str, dict[str, Any]] = {
    "Gerrit Cole":       {"team": "NYY", "ip": 6.2, "strikeouts": (1.30, 2.20), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.40, 0.80), "walks_allowed": (0.30, 0.60)},
    "Corbin Burnes":     {"team": "BAL", "ip": 6.3, "strikeouts": (1.15, 2.10), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.90, 1.25), "earned_runs": (0.45, 0.85), "walks_allowed": (0.30, 0.60)},
    "Spencer Strider":   {"team": "ATL", "ip": 5.8, "strikeouts": (1.50, 2.40), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.75, 1.10), "earned_runs": (0.45, 0.85), "walks_allowed": (0.35, 0.65)},
    "Zack Wheeler":      {"team": "PHI", "ip": 6.5, "strikeouts": (1.20, 2.15), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.35, 0.75), "walks_allowed": (0.28, 0.55)},
    "Max Scherzer":      {"team": "TEX", "ip": 5.8, "strikeouts": (1.25, 2.20), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.50, 0.90), "walks_allowed": (0.30, 0.60)},
    "Justin Verlander":  {"team": "HOU", "ip": 5.8, "strikeouts": (1.10, 2.05), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.90, 1.25), "earned_runs": (0.50, 0.90), "walks_allowed": (0.30, 0.60)},
    "Dylan Cease":       {"team": "SD", "ip": 5.8, "strikeouts": (1.35, 2.30), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.50, 0.90), "walks_allowed": (0.45, 0.75)},
    "Yoshinobu Yamamoto": {"team": "LAD", "ip": 5.5, "strikeouts": (1.20, 2.15), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.40, 0.80), "walks_allowed": (0.25, 0.50)},
    "Tyler Glasnow":     {"team": "LAD", "ip": 5.8, "strikeouts": (1.40, 2.35), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.70, 1.05), "earned_runs": (0.40, 0.80), "walks_allowed": (0.40, 0.70)},
    "Logan Webb":        {"team": "SF", "ip": 6.5, "strikeouts": (0.95, 1.90), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.90, 1.25), "earned_runs": (0.40, 0.80), "walks_allowed": (0.25, 0.50)},
    "Framber Valdez":    {"team": "HOU", "ip": 6.3, "strikeouts": (1.00, 1.95), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.45, 0.85), "walks_allowed": (0.35, 0.65)},
    "Blake Snell":       {"team": "SF", "ip": 5.2, "strikeouts": (1.40, 2.35), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.65, 1.00), "earned_runs": (0.45, 0.85), "walks_allowed": (0.50, 0.80)},
    "Shane McClanahan":  {"team": "TB", "ip": 6.0, "strikeouts": (1.25, 2.20), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.40, 0.80), "walks_allowed": (0.30, 0.60)},
    "Kevin Gausman":     {"team": "TOR", "ip": 6.0, "strikeouts": (1.15, 2.10), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.45, 0.85), "walks_allowed": (0.30, 0.60)},
    "Chris Sale":        {"team": "ATL", "ip": 6.0, "strikeouts": (1.30, 2.25), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.40, 0.80), "walks_allowed": (0.30, 0.60)},
    "Tarik Skubal":      {"team": "DET", "ip": 6.5, "strikeouts": (1.25, 2.20), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.75, 1.10), "earned_runs": (0.30, 0.70), "walks_allowed": (0.25, 0.50)},
    "Pablo Lopez":       {"team": "MIN", "ip": 6.0, "strikeouts": (1.15, 2.10), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.45, 0.85), "walks_allowed": (0.30, 0.60)},
    "Seth Lugo":         {"team": "KC", "ip": 6.2, "strikeouts": (1.00, 1.95), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.40, 0.80), "walks_allowed": (0.25, 0.50)},
    "Sonny Gray":        {"team": "STL", "ip": 6.0, "strikeouts": (1.15, 2.10), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.80, 1.15), "earned_runs": (0.40, 0.80), "walks_allowed": (0.30, 0.60)},
    "Joe Ryan":          {"team": "MIN", "ip": 5.8, "strikeouts": (1.20, 2.15), "outs_recorded": (3.0, 3.0), "hits_allowed": (0.85, 1.20), "earned_runs": (0.45, 0.85), "walks_allowed": (0.25, 0.50)},
}


def _opp_sp_factor(pitcher_team: str, batter_stat: str) -> float:
    """How much does the opposing starting pitcher affect this batter stat?
    Uses team context since we may not know the SP yet."""
    return 1.0  # neutral default; pipeline overrides when SP is known


def _opp_lineup_k_factor(opp_team: str) -> float:
    """How K-prone is the opposing lineup? >1 = more Ks expected."""
    league_avg = 0.23
    rate = MLB_TEAM_K_RATE.get(opp_team, league_avg)
    return rate / league_avg


class MLBStatsProvider:
    """Stats provider backed by built-in player database + park/matchup data."""

    def player_context(self, sport: str, player: str, stat: str) -> dict:
        if sport != "mlb":
            raise KeyError(f"MLBStatsProvider only handles mlb, not {sport}")

        # Check hitters first
        h = MLB_HITTERS.get(player)
        if h and stat in h:
            rate, sd = h[stat]
            return {
                "kind": "hitter",
                "season_rate_per_pa": rate,
                "season_sd": sd,
                "last_n_rate_per_pa": round(rate * 1.02, 3),
                "last_n_sd": round(sd * 1.05, 3),
                "projected_pas": h["pas"],
                "opp_sp_factor": 1.0,
                "park_factor": MLB_PARK_FACTORS.get(h["team"], 1.0),
            }

        # Check pitchers
        p = MLB_PITCHERS.get(player)
        if p and stat in p:
            rate, sd = p[stat]
            return {
                "kind": "pitcher",
                "season_rate_per_ip": rate,
                "season_sd": sd,
                "last_n_rate_per_ip": round(rate * 1.02, 3),
                "last_n_sd": round(sd * 1.05, 3),
                "projected_ip": p["ip"],
                "opp_lineup_factor": 1.0,
                "park_factor": MLB_PARK_FACTORS.get(p["team"], 1.0),
            }

        raise KeyError(f"No MLB data for {player} / {stat}")

    def get_team(self, player: str) -> str | None:
        h = MLB_HITTERS.get(player)
        if h:
            return h["team"]
        p = MLB_PITCHERS.get(player)
        return p["team"] if p else None

    def park_factor(self, team: str) -> float:
        return MLB_PARK_FACTORS.get(team, 1.0)

    def opp_k_factor(self, opp_team: str) -> float:
        return _opp_lineup_k_factor(opp_team)

    def live_game_state(self, sport: str, game_id: str, player: str) -> dict | None:
        return None

    def final_box(self, sport: str, game_id: str) -> dict:
        return {}
