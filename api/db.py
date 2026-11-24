import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "calls.db"


# Open the calls database and wait briefly if another write holds the lock.
def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


# Create the calls table the first time the API starts.
def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = connect()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                room_name TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT
            )
            """
        )
    finally:
        connection.close()


# Turn one database row into the JSON shape the API returns.
def row_to_call(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "config": json.loads(row["config_json"]),
        "createdAt": row["created_at"],
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"],
        "durationSeconds": None,
    }


# Save a new call and return the stored record.
def insert_call(call_id: str, config: dict[str, Any], room_name: str | None) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO calls (id, status, config_json, room_name, created_at)
                VALUES (?, 'created', ?, ?, ?)
                """,
                (call_id, json.dumps(config), room_name, created_at),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    found = get_call(call_id)
    if found is None:
        raise RuntimeError("saved call could not be read back")
    return found


# Read one call, or return None when the id is unknown.
def get_call(call_id: str) -> dict[str, Any] | None:
    connection = connect()
    try:
        row = connection.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return row_to_call(row)


# Read every call, newest first.
def list_calls() -> list[dict[str, Any]]:
    connection = connect()
    try:
        rows = connection.execute("SELECT * FROM calls ORDER BY created_at DESC, id DESC").fetchall()
    finally:
        connection.close()
    return [row_to_call(row) for row in rows]


# Mark a call ended and return the updated record.
def mark_ended(call_id: str) -> dict[str, Any] | None:
    ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                UPDATE calls
                SET status = 'ended', ended_at = ?
                WHERE id = ? AND status != 'ended'
                """,
                (ended_at, call_id),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return get_call(call_id)


# Read the LiveKit room name stored for a call.
def room_name_for(call_id: str) -> str | None:
    connection = connect()
    try:
        row = connection.execute(
            "SELECT room_name FROM calls WHERE id = ?",
            (call_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row["room_name"] is None:
        return None
    return str(row["room_name"])


# Remove a call when room setup fails before the caller receives it.
def delete_call(call_id: str) -> None:
    connection = connect()
    try:
        connection.execute("DELETE FROM calls WHERE id = ?", (call_id,))
    finally:
        connection.close()
