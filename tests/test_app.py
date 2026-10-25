import re
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mm_collection.database import connect
from mm_collection.main import ASSET_VERSION, create_app


def test_index_returns_collection_page(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "M&amp;M Collection" in response.text


def test_health_check(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_assistant_ingress_uses_same_origin_paths(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")
    ingress_path = "/api/hassio_ingress/example-session"
    headers = {"X-Ingress-Path": ingress_path}

    with TestClient(app, base_url="http://example.ui.nabu.casa") as client:
        page = client.get(
            "/",
            headers=headers,
        )
        redirect = client.post(
            "/items/new",
            data={"title": "Ingress object"},
            headers=headers,
            follow_redirects=False,
        )
        detail = client.get("/items/1", headers=headers)
        script = client.get(f"/static/{ASSET_VERSION}/app.js", headers=headers)

    assert page.status_code == 200
    assert f'href="{ingress_path}/items/new"' in page.text
    assert "<style>" in page.text
    assert "background: #1b1d1f" in page.text
    assert "app.css" not in page.text
    assert "http://example.ui.nabu.casa" not in page.text
    assert detail.status_code == 200
    assert f'src="{ingress_path}/static/{ASSET_VERSION}/app.js"' in detail.text
    assert script.status_code == 200
    assert redirect.status_code == 303
    assert redirect.headers["location"] == f"{ingress_path}/"


def test_collection_search_matches_metadata_and_preserves_the_query(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        client.post(
            "/items/new",
            data={
                "title": "Blue vase",
                "author": "Anna Nováková",
                "type": "Ceramics",
                "made": "c. 1950",
                "acquired": "2026-08-19",
                "origin": "Bohemia",
                "location": "Living room cabinet",
                "story": "Found in Brno",
                "background": "Made for the Brussels exhibition",
            },
        )
        client.post(
            "/items/new",
            data={"title": "Wooden chair", "author": "Unknown"},
        )
        response = client.get("/", params={"q": "ceramic"})
        location_response = client.get("/", params={"q": "living room"})
        origin_response = client.get("/", params={"q": "Bohemia"})
        made_response = client.get("/", params={"q": "1950"})
        acquired_response = client.get("/", params={"q": "2026-08-19"})
        story_response = client.get("/", params={"q": "Brno"})
        background_response = client.get("/", params={"q": "Brussels"})

    assert response.status_code == 200
    assert "Blue vase" in response.text
    assert "Wooden chair" not in response.text
    assert 'value="ceramic"' in response.text
    assert "1 object found" in response.text
    assert "Blue vase" in location_response.text
    assert "Blue vase" in origin_response.text
    assert "Blue vase" in made_response.text
    assert "Blue vase" in acquired_response.text
    for matching_response in (story_response, background_response):
        assert matching_response.status_code == 200
        assert "Blue vase" in matching_response.text
        assert "Wooden chair" not in matching_response.text


def test_home_assistant_mode_rejects_direct_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_COLLECTION_INGRESS_ONLY", "true")
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app, client=("192.0.2.1", 50000)) as direct_client:
        direct_response = direct_client.get("/")
    with TestClient(app, client=("172.30.32.2", 50000)) as ingress_client:
        ingress_response = ingress_client.get("/")
    with TestClient(app, client=("127.0.0.1", 50000)) as health_client:
        health_response = health_client.get("/health")

    assert direct_response.status_code == 403
    assert ingress_response.status_code == 200
    assert health_response.status_code == 200


def image_bytes(size=(80, 60), color="red"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, "JPEG", quality=95)
    return output.getvalue()


def mpo_bytes():
    """Return an iPhone-style JPEG with a main image and grayscale gain map."""
    output = BytesIO()
    main = Image.new("RGB", (240, 180), "green")
    gain_map = Image.new("L", (120, 90), 128)
    main.save(output, "MPO", save_all=True, append_images=[gain_map])
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


def test_iphone_mpo_photo_is_preserved_and_converted_for_display(tmp_path):
    database = tmp_path / "collection.sqlite"
    original = mpo_bytes()
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Plate"},
            files={"photos": ("IMG_0064.JPG", original, "image/jpeg")},
            follow_redirects=False,
        )

    assert response.status_code == 303
    with connect(database) as connection:
        photo = connection.execute("SELECT * FROM photos").fetchone()

    original_path = tmp_path / "photos" / photo["original_path"]
    display_path = tmp_path / "photos" / photo["display_path"]
    assert original_path.suffix == ".jpg"
    assert original_path.read_bytes() == original
    with Image.open(original_path) as stored_original:
        assert stored_original.format == "MPO"
        assert stored_original.n_frames == 2
    with Image.open(display_path) as display:
        assert display.format == "JPEG"
        assert display.mode == "RGB"
        assert display.size == (240, 180)


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


def test_type_dropdown_has_only_the_allowed_categories(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/items/new")

    dropdown = re.search(r'<select name="type"[^>]*>(.*?)</select>', response.text, re.DOTALL)
    assert dropdown is not None
    assert re.findall(r'<option value="([^"]*)"', dropdown.group(1)) == [
        "", "Ceramics", "Glass", "Pictures", "Objects", "Textiles"
    ]


@pytest.mark.parametrize("item_type", ["Ceramics", "Glass", "Pictures", "Objects", "Textiles"])
def test_allowed_type_can_be_created_and_edited(tmp_path, item_type):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        created = client.post(
            "/items/new",
            data={"title": "Typed object", "type": item_type},
            follow_redirects=False,
        )
        edit_page = client.get("/items/1/edit")
        with connect(database) as connection:
            assert connection.execute("SELECT type FROM items").fetchone()[0] == item_type
        client.post("/items/1/edit", data={"title": "Typed object", "type": ""})
        with connect(database) as connection:
            assert connection.execute("SELECT type FROM items").fetchone()[0] is None
        edited = client.post(
            "/items/1/edit",
            data={"title": "Typed object", "type": item_type},
            follow_redirects=False,
        )
        invalid_date = client.post(
            "/items/1/edit",
            data={"title": "Typed object", "type": item_type, "acquired": "bad-date"},
        )

    assert created.status_code == 303
    assert edited.status_code == 303
    selected_option = f'<option value="{item_type}" selected>'
    assert selected_option in edit_page.text
    assert invalid_date.status_code == 422
    assert selected_option in invalid_date.text
    with connect(database) as connection:
        assert connection.execute("SELECT type FROM items").fetchone()[0] == item_type


def test_unknown_type_is_rejected_on_create_and_edit(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        created = client.post(
            "/items/new", data={"title": "Invalid", "type": "Furniture"}
        )
        with connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 0
        client.post("/items/new", data={"title": "Original", "type": "Glass"})
        edited = client.post(
            "/items/1/edit", data={"title": "Changed", "type": "Furniture"}
        )

    assert created.status_code == 422
    assert edited.status_code == 422
    assert "Please select one of the available types." in created.text
    assert "Please select one of the available types." in edited.text
    with connect(database) as connection:
        item = connection.execute("SELECT title, type FROM items").fetchone()
    assert tuple(item) == ("Original", "Glass")


def test_made_is_free_text_and_acquired_is_iso(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={
                "title": "Dated object",
                "made": "c. 1950–1960",
                "acquired": "2026-08-19",
                "price": "250 CZK",
                "location": "Hall cabinet",
            },
            follow_redirects=False,
        )
        detail_page = client.get("/items/1")
        edit_page = client.get("/items/1/edit")

    assert response.status_code == 303
    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
    assert item["made"] == "c. 1950–1960"
    assert item["acquired"] == "2026-08-19"
    assert item["price"] == "250 CZK"
    assert item["location"] == "Hall cabinet"
    assert "c. 1950–1960" in detail_page.text
    assert "2026-08-19" in detail_page.text
    assert "<dt>Made</dt>" in detail_page.text
    assert "<dt>Acquired</dt>" in detail_page.text
    assert 'value="c. 1950–1960"' in edit_page.text
    assert 'value="2026-08-19"' in edit_page.text


def test_acquired_has_picker_and_made_is_free_text(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/items/new")

    assert response.status_code == 200
    assert "<span>Made</span>" in response.text
    assert "<span>Acquired</span>" in response.text
    made_input = re.search(
        r'<input[^>]*name="made"[^>]*>', response.text, re.DOTALL
    )
    acquired_input = re.search(
        r'<input[^>]*name="acquired"[^>]*>', response.text, re.DOTALL
    )
    assert made_input is not None
    assert acquired_input is not None
    assert 'type="date"' not in made_input.group()
    assert 'placeholder="e.g. c1950 or 1980s"' in made_input.group()
    assert 'type="date"' in acquired_input.group()
    assert "Acquired <strong>YYYY-MM-DD</strong>" not in response.text


def test_invalid_date_is_rejected(tmp_path):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)

    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Bad date", "acquired": "19/08/2026"},
        )

    assert response.status_code == 422
    assert "Please enter Acquired as YYYY-MM-DD" in response.text
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
                "origin": "Czechoslovakia",
                "location": "Hall cabinet",
                "seller": "Old Town Antiques",
                "story": "Found together.\nKept together.",
                "background": "A studio piece.\nMade by hand.",
            },
            files=[
                ("photos", ("front.jpg", image_bytes(color="green"), "image/jpeg")),
                ("photos", ("side.jpg", image_bytes(color="blue"), "image/jpeg")),
            ],
        )
        collection_page = client.get("/")
        detail_page = client.get("/items/1")

    assert detail_page.status_code == 200
    assert 'href="/items/1"' in collection_page.text
    assert "Glass figure" in detail_page.text
    assert "Unknown maker" in detail_page.text
    assert "Czechoslovakia" in detail_page.text
    assert "Hall cabinet" in detail_page.text
    assert "<dt>Seller</dt>" in detail_page.text
    assert "Old Town Antiques" in detail_page.text
    assert "Found together.\nKept together." in detail_page.text
    assert "A studio piece.\nMade by hand." in detail_page.text
    assert "<h2>Story</h2>" in detail_page.text
    assert "<h2>Background</h2>" in detail_page.text
    assert 'class="object-card__location"' in collection_page.text
    assert "Hall cabinet" in collection_page.text
    assert detail_page.text.index("Edit object") < detail_page.text.index("Delete object")
    assert detail_page.text.index("Manage photos") < detail_page.text.index("Delete object")
    assert detail_page.text.index('<div class="record-actions">') > detail_page.text.index(
        '<article class="object-record">'
    )
    assert 'data-photo-gallery' in detail_page.text
    assert 'data-gallery-image' in detail_page.text
    assert detail_page.text.count('data-gallery-thumbnail') == 2
    assert detail_page.text.count('aria-current="true"') == 1
    assert 'data-gallery-previous' not in detail_page.text
    assert 'data-gallery-next' not in detail_page.text
    with connect(database) as connection:
        photo_paths = [
            row["display_path"]
            for row in connection.execute("SELECT display_path FROM photos")
        ]
    assert all(path in detail_page.text for path in photo_paths)


@pytest.mark.parametrize(
    ("author", "item_type", "made", "expected"),
    [
        (
            "Harry Fenton / Royal Doulton", "Ceramics", "c1950s–1960s",
            "Harry Fenton / Royal Doulton · Ceramics, c1950s–1960s",
        ),
        ("Maker", "Ceramics", "", "Maker · Ceramics"),
        ("Maker", "", "c1950s–1960s", "Maker · c1950s–1960s"),
        ("", "Ceramics", "c1950s–1960s", "Ceramics, c1950s–1960s"),
        ("Maker", "", "", "Maker"),
        ("", "Ceramics", "", "Ceramics"),
        ("", "", "c1950s–1960s", "c1950s–1960s"),
        ("", "", "", None),
    ],
)
def test_object_byline_spacing_with_optional_fields(
    tmp_path, author, item_type, made, expected
):
    app = create_app(tmp_path / "collection.sqlite")
    with TestClient(app) as client:
        response = client.post(
            "/items/new",
            data={"title": "Jug", "author": author, "type": item_type, "made": made},
            follow_redirects=False,
        )
        assert response.status_code == 303
        detail = client.get("/items/1")

    byline = re.search(r'<p class="object-byline">(.*?)</p>', detail.text, re.DOTALL)
    if expected is None:
        assert byline is None
    else:
        assert byline is not None
        text = re.sub(r"<[^>]+>", "", byline.group(1))
        assert text == expected


def test_metadata_can_be_edited_without_changing_photos_or_added(tmp_path):
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
                "made": "2020-05-06",
                "type": "Objects",
                "origin": "Prague",
                "acquired": "2026-08-19",
                "seller": "Market",
                "location": "Office shelf",
                "price": "250 CZK",
                "story": "A revised story",
                "background": "A revised history",
            },
            follow_redirects=False,
        )
        detail_page = client.get("/items/1")
        updated_edit_page = client.get("/items/1/edit")

    assert edit_page.status_code == 200
    assert 'value="Old title"' in edit_page.text
    assert 'name="photos"' not in edit_page.text
    assert response.status_code == 303
    assert response.headers["location"].endswith("/items/1")
    assert "New title" in detail_page.text
    assert "A revised story" in detail_page.text
    assert "A revised history" in detail_page.text
    assert ">A revised story</textarea>" in updated_edit_page.text
    assert ">A revised history</textarea>" in updated_edit_page.text

    with connect(database) as connection:
        after = connection.execute("SELECT * FROM items WHERE id = 1").fetchone()
        photos = connection.execute("SELECT * FROM photos WHERE item_id = 1").fetchall()
    assert after["title"] == "New title"
    assert after["author"] == "New author"
    assert after["origin"] == "Prague"
    assert after["made"] == "2020-05-06"
    assert after["acquired"] == "2026-08-19"
    assert after["price"] == "250 CZK"
    assert after["location"] == "Office shelf"
    assert after["story"] == "A revised story"
    assert after["background"] == "A revised history"
    assert after["added"] == before["added"]
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
            data={"title": "Changed", "acquired": "not-a-date"},
        )

    assert response.status_code == 422
    assert "Please enter Acquired as YYYY-MM-DD" in response.text
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
        "made",
        "type",
        "origin",
        "acquired",
        "seller",
        "location",
        "price",
        "story",
        "background",
    ):
        assert item[field] is None


@pytest.mark.parametrize("field", ["story", "background"])
def test_stories_are_independent_optional_and_can_be_cleared(tmp_path, field):
    database = tmp_path / "collection.sqlite"
    app = create_app(database)
    text = "A personal story.\nA second line with <details> & memories."
    headings = {
        "story": "Story",
        "background": "Background",
    }
    other = next(name for name in headings if name != field)

    with TestClient(app) as client:
        response = client.post(
            "/items/new", data={"title": "Object", field: text},
            follow_redirects=False,
        )
        assert response.status_code == 303
        detail = client.get("/items/1")
        assert f"<h2>{headings[field]}</h2>" in detail.text
        assert f"<h2>{headings[other]}</h2>" not in detail.text
        assert (
            "A personal story.\nA second line with &lt;details&gt; &amp; memories."
            in detail.text
        )

        invalid_edit = client.post(
            "/items/1/edit", data={"title": "", field: text}
        )
        assert invalid_edit.status_code == 422
        assert "A personal story." in invalid_edit.text
        assert "&lt;details&gt; &amp; memories.</textarea>" in invalid_edit.text

        cleared = client.post("/items/1/edit", data={"title": "Object", field: "  "})
        assert cleared.status_code == 200
        assert "<h2>Story</h2>" not in cleared.text
        assert "<h2>Background</h2>" not in cleared.text

    with connect(database) as connection:
        item = connection.execute("SELECT * FROM items").fetchone()
    assert item[field] is None
    assert item[other] is None


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
