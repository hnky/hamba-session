import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .routers.author import api_router, author_navigation_context, router as author_router
from .storage.posts import posts as repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await run_in_threadpool(repository.initialize)
    except Exception:
        logger.exception("Storage initialization failed; bundled content remains available")
    yield


app = FastAPI(title="Hamba", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(
    directory=BASE_DIR / "templates", context_processors=[author_navigation_context]
)
app.state.templates = templates
app.include_router(author_router)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hamba"}


@app.get("/")
async def home(request: Request):
    try:
        posts = await run_in_threadpool(repository.list_posts)
    except Exception:
        logger.exception("Could not read posts from Table Storage; using bundled content")
        from .content import SAMPLE_POSTS
        posts = SAMPLE_POSTS
    return templates.TemplateResponse(request=request, name="index.html", context={"posts": posts})


@app.get("/posts/{slug}")
async def post_detail(request: Request, slug: str):
    try:
        post = await run_in_threadpool(repository.get_post, slug)
    except Exception:
        logger.exception("Could not read post from Table Storage")
        from .content import SAMPLE_POSTS
        post = next((item for item in SAMPLE_POSTS if item["slug"] == slug), None)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return templates.TemplateResponse(request=request, name="post.html", context={"post": post})


@app.get("/images/{blob_name}")
async def image(blob_name: str):
    try:
        result = await run_in_threadpool(repository.get_image, blob_name)
    except Exception:
        logger.exception("Could not read image from Blob Storage")
        result = None
    if result is None:
        return FileResponse(BASE_DIR / "static" / "placeholder.svg", media_type="image/svg+xml")
    content, content_type = result
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
