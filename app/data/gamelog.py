"""Deterministic player game-log generator for the PropsMadness-style graph.

The web UI shows a bar chart of a player's recent games for a given stat with
the prop line drawn across. We don't have real play-by-play archives wired in,
so this module generates a plausible recent-history log from the player's
season mean/SD. Results are deterministic (seeded by player+stat) so the graph
stays stable across refreshes.

The log mixes recent regular-season games with the first couple of playoff
games against the current first-round opponent (from NBA_PLAYOFF_BRACKET).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, asdict
from datetime import date, timedelta

from app.data.nba_stats import (
    NBA_PLAYERS,
    NBA_PLAYOFF_TEAMS,
    NBA_TEAM_NAMES,
    COMBO_STATS,
)


@dataclass
class GameBar:
    date: str            # "Apr 18"
    opponent: str        # team abbr, e.g. "LAL"
    opponent_name: str   # full team name
    value: float | None  # None = game not yet played
    is_playoff: bool
    home: bool           # True if home game


def _seed(player: str, stat: str) -> int:
    """Derive a stable int seed from player + stat."""
    h = hashlib.md5(f"{player}|{stat}".encode()).hexdigest()
    return int(h[:12], 16)


def _round_for_stat(stat: str, v: float) -> float:
    """Points/rebounds/etc. are integers in box scores; combo stats too."""
    return float(int(round(v)))


def _player_mean_sd(player: str, stat: str) -> tuple[float, float]:
    p = NBA_PLAYERS[player]
    if stat in COMBO_STATS:
        components = COMBO_STATS[stat]
        mean = sum(p[c][0] for c in components)
        # correlated components → sd less than straight sum
        sd = sum(p[c][1] for c in components) * 0.7
        return mean, sd
    if stat in p and isinstance(p[stat], tuple):
        return p[stat][0], p[stat][1]
    raise KeyError(f"No season stat for {player} / {stat}")


def _recent_opponents(player_team: str, rng: random.Random) -> list[str]:
    """Pick a plausible list of regular-season opponents (not the player's own team)."""
    pool = [t for t in NBA_TEAM_NAMES.keys() if t != player_team]
    rng.shuffle(pool)
    return pool


def build_nba_gamelog(
    player: str,
    stat: str,
    line: float | None = None,
    today: date | None = None,
    n_games: int = 12,
) -> dict:
    """Build a deterministic recent-game log for the PropsMadness graph.

    Returns a dict with season/graph averages, hit rate vs the line, and a list
    of GameBar entries (most recent last).
    """
    if player not in NBA_PLAYERS:
        raise KeyError(f"Unknown NBA player: {player}")

    today = today or date.today()
    mean, sd = _player_mean_sd(player, stat)
    if line is None:
        # pick a half-integer line close to the season mean
        line = round(mean * 2) / 2.0

    p = NBA_PLAYERS[player]
    team = p["team"]
    rng = random.Random(_seed(player, stat))

    # Build the schedule of dates, most recent last. Dates regularly 1-3 days apart.
    dates: list[date] = []
    d = today
    for _ in range(n_games):
        dates.append(d)
        d = d - timedelta(days=rng.choice([1, 2, 2, 3]))
    dates.reverse()

    # First-round playoff opponent (if this team made it)
    playoff_info = NBA_PLAYOFF_TEAMS.get(team)
    playoff_opp = playoff_info["opp"] if playoff_info else None

    # Recent (non-playoff) opponents, drawn from a shuffled pool
    regular_opps = _recent_opponents(team, rng)
    opp_cursor = 0

    bars: list[GameBar] = []
    # The last 2-3 games are playoff games vs `playoff_opp` if it exists.
    # Pick a playoff start date a few days before today so Game 1 & 2 land in the log.
    playoff_start = today - timedelta(days=3)

    for g_date in dates:
        is_playoff = playoff_opp is not None and g_date >= playoff_start
        opp = playoff_opp if is_playoff else regular_opps[opp_cursor % len(regular_opps)]
        if not is_playoff:
            opp_cursor += 1

        # Home/away alternates roughly; use rng for stability
        home = rng.random() < 0.5

        # Draw value from a truncated normal-ish distribution around mean
        # Add mild matchup noise scaled by sd.
        raw = rng.gauss(mean, sd)
        value: float | None = max(0.0, _round_for_stat(stat, raw))

        # Leave today's game as "to be played" so the rightmost bar shows "?"
        if g_date == today:
            value = None

        bars.append(GameBar(
            date=g_date.strftime("%b %d"),
            opponent=opp,
            opponent_name=NBA_TEAM_NAMES.get(opp, opp),
            value=value,
            is_playoff=is_playoff,
            home=home,
        ))

    played = [b for b in bars if b.value is not None]
    graph_avg = sum(b.value for b in played) / len(played) if played else 0.0
    hits = sum(1 for b in played if b.value > line)
    hit_rate = hits / len(played) if played else 0.0

    return {
        "player": player,
        "team": team,
        "team_name": NBA_TEAM_NAMES.get(team, team),
        "stat": stat,
        "line": line,
        "season_avg": round(mean, 1),
        "graph_avg": round(graph_avg, 1),
        "hit_rate": round(hit_rate, 3),
        "hits": hits,
        "games_played": len(played),
        "is_playoff_team": playoff_info is not None,
        "playoff_series": playoff_info["series"] if playoff_info else None,
        "games": [asdict(b) for b in bars],
    }
