"""Admin HTML key management only; no API authentication or API endpoints."""

import re

from azure.core.exceptions import AzureError
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response

from ..auth import Author
from ..storage.posts import posts
from .author import _check_csrf, _read_form, _require_session, _templates

router = APIRouter(prefix="/author/api-keys", tags=["author-key-management"])
PRIVATE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "Vary": "Cookie",
}


def _require_admin(request: Request) -> tuple[Author, str] | RedirectResponse:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    if not current[0].is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return current


@router.get("", response_class=Response)
async def key_list(request: Request) -> Response:
    current = _require_admin(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    try:
        keys = await run_in_threadpool(posts.list_api_keys, author.username)
    except AzureError as exc:
        raise HTTPException(status_code=503, detail="Key storage is unavailable. Please try again.", headers=PRIVATE_HEADERS) from exc
    return _templates(request).TemplateResponse(
        request=request, name="author/api_keys.html",
        context={"author": author, "csrf_token": csrf, "keys": keys},
        headers=PRIVATE_HEADERS,
    )


@router.post("", response_class=Response)
async def key_create(request: Request) -> Response:
    current = _require_admin(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    form = await _read_form(request)
    _check_csrf(form, csrf)
    try:
        metadata, raw_key = await run_in_threadpool(posts.create_api_key, author.username, form.get("name", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc), headers=PRIVATE_HEADERS) from exc
    except AzureError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not confirm key creation. Check the key list before retrying; revoke any key whose value was not shown.",
            headers=PRIVATE_HEADERS,
        ) from exc
    return _templates(request).TemplateResponse(
        request=request, name="author/api_key_created.html",
        context={"author": author, "csrf_token": csrf, "key": metadata, "raw_key": raw_key},
        headers=PRIVATE_HEADERS, status_code=201,
    )


@router.post("/{key_id}/revoke", response_class=Response)
async def key_revoke(request: Request, key_id: str) -> Response:
    current = _require_admin(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    form = await _read_form(request)
    _check_csrf(form, csrf)
    if not re.fullmatch(r"[0-9a-f]{32}", key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    try:
        revoked = await run_in_threadpool(posts.revoke_api_key, author.username, key_id)
    except AzureError as exc:
        raise HTTPException(status_code=503, detail="Could not revoke the key. Please try again.", headers=PRIVATE_HEADERS) from exc
    if not revoked:
        raise HTTPException(status_code=404, detail="Key not found")
    return RedirectResponse("/author/api-keys", status_code=303, headers=PRIVATE_HEADERS)