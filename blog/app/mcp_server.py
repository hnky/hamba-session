"""Authenticated FastMCP article endpoint for the Hamba live demo.

The server exposes story publishing and public article summaries. Managed keys
come from the admin UI; legacy AUTHOR_CONFIG API keys remain REST-only.

Requests check the host and Bearer key before listing summaries or publishing.
Publishing never overwrites an existing story and requires client-side approval;
an accepted add_story call publishes immediately.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging
import os
from typing import Annotated

import httpx
from azure.core.exceptions import AzureError
from fastapi.concurrency import run_in_threadpool
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .auth import Author, get_auth
from .repository import DuplicatePostError
from .routers.author import post_values
from .storage.posts import posts

logger = logging.getLogger(__name__)


def _trusted_hosts() -> list[str]:
    """Allow local/test server names plus deployed names supplied by configuration."""
    # These are destination server hostnames, not a list of permitted clients.
    hosts = ["localhost", "127.0.0.1", "testserver"]
    for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(","):
        if host.strip():
            hosts.append(host.strip())
    return hosts


class ManagedApiKeyVerifier(TokenVerifier):
    """Authenticate managed keys and restrict MCP access to admins."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return a verified identity, or None so the transport rejects the request."""
        try:
            # The repository checks the stored key hash and revocation status.
            # Its storage calls are synchronous, so keep them off the event loop.
            username = await run_in_threadpool(posts.verify_api_key, token)
            author = get_auth().get_author(username) if username else None
        except Exception:
            # Fail closed: a storage/configuration failure must never grant access.
            logger.exception("Managed API key verification failed")
            return None
        if author is None or not author.is_admin:
            return None
        # Carry the verified username into the tool's request context.
        return AccessToken(
            token=token,
            client_id=f"hamba-managed-key:{author.username}",
            subject=author.username,
            scopes=["add_story", "list_articles"],
        )


def _current_author() -> Author:
    """Resolve the request identity; admin authorization belongs to the verifier."""
    # Read identity from the authenticated request, never from tool arguments.
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("Authentication is required to use MCP tools.")

    author = get_auth().get_author(token.subject)
    if author is None:
        raise ToolError("Authentication is required to use MCP tools.")
    return author


@contextmanager
def _publishing_errors() -> Iterator[None]:
    """Translate publishing failures into safe MCP errors; log internal details."""
    try:
        yield
    except DuplicatePostError as exc:
        raise ToolError("A story with this slug already exists.") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ToolError("Could not download the destination image.") from exc
    except AzureError as exc:
        logger.exception("Story storage failed")
        raise ToolError("Story storage is unavailable. Please try again.") from exc
    except Exception as exc:
        logger.exception("Unexpected story publication failure")
        raise ToolError("The story could not be published. Please try again.") from exc


# These types describe the tool's public input schema to MCP clients.
# Field constraints enforce shape and size; post_values checks content semantics
# such as valid dates and URLs, using the same rules as the author UI and REST API.
Slug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Public identifier containing lowercase words separated by hyphens.",
        examples=["uganda-where-the-earth-breathes-green"],
    ),
]
Title = Annotated[
    str,
    Field(min_length=1, max_length=160, description="Story title, up to 160 characters."),
]
Lead = Annotated[
    str,
    Field(min_length=1, max_length=400, description="Story introduction, up to 400 characters."),
]
Paragraph = Annotated[str, Field(min_length=1, max_length=4000)]
Story = Annotated[
    list[Paragraph],
    Field(
        min_length=1,
        max_length=100,
        description="Between 1 and 100 nonempty paragraphs; each may contain up to 4,000 characters.",
    ),
]
OptionalUrl = Annotated[
    str | None,
    Field(max_length=2048, description="Optional absolute HTTP or HTTPS URL, up to 2,048 characters."),
]
PublicationDate = Annotated[
    str,
    Field(
        min_length=10,
        max_length=64,
        description=(
            "Publication date as YYYY-MM-DD or an ISO 8601 datetime. "
            "Datetime values are normalized to their calendar date."
        ),
        examples=["2025-01-01", "2025-01-01T00:00:00Z"],
    ),
]


class AddStoryResult(BaseModel):
    """Expose only the published story's identifier, title, and relative page URL."""

    slug: str
    title: str
    path: str


class ArticleSummary(BaseModel):
    """Public summary only; never serialize a complete repository record."""

    slug: str
    title: str
    lead: str
    published_at: str
    author: str = ""
    path: str
    source_url: str = ""


class ListArticlesResult(BaseModel):
    """All published article summaries in repository order, newest first."""

    articles: list[ArticleSummary]


# Authentication applies to the MCP server, including tool discovery and calls.
# Unexpected errors are masked; deliberate ToolError messages remain client-visible.
mcp = FastMCP(
    name="Hamba Publishing",
    instructions=(
        "List public Hamba article summaries before publishing new travel stories. "
        "list_articles is read-only; add_story writes immediately and requires approval."
    ),
    auth=ManagedApiKeyVerifier(),
    mask_error_details=True,
    strict_input_validation=True,
)


# Annotations help clients explain the action; they do not enforce user approval.
# This tool writes new content and may download an image from an external URL.
@mcp.tool(
    description=(
        "Create and immediately publish a new Hamba travel story. "
        "Rejects an existing slug instead of overwriting it."
    ),
    annotations=ToolAnnotations(
        title="Publish a Hamba story",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)
async def add_story(
    slug: Slug,
    title: Title,
    lead: Lead,
    published_at: PublicationDate,
    story: Story,
    source_url: OptionalUrl = None,
    image_url: OptionalUrl = None,
) -> AddStoryResult:
    """Validate and publish a story; the client is responsible for approval."""
    author = _current_author()
    # Adapt MCP arguments to the existing shared post validator.
    values: dict[str, object] = {
        "slug": slug,
        "title": title,
        "lead": lead,
        "published_at": published_at,
        "story": story,
        "source_url": source_url or "",
        "image_url": image_url or "",
    }

    with _publishing_errors():
        # Normalize content (including datetime -> calendar date) before storage.
        post, normalized_image_url = post_values(values, author)
        # Create-only storage rejects duplicate slugs instead of updating a story.
        saved = await run_in_threadpool(posts.create_post, post, normalized_image_url)

    return AddStoryResult(
        slug=saved["slug"],
        title=saved["title"],
        path=f"/posts/{saved['slug']}",
    )


@mcp.tool(
    description=(
        "List public article summaries for all published Hamba articles, newest first. "
        "Reads only Hamba's own storage; does not return full stories or image details."
    ),
    annotations=ToolAnnotations(
        title="List Hamba articles",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_articles() -> ListArticlesResult:
    """Read published summaries without exposing internal repository fields."""
    _current_author()
    try:
        published = await run_in_threadpool(posts.list_posts)
        return ListArticlesResult(articles=[
            ArticleSummary(
                slug=post["slug"],
                title=post["title"],
                lead=post["lead"],
                published_at=post["published_at"],
                author=post.get("author") or "",
                path=f"/posts/{post['slug']}",
                source_url=post.get("source_url") or "",
            )
            for post in published
        ])
    except Exception as exc:
        logger.exception("Article listing failed")
        raise ToolError("Articles could not be listed. Please try again.") from exc


# The main FastAPI app serves this authenticated ASGI app at /mcp.
# Stateless HTTP needs no persistent MCP session between requests.
# Host/Origin checks add DNS-rebinding protection; Bearer keys authenticate callers.
mcp_http_app = mcp.http_app(
    path="/mcp",
    stateless_http=True,
    host_origin_protection=True,
    allowed_hosts=_trusted_hosts(),
    allowed_origins=[],  # Do not add extra browser origins to the transport's policy.
)