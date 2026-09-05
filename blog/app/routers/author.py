"""Authenticated author pages and per-user API-key endpoints."""

from __future__ import annotations

from datetime import date
import json
import re
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..auth import Author, SESSION_COOKIE, SESSION_MAX_AGE, get_auth
from ..storage.posts import posts

router = APIRouter(prefix="/author", tags=["author"])
api_router = APIRouter(prefix="/api/author", tags=["author-api"])
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_FORM_BYTES = 64 * 1024


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


async def _read_form(request: Request) -> dict[str, str]:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Expected a URL-encoded form")
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="Form is too large")
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _session(request: Request) -> tuple[Author, str] | None:
    return get_auth().read_session(request.cookies.get(SESSION_COOKIE))


def _require_session(request: Request) -> tuple[Author, str] | RedirectResponse:
    current = _session(request)
    if current is None:
        return RedirectResponse("/author/login", status_code=status.HTTP_303_SEE_OTHER)
    return current


def _check_csrf(form: dict[str, str], expected: str) -> None:
    if not expected or form.get("csrf_token") != expected:
        raise HTTPException(status_code=403, detail="Invalid form token")


def _post_values(data: dict[str, object], author: Author, existing: dict | None = None) -> tuple[dict, str | None]:
    slug = str(existing["slug"] if existing else data.get("slug", "")).strip().lower()
    title = str(data.get("title", "")).strip()
    lead = str(data.get("lead", "")).strip()
    published_at = str(data.get("published_at", "")).strip()
    source_url = str(data.get("source_url", "")).strip()
    image_url = str(data.get("image_url", "")).strip() or None
    raw_story = data.get("story", "")
    if isinstance(raw_story, list):
        story = [str(paragraph).strip() for paragraph in raw_story if str(paragraph).strip()]
    else:
        story = [paragraph.strip() for paragraph in str(raw_story).split("\n\n") if paragraph.strip()]

    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Slug must contain lowercase words separated by hyphens")
    if not title or len(title) > 160:
        raise ValueError("Title is required and must be at most 160 characters")
    if not lead or len(lead) > 400:
        raise ValueError("Lead is required and must be at most 400 characters")
    if not story or any(len(paragraph) > 4000 for paragraph in story):
        raise ValueError("Story requires at least one paragraph; each may be at most 4,000 characters")
    try:
        date.fromisoformat(published_at)
    except ValueError as exc:
        raise ValueError("Publication date must use YYYY-MM-DD") from exc
    if not existing and not image_url:
        raise ValueError("A destination image URL is required for a new post")

    return (
        {
            "slug": slug,
            "title": title,
            "lead": lead,
            "published_at": published_at,
            "image_blob": existing.get("image_blob") if existing else f"{slug}.jpg",
            "story": story,
            "source_url": source_url,
            "author": author.username,
        },
        image_url,
    )


def _api_author(api_key: str | None) -> Author:
    author = get_auth().verify_api_key(api_key or "")
    if author is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return author


@router.get("/login", response_class=Response)
async def login_page(request: Request) -> Response:
    if _session(request):
        return RedirectResponse("/author/posts", status_code=status.HTTP_303_SEE_OTHER)
    return _templates(request).TemplateResponse(
        request=request,
        name="author/login.html",
        context={"error": None, "configured": get_auth().is_configured},
    )


@router.post("/login", response_class=Response)
async def login(request: Request) -> Response:
    form = await _read_form(request)
    author = await run_in_threadpool(
        get_auth().verify_login, form.get("username", ""), form.get("password", "")
    )
    if author is None:
        return _templates(request).TemplateResponse(
            request=request,
            name="author/login.html",
            context={"error": "Invalid username or password.", "configured": get_auth().is_configured},
            status_code=401,
        )
    token, _ = get_auth().create_session(author)
    response = RedirectResponse("/author/posts", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", response_class=Response)
async def logout(request: Request) -> Response:
    current = _session(request)
    if current is not None:
        form = await _read_form(request)
        _check_csrf(form, current[1])
    response = RedirectResponse("/author/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/posts", response_class=Response)
async def author_posts(request: Request) -> Response:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    blog_posts = await run_in_threadpool(posts.list_posts)
    return _templates(request).TemplateResponse(
        request=request,
        name="author/list.html",
        context={"posts": blog_posts, "author": author, "csrf_token": csrf},
    )


@router.get("/posts/new", response_class=Response)
async def new_post_page(request: Request) -> Response:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    return _templates(request).TemplateResponse(
        request=request,
        name="author/edit.html",
        context={"post": None, "author": author, "csrf_token": csrf, "error": None},
    )


@router.post("/posts/new", response_class=Response)
async def create_post(request: Request) -> Response:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    form = await _read_form(request)
    _check_csrf(form, csrf)
    try:
        post, image_url = _post_values(form, author)
        if await run_in_threadpool(posts.get_post, post["slug"]):
            raise ValueError("A post with this slug already exists")
        await run_in_threadpool(posts.save_post, post, image_url)
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return _templates(request).TemplateResponse(
            request=request,
            name="author/edit.html",
            context={"post": form, "author": author, "csrf_token": csrf, "error": message},
            status_code=400,
        )
    return RedirectResponse("/author/posts", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/posts/{slug}/edit", response_class=Response)
async def edit_post_page(request: Request, slug: str) -> Response:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    post = await run_in_threadpool(posts.get_post, slug)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return _templates(request).TemplateResponse(
        request=request,
        name="author/edit.html",
        context={"post": post, "author": author, "csrf_token": csrf, "error": None},
    )


@router.post("/posts/{slug}/edit", response_class=Response)
async def update_post(request: Request, slug: str) -> Response:
    current = _require_session(request)
    if isinstance(current, RedirectResponse):
        return current
    author, csrf = current
    form = await _read_form(request)
    _check_csrf(form, csrf)
    existing = await run_in_threadpool(posts.get_post, slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="Post not found")
    try:
        post, image_url = _post_values(form, author, existing)
        await run_in_threadpool(posts.save_post, post, image_url)
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        display_post = {**existing, **form}
        return _templates(request).TemplateResponse(
            request=request,
            name="author/edit.html",
            context={"post": display_post, "author": author, "csrf_token": csrf, "error": message},
            status_code=400,
        )
    return RedirectResponse("/author/posts", status_code=status.HTTP_303_SEE_OTHER)


@api_router.get("/posts", response_class=JSONResponse)
async def api_list_posts(x_api_key: str | None = Header(default=None)) -> JSONResponse:
    _api_author(x_api_key)
    return JSONResponse(await run_in_threadpool(posts.list_posts))


@api_router.post("/posts", response_class=JSONResponse, status_code=201)
async def api_create_post(request: Request, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    author = _api_author(x_api_key)
    try:
        payload = await request.json()
        post, image_url = _post_values(payload, author)
        if await run_in_threadpool(posts.get_post, post["slug"]):
            raise ValueError("A post with this slug already exists")
        saved = await run_in_threadpool(posts.save_post, post, image_url)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(saved, status_code=201)


@api_router.put("/posts/{slug}", response_class=JSONResponse)
async def api_update_post(
    request: Request, slug: str, x_api_key: str | None = Header(default=None)
) -> JSONResponse:
    author = _api_author(x_api_key)
    existing = await run_in_threadpool(posts.get_post, slug)
    if existing is None:
        raise HTTPException(status_code=404, detail="Post not found")
    try:
        payload = await request.json()
        post, image_url = _post_values(payload, author, existing)
        saved = await run_in_threadpool(posts.save_post, post, image_url)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(saved)
