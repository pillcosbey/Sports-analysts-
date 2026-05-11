"""Reconstruct halftime per-player box from ESPN's play-by-play.

The summary endpoint already returns final boxscore totals. To run a
halftime backtest (project at half, compare to final), we need to know
each player's stats at the end of Q2. We get that by parsing the
play-by-play that's bundled in the same summary response.

ESPN's play types are inconsistent across game ids, so we match on the
common substrings ("made", "rebound", "block", "steal", "assist",
"foul") and trust the `scoreValue` field on scoring plays.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import httpx

from app.data.live_boxscore import ESPN_NBA_SUMMARY, NBABoxGame, NBABoxPlayer

log = logging.getLogger(__name__)


def _empty_player() -> dict[str, Any]:
    return {
        "points": 0, "rebounds": 0, "assists": 0,
        "threes_made": 0, "steals": 0, "blocks": 0,
        "turnovers": 0, "fouls": 0,
        "fg_made": 0, "fg_att": 0, "ft_made": 0, "ft_att": 0,
        "minutes": 0.0, "team": "",
    }


def _classify_play(play: dict) -> str:
    """Return a short tag for the play type."""
    ptype = (play.get("type") or {}).get("text", "").lower()
    text = (play.get("text") or "").lower()
    blob = f"{ptype} {text}"
    if "made" in blob and "free throw" not in blob:
        return "made_shot"
    if "missed" in blob and "free throw" not in blob:
        return "missed_shot"
    if "free throw" in blob and "made" in blob:
        return "made_ft"
    if "free throw" in blob and ("missed" in blob or "miss" in blob):
        return "missed_ft"
    if "rebound" in blob:
        return "rebound"
    if "assist" in blob:
        return "assist"
    if "block" in blob:
        return "block"
    if "steal" in blob:
        return "steal"
    if "turnover" in blob:
        return "turnover"
    if "foul" in blob:
        return "foul"
    return "other"


def halftime_box_from_summary(
    summary: dict,
    espn_game_id: str = "",
) -> NBABoxGame | None:
    """Build an NBABoxGame snapshot reflecting each player's stats at the
    end of the 2nd quarter, derived from the summary's `plays` array.
    """
    plays = summary.get("plays") or []
    if not plays:
        return None

    stats: dict[str, dict[str, Any]] = defaultdict(_empty_player)

    for play in plays:
        period = (play.get("period") or {}).get("number") or play.get("periodNumber", 0)
        try:
            period_n = int(period or 0)
        except (TypeError, ValueError):
            period_n = 0
        if period_n > 2 or period_n == 0:
            continue

        tag = _classify_play(play)
        participants = play.get("participants") or []
        score_val = play.get("scoreValue") or 0
        # The `text` sometimes includes "3-pointer" while the score is 3
        is_three = "3-point" in (play.get("text") or "").lower() or score_val == 3
        scoring = bool(play.get("scoringPlay"))

        # First participant is the actor; second (if present) is assister
        actor = participants[0] if participants else None

        def _name(p):
            return ((p or {}).get("athlete") or {}).get("displayName")

        def _team(p):
            return ((p or {}).get("athlete") or {}).get("team", {}).get("abbreviation") or \
                   (p or {}).get("team", {}).get("abbreviation", "")

        if tag == "made_shot" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["points"] += int(score_val) if score_val else (3 if is_three else 2)
            s["fg_made"] += 1
            s["fg_att"] += 1
            if is_three:
                s["threes_made"] += 1
            # Assister: any participant beyond the first
            for ap in participants[1:]:
                an = _name(ap)
                if an and an != n:
                    a = stats[an]
                    a["team"] = a["team"] or _team(ap)
                    a["assists"] += 1
                    break

        elif tag == "missed_shot" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["fg_att"] += 1
            # Block credit if a second participant exists
            for bp in participants[1:]:
                bn = _name(bp)
                if bn and bn != n:
                    b = stats[bn]
                    b["team"] = b["team"] or _team(bp)
                    b["blocks"] += 1
                    break

        elif tag == "made_ft" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["points"] += 1
            s["ft_made"] += 1
            s["ft_att"] += 1
        elif tag == "missed_ft" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["ft_att"] += 1

        elif tag == "rebound" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["rebounds"] += 1

        elif tag == "steal" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["steals"] += 1

        elif tag == "turnover" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["turnovers"] += 1

        elif tag == "foul" and actor:
            n = _name(actor)
            if not n:
                continue
            s = stats[n]
            s["team"] = s["team"] or _team(actor)
            s["fouls"] += 1

    # Get team abbrs / score from the header
    header = summary.get("header") or {}
    comps = (header.get("competitions") or [{}])[0]
    competitors = comps.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0] if competitors else {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else {})

    home_q = [int(ls.get("displayValue", 0) or 0) for ls in home.get("linescores", [])]
    away_q = [int(ls.get("displayValue", 0) or 0) for ls in away.get("linescores", [])]
    ht_home = sum(home_q[:2]) if home_q else 0
    ht_away = sum(away_q[:2]) if away_q else 0

    players = [
        NBABoxPlayer(
            player=name,
            team=s["team"],
            starter=False,
            minutes=24.0,  # placeholder — we project off stat rates, not minutes
            points=s["points"],
            rebounds=s["rebounds"],
            assists=s["assists"],
            threes_made=s["threes_made"],
            steals=s["steals"],
            blocks=s["blocks"],
            turnovers=s["turnovers"],
            fouls=s["fouls"],
            fg_made=s["fg_made"],
            fg_att=s["fg_att"],
            ft_made=s["ft_made"],
            ft_att=s["ft_att"],
        )
        for name, s in stats.items()
        # Keep anyone who registered any tracked event in 1H — including
        # defense-only or foul-only lines, since the model can still
        # project off season mean for them.
        if any(s[k] for k in (
            "points", "rebounds", "assists", "threes_made",
            "steals", "blocks", "turnovers", "fouls", "fg_att", "ft_att",
        ))
    ]

    return NBABoxGame(
        game_id=espn_game_id,
        home_team=home.get("team", {}).get("abbreviation", ""),
        away_team=away.get("team", {}).get("abbreviation", ""),
        home_team_name=home.get("team", {}).get("displayName", ""),
        away_team_name=away.get("team", {}).get("displayName", ""),
        home_score=ht_home,
        away_score=ht_away,
        quarter=2,
        clock="0:00",
        is_halftime=True,
        is_final=False,
        home_quarters=home_q[:2],
        away_quarters=away_q[:2],
        players=players,
    )


def fetch_summary(game_id: str, timeout: float = 10.0) -> dict | None:
    """Fetch the full ESPN summary (boxscore + plays) for a finished game."""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(ESPN_NBA_SUMMARY, params={"event": game_id})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        log.warning("ESPN summary fetch failed for %s: %s", game_id, e)
        return None
