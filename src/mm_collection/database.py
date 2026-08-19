"""SQLite connection and migration helpers."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

DATABASE_FILENAME = "collection.sqlite"

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def data_directory() -> Path:
    """Return the configured runtime data directory."""
    configured = os.environ.get("MM_COLLECTION_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "data"


def database_path() -> Path:
    return data_directory() / DATABASE_FILENAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a database connection with referential integrity enabled."""
    target = path or database_path()
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initial_schema(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL CHECK (length(trim(title)) > 0),
            date_added TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            ),
            author TEXT,
            date_created TEXT,
            type TEXT,
            date_acquired TEXT,
            seller TEXT,
            price TEXT,
            story TEXT
        )
        """,
        """
        CREATE TABLE photos (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            original_path TEXT NOT NULL CHECK (length(trim(original_path)) > 0),
            display_path TEXT NOT NULL CHECK (length(trim(display_path)) > 0),
            position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            caption TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX photos_item_position_idx
        ON photos(item_id, position, id)
        """,
        """
        CREATE UNIQUE INDEX photos_one_primary_per_item_idx
        ON photos(item_id)
        WHERE is_primary = 1
        """,
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS: tuple[Migration, ...] = (
    (1, "initial_schema", _initial_schema),
)


def apply_migrations(path: Path | None = None) -> None:
    """Create the database and atomically apply each pending migration once."""
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    with connect(target) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
            """
        )
        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for version, name, migration in MIGRATIONS:
            if version in applied:
                continue
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )

