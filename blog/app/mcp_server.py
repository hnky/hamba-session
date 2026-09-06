"""Authenticated FastMCP publishing endpoint for the Hamba live demo.

The server deliberately exposes one immediately-publishing tool. Managed keys
come from the admin UI; legacy AUTHOR_CONFIG API keys remain REST-only.
"""

from __future__ import annotations

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

from .auth import get_auth
from .repository import DuplicatePostError
from .routers.author import post_values
from .storage.posts import posts

logger = logging.getLogger(__name__)


def _trusted_hosts() -> list[str]:
    configured = [host.strip() for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")]
    return ["localhost", "127.0.0.1", "testserver", *(host for host in configured if host)]


class ManagedApiKeyVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            username = await run_in_threadpool(posts.verify_api_key, token)
            author = get_auth().get_author(username) if username else None
        except Exception:
            logger.exception("Managed API key verification failed")
            return None
        if author is None or not author.is_admin:
            return None
        return AccessToken(
            token=token,
            client_id=f"hamba-managed-key:{author.username}",
            subject=author.username,
            scopes=["add_story"],
        )


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
Title = Annotated[str, Field(min_length=1, max_length=160, description="Story title, up to 160 characters.")]
Lead = Annotated[str, Field(min_length=1, max_length=400, description="Story introduction, up to 400 characters.")]
Paragraph = Annotated[str, Field(min_length=1, max_length=4000)]
Story = Annotated[
    list[Paragraph],
    Field(min_length=1, max_length=100, description="Between 1 and 100 nonempty paragraphs; each may contain up to 4,000 characters."),
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
    slug: str
    title: str
    path: str


mcp = FastMCP(
    name="Hamba Publishing",
    instructions="Publish new Hamba travel stories. Every tool call writes immediately and requires approval.",
    auth=ManagedApiKeyVerifier(),
    mask_error_details=True,
    strict_input_validation=True,
)


@mcp.tool(
    description="Create and immediately publish a new Hamba travel story. Rejects an existing slug instead of overwriting it.",
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
    """Create and publish a story immediately after the client approves the call."""
    access_token = get_access_token()
    username = access_token.subject if access_token is not None else None
    author = get_auth().get_author(username) if username else None
    if author is None or not author.is_admin:
        raise ToolError("Authentication is required to publish a story.")

    try:
        post, normalized_image_url = post_values(
            {
                "slug": slug,
                "title": title,
                "lead": lead,
                "published_at": published_at,
                "story": story,
                "source_url": source_url or "",
                "image_url": image_url or "",
            },
            author,
        )
        saved = await run_in_threadpool(posts.create_post, post, normalized_image_url)
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

    return AddStoryResult(slug=saved["slug"], title=saved["title"], path=f"/posts/{saved['slug']}")


mcp_http_app = mcp.http_app(
    path="/mcp",
    stateless_http=True,
    host_origin_protection=True,
    allowed_hosts=_trusted_hosts(),
    allowed_origins=[],
)