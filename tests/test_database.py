import sqlite3

import pytest

from mm_collection import database
from mm_collection.database import MIGRATIONS, _initial_schema, apply_migrations, connect


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
        (3, "rename_item_dates"),
        (4, "rename_acquired_on"),
        (5, "rename_acquired"),
        (6, "rename_added"),
        (7, "add_background"),
        (8, "drop_photo_captions"),
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
        (3, "rename_item_dates"),
        (4, "rename_acquired_on"),
        (5, "rename_acquired"),
        (6, "rename_added"),
        (7, "add_background"),
        (8, "drop_photo_captions"),
    ]


@pytest.mark.parametrize("schema_version", [2, 3, 4, 5])
def test_date_rename_preserves_existing_items_and_photos(tmp_path, schema_version):
    path = tmp_path / "collection.sqlite"
    made_column = "date_created" if schema_version == 2 else "made"
    acquired_column = {
        2: "date_acquired",
        3: "acquired",
        4: "acquired_on",
        5: "acquired",
    }[schema_version]

    with connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT)"
        )
        for version, name, migration in MIGRATIONS[:schema_version]:
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )
        connection.execute(
            f"""
            INSERT INTO items(
                title, author, {made_column}, type, origin, {acquired_column},
                seller, price, location, story
            ) VALUES (
                'Vase', 'Maker', 'c. 1950', 'Ceramic', 'Prague', '2026-08-19',
                'Market', '250 CZK', 'Hall cabinet', 'Found in Brno'
            )
            """
        )
        connection.execute("INSERT INTO items(title) VALUES ('Undated object')")
        connection.execute(
            """
            INSERT INTO photos(item_id, original_path, display_path, is_primary)
            VALUES (1, 'original.jpg', 'display.jpg', 1)
            """
        )
        before_items = [
            dict(row) for row in connection.execute("SELECT * FROM items ORDER BY id")
        ]
        before_photo = dict(connection.execute("SELECT * FROM photos").fetchone())

    apply_migrations(path)
    apply_migrations(path)

    with connect(path) as connection:
        after_items = [
            dict(row) for row in connection.execute("SELECT * FROM items ORDER BY id")
        ]
        after_photo = dict(connection.execute("SELECT * FROM photos").fetchone())

    for before, after in zip(before_items, after_items, strict=True):
        before["made"] = before.pop(made_column)
        before["acquired"] = before.pop(acquired_column)
        before["added"] = before.pop("date_added")
        before["background"] = None
        assert after == before
    before_photo.pop("caption")
    assert after_photo == before_photo


@pytest.mark.parametrize("story", [None, "", "Found in Brno.\nA gift from Anna."])
def test_background_migration_preserves_existing_story_and_photos(tmp_path, story):
    path = tmp_path / "collection.sqlite"
    with connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT)"
        )
        for version, name, migration in MIGRATIONS[:6]:
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )
        connection.execute(
            "INSERT INTO items(title, story) VALUES ('Existing object', ?)", (story,)
        )
        connection.execute(
            """
            INSERT INTO photos(item_id, original_path, display_path, is_primary)
            VALUES (1, 'original.jpg', 'display.jpg', 1)
            """
        )
        before_item = dict(connection.execute("SELECT * FROM items").fetchone())
        before_photo = dict(connection.execute("SELECT * FROM photos").fetchone())

    apply_migrations(path)
    apply_migrations(path)

    with connect(path) as connection:
        item = dict(connection.execute("SELECT * FROM items").fetchone())
        photo = dict(connection.execute("SELECT * FROM photos").fetchone())

    before_item["background"] = None
    before_photo.pop("caption")
    assert item == before_item
    assert photo == before_photo


def test_caption_migration_preserves_other_photo_fields(tmp_path):
    path = tmp_path / "collection.sqlite"
    with connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT)"
        )
        for version, name, migration in MIGRATIONS[:7]:
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )
        connection.execute("INSERT INTO items(title) VALUES ('Existing object')")
        connection.execute(
            """
            INSERT INTO photos(
                item_id, original_path, display_path, position, is_primary, caption
            )
            VALUES (1, 'original.jpg', 'display.jpg', 2, 1, 'Front view')
            """
        )
        before = dict(connection.execute("SELECT * FROM photos").fetchone())

    apply_migrations(path)
    apply_migrations(path)

    with connect(path) as connection:
        after = dict(connection.execute("SELECT * FROM photos").fetchone())

    before.pop("caption")
    assert after == before


def test_failed_migration_rolls_back_schema_and_data(tmp_path, monkeypatch):
    path = tmp_path / "collection.sqlite"
    apply_migrations(path)
    with connect(path) as connection:
        connection.execute("INSERT INTO items(title, made) VALUES ('Vase', 'c. 1950')")

    def failing_migration(connection):
        connection.execute("ALTER TABLE items RENAME COLUMN made TO partial_rename")
        connection.execute("UPDATE items SET partial_rename = 'Changed'")
        raise RuntimeError("Migration failed")

    monkeypatch.setattr(
        database, "MIGRATIONS", MIGRATIONS + ((9, "failing_migration", failing_migration),)
    )
    with pytest.raises(RuntimeError, match="Migration failed"):
        apply_migrations(path)

    with connect(path) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
        versions = [
            row[0] for row in connection.execute("SELECT version FROM schema_migrations")
        ]
    assert item["made"] == "c. 1950"
    assert "partial_rename" not in item.keys()
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]


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
            "SELECT added FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row["added"].endswith("Z")

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
