from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from mm_collection.database import connect
from mm_collection.main import create_app


def test_index_returns_collection_page(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "M&amp;M Collection" in response.text


def image_bytes(size=(80, 60), color="red"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "JPEG", quality=95)
    return output.getvalue()


def test_title_only_item_can_be_added_and_browsed(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "  Yellow dispenser  ", "story": "Found in Brno"},
            follow_redirects=False,
        )
        page = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/")
    assert "Yellow dispenser" in page.text
    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
    assert item["title"] == "Yellow dispenser"
    assert item["story"] == "Found in Brno"
    assert item["author"] is None


def test_multiple_photos_are_preserved_resized_and_served(tmp_path):
    database = tmp_path / "collection.sqlite"
    first = image_bytes(size=(2400, 1800), color="red")
    second = image_bytes(size=(600, 900), color="blue")
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Two views"},
            files=[
                ("photos", ("front.jpg", first, "image/jpeg")),
                ("photos", ("back.jpg", second, "image/jpeg")),
            ],
            follow_redirects=False,
        )

        with connect(database) as connection:
            photos = connection.execute(
                "SELECT * FROM photos ORDER BY position"
            ).fetchall()

        media_response = client.get(f"/media/{photos[0]['display_path']}")
        page = client.get("/")

    assert response.status_code == 303
    assert len(photos) == 2
    assert [row["position"] for row in photos] == [0, 1]
    assert [row["is_primary"] for row in photos] == [1, 0]

    photo_directory = tmp_path / "photos"
    first_original = photo_directory / photos[0]["original_path"]
    first_display = photo_directory / photos[0]["display_path"]
    assert first_original.read_bytes() == first
    with Image.open(first_display) as display_image:
        assert display_image.size == (1600, 1200)
        assert display_image.format == "JPEG"

    assert media_response.status_code == 200
    assert media_response.headers["content-type"] == "image/jpeg"
    assert photos[0]["display_path"] in page.text


def test_bad_photo_rolls_back_database_and_files(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Should not survive"},
            files={"photos": ("not-a-photo.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    assert "not a readable image" in response.text
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM photos").fetchone()[0] == 0
    assert list((tmp_path / "photos").iterdir()) == []


def test_blank_title_is_rejected(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post("/items/new", data={"title": "   "})

    assert response.status_code == 422
    assert "Please enter a title" in response.text
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_dates_are_saved_as_iso_dates(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={
                "title": "Dated object",
                "date_created": "2026-08-09",
                "date_acquired": "2026-08-19",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
    assert item["date_created"] == "2026-08-09"
    assert item["date_acquired"] == "2026-08-19"


def test_invalid_date_is_rejected(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Bad date", "date_created": "19/08/2026"},
        )

    assert response.status_code == 422
    assert "Please enter dates as YYYY-MM-DD" in response.text
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_object_detail_shows_metadata_and_all_photos(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={
                "title": "Glass figure",
                "author": "Unknown maker",
                "story": "Found together.\nKept together.",
            },
            files=[
                ("photos", ("front.jpg", image_bytes(color="green"), "image/jpeg")),
                ("photos", ("side.jpg", image_bytes(color="blue"), "image/jpeg")),
            ],
        )
        collection_page = client.get("/")
        detail_page = client.get("/items/1")

    assert detail_page.status_code == 200
    assert 'href="http://testserver/items/1"' in collection_page.text
    assert "Glass figure" in detail_page.text
    assert "Unknown maker" in detail_page.text
    assert "Found together.\nKept together." in detail_page.text
    with connect(database) as connection:
        photo_paths = [
            row["display_path"]
            for row in connection.execute("SELECT display_path FROM photos")
        ]
    assert all(path in detail_page.text for path in photo_paths)


def test_metadata_can_be_edited_without_changing_photos_or_date_added(tmp_path):
    database = tmp_path / "collection.sqlite"
    original_photo = image_bytes(color="purple")
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={"title": "Old title", "author": "Old author"},
            files={"photos": ("object.jpg", original_photo, "image/jpeg")},
        )
        with connect(database) as connection:
            before = connection.execute("SELECT * FROM items WHERE id = 1").fetchone()
            photo = connection.execute("SELECT * FROM photos WHERE item_id = 1").fetchone()

        edit_page = client.get("/items/1/edit")
        response = client.post(
            "/items/1/edit",
            data={
                "title": "New title",
                "author": "New author",
                "date_created": "2020-05-06",
                "type": "Figurine",
                "date_acquired": "2026-08-19",
                "seller": "Market",
                "price": "250 CZK",
                "story": "A revised story",
            },
            follow_redirects=False,
        )
        detail_page = client.get("/items/1")

    assert edit_page.status_code == 200
    assert 'value="Old title"' in edit_page.text
    assert 'name="photos"' not in edit_page.text
    assert response.status_code == 303
    assert response.headers["location"].endswith("/items/1")
    assert "New title" in detail_page.text
    assert "A revised story" in detail_page.text

    with connect(database) as connection:
        after = connection.execute("SELECT * FROM items WHERE id = 1").fetchone()
        photos = connection.execute("SELECT * FROM photos WHERE item_id = 1").fetchall()
    assert after["title"] == "New title"
    assert after["author"] == "New author"
    assert after["date_added"] == before["date_added"]
    assert len(photos) == 1
    assert photos[0]["id"] == photo["id"]
    assert (tmp_path / "photos" / photo["original_path"]).read_bytes() == original_photo


def test_invalid_edit_leaves_the_existing_item_unchanged(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post("/items/new", data={"title": "Original"})
        response = client.post(
            "/items/1/edit",
            data={"title": "Changed", "date_created": "not-a-date"},
        )

    assert response.status_code == 422
    assert "Please enter dates as YYYY-MM-DD" in response.text
    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items WHERE id = 1").fetchone()
    assert item["title"] == "Original"


def test_edit_form_keeps_empty_optional_fields_empty(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post("/items/new", data={"title": "Sparse record"})
        edit_page = client.get("/items/1/edit")
        response = client.post("/items/1/edit", data={"title": "Renamed record"})

    assert edit_page.status_code == 200
    assert 'value="None"' not in edit_page.text
    assert ">None</textarea>" not in edit_page.text
    assert response.status_code == 200
    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items WHERE id = 1").fetchone()
    for field in (
        "author",
        "date_created",
        "type",
        "date_acquired",
        "seller",
        "price",
        "story",
    ):
        assert item[field] is None


def test_missing_object_pages_return_404(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        detail_response = client.get("/items/999")
        edit_response = client.get("/items/999/edit")
        update_response = client.post("/items/999/edit", data={"title": "Nope"})

    assert detail_response.status_code == 404
    assert edit_response.status_code == 404
    assert update_response.status_code == 404


def test_photos_can_be_added_to_an_existing_object(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post("/items/new", data={"title": "Initially bare"})
        response = client.post(
            "/items/1/photos",
            files=[
                ("photos", ("first.jpg", image_bytes(color="red"), "image/jpeg")),
                ("photos", ("second.jpg", image_bytes(color="blue"), "image/jpeg")),
            ],
            follow_redirects=False,
        )
        manager_page = client.get("/items/1/photos")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/items/1/photos")
    with connect(database) as connection:
        photos = connection.execute(
            "SELECT * FROM photos ORDER BY position"
        ).fetchall()
    assert len(photos) == 2
    assert [photo["position"] for photo in photos] == [0, 1]
    assert [photo["is_primary"] for photo in photos] == [1, 0]
    assert all(photo["display_path"] in manager_page.text for photo in photos)


def test_bad_photo_addition_keeps_existing_photos_and_removes_new_files(tmp_path):
    database = tmp_path / "collection.sqlite"
    existing_contents = image_bytes(color="green")
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={"title": "Protected object"},
            files={"photos": ("existing.jpg", existing_contents, "image/jpeg")},
        )
        response = client.post(
            "/items/1/photos",
            files=[
                ("photos", ("valid.jpg", image_bytes(color="yellow"), "image/jpeg")),
                ("photos", ("broken.txt", b"not an image", "text/plain")),
            ],
        )

    assert response.status_code == 400
    with connect(database) as connection:
        photos = connection.execute("SELECT * FROM photos").fetchall()
    assert len(photos) == 1
    original = tmp_path / "photos" / photos[0]["original_path"]
    assert original.read_bytes() == existing_contents
    assert len(list((tmp_path / "photos" / "1" / "originals").iterdir())) == 1
    assert len(list((tmp_path / "photos" / "1" / "display").iterdir())) == 1


def test_photo_caption_primary_and_order_can_be_managed(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={"title": "Three views"},
            files=[
                ("photos", ("one.jpg", image_bytes(color="red"), "image/jpeg")),
                ("photos", ("two.jpg", image_bytes(color="green"), "image/jpeg")),
                ("photos", ("three.jpg", image_bytes(color="blue"), "image/jpeg")),
            ],
        )
        with connect(database) as connection:
            initial = connection.execute(
                "SELECT * FROM photos ORDER BY position"
            ).fetchall()
        first_id, second_id, third_id = [row["id"] for row in initial]

        move_response = client.post(
            f"/items/1/photos/{third_id}",
            data={"caption": "Blue side", "action": "earlier"},
            follow_redirects=False,
        )
        primary_response = client.post(
            f"/items/1/photos/{third_id}",
            data={"caption": "Blue side", "action": "primary"},
            follow_redirects=False,
        )
        detail_page = client.get("/items/1")

    assert move_response.status_code == 303
    assert primary_response.status_code == 303
    with connect(database) as connection:
        ordered = connection.execute(
            "SELECT * FROM photos ORDER BY position"
        ).fetchall()
    assert [row["id"] for row in ordered] == [first_id, third_id, second_id]
    assert [row["position"] for row in ordered] == [0, 1, 2]
    assert [row["id"] for row in ordered if row["is_primary"]] == [third_id]
    assert next(row for row in ordered if row["id"] == third_id)["caption"] == "Blue side"
    assert "Blue side" in detail_page.text


def test_removing_primary_photo_reassigns_primary_and_cleans_files(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={"title": "Two photographs"},
            files=[
                ("photos", ("one.jpg", image_bytes(color="red"), "image/jpeg")),
                ("photos", ("two.jpg", image_bytes(color="blue"), "image/jpeg")),
            ],
        )
        with connect(database) as connection:
            before = connection.execute(
                "SELECT * FROM photos ORDER BY position"
            ).fetchall()
        removed_original = tmp_path / "photos" / before[0]["original_path"]
        removed_display = tmp_path / "photos" / before[0]["display_path"]
        kept_original = tmp_path / "photos" / before[1]["original_path"]

        response = client.post(
            f"/items/1/photos/{before[0]['id']}",
            data={"action": "delete"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    with connect(database) as connection:
        remaining = connection.execute("SELECT * FROM photos").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["id"] == before[1]["id"]
    assert remaining[0]["position"] == 0
    assert remaining[0]["is_primary"] == 1
    assert not removed_original.exists()
    assert not removed_display.exists()
    assert kept_original.exists()


def test_object_deletion_removes_database_rows_and_photo_directory(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={"title": "Temporary object"},
            files={"photos": ("object.jpg", image_bytes(), "image/jpeg")},
        )
        item_directory = tmp_path / "photos" / "1"
        assert item_directory.is_dir()

        response = client.post("/items/1/delete", follow_redirects=False)
        detail_response = client.get("/items/1")

    assert response.status_code == 303
    assert response.headers["location"].endswith("/")
    assert detail_response.status_code == 404
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM photos").fetchone()[0] == 0
    assert not item_directory.exists()
