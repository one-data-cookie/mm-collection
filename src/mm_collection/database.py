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


def list_items(path: Path | None = None) -> list[dict[str, object]]:
    """Return newest items first, including each item's primary display photo."""
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT items.*, photos.display_path AS primary_photo
            FROM items
            LEFT JOIN photos
                ON photos.item_id = items.id
                AND photos.is_primary = 1
            ORDER BY items.date_added DESC, items.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_item(item_id: int, path: Path | None = None) -> dict[str, object] | None:
    """Return one item with its ordered photographs, or None when absent."""
    with connect(path) as connection:
        item_row = connection.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if item_row is None:
            return None
        photo_rows = connection.execute(
            """
            SELECT * FROM photos
            WHERE item_id = ?
            ORDER BY position, id
            """,
            (item_id,),
        ).fetchall()

    item = dict(item_row)
    photos = [dict(row) for row in photo_rows]
    primary = next((photo for photo in photos if photo["is_primary"]), None)
    item["photos"] = photos
    item["primary_photo"] = primary
    item["additional_photos"] = [
        photo for photo in photos if primary is None or photo["id"] != primary["id"]
    ]
    return item


def update_item(
    item_id: int,
    values: dict[str, str | None],
    path: Path | None = None,
) -> bool:
    """Update editable metadata without changing the creation timestamp."""
    with connect(path) as connection:
        result = connection.execute(
            """
            UPDATE items SET
                title = ?,
                author = ?,
                date_created = ?,
                type = ?,
                date_acquired = ?,
                seller = ?,
                price = ?,
                story = ?
            WHERE id = ?
            """,
            (
                values.get("title"),
                values.get("author"),
                values.get("date_created"),
                values.get("type"),
                values.get("date_acquired"),
                values.get("seller"),
                values.get("price"),
                values.get("story"),
                item_id,
            ),
        )
    return result.rowcount == 1
