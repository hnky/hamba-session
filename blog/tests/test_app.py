from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "hamba"}


def test_home_lists_ten_hamba_stories() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.text.count("<article") == 10
    assert "Africa’s national parks ranked" in response.text
    assert "Sesame bread and knafeh" in response.text
    assert "Caribbean’s eight best islands" in response.text


def test_post_detail_and_missing_post() -> None:
    with TestClient(app) as client:
        response = client.get("/posts/ascensor-reina-victoria-valparaiso")
        missing = client.get("/posts/not-a-place")
    assert response.status_code == 200
    assert "source story on Hamba.nl" in response.text
    assert "infrastructure can become part of a city’s identity" in response.text
    assert missing.status_code == 404
