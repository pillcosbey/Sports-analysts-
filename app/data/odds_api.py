"""Client for The Odds API (https://the-odds-api.com).

Free tier: 500 requests/month. Player props cost more credits than
moneylines, so we cache aggressively and batch markets per event.

Docs: https://the-odds-api.com/liveapi/guides/v4/
"""

from __future__ import annotations

import logging
import os
import time
from typing import Iterable

import httpx

from app.data.providers import OddsQuote

log = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4"

SPORT_KEY = {
    "nba": "basketball_nba",
    "mlb": "baseball_mlb",
}

# Internal stat name -> The Odds API market key
NBA_STAT_TO_MARKET = {
    "points":       "player_points",
    "rebounds":     "player_rebounds",
    "assists":      "player_assists",
    "threes_made":  "player_threes",
    "steals":       "player_steals",
    "blocks":       "player_blocks",
    "pra":          "player_points_rebounds_assists",
    "pr":           "player_points_rebounds",
    "pa":           "player_points_assists",
    "ra":           "player_rebounds_assists",
}

MLB_STAT_TO_MARKET = {
    "hits":          "batter_hits",
    "total_bases":   "batter_total_bases",
    "runs":          "batter_runs_scored",
    "rbis":          "batter_rbis",
    "home_runs":     "batter_home_runs",
    "stolen_bases":  "batter_stolen_bases",
    "walks":         "batter_walks",
    "strikeouts":    "pitcher_strikeouts",
    "outs_recorded": "pitcher_outs",
    "hits_allowed":  "pitcher_hits_allowed",
    "earned_runs":   "pitcher_earned_runs",
    "walks_allowed": "pitcher_walks",
}

NBA_MARKET_TO_STAT = {v: k for k, v in NBA_STAT_TO_MARKET.items()}
MLB_MARKET_TO_STAT = {v: k for k, v in MLB_STAT_TO_MARKET.items()}


class OddsAPIClient:
    """Fetches real player-prop odds from The Odds API.

    Implements the same ``player_prop_odds(sport)`` interface as MockOdds
    so the pipeline can swap seamlessly.
    """

    def __init__(
        self,
        api_key: str,
        regions: str = "us",
        bookmakers: Iterable[str] = ("draftkings", "fanduel"),
        cache_ttl_seconds: int = 120,
        timeout: float = 15.0,
    ):
        self.api_key = api_key
        self.regions = regions
        self.bookmakers = list(bookmakers)
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[OddsQuote]]] = {}
        self._timeout = timeout

    # ---------- cache ----------

    def _cached(self, key: str) -> list[OddsQuote] | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self.cache_ttl:
                return val
        return None

    def _store(self, key: str, val: list[OddsQuote]) -> None:
        self._cache[key] = (time.time(), val)

    # ---------- HTTP ----------

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        params = dict(params or {})
        params["apiKey"] = self.api_key
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(f"{BASE}{path}", params=params)
            remaining = r.headers.get("x-requests-remaining")
            if remaining is not None:
                log.info("Odds API requests remaining: %s", remaining)
            r.raise_for_status()
            return r.json()

    # ---------- public ----------

    def player_prop_odds(self, sport: str) -> list[OddsQuote]:
        if sport not in SPORT_KEY:
            return []

        cached = self._cached(f"{sport}:props")
        if cached is not None:
            log.info("Returning cached %s odds (%d quotes)", sport, len(cached))
            return cached

        sport_key = SPORT_KEY[sport]
        market_to_stat = (
            NBA_MARKET_TO_STAT if sport == "nba" else MLB_MARKET_TO_STAT
        )
        markets_csv = ",".join(market_to_stat.keys())

        # Step 1: list today's events
        try:
            events = self._get(f"/sports/{sport_key}/events")
        except httpx.HTTPError as e:
            log.warning("Odds API events fetch failed for %s: %s", sport, e)
            return []

        if not isinstance(events, list):
            log.warning("Unexpected events response: %s", type(events))
            return []

        log.info("Found %d %s events", len(events), sport.upper())

        # Step 2: fetch player-prop odds per event
        quotes: list[OddsQuote] = []
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            try:
                data = self._get(
                    f"/sports/{sport_key}/events/{event_id}/odds",
                    params={
                        "regions": self.regions,
                        "markets": markets_csv,
                        "oddsFormat": "american",
                        "bookmakers": ",".join(self.bookmakers),
                    },
                )
            except httpx.HTTPError as e:
                log.warning("Odds fetch failed for event %s: %s", event_id, e)
                continue

            if isinstance(data, dict):
                quotes.extend(
                    _parse_event(data, sport, market_to_stat)
                )

        log.info("Parsed %d %s player-prop quotes", len(quotes), sport.upper())
        self._store(f"{sport}:props", quotes)
        return quotes


# ---------- response parsing (module-level, testable) ----------

def _parse_event(
    event: dict,
    sport: str,
    market_to_stat: dict[str, str],
) -> list[OddsQuote]:
    """Flatten one event's bookmakers into OddsQuote records.

    For each (player, market, line) tuple, picks the **best price** for
    over and under across all bookmakers in the response.
    """
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    matchup = f"{away} @ {home}" if home and away else ""
    event_id = event.get("id", "")

    # Accumulator: (player, stat, line) -> {"over": (price, book), "under": (price, book)}
    best: dict[tuple[str, str, float], dict[str, tuple[int, str]]] = {}

    for bookmaker in event.get("bookmakers", []):
        book_key = bookmaker.get("key", "")
        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            stat = market_to_stat.get(market_key)
            if stat is None:
                continue
            for outcome in market.get("outcomes", []):
                side = outcome.get("name", "").lower()
                if side not in ("over", "under"):
                    continue
                player = outcome.get("description", "")
                price = outcome.get("price")
                point = outcome.get("point")
                if not player or price is None or point is None:
                    continue
                key = (player, stat, float(point))
                entry = best.setdefault(key, {})
                current = entry.get(side)
                if current is None or price > current[0]:
                    entry[side] = (int(price), book_key)

    quotes: list[OddsQuote] = []
    for (player, stat, line), sides in best.items():
        over = sides.get("over")
        under = sides.get("under")
        if not over or not under:
            continue
        book = over[1] if over[1] == under[1] else f"{over[1]}/{under[1]}"
        quotes.append(
            OddsQuote(
                sport=sport,
                player=player,
                team=matchup,
                stat=stat,
                line=line,
                over_odds=over[0],
                under_odds=under[0],
                book=book,
                game_id=event_id,
            )
        )
    return quotes
