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
