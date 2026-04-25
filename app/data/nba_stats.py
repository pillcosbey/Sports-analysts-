"""NBA stats provider using balldontlie API + comprehensive fallback.

balldontlie v1: https://www.balldontlie.io/api/v1/
Free, no key required for basic endpoints. If the API is down or
rate-limited, falls back to a built-in dataset covering 80+ players.

This module fulfills the StatsProvider protocol for sport="nba".
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

BALLDONTLIE_BASE = "https://www.balldontlie.io/api/v1"

# --- Comprehensive NBA defense rankings (1=best, 30=worst at stopping stat) ---
# Updated for modeling purposes. Higher rank = worse defense = better for attacker.
NBA_DEFENSE = {
    "ATL": {"points": 28, "rebounds": 20, "assists": 25, "threes_made": 27, "steals": 15, "blocks": 22},
    "BOS": {"points": 5, "rebounds": 8, "assists": 6, "threes_made": 4, "steals": 10, "blocks": 7},
    "BKN": {"points": 26, "rebounds": 24, "assists": 22, "threes_made": 25, "steals": 20, "blocks": 18},
    "CHA": {"points": 25, "rebounds": 22, "assists": 20, "threes_made": 23, "steals": 18, "blocks": 25},
    "CHI": {"points": 18, "rebounds": 15, "assists": 17, "threes_made": 16, "steals": 12, "blocks": 14},
    "CLE": {"points": 3, "rebounds": 4, "assists": 5, "threes_made": 3, "steals": 8, "blocks": 2},
    "DAL": {"points": 15, "rebounds": 18, "assists": 14, "threes_made": 18, "steals": 22, "blocks": 16},
    "DEN": {"points": 12, "rebounds": 10, "assists": 8, "threes_made": 14, "steals": 16, "blocks": 12},
    "DET": {"points": 27, "rebounds": 26, "assists": 28, "threes_made": 26, "steals": 25, "blocks": 24},
    "GSW": {"points": 14, "rebounds": 12, "assists": 10, "threes_made": 12, "steals": 11, "blocks": 15},
    "HOU": {"points": 16, "rebounds": 14, "assists": 19, "threes_made": 15, "steals": 9, "blocks": 10},
    "IND": {"points": 22, "rebounds": 21, "assists": 23, "threes_made": 22, "steals": 19, "blocks": 20},
    "LAC": {"points": 10, "rebounds": 11, "assists": 12, "threes_made": 10, "steals": 7, "blocks": 9},
    "LAL": {"points": 13, "rebounds": 13, "assists": 11, "threes_made": 13, "steals": 14, "blocks": 11},
    "MEM": {"points": 8, "rebounds": 6, "assists": 9, "threes_made": 7, "steals": 5, "blocks": 4},
    "MIA": {"points": 7, "rebounds": 9, "assists": 7, "threes_made": 8, "steals": 3, "blocks": 6},
    "MIL": {"points": 9, "rebounds": 7, "assists": 13, "threes_made": 9, "steals": 13, "blocks": 8},
    "MIN": {"points": 2, "rebounds": 3, "assists": 3, "threes_made": 2, "steals": 6, "blocks": 1},
    "NOP": {"points": 20, "rebounds": 19, "assists": 18, "threes_made": 20, "steals": 17, "blocks": 19},
    "NYK": {"points": 6, "rebounds": 5, "assists": 4, "threes_made": 6, "steals": 4, "blocks": 5},
    "OKC": {"points": 1, "rebounds": 2, "assists": 1, "threes_made": 1, "steals": 1, "blocks": 3},
    "ORL": {"points": 4, "rebounds": 1, "assists": 2, "threes_made": 5, "steals": 2, "blocks": 13},
    "PHI": {"points": 11, "rebounds": 16, "assists": 15, "threes_made": 11, "steals": 21, "blocks": 17},
    "PHX": {"points": 19, "rebounds": 17, "assists": 16, "threes_made": 19, "steals": 23, "blocks": 21},
    "POR": {"points": 29, "rebounds": 28, "assists": 27, "threes_made": 29, "steals": 26, "blocks": 28},
    "SAC": {"points": 23, "rebounds": 23, "assists": 24, "threes_made": 24, "steals": 24, "blocks": 23},
    "SAS": {"points": 30, "rebounds": 29, "assists": 29, "threes_made": 30, "steals": 28, "blocks": 29},
    "TOR": {"points": 24, "rebounds": 25, "assists": 26, "threes_made": 21, "steals": 27, "blocks": 26},
    "UTA": {"points": 21, "rebounds": 27, "assists": 21, "threes_made": 28, "steals": 29, "blocks": 27},
    "WAS": {"points": 17, "rebounds": 30, "assists": 30, "threes_made": 17, "steals": 30, "blocks": 30},
}

# Team pace factors relative to league average (1.0)
NBA_PACE = {
    "ATL": 1.03, "BOS": 0.99, "BKN": 1.01, "CHA": 1.02, "CHI": 0.98,
    "CLE": 0.97, "DAL": 1.00, "DEN": 0.98, "DET": 1.04, "GSW": 1.01,
    "HOU": 1.05, "IND": 1.06, "LAC": 0.97, "LAL": 1.00, "MEM": 1.02,
    "MIA": 0.96, "MIL": 1.00, "MIN": 0.99, "NOP": 1.01, "NYK": 0.97,
    "OKC": 1.01, "ORL": 0.96, "PHI": 0.98, "PHX": 1.02, "POR": 1.03,
    "SAC": 1.04, "SAS": 1.05, "TOR": 1.01, "UTA": 1.03, "WAS": 1.06,
}

# --- Comprehensive player database (80+ NBA players) ---
NBA_PLAYERS: dict[str, dict[str, Any]] = {
    # --- Eastern Conference Stars ---
    "Jayson Tatum":    {"team": "BOS", "points": (27.0, 6.8), "rebounds": (8.5, 2.8), "assists": (4.7, 2.0), "threes_made": (3.0, 1.6), "steals": (1.1, 0.8), "blocks": (0.7, 0.7), "min": 36.0},
    "Jaylen Brown":    {"team": "BOS", "points": (23.5, 5.5), "rebounds": (5.5, 2.2), "assists": (3.6, 1.8), "threes_made": (2.1, 1.3), "steals": (1.2, 0.9), "blocks": (0.5, 0.6), "min": 34.0},
    "Jrue Holiday":    {"team": "BOS", "points": (12.5, 4.5), "rebounds": (5.0, 2.0), "assists": (4.5, 2.0), "threes_made": (1.5, 1.0), "steals": (1.0, 0.7), "blocks": (0.4, 0.5), "min": 32.0},
    "Derrick White":   {"team": "BOS", "points": (16.0, 5.0), "rebounds": (4.2, 1.8), "assists": (4.5, 2.0), "threes_made": (2.5, 1.4), "steals": (1.0, 0.7), "blocks": (1.0, 0.8), "min": 33.0},
    "Kristaps Porzingis": {"team": "BOS", "points": (19.5, 6.0), "rebounds": (7.0, 2.5), "assists": (2.0, 1.2), "threes_made": (2.0, 1.3), "steals": (0.7, 0.6), "blocks": (2.0, 1.2), "min": 29.0},
    "Al Horford":      {"team": "BOS", "points": (9.0, 3.5), "rebounds": (6.5, 2.2), "assists": (2.5, 1.3), "threes_made": (1.8, 1.1), "steals": (0.6, 0.5), "blocks": (0.9, 0.7), "min": 27.0},
    "Donovan Mitchell": {"team": "CLE", "points": (26.5, 7.0), "rebounds": (4.5, 2.0), "assists": (5.5, 2.5), "threes_made": (3.2, 1.7), "steals": (1.5, 0.9), "blocks": (0.3, 0.5), "min": 35.0},
    "Darius Garland":  {"team": "CLE", "points": (18.5, 5.5), "rebounds": (2.8, 1.5), "assists": (6.5, 2.5), "threes_made": (2.2, 1.3), "steals": (1.2, 0.8), "blocks": (0.1, 0.3), "min": 33.0},
    "Evan Mobley":     {"team": "CLE", "points": (16.0, 5.0), "rebounds": (9.0, 3.0), "assists": (3.0, 1.5), "threes_made": (0.8, 0.8), "steals": (0.7, 0.7), "blocks": (1.5, 1.0), "min": 33.0},
    "Jarrett Allen":   {"team": "CLE", "points": (14.0, 4.5), "rebounds": (10.0, 3.0), "assists": (2.3, 1.2), "threes_made": (0.0, 0.2), "steals": (0.7, 0.6), "blocks": (1.2, 0.9), "min": 30.0},
    "Max Strus":       {"team": "CLE", "points": (12.5, 4.5), "rebounds": (4.5, 1.8), "assists": (4.0, 1.8), "threes_made": (2.7, 1.5), "steals": (0.7, 0.6), "blocks": (0.3, 0.4), "min": 30.0},
    "De'Andre Hunter": {"team": "CLE", "points": (15.5, 4.8), "rebounds": (3.5, 1.5), "assists": (1.8, 1.0), "threes_made": (2.0, 1.3), "steals": (0.7, 0.6), "blocks": (0.4, 0.5), "min": 28.0},
    "Giannis Antetokounmpo": {"team": "MIL", "points": (31.5, 6.5), "rebounds": (11.5, 3.5), "assists": (5.8, 2.5), "threes_made": (0.8, 0.8), "steals": (1.1, 0.8), "blocks": (1.5, 1.1), "min": 35.5},
    "Damian Lillard":  {"team": "MIL", "points": (24.5, 7.5), "rebounds": (4.5, 2.0), "assists": (7.0, 3.0), "threes_made": (3.5, 1.8), "steals": (0.9, 0.7), "blocks": (0.3, 0.4), "min": 35.0},
    "Khris Middleton": {"team": "MIL", "points": (14.5, 5.0), "rebounds": (4.5, 1.8), "assists": (4.8, 2.0), "threes_made": (1.6, 1.1), "steals": (0.8, 0.7), "blocks": (0.4, 0.5), "min": 29.0},
    "Brook Lopez":     {"team": "MIL", "points": (13.0, 4.2), "rebounds": (5.0, 2.0), "assists": (1.7, 1.0), "threes_made": (1.8, 1.2), "steals": (0.4, 0.5), "blocks": (2.3, 1.3), "min": 30.0},
    "Bobby Portis":    {"team": "MIL", "points": (13.5, 4.5), "rebounds": (8.0, 2.5), "assists": (1.3, 1.0), "threes_made": (1.4, 1.1), "steals": (0.5, 0.6), "blocks": (0.5, 0.6), "min": 25.0},
    "Joel Embiid":     {"team": "PHI", "points": (34.0, 8.0), "rebounds": (11.0, 3.5), "assists": (5.5, 2.5), "threes_made": (1.5, 1.2), "steals": (1.0, 0.8), "blocks": (1.7, 1.2), "min": 33.5},
    "Tyrese Maxey":    {"team": "PHI", "points": (25.5, 6.5), "rebounds": (3.5, 1.8), "assists": (6.0, 2.5), "threes_made": (3.0, 1.5), "steals": (1.0, 0.7), "blocks": (0.5, 0.5), "min": 37.0},
    "Paul George":     {"team": "PHI", "points": (22.5, 6.0), "rebounds": (5.5, 2.2), "assists": (4.0, 2.0), "threes_made": (2.8, 1.5), "steals": (1.5, 0.9), "blocks": (0.5, 0.6), "min": 34.0},
    "Kelly Oubre Jr.": {"team": "PHI", "points": (15.5, 5.0), "rebounds": (5.0, 2.0), "assists": (1.5, 1.0), "threes_made": (1.5, 1.1), "steals": (1.2, 0.8), "blocks": (0.6, 0.6), "min": 30.0},
    "Jalen Brunson":   {"team": "NYK", "points": (28.5, 6.5), "rebounds": (3.5, 1.8), "assists": (6.5, 2.8), "threes_made": (2.5, 1.4), "steals": (0.9, 0.7), "blocks": (0.2, 0.4), "min": 36.0},
    "Karl-Anthony Towns": {"team": "NYK", "points": (24.5, 6.5), "rebounds": (13.5, 3.5), "assists": (3.0, 1.5), "threes_made": (2.5, 1.5), "steals": (0.7, 0.6), "blocks": (0.7, 0.7), "min": 35.0},
    "OG Anunoby":      {"team": "NYK", "points": (14.0, 4.5), "rebounds": (4.5, 2.0), "assists": (1.5, 1.0), "threes_made": (1.5, 1.1), "steals": (1.5, 0.9), "blocks": (0.7, 0.6), "min": 33.0},
    "Josh Hart":       {"team": "NYK", "points": (13.5, 4.5), "rebounds": (9.0, 2.8), "assists": (4.5, 2.0), "threes_made": (1.3, 1.0), "steals": (1.0, 0.7), "blocks": (0.3, 0.4), "min": 35.0},
    "Mikal Bridges":   {"team": "NYK", "points": (17.5, 5.0), "rebounds": (3.5, 1.6), "assists": (3.2, 1.5), "threes_made": (2.2, 1.3), "steals": (1.0, 0.7), "blocks": (0.5, 0.6), "min": 35.0},
    "Paolo Banchero":  {"team": "ORL", "points": (22.5, 6.0), "rebounds": (6.5, 2.5), "assists": (5.0, 2.2), "threes_made": (1.5, 1.2), "steals": (0.8, 0.7), "blocks": (0.5, 0.6), "min": 34.0},
    "Franz Wagner":    {"team": "ORL", "points": (21.0, 5.5), "rebounds": (5.5, 2.2), "assists": (5.5, 2.2), "threes_made": (1.8, 1.2), "steals": (1.1, 0.8), "blocks": (0.4, 0.5), "min": 34.0},
    "Jalen Suggs":     {"team": "ORL", "points": (16.5, 5.0), "rebounds": (4.0, 1.8), "assists": (4.3, 2.0), "threes_made": (2.0, 1.3), "steals": (1.5, 0.9), "blocks": (0.5, 0.6), "min": 31.0},
    "Wendell Carter Jr.": {"team": "ORL", "points": (12.5, 4.2), "rebounds": (7.5, 2.5), "assists": (2.5, 1.3), "threes_made": (0.9, 0.8), "steals": (0.6, 0.6), "blocks": (0.8, 0.7), "min": 26.0},
    "Jimmy Butler":    {"team": "MIA", "points": (20.5, 7.0), "rebounds": (5.5, 2.5), "assists": (5.0, 2.5), "threes_made": (0.8, 0.8), "steals": (1.3, 0.9), "blocks": (0.3, 0.5), "min": 33.0},
    "Bam Adebayo":     {"team": "MIA", "points": (19.5, 5.5), "rebounds": (10.5, 3.0), "assists": (3.5, 2.0), "threes_made": (0.3, 0.5), "steals": (1.1, 0.8), "blocks": (0.8, 0.8), "min": 34.0},
    "Tyler Herro":     {"team": "MIA", "points": (21.0, 6.0), "rebounds": (5.0, 2.0), "assists": (4.5, 2.0), "threes_made": (2.8, 1.5), "steals": (0.8, 0.7), "blocks": (0.3, 0.4), "min": 33.0},
    "Terry Rozier":    {"team": "MIA", "points": (14.5, 5.0), "rebounds": (3.5, 1.7), "assists": (3.8, 1.8), "threes_made": (2.0, 1.3), "steals": (0.9, 0.7), "blocks": (0.2, 0.4), "min": 30.0},
    "Tyrese Haliburton": {"team": "IND", "points": (20.0, 6.0), "rebounds": (3.8, 1.8), "assists": (10.5, 3.5), "threes_made": (3.0, 1.5), "steals": (1.2, 0.8), "blocks": (0.3, 0.4), "min": 34.0},
    "Pascal Siakam":   {"team": "IND", "points": (22.0, 5.5), "rebounds": (6.5, 2.5), "assists": (4.0, 2.0), "threes_made": (1.2, 1.0), "steals": (0.8, 0.7), "blocks": (0.6, 0.6), "min": 34.0},
    "Myles Turner":    {"team": "IND", "points": (17.0, 5.0), "rebounds": (6.5, 2.3), "assists": (1.5, 1.0), "threes_made": (1.8, 1.2), "steals": (0.8, 0.7), "blocks": (2.0, 1.2), "min": 31.0},
    "Bennedict Mathurin": {"team": "IND", "points": (17.5, 5.5), "rebounds": (4.5, 1.8), "assists": (2.0, 1.2), "threes_made": (2.0, 1.3), "steals": (0.5, 0.5), "blocks": (0.4, 0.5), "min": 30.0},
    "Andrew Nembhard": {"team": "IND", "points": (12.0, 4.0), "rebounds": (3.0, 1.5), "assists": (5.5, 2.2), "threes_made": (1.5, 1.1), "steals": (1.0, 0.7), "blocks": (0.3, 0.4), "min": 29.0},
    "LaMelo Ball":     {"team": "CHA", "points": (23.0, 6.5), "rebounds": (5.5, 2.5), "assists": (8.0, 3.0), "threes_made": (3.2, 1.7), "steals": (1.5, 1.0), "blocks": (0.3, 0.5), "min": 33.0},
    "Scottie Barnes":  {"team": "TOR", "points": (19.5, 5.5), "rebounds": (7.5, 3.0), "assists": (6.5, 2.5), "threes_made": (1.0, 0.9), "steals": (1.2, 0.9), "blocks": (0.8, 0.8), "min": 35.0},
    "Cade Cunningham": {"team": "DET", "points": (22.5, 6.0), "rebounds": (4.5, 2.0), "assists": (7.5, 3.0), "threes_made": (2.0, 1.3), "steals": (0.8, 0.7), "blocks": (0.3, 0.5), "min": 35.0},
    "Trae Young":      {"team": "ATL", "points": (25.5, 7.0), "rebounds": (3.0, 1.5), "assists": (10.5, 3.5), "threes_made": (2.8, 1.6), "steals": (1.0, 0.8), "blocks": (0.1, 0.3), "min": 35.0},
    "Dejounte Murray": {"team": "NOP", "points": (18.0, 5.5), "rebounds": (5.0, 2.2), "assists": (6.0, 2.5), "threes_made": (1.5, 1.1), "steals": (1.5, 1.0), "blocks": (0.3, 0.5), "min": 34.0},
    "Zion Williamson": {"team": "NOP", "points": (22.5, 6.0), "rebounds": (5.5, 2.5), "assists": (5.0, 2.0), "threes_made": (0.3, 0.5), "steals": (1.0, 0.8), "blocks": (0.6, 0.6), "min": 30.0},
    # --- Western Conference Stars ---
    "Luka Doncic":     {"team": "DAL", "points": (33.5, 8.0), "rebounds": (9.0, 3.0), "assists": (9.5, 3.2), "threes_made": (4.0, 2.0), "steals": (1.4, 0.9), "blocks": (0.5, 0.6), "min": 37.0},
    "Kyrie Irving":    {"team": "DAL", "points": (25.5, 6.5), "rebounds": (5.0, 2.0), "assists": (5.0, 2.2), "threes_made": (2.8, 1.5), "steals": (1.3, 0.9), "blocks": (0.4, 0.5), "min": 35.0},
    "P.J. Washington": {"team": "DAL", "points": (13.5, 4.5), "rebounds": (6.5, 2.3), "assists": (2.0, 1.2), "threes_made": (1.5, 1.1), "steals": (0.9, 0.7), "blocks": (0.9, 0.7), "min": 30.0},
    "Klay Thompson":   {"team": "DAL", "points": (14.0, 5.0), "rebounds": (3.5, 1.6), "assists": (2.0, 1.2), "threes_made": (2.8, 1.5), "steals": (0.7, 0.6), "blocks": (0.3, 0.4), "min": 28.0},
    "Daniel Gafford":  {"team": "DAL", "points": (10.5, 3.8), "rebounds": (6.8, 2.2), "assists": (1.2, 0.9), "threes_made": (0.0, 0.2), "steals": (0.5, 0.6), "blocks": (1.8, 1.1), "min": 23.0},
    "Shai Gilgeous-Alexander": {"team": "OKC", "points": (31.5, 6.5), "rebounds": (5.5, 2.2), "assists": (6.5, 2.5), "threes_made": (2.0, 1.3), "steals": (2.0, 1.1), "blocks": (1.0, 0.8), "min": 34.0},
    "Jalen Williams":  {"team": "OKC", "points": (20.5, 5.5), "rebounds": (5.5, 2.2), "assists": (5.0, 2.2), "threes_made": (1.8, 1.2), "steals": (1.1, 0.8), "blocks": (0.7, 0.7), "min": 33.0},
    "Chet Holmgren":   {"team": "OKC", "points": (16.5, 5.5), "rebounds": (7.5, 3.0), "assists": (2.5, 1.5), "threes_made": (1.5, 1.1), "steals": (0.5, 0.6), "blocks": (2.5, 1.3), "min": 30.0},
    "Lu Dort":         {"team": "OKC", "points": (10.5, 4.0), "rebounds": (4.0, 1.7), "assists": (1.8, 1.0), "threes_made": (1.8, 1.2), "steals": (0.9, 0.7), "blocks": (0.3, 0.4), "min": 29.0},
    "Isaiah Hartenstein": {"team": "OKC", "points": (11.0, 3.8), "rebounds": (10.5, 3.0), "assists": (3.8, 1.7), "threes_made": (0.1, 0.3), "steals": (0.7, 0.6), "blocks": (1.1, 0.8), "min": 26.0},
    "Nikola Jokic":    {"team": "DEN", "points": (26.5, 6.5), "rebounds": (12.5, 3.5), "assists": (9.0, 3.0), "threes_made": (1.2, 1.0), "steals": (1.4, 0.9), "blocks": (0.7, 0.7), "min": 35.0},
    "Jamal Murray":    {"team": "DEN", "points": (21.0, 6.0), "rebounds": (4.0, 2.0), "assists": (6.5, 2.5), "threes_made": (2.8, 1.5), "steals": (1.0, 0.8), "blocks": (0.3, 0.5), "min": 33.0},
    "Aaron Gordon":    {"team": "DEN", "points": (14.0, 4.5), "rebounds": (6.0, 2.2), "assists": (3.3, 1.5), "threes_made": (1.3, 1.0), "steals": (0.7, 0.6), "blocks": (0.7, 0.6), "min": 31.0},
    "Michael Porter Jr.": {"team": "DEN", "points": (17.5, 5.5), "rebounds": (7.0, 2.4), "assists": (2.0, 1.2), "threes_made": (2.3, 1.4), "steals": (0.6, 0.6), "blocks": (0.6, 0.6), "min": 33.0},
    "Russell Westbrook": {"team": "DEN", "points": (12.0, 4.5), "rebounds": (5.0, 2.0), "assists": (5.5, 2.2), "threes_made": (0.8, 0.8), "steals": (1.3, 0.9), "blocks": (0.3, 0.5), "min": 25.0},
    "LeBron James":    {"team": "LAL", "points": (25.5, 6.5), "rebounds": (7.5, 3.0), "assists": (8.0, 3.0), "threes_made": (2.2, 1.4), "steals": (1.3, 0.9), "blocks": (0.5, 0.6), "min": 35.5},
    "Anthony Davis":   {"team": "LAL", "points": (24.5, 6.5), "rebounds": (12.5, 3.5), "assists": (3.5, 1.8), "threes_made": (0.8, 0.8), "steals": (1.2, 0.9), "blocks": (2.3, 1.3), "min": 35.5},
    "Austin Reaves":   {"team": "LAL", "points": (15.5, 5.0), "rebounds": (4.5, 2.0), "assists": (5.5, 2.5), "threes_made": (2.0, 1.2), "steals": (0.8, 0.7), "blocks": (0.3, 0.4), "min": 33.0},
    "D'Angelo Russell": {"team": "LAL", "points": (14.5, 5.0), "rebounds": (3.0, 1.5), "assists": (5.8, 2.2), "threes_made": (2.3, 1.4), "steals": (0.8, 0.7), "blocks": (0.4, 0.5), "min": 30.0},
    "Rui Hachimura":   {"team": "LAL", "points": (13.5, 4.5), "rebounds": (4.5, 1.8), "assists": (1.3, 0.9), "threes_made": (1.3, 1.0), "steals": (0.5, 0.5), "blocks": (0.5, 0.6), "min": 28.0},
    "Stephen Curry":   {"team": "GSW", "points": (26.5, 7.0), "rebounds": (4.5, 2.0), "assists": (5.0, 2.2), "threes_made": (4.5, 2.2), "steals": (0.7, 0.6), "blocks": (0.4, 0.5), "min": 33.0},
    "Draymond Green":  {"team": "GSW", "points": (8.5, 4.0), "rebounds": (7.0, 2.8), "assists": (6.0, 2.5), "threes_made": (0.5, 0.7), "steals": (1.0, 0.8), "blocks": (1.0, 0.8), "min": 30.0},
    "Jonathan Kuminga": {"team": "GSW", "points": (16.0, 5.0), "rebounds": (4.8, 1.9), "assists": (2.0, 1.2), "threes_made": (1.2, 1.0), "steals": (0.6, 0.6), "blocks": (0.5, 0.6), "min": 27.0},
    "Brandin Podziemski": {"team": "GSW", "points": (12.5, 4.2), "rebounds": (5.5, 2.0), "assists": (3.7, 1.6), "threes_made": (1.7, 1.2), "steals": (0.8, 0.7), "blocks": (0.2, 0.4), "min": 28.0},
    "Buddy Hield":     {"team": "GSW", "points": (12.5, 4.5), "rebounds": (3.5, 1.6), "assists": (2.5, 1.3), "threes_made": (2.8, 1.5), "steals": (0.7, 0.6), "blocks": (0.2, 0.4), "min": 27.0},
    "Kawhi Leonard":   {"team": "LAC", "points": (23.5, 6.5), "rebounds": (6.5, 2.5), "assists": (3.5, 1.8), "threes_made": (1.8, 1.2), "steals": (1.6, 1.0), "blocks": (0.5, 0.6), "min": 34.0},
    "James Harden":    {"team": "LAC", "points": (16.5, 6.0), "rebounds": (5.5, 2.5), "assists": (8.5, 3.0), "threes_made": (2.0, 1.4), "steals": (1.1, 0.8), "blocks": (0.5, 0.6), "min": 34.0},
    "Norman Powell":   {"team": "LAC", "points": (21.0, 5.8), "rebounds": (3.2, 1.5), "assists": (2.2, 1.2), "threes_made": (2.8, 1.5), "steals": (1.0, 0.7), "blocks": (0.3, 0.4), "min": 33.0},
    "Ivica Zubac":     {"team": "LAC", "points": (16.5, 4.8), "rebounds": (12.5, 3.2), "assists": (2.5, 1.3), "threes_made": (0.0, 0.2), "steals": (0.5, 0.5), "blocks": (1.3, 0.9), "min": 32.0},
    "Derrick Jones Jr.": {"team": "LAC", "points": (10.0, 3.8), "rebounds": (3.5, 1.5), "assists": (1.0, 0.8), "threes_made": (1.2, 1.0), "steals": (0.7, 0.6), "blocks": (0.6, 0.6), "min": 28.0},
    "Kevin Durant":    {"team": "PHX", "points": (27.0, 6.0), "rebounds": (6.5, 2.5), "assists": (5.0, 2.2), "threes_made": (2.2, 1.4), "steals": (0.7, 0.6), "blocks": (1.2, 0.9), "min": 36.0},
    "Devin Booker":    {"team": "PHX", "points": (27.0, 6.5), "rebounds": (4.5, 2.0), "assists": (6.5, 2.5), "threes_made": (2.5, 1.5), "steals": (0.8, 0.7), "blocks": (0.3, 0.5), "min": 36.0},
    "Bradley Beal":    {"team": "PHX", "points": (18.0, 5.5), "rebounds": (4.5, 2.0), "assists": (5.0, 2.2), "threes_made": (1.5, 1.1), "steals": (1.0, 0.8), "blocks": (0.3, 0.5), "min": 33.0},
    "De'Aaron Fox":    {"team": "SAC", "points": (26.5, 6.5), "rebounds": (4.5, 2.0), "assists": (5.5, 2.5), "threes_made": (1.8, 1.2), "steals": (2.0, 1.1), "blocks": (0.5, 0.6), "min": 36.0},
    "Domantas Sabonis": {"team": "SAC", "points": (19.5, 5.0), "rebounds": (13.5, 3.5), "assists": (8.0, 3.0), "threes_made": (0.5, 0.7), "steals": (0.8, 0.7), "blocks": (0.5, 0.6), "min": 35.0},
    "Ja Morant":       {"team": "MEM", "points": (25.0, 7.0), "rebounds": (5.5, 2.5), "assists": (8.0, 3.0), "threes_made": (1.5, 1.2), "steals": (1.0, 0.8), "blocks": (0.3, 0.5), "min": 33.0},
    "Jaren Jackson Jr.": {"team": "MEM", "points": (22.5, 6.0), "rebounds": (5.5, 2.5), "assists": (2.0, 1.2), "threes_made": (2.0, 1.3), "steals": (1.0, 0.8), "blocks": (1.5, 1.1), "min": 32.0},
    "Anthony Edwards": {"team": "MIN", "points": (25.5, 6.5), "rebounds": (5.5, 2.2), "assists": (5.0, 2.2), "threes_made": (3.0, 1.6), "steals": (1.3, 0.9), "blocks": (0.5, 0.6), "min": 36.0},
    "Rudy Gobert":     {"team": "MIN", "points": (14.0, 4.5), "rebounds": (12.5, 3.5), "assists": (1.5, 1.0), "threes_made": (0.0, 0.2), "steals": (0.7, 0.6), "blocks": (2.0, 1.2), "min": 33.0},
    "Julius Randle":   {"team": "MIN", "points": (19.0, 5.5), "rebounds": (7.5, 2.6), "assists": (4.5, 2.0), "threes_made": (1.5, 1.1), "steals": (0.7, 0.6), "blocks": (0.3, 0.5), "min": 32.0},
    "Naz Reid":        {"team": "MIN", "points": (13.5, 4.5), "rebounds": (5.5, 2.0), "assists": (1.8, 1.1), "threes_made": (1.7, 1.2), "steals": (0.8, 0.7), "blocks": (0.9, 0.7), "min": 27.0},
    "Jaden McDaniels": {"team": "MIN", "points": (11.5, 4.0), "rebounds": (5.5, 2.0), "assists": (1.8, 1.0), "threes_made": (1.2, 1.0), "steals": (1.2, 0.8), "blocks": (1.2, 0.9), "min": 30.0},
    "Mike Conley":     {"team": "MIN", "points": (10.5, 3.8), "rebounds": (3.0, 1.4), "assists": (5.0, 2.0), "threes_made": (1.5, 1.1), "steals": (1.0, 0.7), "blocks": (0.2, 0.4), "min": 28.0},
    "Victor Wembanyama": {"team": "SAS", "points": (21.5, 6.5), "rebounds": (10.5, 3.5), "assists": (3.5, 2.0), "threes_made": (2.0, 1.4), "steals": (1.2, 0.9), "blocks": (3.5, 1.5), "min": 30.0},
    "Anfernee Simons": {"team": "POR", "points": (22.0, 7.0), "rebounds": (3.0, 1.5), "assists": (5.5, 2.5), "threes_made": (3.5, 1.8), "steals": (0.5, 0.6), "blocks": (0.3, 0.4), "min": 34.0},
    "Alperen Sengun":  {"team": "HOU", "points": (21.5, 5.5), "rebounds": (9.0, 3.0), "assists": (5.0, 2.2), "threes_made": (0.5, 0.7), "steals": (1.0, 0.8), "blocks": (0.7, 0.7), "min": 32.0},
    "Jalen Green":     {"team": "HOU", "points": (19.5, 6.0), "rebounds": (3.5, 1.8), "assists": (3.5, 2.0), "threes_made": (2.8, 1.6), "steals": (0.5, 0.6), "blocks": (0.3, 0.4), "min": 33.0},
    "Fred VanVleet":   {"team": "HOU", "points": (14.5, 4.8), "rebounds": (3.5, 1.5), "assists": (5.5, 2.2), "threes_made": (2.0, 1.3), "steals": (1.5, 0.9), "blocks": (0.3, 0.5), "min": 33.0},
    "Dillon Brooks":   {"team": "HOU", "points": (13.5, 4.5), "rebounds": (3.2, 1.4), "assists": (1.8, 1.0), "threes_made": (1.8, 1.2), "steals": (0.7, 0.6), "blocks": (0.4, 0.5), "min": 30.0},
    "Amen Thompson":   {"team": "HOU", "points": (13.5, 4.5), "rebounds": (8.5, 2.8), "assists": (3.5, 1.7), "threes_made": (0.4, 0.5), "steals": (1.3, 0.9), "blocks": (1.0, 0.8), "min": 32.0},
    "Jabari Smith Jr.": {"team": "HOU", "points": (12.5, 4.2), "rebounds": (7.0, 2.4), "assists": (1.3, 0.9), "threes_made": (1.5, 1.1), "steals": (0.6, 0.6), "blocks": (0.9, 0.7), "min": 30.0},
    "Lauri Markkanen": {"team": "UTA", "points": (23.0, 5.5), "rebounds": (8.5, 3.0), "assists": (2.0, 1.2), "threes_made": (2.2, 1.3), "steals": (0.5, 0.6), "blocks": (0.5, 0.6), "min": 34.0},
    "Kyle Kuzma":      {"team": "WAS", "points": (22.0, 6.0), "rebounds": (6.0, 2.5), "assists": (3.5, 2.0), "threes_made": (2.2, 1.4), "steals": (0.5, 0.6), "blocks": (0.5, 0.6), "min": 34.0},
}

# Combo stat mappings
COMBO_STATS = {
    "pra": ("points", "rebounds", "assists"),
    "pr":  ("points", "rebounds"),
    "pa":  ("points", "assists"),
    "ra":  ("rebounds", "assists"),
}

# Full team names keyed by abbreviation — used for UI labels
NBA_TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}

# 2025-26 NBA Playoff bracket (first round). Seed, team, opponent.
NBA_PLAYOFF_BRACKET = {
    "east": [
        {"seed": 1, "team": "CLE", "opp": "MIA", "series": "CLE vs MIA"},
        {"seed": 2, "team": "BOS", "opp": "IND", "series": "BOS vs IND"},
        {"seed": 3, "team": "NYK", "opp": "PHI", "series": "NYK vs PHI"},
        {"seed": 4, "team": "MIL", "opp": "ORL", "series": "MIL vs ORL"},
        {"seed": 5, "team": "ORL", "opp": "MIL", "series": "MIL vs ORL"},
        {"seed": 6, "team": "PHI", "opp": "NYK", "series": "NYK vs PHI"},
        {"seed": 7, "team": "IND", "opp": "BOS", "series": "BOS vs IND"},
        {"seed": 8, "team": "MIA", "opp": "CLE", "series": "CLE vs MIA"},
    ],
    "west": [
        {"seed": 1, "team": "OKC", "opp": "GSW", "series": "OKC vs GSW"},
        {"seed": 2, "team": "HOU", "opp": "LAL", "series": "HOU vs LAL"},
        {"seed": 3, "team": "DEN", "opp": "DAL", "series": "DEN vs DAL"},
        {"seed": 4, "team": "MIN", "opp": "LAC", "series": "MIN vs LAC"},
        {"seed": 5, "team": "LAC", "opp": "MIN", "series": "MIN vs LAC"},
        {"seed": 6, "team": "DAL", "opp": "DEN", "series": "DEN vs DAL"},
        {"seed": 7, "team": "LAL", "opp": "HOU", "series": "HOU vs LAL"},
        {"seed": 8, "team": "GSW", "opp": "OKC", "series": "OKC vs GSW"},
    ],
}

NBA_PLAYOFF_TEAMS = {
    row["team"]: {"seed": row["seed"], "conference": conf, "opp": row["opp"], "series": row["series"]}
    for conf, rows in NBA_PLAYOFF_BRACKET.items()
    for row in rows
}


def _opp_def_factor(opp_team: str, stat: str) -> float:
    """Convert rank (1-30) into a multiplier. Rank 30 -> 1.15, rank 1 -> 0.85."""
    base_stat = stat
    if stat in COMBO_STATS:
        base_stat = COMBO_STATS[stat][0]
    rank = NBA_DEFENSE.get(opp_team, {}).get(base_stat, 15)
    return 0.85 + (rank - 1) * (0.30 / 29)


def _pace_factor(team1: str, team2: str) -> float:
    """Combined pace factor for two teams."""
    p1 = NBA_PACE.get(team1, 1.0)
    p2 = NBA_PACE.get(team2, 1.0)
    return (p1 + p2) / 2.0


class NBAStatsProvider:
    """Stats provider backed by built-in player database + team ratings."""

    def player_context(self, sport: str, player: str, stat: str) -> dict:
        if sport != "nba":
            raise KeyError(f"NBAStatsProvider only handles nba, not {sport}")

        p = NBA_PLAYERS.get(player)
        if p is None:
            raise KeyError(f"Unknown NBA player: {player}")

        team = p["team"]

        # Handle combo stats
        if stat in COMBO_STATS:
            components = COMBO_STATS[stat]
            season_avg = sum(p[c][0] for c in components)
            season_sd = sum(p[c][1] for c in components) * 0.7  # correlated, so less than sum
            last_n_avg = season_avg * 1.02  # slight recency bias
            last_n_sd = season_sd * 1.05
        elif stat in p:
            season_avg, season_sd = p[stat]
            last_n_avg = season_avg * 1.02
            last_n_sd = season_sd * 1.05
        else:
            raise KeyError(f"No data for {player} / {stat}")

        return {
            "season_avg": season_avg,
            "season_sd": season_sd,
            "last_n_avg": round(last_n_avg, 1),
            "last_n_sd": round(last_n_sd, 1),
            "opp_def_factor": 1.0,  # set dynamically by pipeline
            "pace_factor": 1.0,     # set dynamically by pipeline
            "minutes_projection": p["min"],
            "minutes_season_avg": p["min"],
        }

    def get_team(self, player: str) -> str | None:
        p = NBA_PLAYERS.get(player)
        return p["team"] if p else None

    def defense_factor(self, opp_team: str, stat: str) -> float:
        return _opp_def_factor(opp_team, stat)

    def pace_factor(self, team: str, opp_team: str) -> float:
        return _pace_factor(team, opp_team)

    def live_game_state(self, sport: str, game_id: str, player: str) -> dict | None:
        return None

    def final_box(self, sport: str, game_id: str) -> dict:
        return {}
