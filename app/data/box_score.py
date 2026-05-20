"""Source-agnostic final box-score fetcher.

Tries providers in order:
  1. ESPN summary endpoint (works for any game with an ESPN id)
  2. balldontlie.io (free, key required, looked up by date + teams)
  3. nba_api (open-source NBA.com client, no key required)

The grader and any future consumer should call `fetch_final_box(...)`
rather than the individual providers — that way new sources slot in
here without touching consumer code.
"""

from __future__ import annotations

import logging

from app.data.balldontlie import fetch_final_box_by_date_teams
from app.data.live_boxscore import NBABoxGame, fetch_nba_boxscore
from app.data.nba_api_source import fetch_live_box_by_date_teams as fetch_nba_api_box

log = logging.getLogger(__name__)


def fetch_final_box(
    espn_game_id: str | None = None,
    *,
    game_date: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> NBABoxGame | None:
    """Fetch the final box from whichever source is available.

    At least one of these must be passable:
      - `espn_game_id` (e.g. '401871155')
      - or a complete (game_date, home_team, away_team) triple for the
        balldontlie / nba_api fallbacks. `game_date` is YYYY-MM-DD.

    Returns None only when every source fails or no identifiers are provided.
    """
    if espn_game_id:
        box = fetch_nba_boxscore(espn_game_id)
        if box is not None:
            return box
        log.info("ESPN had no box for %s — trying balldontlie", espn_game_id)

    if game_date and home_team and away_team:
        bdl = fetch_final_box_by_date_teams(
            date=game_date,
            home_abbr=home_team,
            away_abbr=away_team,
            espn_game_id=espn_game_id or "",
        )
        if bdl is not None:
            return bdl
        log.info("balldontlie had no box for %s %s@%s — trying nba_api",
                 game_date, away_team, home_team)
        return fetch_nba_api_box(
            date=game_date,
            home_abbr=home_team,
            away_abbr=away_team,
            espn_game_id=espn_game_id or "",
        )

    return None
