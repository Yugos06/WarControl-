from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Iterable

from .config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _ensure_db_dir() -> None:
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                actor TEXT,
                target TEXT,
                server TEXT,
                source TEXT,
                raw TEXT
            )
            """
        )
        _conn.commit()


def insert_events(events: Iterable[dict[str, Any]]) -> int:
    rows = []
    for event in events:
        ts = event.get("ts")
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        rows.append(
            (
                ts,
                event.get("type"),
                event.get("message"),
                event.get("actor"),
                event.get("target"),
                event.get("server"),
                event.get("source"),
                event.get("raw"),
            )
        )
    if not rows:
        return 0
    assert _conn is not None
    with _lock:
        _conn.executemany(
            """
            INSERT INTO events (ts, type, message, actor, target, server, source, raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        _conn.commit()
    return len(rows)


def fetch_events(
    *,
    limit: int = 200,
    since: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    assert _conn is not None
    clauses = []
    params: list[Any] = []
    if since:
        clauses.append("ts >= ?")
        params.append(since)
    if event_type:
        clauses.append("type = ?")
        params.append(event_type)

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    sql = (
        "SELECT id, ts, type, message, actor, target, server, source, raw "
        "FROM events "
        f"{where_sql} "
        "ORDER BY id DESC "
        "LIMIT ?"
    )
    params.append(limit)

    with _lock:
        rows = _conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def stats_by_type() -> list[dict[str, Any]]:
    assert _conn is not None
    with _lock:
        rows = _conn.execute(
            "SELECT type, COUNT(*) AS count FROM events GROUP BY type ORDER BY count DESC"
        ).fetchall()
    return [dict(row) for row in rows]
