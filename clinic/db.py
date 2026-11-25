import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# Folder for clinic.db, or the clinic folder when DATA_DIR is empty.
def database_path() -> Path:
    folder = os.environ.get("DATA_DIR", "").strip()
    if folder:
        return Path(folder) / "clinic.db"
    return Path(__file__).resolve().parent / "clinic.db"


DB_PATH = database_path()
OPEN_TIMES = ("09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00")
SEED_DAYS = 14


# Open the database file and wait up to 5 seconds if another write holds the lock.
def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


# Create the slots table the first time the service starts.
def create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            booked INTEGER NOT NULL DEFAULT 0,
            patient_name TEXT,
            patient_phone TEXT,
            booked_at TEXT,
            UNIQUE (date, time)
        )
        """
    )


# Add hourly slots for the next 14 days only when the table has no rows yet.
def seed_slots_if_empty(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM slots").fetchone()
    if count is None or count[0] > 0:
        return

    today = date.today()
    rows: list[tuple[str, str]] = []
    for offset in range(SEED_DAYS):
        day = (today + timedelta(days=offset)).isoformat()
        for slot_time in OPEN_TIMES:
            rows.append((day, slot_time))

    connection.executemany(
        "INSERT INTO slots (date, time, booked) VALUES (?, ?, 0)",
        rows,
    )


# Create the database file, the table, and the starter slots.
def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = connect()
    try:
        create_table(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            seed_slots_if_empty(connection)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()


# Return the open appointment times for one date, earliest first.
def free_slots(day: str) -> list[str]:
    connection = connect()
    try:
        rows = connection.execute(
            """
            SELECT time
            FROM slots
            WHERE date = ? AND booked = 0
            ORDER BY time
            """,
            (day,),
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        connection.close()


# Book a slot only if it is still free, so two callers cannot take the same one.
def book_slot(day: str, slot_time: str, name: str, phone: str) -> dict[str, Any]:
    booked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute(
                """
                UPDATE slots
                SET booked = 1, patient_name = ?, patient_phone = ?, booked_at = ?
                WHERE date = ? AND time = ? AND booked = 0
                """,
                (name, phone, booked_at, day, slot_time),
            )
            if cursor.rowcount == 1:
                outcome: dict[str, Any] = {"status": "booked"}
            else:
                existing = connection.execute(
                    "SELECT 1 FROM slots WHERE date = ? AND time = ?",
                    (day, slot_time),
                ).fetchone()
                if existing is None:
                    outcome = {"status": "not_found"}
                else:
                    alternatives = connection.execute(
                        """
                        SELECT time
                        FROM slots
                        WHERE date = ? AND booked = 0
                        ORDER BY time
                        LIMIT 3
                        """,
                        (day,),
                    ).fetchall()
                    outcome = {
                        "status": "already_booked",
                        "alternatives": [row[0] for row in alternatives],
                    }
            connection.execute("COMMIT")
            return outcome
        except Exception:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
