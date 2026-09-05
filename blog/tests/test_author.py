"""Author workflows use generated, ephemeral credentials, never stored secrets."""

from copy import deepcopy
from collections.abc import Iterator
from io import BytesIO
import json
import re
import secrets
from unittest.mock import MagicMock

from azure.core.exceptions import ResourceNotFoundError
from fastapi.testclient import TestClient
import httpx
import pytest
from PIL import Image

from app import auth as auth_module
from app.auth import AuthorAuth, SESSION_COOKIE, get_auth
from app.content import SAMPLE_POSTS
from app.main import app, repository
from app.repository import BlogRepository
from app.routers import author as routes
from app.storage.images import MAX_IMAGE_BYTES, normalize_upload

AuthorClient = tuple[TestClient, str, str]

@pytest.fixture
def author_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[AuthorClient]:
    password = secrets.token_urlsafe(24)
    api_key = secrets.token_urlsafe(24)
    auth = AuthorAuth(json.dumps({
        "session_secret": secrets.token_urlsafe(48),
        "users": [{
            "username": "editor",
            "password_hash": AuthorAuth.hash_password(password),
            "api_key_hash": AuthorAuth.hash_api_key(api_key),
        }],
    }))
    monkeypatch.setattr(routes, "get_auth", lambda: auth)
    monkeypatch.setattr(repository, "is_cloud_backed", False)
    monkeypatch.setattr(repository, "_local_posts", {p["slug"]: deepcopy(p) for p in SAMPLE_POSTS})
    monkeypatch.setattr(repository, "_local_images", {})
    monkeypatch.setattr(repository, "_download_image", lambda url: (b"test-image", "image/jpeg"))
    with TestClient(app, base_url="https://testserver") as client:
        yield client, password, api_key


def sign_in(client: TestClient, password: str) -> str:
    response = client.post("/author/login", data={"username": "editor", "password": password}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/author/posts"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    page = client.get("/author/posts")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match is not None
    return match.group(1)


def new_post(csrf: str) -> dict[str, str]:
    return {
        "csrf_token": csrf, "slug": "quiet-coast", "title": "A quiet coast",
        "lead": "Slow mornings by the sea.", "published_at": "2026-09-05",
        "story": "First paragraph.\n\nSecond paragraph.",
        "image_url": "https://example.com/coast.jpg", "source_url": "https://example.com/story",
    }


def test_author_pages_require_login(author_client: AuthorClient) -> None:
    client, _, _ = author_client
    assert client.get("/author/login").status_code == 200
    slug = SAMPLE_POSTS[0]["slug"]
    for url in ("/author/posts", "/author/posts/new", f"/author/posts/{slug}/edit"):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/author/login"
    for url in ("/author/posts/new", f"/author/posts/{slug}/edit"):
        assert client.post(url, data={}, follow_redirects=False).status_code == 303


def test_login_failure_and_logout(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    response = client.post("/author/login", data={"username": "editor", "password": secrets.token_urlsafe(20)})
    assert response.status_code == 401
    assert "Invalid username or password" in response.text
    csrf = sign_in(client, password)
    assert client.post("/author/logout", data={"csrf_token": ""}).status_code == 403
    assert client.post("/author/logout", data={"csrf_token": csrf}, follow_redirects=False).status_code == 303
    assert SESSION_COOKIE not in client.cookies
    assert client.get("/author/posts", follow_redirects=False).status_code == 303


def test_cross_origin_login_blocked(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    response = client.post("/author/login", data={"username": "editor", "password": password}, headers={"Origin": "https://other.example"})
    assert response.status_code == 403


def test_admin_navigation_pill_follows_verified_session(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    pill = 'aria-label="Admin · Manage posts"'
    public_pages = ("/", f"/posts/{SAMPLE_POSTS[0]['slug']}", "/author/login")
    for url in public_pages:
        assert pill not in client.get(url).text
    csrf = sign_in(client, password)
    for url in ("/", public_pages[1], "/author/posts", "/author/posts/new"):
        response = client.get(url)
        assert response.status_code == 200
        assert pill in response.text
    client.post("/author/logout", data={"csrf_token": csrf})
    assert pill not in client.get("/").text
    client.cookies.set(SESSION_COOKIE, "invalid.signature")
    assert pill not in client.get("/").text


def test_create_edit_and_public_visibility(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    assert client.get("/author/posts/new").status_code == 200
    data = new_post(csrf)
    response = client.post("/author/posts/new", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert data["title"] in client.get("/").text
    assert "Second paragraph." in client.get("/posts/quiet-coast").text
    assert client.get("/images/quiet-coast.jpg").content == b"test-image"
    page = client.get("/author/posts/quiet-coast/edit")
    assert page.status_code == 200
    assert "First paragraph.\n\nSecond paragraph." in page.text
    data.update(title="The coast revisited", story="Revised story.", image_url="")
    assert client.post("/author/posts/quiet-coast/edit", data=data, follow_redirects=False).status_code == 303
    assert "The coast revisited" in client.get("/").text
    assert "Revised story." in client.get("/posts/quiet-coast").text
    assert client.get("/images/quiet-coast.jpg").content == b"test-image"


def test_edit_existing_seed_and_escape_html(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    slug = SAMPLE_POSTS[0]["slug"]
    data = new_post(csrf)
    data.update(title="<script>alert(1)</script>", image_url="")
    assert client.post(f"/author/posts/{slug}/edit", data=data, follow_redirects=False).status_code == 303
    page = client.get(f"/posts/{slug}")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert repository.get_post(slug)["image_source"] == SAMPLE_POSTS[0]["image_source"]


def test_invalid_forms_preserve_input_and_reject_csrf(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    data = new_post(csrf)
    assert client.post("/author/posts/new", data={**data, "csrf_token": "incorrect"}).status_code == 403
    response = client.post("/author/posts/new", data={**data, "published_at": "not-a-date"})
    assert response.status_code == 400
    assert 'action="/author/posts/new"' in response.text
    assert "A quiet coast" in response.text
    assert 'id="slug"' in response.text
    assert "readonly" not in response.text
    assert client.post("/author/posts/new", data={**data, "source_url": "javascript:alert(1)"}).status_code == 400
    assert client.post("/author/posts/new", data=data, follow_redirects=False).status_code == 303
    assert client.post("/author/posts/new", data=data).status_code == 400
    assert client.get("/author/posts/missing/edit").status_code == 404


def test_image_download_error_is_displayed(author_client: AuthorClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)

    def fail(url: str) -> tuple[bytes, str]:
        raise httpx.ConnectError("Image unavailable")

    monkeypatch.setattr(repository, "_download_image", fail)
    response = client.post("/author/posts/new", data=new_post(csrf))
    assert response.status_code == 400
    assert "Could not download the destination image" in response.text


def test_api_auth_and_invalid_json(author_client: AuthorClient) -> None:
    client, _, api_key = author_client
    assert client.get("/api/author/posts").status_code == 401
    headers = {"X-API-Key": api_key}
    assert client.get("/api/author/posts", headers=headers).status_code == 200
    assert client.post("/api/author/posts", headers=headers, json=[]).status_code == 400
    data = new_post("")
    assert client.post("/api/author/posts", headers=headers, json=data).status_code == 201
    assert client.put("/api/author/posts/quiet-coast", headers=headers, json={**data, "title": "API edit", "image_url": ""}).status_code == 200
    assert "API edit" in client.get("/posts/quiet-coast").text


def test_form_limits_and_encoding(author_client: AuthorClient) -> None:
    client, _, _ = author_client
    assert client.post("/author/login", json={}).status_code == 415
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    assert client.post("/author/login", content=b"x" * (routes.MAX_FORM_BYTES + 1), headers=headers).status_code == 413
    assert client.post("/author/login", content=b"\xff", headers=headers).status_code == 400


def test_cloud_restart_preserves_author_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_STORAGE_BLOB_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_TABLE_URL", raising=False)
    store = BlogRepository()
    store.is_cloud_backed = True
    entities: dict[str, dict] = {}

    def get_entity(partition: str, slug: str) -> dict:
        if slug not in entities:
            raise ResourceNotFoundError("missing")
        return entities[slug]

    def write(entity: dict) -> None:
        entities[entity["RowKey"]] = deepcopy(entity)

    store._table = MagicMock()
    store._table.get_entity.side_effect = get_entity
    store._table.create_entity.side_effect = write
    store._table.upsert_entity.side_effect = write
    store._container = MagicMock()
    store.initialize()
    edited = {**SAMPLE_POSTS[0], "title": "An author's lasting edit", "author": "editor"}
    store.save_post(edited)
    store.initialize()
    assert store.get_post(edited["slug"])["title"] == edited["title"]
    assert store._table.create_entity.call_count == len(SAMPLE_POSTS)


@pytest.mark.parametrize("raw", ["", "[]", "null", "broken", '{"users": []}'])
def test_invalid_auth_config_fails_closed(raw: str) -> None:
    assert not AuthorAuth(raw).is_configured


def test_local_config_is_not_loaded_on_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    get_auth.cache_clear()
    monkeypatch.delenv("AUTHOR_CONFIG", raising=False)
    monkeypatch.setenv("CONTAINER_APP_NAME", "cloud-app")
    path = MagicMock()
    monkeypatch.setattr(auth_module, "Path", path)
    try:
        assert not get_auth().is_configured
        path.assert_not_called()
    finally:
        get_auth.cache_clear()


def test_unconfigured_login_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "get_auth", lambda: AuthorAuth())
    with TestClient(app) as client:
        page = client.get("/author/login")
        assert page.status_code == 200
        assert "Author login is not configured" in page.text
        assert client.post("/author/login", data={}).status_code == 503


def image_bytes(image_format: str = "PNG", color: str = "coral") -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 20), color).save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_image_upload_publishes_real_image(author_client: AuthorClient, image_format: str) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    data = {**new_post(csrf), "image_url": ""}
    response = client.post("/author/posts/new", data=data, files={"image_file": ("../photo", image_bytes(image_format), "application/octet-stream")}, follow_redirects=False)
    assert response.status_code == 303
    post = repository.get_post("quiet-coast")
    assert post is not None
    assert post["image_blob"].startswith("quiet-coast-")
    assert ".." not in post["image_blob"]
    image = client.get(f"/images/{post['image_blob']}")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(image.content)) as decoded:
        assert decoded.size == (32, 20)
        assert decoded.format == "JPEG"
    assert f'/images/{post["image_blob"]}' in client.get("/posts/quiet-coast").text


def test_upload_replace_keep_and_url_priority(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    slug = SAMPLE_POSTS[0]["slug"]
    data = new_post(csrf)
    # A supplied file takes precedence over the URL and the download stub.
    response = client.post(f"/author/posts/{slug}/edit", data=data, files={"image_file": ("photo.png", image_bytes(), "image/png")}, follow_redirects=False)
    assert response.status_code == 303
    image_blob = repository.get_post(slug)["image_blob"]
    assert image_blob != SAMPLE_POSTS[0]["image_blob"]
    assert client.get(f"/images/{image_blob}").content.startswith(b"\xff\xd8")
    data["image_url"] = ""
    assert client.post(f"/author/posts/{slug}/edit", data=data, files={"image_file": ("", b"", "application/octet-stream")}, follow_redirects=False).status_code == 303
    assert repository.get_post(slug)["image_blob"] == image_blob


@pytest.mark.parametrize("content", [b"", b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x89PNG\r\n\x1a\ntruncated"])
def test_invalid_upload_preserves_story_form(author_client: AuthorClient, content: bytes) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    response = client.post("/author/posts/new", data={**new_post(csrf), "image_url": ""}, files={"image_file": ("photo.png", content, "image/png")})
    assert response.status_code == 400
    assert "A quiet coast" in response.text
    assert "choose it again" in response.text
    assert repository.get_post("quiet-coast") is None


def test_upload_requires_session_and_csrf(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    files = {"image_file": ("photo.png", image_bytes(), "image/png")}
    assert client.post("/author/posts/new", data=new_post(""), files=files, follow_redirects=False).status_code == 303
    sign_in(client, password)
    assert client.post("/author/posts/new", data=new_post(""), files=files).status_code == 403
    assert repository.get_post("quiet-coast") is None


def test_oversized_upload_rejected(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    for size in (MAX_IMAGE_BYTES + 1, MAX_IMAGE_BYTES + routes.MAX_FORM_BYTES + 1):
        response = client.post("/author/posts/new", data=new_post(csrf), files={"image_file": ("large.png", b"x" * size, "image/png")})
        assert response.status_code == 413
    assert repository.get_post("quiet-coast") is None


def test_image_pixel_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.storage import images
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValueError, match="megapixel"):
        normalize_upload(image_bytes())


def test_multiple_uploads_rejected(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    response = client.post("/author/posts/new", data=new_post(csrf), files=[("image_file", ("one.png", image_bytes(), "image/png")), ("image_file", ("two.png", image_bytes(), "image/png"))])
    assert response.status_code == 400


def test_upload_uses_cloud_blob_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_STORAGE_BLOB_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_TABLE_URL", raising=False)
    store = BlogRepository()
    store.is_cloud_backed = True
    store._container = MagicMock()
    store._table = MagicMock()
    saved = store.save_post({**SAMPLE_POSTS[0], "author": "editor"}, image_upload=image_bytes())
    store._container.get_blob_client.assert_called_once_with(saved["image_blob"])
    upload = store._container.get_blob_client.return_value.upload_blob.call_args
    assert upload.args[0].startswith(b"\xff\xd8")
    assert upload.kwargs["content_settings"].content_type == "image/jpeg"
    entity = store._table.upsert_entity.call_args.args[0]
    assert entity["image_blob"] == saved["image_blob"]


def test_create_without_image_uses_placeholder(author_client: AuthorClient) -> None:
    client, password, _ = author_client
    csrf = sign_in(client, password)
    data = new_post(csrf)
    data.pop("image_url")
    response = client.post(
        "/author/posts/new", data=data,
        files={"image_file": ("", b"", "application/octet-stream")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "A quiet coast" in client.get("/posts/quiet-coast").text
    post = repository.get_post("quiet-coast")
    assert post is not None
    image = client.get(f"/images/{post['image_blob']}")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/svg+xml"


def test_api_create_without_image(author_client: AuthorClient) -> None:
    client, _, api_key = author_client
    data = new_post("")
    data.pop("image_url")
    response = client.post("/api/author/posts", headers={"X-API-Key": api_key}, json=data)
    assert response.status_code == 201
    assert client.get("/posts/quiet-coast").status_code == 200