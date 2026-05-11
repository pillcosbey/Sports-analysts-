"""Claude pick log — every parlay I suggest gets recorded here automatically.

This is the "model track record" — separate from the user's real Bets log.
Each pick is graded at a flat $1 hypothetical stake so ROI is comparable
over time independent of how much the user actually staked (or whether
they played the pick at all).

A pick can be "promoted" to a real bet — that copies it into the Bets
store at a user-chosen stake and links the two records.
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


DEFAULT_STORE = Path(os.environ.get("PICK_LOG_PATH", "data/picks.json"))


@dataclass
class PickLeg:
    description: str           # human-readable e.g. "Dylan Harper Over 21.5 Points"
    player: str = ""
    team: str = ""
    stat: str = ""
    side: str = ""             # "OVER" / "UNDER"
    line: float | None = None
    model_prob: float | None = None   # my probability at time of suggestion
    american_odds: int | None = None  # the book line I priced against
    status: str = "open"              # "open" | "won" | "lost" | "push" | "void"


@dataclass
class Pick:
    id: str
    suggested_at: float
    sport: str                       # "nba" | "mlb" | "other"
    game_id: str = ""
    confidence: str = "medium"       # "low" | "medium" | "high"
    legs: list[PickLeg] = field(default_factory=list)
    american_odds: int | None = None      # combined parlay odds
    decimal_odds: float = 1.0
    model_prob: float | None = None       # combined correlated probability
    ev_per_dollar: float | None = None
    rationale: str = ""                   # short one-liner explaining the pick
    source: str = "claude"
    status: str = "open"             # "open" | "won" | "lost" | "push" | "void"
    settled_at: float | None = None
    promoted_to_bet_id: str | None = None  # set if user promoted to real bet

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PickStore:
    """Thread-safe JSON-file pick log."""

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

    def get(self, pick_id: str) -> dict | None:
        with self._lock:
            for p in self._read():
                if p.get("id") == pick_id:
                    return p
            return None

    def add(self, pick: Pick) -> dict:
        with self._lock:
            items = self._read()
            items.append(pick.to_dict())
            self._write(items)
            return pick.to_dict()

    def update_status(
        self,
        pick_id: str,
        status: str,
    ) -> dict | None:
        with self._lock:
            items = self._read()
            for p in items:
                if p.get("id") != pick_id:
                    continue
                p["status"] = status
                p["settled_at"] = time.time() if status != "open" else None
                self._write(items)
                return p
            return None

    def set_promoted(self, pick_id: str, bet_id: str) -> dict | None:
        with self._lock:
            items = self._read()
            for p in items:
                if p.get("id") != pick_id:
                    continue
                p["promoted_to_bet_id"] = bet_id
                self._write(items)
                return p
            return None

    def delete(self, pick_id: str) -> bool:
        with self._lock:
            items = self._read()
            keep = [p for p in items if p.get("id") != pick_id]
            if len(keep) == len(items):
                return False
            self._write(keep)
            return True

    def stats(self) -> dict[str, Any]:
        """Track record at flat $1 per pick."""
        items = self._read()
        settled = [p for p in items if p.get("status") in ("won", "lost", "push", "void")]
        open_ = [p for p in items if p.get("status") == "open"]

        wagered = float(len(settled))           # flat $1 per pick
        returned = 0.0
        for p in settled:
            if p["status"] == "won":
                returned += float(p.get("decimal_odds") or 1.0)
            elif p["status"] == "push":
                returned += 1.0
        pnl = round(returned - wagered, 2)
        roi = (pnl / wagered * 100.0) if wagered > 0 else 0.0

        wins = sum(1 for p in settled if p["status"] == "won")
        losses = sum(1 for p in settled if p["status"] == "lost")
        pushes = sum(1 for p in settled if p["status"] == "push")

        by_sport: dict[str, dict[str, float]] = {}
        for p in settled:
            s = by_sport.setdefault(p.get("sport", "other"), {"w": 0, "l": 0, "pnl": 0.0, "wagered": 0.0})
            s["wagered"] += 1.0
            if p["status"] == "won":
                s["w"] += 1
                s["pnl"] += float(p.get("decimal_odds") or 1.0) - 1.0
            elif p["status"] == "lost":
                s["l"] += 1
                s["pnl"] -= 1.0
        for s in by_sport.values():
            s["roi"] = round((s["pnl"] / s["wagered"]) * 100.0, 2) if s["wagered"] else 0.0
            s["pnl"] = round(s["pnl"], 2)
            s["wagered"] = round(s["wagered"], 2)

        # Calibration: average model prob vs. actual hit rate
        win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else 0.0
        avg_model_prob = 0.0
        prob_count = 0
        for p in settled:
            if p.get("model_prob") is not None:
                avg_model_prob += float(p["model_prob"])
                prob_count += 1
        avg_model_prob = (avg_model_prob / prob_count) if prob_count else 0.0

        return {
            "total_picks": len(items),
            "open_picks": len(open_),
            "settled_picks": len(settled),
            "wagered": round(wagered, 2),
            "returned": round(returned, 2),
            "pnl": pnl,
            "roi_pct": round(roi, 2),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": round(win_rate, 3),
            "avg_model_prob": round(avg_model_prob, 3),
            "calibration_gap": round(win_rate - avg_model_prob, 3),
            "by_sport": by_sport,
        }


def make_pick(
    *,
    sport: str,
    legs: list[PickLeg],
    american_odds: int | None = None,
    model_prob: float | None = None,
    ev_per_dollar: float | None = None,
    rationale: str = "",
    confidence: str = "medium",
    game_id: str = "",
    source: str = "claude",
) -> Pick:
    """Build a Pick — `decimal_odds` is derived from american_odds if not given."""
    dec = american_to_decimal(int(american_odds)) if american_odds else 1.0
    return Pick(
        id=uuid.uuid4().hex[:12],
        suggested_at=time.time(),
        sport=sport,
        game_id=game_id,
        confidence=confidence,
        legs=legs,
        american_odds=american_odds,
        decimal_odds=round(dec, 4),
        model_prob=model_prob,
        ev_per_dollar=ev_per_dollar,
        rationale=rationale,
        source=source,
    )
