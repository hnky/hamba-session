"""Key-management lifecycle and permissions; no API implementation."""

from collections.abc import Iterator
from copy import deepcopy
import hashlib
import json
import re
import secrets
from unittest.mock import MagicMock

from azure.core.exceptions import AzureError, ResourceNotFoundError
from fastapi.testclient import TestClient
import pytest

from app.auth import AuthorAuth, SESSION_COOKIE
from app.main import app, repository
from app.repository import BlogRepository
from app.routers import author as author_routes


@pytest.fixture
def admin_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    users = [
        {"username": username, "password_hash": AuthorAuth.hash_password(secrets.token_urlsafe(24)),
         "api_key_hash": AuthorAuth.hash_api_key(secrets.token_urlsafe(32))}
        for username in ("admin", "editor")
    ]
    auth = AuthorAuth(json.dumps({"session_secret": secrets.token_urlsafe(48), "users": users}))
    monkeypatch.setattr(author_routes, "get_auth", lambda: auth)
    monkeypatch.setattr(repository, "is_cloud_backed", False)
    monkeypatch.setattr(repository, "_local_api_keys", {})
    with TestClient(app, base_url="https://testserver") as client:
        author = auth._authors["admin"]
        token, _ = auth.create_session(author)
        client.cookies.set(SESSION_COOKIE, token)
        yield client


def csrf_token(client: TestClient) -> str:
    page = client.get("/author/api-keys")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match
    return match.group(1)


def test_admin_can_create_list_and_revoke(admin_client: TestClient) -> None:
    client = admin_client
    csrf = csrf_token(client)
    assert 'href="/author/api-keys"' in client.get("/author/posts").text
    response = client.post("/author/api-keys", data={"csrf_token": csrf, "name": "Publishing"})
    assert response.status_code == 201
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["referrer-policy"] == "no-referrer"
    key = re.search(r'hamba_[0-9a-f]{32}_[A-Za-z0-9_-]{43}', response.text)
    assert key is not None
    raw_key = key.group(0)
    stored = next(iter(repository._local_api_keys.values()))
    assert stored["key_hash"] == "sha256$" + hashlib.sha256(raw_key.encode()).hexdigest()
    assert raw_key not in json.dumps(repository._local_api_keys)
    assert len(repository.list_api_keys("admin")) == 1
    assert "key_hash" not in repository.list_api_keys("admin")[0]
    page = client.get("/author/api-keys")
    assert "Publishing" in page.text and "Active" in page.text
    assert raw_key not in page.text and stored["key_hash"] not in page.text
    assert "no-store" in page.headers["cache-control"]
    result = client.post(f"/author/api-keys/{stored['RowKey']}/revoke", data={"csrf_token": csrf}, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == "/author/api-keys"
    assert repository.list_api_keys("admin")[0]["revoked_at"]
    assert "Revoked" in client.get("/author/api-keys").text
    assert client.post(f"/author/api-keys/{stored['RowKey']}/revoke", data={"csrf_token": csrf}, follow_redirects=False).status_code == 303
    # These keys are deliberately not wired to any API authentication yet.
    assert client.get("/api/author/posts", headers={"X-API-Key": raw_key}).status_code == 401


def test_new_keys_are_unique_and_separate_from_posts(admin_client: TestClient) -> None:
    initial_posts = len(repository.list_posts())
    first, first_key = repository.create_api_key("admin", "Same name")
    second, second_key = repository.create_api_key("admin", "Same name")
    assert first_key != second_key
    assert first["id"] != second["id"]
    assert len(repository.list_posts()) == initial_posts
    assert repository.get_post(first["id"]) is None
    assert repository.list_api_keys("editor") == []
    assert not repository.revoke_api_key("editor", first["id"])
    assert not repository.list_api_keys("admin")[0]["revoked_at"]


def test_anonymous_and_forged_sessions_cannot_manage_keys(admin_client: TestClient) -> None:
    client = admin_client
    for token in (None, "invalid.signature"):
        client.cookies.clear()
        if token:
            client.cookies.set(SESSION_COOKIE, token)
        assert client.get("/author/api-keys", follow_redirects=False).status_code == 303
        for url in ("/author/api-keys", f"/author/api-keys/{'a' * 32}/revoke"):
            response = client.post(url, data={"name": "Not allowed"}, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/author/login"
    assert repository.list_api_keys("admin") == []


def test_non_admin_author_is_forbidden(admin_client: TestClient) -> None:
    client = admin_client
    auth = author_routes.get_auth()
    token, csrf = auth.create_session(auth._authors["editor"])
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, token)
    assert 'href="/author/api-keys"' not in client.get("/author/posts").text
    assert client.get("/author/api-keys").status_code == 403
    for url in ("/author/api-keys", f"/author/api-keys/{'a' * 32}/revoke"):
        assert client.post(url, data={"name": "Not allowed", "csrf_token": csrf}).status_code == 403


def test_management_requires_csrf_and_post(admin_client: TestClient) -> None:
    client = admin_client
    metadata, _ = repository.create_api_key("admin", "Keep me")
    for url in ("/author/api-keys", f"/author/api-keys/{metadata['id']}/revoke"):
        for csrf in ("", "forged"):
            assert client.post(url, data={"name": "Invalid request", "csrf_token": csrf}).status_code == 403
    assert client.get(f"/author/api-keys/{metadata['id']}/revoke").status_code == 405
    assert len(repository.list_api_keys("admin")) == 1
    assert not repository.list_api_keys("admin")[0]["revoked_at"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "bad\nname"])
def test_invalid_key_names_rejected(admin_client: TestClient, name: str) -> None:
    response = admin_client.post("/author/api-keys", data={"csrf_token": csrf_token(admin_client), "name": name})
    assert response.status_code == 400
    assert repository.list_api_keys("admin") == []


def test_key_names_are_escaped(admin_client: TestClient) -> None:
    name = '<script>alert("test")</script>'
    response = admin_client.post("/author/api-keys", data={"csrf_token": csrf_token(admin_client), "name": name})
    assert response.status_code == 201
    assert name not in response.text
    assert "&lt;script&gt;" in response.text
    page = admin_client.get("/author/api-keys")
    assert name not in page.text
    assert "&lt;script&gt;" in page.text


@pytest.mark.parametrize("key_id", ["not-a-key", "a" * 32])
def test_missing_key_revoke_is_404(admin_client: TestClient, key_id: str) -> None:
    response = admin_client.post(f"/author/api-keys/{key_id}/revoke", data={"csrf_token": csrf_token(admin_client)})
    assert response.status_code == 404


def test_storage_errors_do_not_expose_details(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    csrf = csrf_token(admin_client)
    for method, url in (("create_api_key", "/author/api-keys"), ("revoke_api_key", f"/author/api-keys/{'a' * 32}/revoke")):
        monkeypatch.setattr(repository, method, MagicMock(side_effect=AzureError("internal storage details")))
        response = admin_client.post(url, data={"csrf_token": csrf, "name": "New key"})
        assert response.status_code == 503
        assert "internal storage details" not in response.text
    monkeypatch.setattr(repository, "list_api_keys", MagicMock(side_effect=AzureError("internal storage details")))
    response = admin_client.get("/author/api-keys")
    assert response.status_code == 503
    assert "internal storage details" not in response.text


def test_cloud_keys_survive_repository_recreation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_STORAGE_BLOB_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_TABLE_URL", raising=False)
    entities: dict[str, dict] = {}
    table = MagicMock()

    def create(entity: dict) -> None:
        assert entity["PartitionKey"] == "api-keys"
        entities[entity["RowKey"]] = deepcopy(entity)

    def get(partition: str, key_id: str) -> dict:
        assert partition == "api-keys"
        if key_id not in entities:
            raise ResourceNotFoundError("missing")
        return deepcopy(entities[key_id])

    def query(query_filter: str, parameters: dict, select: list[str]) -> list[dict]:
        assert query_filter == "PartitionKey eq @partition and created_by eq @owner"
        assert parameters["partition"] == "api-keys"
        assert "key_hash" not in select
        return [{key: value for key, value in entity.items() if key in select}
                for entity in entities.values() if entity["created_by"] == parameters["owner"]]

    def update(entity: dict, mode: str) -> None:
        assert mode == "merge"
        entities[entity["RowKey"]].update(entity)

    table.create_entity.side_effect = create
    table.get_entity.side_effect = get
    table.query_entities.side_effect = query
    table.update_entity.side_effect = update
    first = BlogRepository()
    first.is_cloud_backed = True
    first._table = table
    metadata, raw_key = first.create_api_key("admin", "Persistent key")
    assert raw_key not in json.dumps(entities)
    second = BlogRepository()
    second.is_cloud_backed = True
    second._table = table
    assert second.list_api_keys("admin")[0]["id"] == metadata["id"]
    assert second.list_api_keys("editor") == []
    assert not second.revoke_api_key("editor", metadata["id"])
    assert not second.revoke_api_key("admin", "missing")
    assert second.revoke_api_key("admin", metadata["id"])
    assert first.list_api_keys("admin")[0]["revoked_at"]
    assert second.revoke_api_key("admin", metadata["id"])
    assert table.update_entity.call_count == 1