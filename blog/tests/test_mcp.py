"""End-to-end tests for the authenticated MCP HTTP transport."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
from typing import Any

from azure.core.exceptions import AzureError
from fastapi.testclient import TestClient
import pytest

from app import mcp_server
from app.auth import AuthorAuth
from app.main import app, repository

MCP_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"


@pytest.fixture
def mcp_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, str]]:
    auth = _auth("admin")
    monkeypatch.setattr(mcp_server, "get_auth", lambda: auth)
    monkeypatch.setattr(repository, "is_cloud_backed", False)
    monkeypatch.setattr(repository, "_local_posts", {})
    monkeypatch.setattr(repository, "_local_images", {})
    monkeypatch.setattr(repository, "_local_api_keys", {})
    _, raw_key = repository.create_api_key("admin", "MCP tests")
    with TestClient(app, base_url="http://testserver") as client:
        yield client, raw_key


def _auth(*usernames: str) -> AuthorAuth:
    return AuthorAuth(json.dumps({
        "session_secret": secrets.token_urlsafe(48),
        "users": [
            {
                "username": username,
                "password_hash": "unused",
                "api_key_hash": "unused",
            }
            for username in usernames
        ],
    }))


def _headers(raw_key: str, method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    return headers


def _modern_meta() -> dict[str, object]:
    return {
        "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "hamba-tests", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _modern_request(
    client: TestClient,
    raw_key: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> Any:
    request_params = dict(params or {})
    request_params["_meta"] = _modern_meta()
    name = str(request_params["name"]) if method == "tools/call" else None
    return client.post(
        "/mcp",
        headers=_headers(raw_key, method, name),
        json={"jsonrpc": "2.0", "id": secrets.randbelow(1_000_000), "method": method, "params": request_params},
    )


def _story(slug: str = "mcp-story", title: str = "Across the salt pans") -> dict[str, object]:
    return {
        "slug": slug,
        "title": title,
        "lead": "A patient journey across a changing landscape.",
        "published_at": "2026-09-05",
        "story": ["The first paragraph.", "The second paragraph."],
        "source_url": "https://example.com/story",
    }


def test_modern_discovery_lists_exactly_one_safe_tool(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    discovery = _modern_request(client, raw_key, "server/discover")
    assert discovery.status_code == 200
    assert MCP_VERSION in discovery.json()["result"]["supportedVersions"]

    response = _modern_request(client, raw_key, "tools/list")
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["add_story"]
    tool = tools[0]
    assert tool["annotations"] == {
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
        "readOnlyHint": False,
        "title": "Publish a Hamba story",
    }
    serialized = json.dumps(tool).lower()
    assert raw_key not in serialized
    assert "key_hash" not in serialized
    assert "author" not in tool["inputSchema"]["properties"]


def test_legacy_initialization_and_tool_listing(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Accept": "application/json, text/event-stream",
    }
    initialized = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LEGACY_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "legacy-test", "version": "1"},
        },
    })
    assert initialized.status_code == 200
    assert _response_json(initialized)["result"]["protocolVersion"] == LEGACY_VERSION

    listed = client.post(
        "/mcp",
        headers={**headers, "MCP-Protocol-Version": LEGACY_VERSION},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert listed.status_code == 200
    assert [tool["name"] for tool in _response_json(listed)["result"]["tools"]] == ["add_story"]


def _response_json(response: Any) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        return json.loads(data)
    return response.json()


def test_add_story_publishes_with_verified_owner(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    response = _modern_request(
        client,
        raw_key,
        "tools/call",
        {"name": "add_story", "arguments": _story()},
    )
    result = response.json()["result"]
    assert response.status_code == 200
    assert not result["isError"]
    assert result["structuredContent"] == {
        "slug": "mcp-story",
        "title": "Across the salt pans",
        "path": "/posts/mcp-story",
    }
    assert repository.get_post("mcp-story")["author"] == "admin"
    page = client.get("/posts/mcp-story")
    assert page.status_code == 200
    assert "The second paragraph." in page.text
    image = client.get("/images/mcp-story.jpg")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/svg+xml"
    serialized = json.dumps(result)
    assert raw_key not in serialized
    assert "sha256$" not in serialized


def test_add_story_image_and_duplicate_errors_are_safe(
    mcp_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, raw_key = mcp_client
    monkeypatch.setattr(repository, "_download_image", lambda _: (b"image", "image/jpeg"))
    arguments = {**_story(), "image_url": "https://example.com/image.jpg"}
    first = _modern_request(client, raw_key, "tools/call", {"name": "add_story", "arguments": arguments})
    assert not first.json()["result"]["isError"]
    saved = repository.get_post("mcp-story")
    assert saved is not None
    assert repository.get_image(saved["image_blob"]) == (b"image", "image/jpeg")

    duplicate = _modern_request(
        client,
        raw_key,
        "tools/call",
        {"name": "add_story", "arguments": {**arguments, "title": "Replacement"}},
    )
    assert duplicate.json()["result"]["isError"]
    assert "already exists" in duplicate.json()["result"]["content"][0]["text"]
    assert repository.get_post("mcp-story")["title"] == "Across the salt pans"
    assert raw_key not in duplicate.text


def test_validation_rejects_invalid_story(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    for changes in ({"slug": "Bad Slug"}, {"published_at": "not-a-date"}, {"story": []}):
        response = _modern_request(
            client,
            raw_key,
            "tools/call",
            {"name": "add_story", "arguments": {**_story(), **changes}},
        )
        assert response.status_code == 200
        assert response.json()["result"]["isError"]
    assert repository.get_post("mcp-story") is None


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic invalid"},
        {"Authorization": "Bearer malformed"},
        {"Authorization": "Bearer malformed extra"},
        {"X-API-Key": "ignored"},
    ],
)
def test_rejects_missing_malformed_and_alternative_credentials(
    mcp_client: tuple[TestClient, str], headers: dict[str, str]
) -> None:
    client, _ = mcp_client
    response = client.post(
        "/mcp?access_token=ignored",
        headers={"Accept": "application/json, text/event-stream", "Cookie": "hamba_author=ignored", **headers},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_tampering_revocation_and_removed_owner_take_effect_immediately(
    mcp_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, raw_key = mcp_client
    assert _modern_request(client, raw_key, "tools/list").status_code == 200
    tampered = raw_key[:-1] + ("A" if raw_key[-1] != "A" else "B")
    assert _modern_request(client, tampered, "tools/list").status_code == 401

    key_id = raw_key.split("_", 2)[1]
    assert repository.revoke_api_key("admin", key_id)
    assert _modern_request(client, raw_key, "tools/list").status_code == 401

    _, replacement = repository.create_api_key("admin", "Removed owner")
    monkeypatch.setattr(mcp_server, "get_auth", lambda: _auth("editor"))
    assert _modern_request(client, replacement, "tools/list").status_code == 401


def test_concurrent_callers_do_not_share_authentication(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    invalid_key = raw_key[:-1] + ("A" if raw_key[-1] != "A" else "B")
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda key: _modern_request(client, key, "tools/list").status_code, (raw_key, invalid_key)))
    assert sorted(statuses) == [200, 401]


def test_storage_failure_fails_closed_without_exposing_key(
    mcp_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, raw_key = mcp_client
    monkeypatch.setattr(repository, "verify_api_key", lambda _: (_ for _ in ()).throw(AzureError("storage details")))
    response = _modern_request(client, raw_key, "tools/list")
    assert response.status_code == 401
    assert raw_key not in response.text
    assert raw_key not in caplog.text
    assert "storage details" not in response.text


def test_story_storage_failure_is_sanitized(
    mcp_client: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, raw_key = mcp_client
    monkeypatch.setattr(
        repository,
        "create_post",
        lambda *_: (_ for _ in ()).throw(AzureError("internal table details")),
    )
    response = _modern_request(
        client,
        raw_key,
        "tools/call",
        {"name": "add_story", "arguments": _story()},
    )
    result = response.json()["result"]
    assert result["isError"]
    assert "Story storage is unavailable" in result["content"][0]["text"]
    assert "internal table details" not in response.text
    assert raw_key not in response.text


def test_host_origin_and_endpoint_protection(mcp_client: tuple[TestClient, str]) -> None:
    client, raw_key = mcp_client
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _modern_meta()}}
    headers = _headers(raw_key, "tools/list")
    assert client.post("/mcp", headers={**headers, "Host": "evil.example"}, json=payload).status_code == 421
    assert client.post("/mcp", headers={**headers, "Origin": "https://evil.example"}, json=payload).status_code == 403
    trailing = client.post("/mcp/", headers=headers, json=payload, follow_redirects=False)
    assert trailing.status_code == 307
    assert trailing.headers["location"] == "http://testserver/mcp"
    assert client.get("/health").json() == {"status": "ok", "service": "hamba"}


def test_repeated_application_lifecycles(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = _auth("admin")
    monkeypatch.setattr(mcp_server, "get_auth", lambda: auth)
    monkeypatch.setattr(repository, "is_cloud_backed", False)
    monkeypatch.setattr(repository, "_local_api_keys", {})
    _, raw_key = repository.create_api_key("admin", "Lifecycle")
    for _ in range(2):
        with TestClient(app, base_url="http://testserver") as client:
            assert _modern_request(client, raw_key, "tools/list").status_code == 200
