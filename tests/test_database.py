import sqlite3

import pytest

from mm_collection.database import _initial_schema, apply_migrations, connect


def test_startup_creates_schema_and_is_repeatable(tmp_path):
    path = tmp_path / "nested" / "collection.sqlite"

    apply_migrations(path)
    apply_migrations(path)

    assert path.is_file()
    with connect(path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migrations = connection.execute(
            "SELECT version, name FROM schema_migrations"
        ).fetchall()

    assert {"items", "photos"} <= tables
    assert [tuple(row) for row in migrations] == [
        (1, "initial_schema"),
        (2, "add_location_and_origin"),
    ]


def test_location_migration_preserves_existing_items(tmp_path):
    path = tmp_path / "collection.sqlite"

    with connect(path) as connection:
        _initial_schema(connection)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (1, 'initial_schema')"
        )
        connection.execute("INSERT INTO items(title) VALUES ('Existing object')")

    apply_migrations(path)

    with connect(path) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
        migrations = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert item["title"] == "Existing object"
    assert item["location"] is None
    assert item["origin"] is None
    assert [tuple(row) for row in migrations] == [
        (1, "initial_schema"),
        (2, "add_location_and_origin"),
    ]


def test_item_and_photo_constraints(tmp_path):
    path = tmp_path / "collection.sqlite"
    apply_migrations(path)

    with connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO items(title) VALUES ('   ')")

        item_id = connection.execute(
            "INSERT INTO items(title) VALUES ('Dispenser')"
        ).lastrowid
        row = connection.execute(
            "SELECT date_added FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row["date_added"].endswith("Z")

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO photos(item_id, original_path, display_path)
                VALUES (999, 'original.jpg', 'display.jpg')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO photos(
                    item_id, original_path, display_path, position
                ) VALUES (?, 'original.jpg', 'display.jpg', -1)
                """,
                (item_id,),
            )

        connection.execute(
            """
            INSERT INTO photos(
                item_id, original_path, display_path, is_primary
            ) VALUES (?, 'one-original.jpg', 'one-display.jpg', 1)
            """,
            (item_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO photos(
                    item_id, original_path, display_path, is_primary
                ) VALUES (?, 'two-original.jpg', 'two-display.jpg', 1)
                """,
                (item_id,),
            )

        connection.execute("DELETE FROM items WHERE id = ?", (item_id,))
        photo_count = connection.execute("SELECT count(*) FROM photos").fetchone()[0]

    assert photo_count == 0
