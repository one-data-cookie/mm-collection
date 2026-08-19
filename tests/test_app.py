from fastapi.testclient import TestClient

from mm_collection.main import create_app


def test_index_returns_collection_page(tmp_path):
    app = create_app(tmp_path / "collection.sqlite")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "M&amp;M Collection" in response.text

