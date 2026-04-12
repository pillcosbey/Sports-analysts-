"""Local SQLite store for recommendations, results, and learning residuals.

Schema:
    picks       — one row per recommendation the system emitted
    results     — one row per finalized game stat (ground truth)
    residuals   — projected - actual for each pick, drives the learning loop
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "picks.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    sport           TEXT NOT NULL,         -- 'nba' or 'mlb'
    player          TEXT NOT NULL,
    stat            TEXT NOT NULL,
    line            REAL NOT NULL,
    side            TEXT NOT NULL,         -- 'OVER' or 'UNDER'
    model_prob      REAL NOT NULL,
    fair_prob       REAL NOT NULL,
    edge_pct        REAL NOT NULL,
    projected_mean  REAL NOT NULL,
    projected_sd    REAL NOT NULL,
    sim_trials      INTEGER NOT NULL,
    phase           TEXT NOT NULL,         -- 'pregame' or 'live'
    game_id         TEXT,
    book            TEXT,
    odds            INTEGER,
    graded          INTEGER DEFAULT 0,
    won             INTEGER               -- NULL until graded
);

CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    sport       TEXT NOT NULL,
    player      TEXT NOT NULL,
    stat        TEXT NOT NULL,
    actual      REAL NOT NULL,
    game_id     TEXT
);

CREATE TABLE IF NOT EXISTS residuals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_id     INTEGER NOT NULL,
    sport       TEXT NOT NULL,
    stat        TEXT NOT NULL,
    projected   REAL NOT NULL,
    actual      REAL NOT NULL,
    residual    REAL NOT NULL,         -- projected - actual
    phase       TEXT NOT NULL,
    FOREIGN KEY(pick_id) REFERENCES picks(id)
);

CREATE INDEX IF NOT EXISTS idx_picks_sport_stat ON picks(sport, stat);
CREATE INDEX IF NOT EXISTS idx_residuals_sport_stat ON residuals(sport, stat);
"""


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_pick(row: dict) -> int:
    """Insert a pick and return its id."""
    cols = ",".join(row.keys())
    placeholders = ",".join("?" * len(row))
    with connect() as c:
        cur = c.execute(
            f"INSERT INTO picks ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        return cur.lastrowid or 0


def insert_result(row: dict) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO results (recorded_at, sport, player, stat, actual, game_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["recorded_at"], row["sport"], row["player"],
                row["stat"], row["actual"], row.get("game_id"),
            ),
        )
        return cur.lastrowid or 0


def insert_residual(row: dict) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO residuals (pick_id, sport, stat, projected, actual, residual, phase) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["pick_id"], row["sport"], row["stat"],
                row["projected"], row["actual"], row["residual"], row["phase"],
            ),
        )
        return cur.lastrowid or 0


def ungraded_picks(sport: str | None = None):
    with connect() as c:
        q = "SELECT * FROM picks WHERE graded = 0"
        params: tuple = ()
        if sport:
            q += " AND sport = ?"
            params = (sport,)
        return [dict(r) for r in c.execute(q, params).fetchall()]


def mark_graded(pick_id: int, won: bool) -> None:
    with connect() as c:
        c.execute(
            "UPDATE picks SET graded = 1, won = ? WHERE id = ?",
            (1 if won else 0, pick_id),
        )


def residuals_for(sport: str, stat: str, limit: int = 500):
    with connect() as c:
        rows = c.execute(
            "SELECT residual FROM residuals WHERE sport = ? AND stat = ? "
            "ORDER BY id DESC LIMIT ?",
            (sport, stat, limit),
        ).fetchall()
        return [r["residual"] for r in rows]
