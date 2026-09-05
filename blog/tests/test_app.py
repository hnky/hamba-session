from fastapi.testclient import TestClient

from app.main import app, repository


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


def test_local_seed_image_is_downloaded_and_cached(monkeypatch) -> None:
    image = (b"webp-image", "image/webp")
    repository._local_images.clear()
    calls: list[str] = []

    def download(url: str) -> tuple[bytes, str]:
        calls.append(url)
        return image

    monkeypatch.setattr(repository, "_download_image", download)
    with TestClient(app) as client:
        first = client.get("/images/africa-national-parks.jpg")
        second = client.get("/images/africa-national-parks.jpg")

    assert first.content == image[0]
    assert first.headers["content-type"] == image[1]
    assert second.content == image[0]
    assert len(calls) == 1
