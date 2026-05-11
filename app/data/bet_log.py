"""Bet log — persistent record of placed bets used for real ROI tracking.

Bets are stored as a JSON list on disk (kept small so JSON is fine — we'll
move to SQLite only if it ever grows past a few thousand rows).

Each bet has: stake, american odds, decimal odds, list of legs, status
('open'|'won'|'lost'|'push'|'void'), and the parsed source (manual / image).
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from app.core.math_utils import american_to_decimal


DEFAULT_STORE = Path(os.environ.get("BET_LOG_PATH", "data/bets.json"))


@dataclass
class BetLeg:
    description: str       # e.g. "Dylan Harper - Over 21.5 Points"
    player: str = ""
    stat: str = ""
    side: str = ""         # "OVER" / "UNDER"
    line: float | None = None
    status: str = "open"   # "open" | "won" | "lost" | "push" | "void"


@dataclass
class Bet:
    id: str
    placed_at: float                 # epoch seconds
    sport: str                       # "nba" | "mlb" | "other"
    book: str                        # "bet365", "draftkings", ...
    stake: float
    american_odds: int | None
    decimal_odds: float
    legs: list[BetLeg] = field(default_factory=list)
    status: str = "open"             # "open" | "won" | "lost" | "push" | "void" | "cashout"
    returned: float = 0.0            # filled when settled
    source: str = "manual"           # "manual" | "image"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class BetStore:
    """Thread-safe JSON-file bet log."""

    def __init__(self, path: Path | str = DEFAULT_STORE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.write_text("[]")

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text() or "[]")
        except json.JSONDecodeError:
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2))
        tmp.replace(self.path)

    def all(self) -> list[dict]:
        with self._lock:
            return self._read()

    def get(self, bet_id: str) -> dict | None:
        with self._lock:
            for b in self._read():
                if b.get("id") == bet_id:
                    return b
            return None

    def add(self, bet: Bet) -> dict:
        with self._lock:
            items = self._read()
            items.append(bet.to_dict())
            self._write(items)
            return bet.to_dict()

    def update_status(
        self,
        bet_id: str,
        status: str,
        returned: float | None = None,
    ) -> dict | None:
        with self._lock:
            items = self._read()
            for b in items:
                if b.get("id") != bet_id:
                    continue
                b["status"] = status
                if returned is not None:
                    b["returned"] = float(returned)
                elif status == "won":
                    b["returned"] = round(float(b["stake"]) * float(b["decimal_odds"]), 2)
                elif status in ("lost", "void"):
                    b["returned"] = 0.0
                elif status == "push":
                    b["returned"] = float(b["stake"])
                self._write(items)
                return b
            return None

    def delete(self, bet_id: str) -> bool:
        with self._lock:
            items = self._read()
            keep = [b for b in items if b.get("id") != bet_id]
            if len(keep) == len(items):
                return False
            self._write(keep)
            return True

    def stats(self) -> dict[str, Any]:
        """Roll up all settled bets into ROI / record / breakdowns."""
        items = self._read()
        settled = [b for b in items if b.get("status") in ("won", "lost", "push", "void")]
        open_ = [b for b in items if b.get("status") == "open"]

        wagered = sum(float(b["stake"]) for b in settled)
        returned = sum(float(b.get("returned", 0)) for b in settled)
        pnl = round(returned - wagered, 2)
        roi = (pnl / wagered * 100.0) if wagered > 0 else 0.0

        wins = sum(1 for b in settled if b["status"] == "won")
        losses = sum(1 for b in settled if b["status"] == "lost")
        pushes = sum(1 for b in settled if b["status"] == "push")

        by_sport: dict[str, dict[str, float]] = {}
        for b in settled:
            s = by_sport.setdefault(b.get("sport", "other"), {"w": 0, "l": 0, "pnl": 0.0, "wagered": 0.0})
            s["wagered"] += float(b["stake"])
            s["pnl"] += float(b.get("returned", 0)) - float(b["stake"])
            if b["status"] == "won":
                s["w"] += 1
            elif b["status"] == "lost":
                s["l"] += 1
        for s in by_sport.values():
            s["roi"] = round((s["pnl"] / s["wagered"]) * 100.0, 2) if s["wagered"] else 0.0
            s["pnl"] = round(s["pnl"], 2)
            s["wagered"] = round(s["wagered"], 2)

        return {
            "total_bets": len(items),
            "open_bets": len(open_),
            "settled_bets": len(settled),
            "wagered": round(wagered, 2),
            "returned": round(returned, 2),
            "pnl": pnl,
            "roi_pct": round(roi, 2),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "by_sport": by_sport,
        }


def make_bet(
    *,
    sport: str,
    book: str,
    stake: float,
    american_odds: int | None,
    legs: list[BetLeg],
    source: str = "manual",
    note: str = "",
) -> Bet:
    dec = american_to_decimal(int(american_odds)) if american_odds is not None else 1.0
    return Bet(
        id=uuid.uuid4().hex[:12],
        placed_at=time.time(),
        sport=sport,
        book=book,
        stake=float(stake),
        american_odds=american_odds,
        decimal_odds=round(dec, 4),
        legs=legs,
        source=source,
        note=note,
    )
