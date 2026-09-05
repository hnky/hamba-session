import json
import ipaddress
import logging
import os
from pathlib import Path
import socket
from urllib.parse import urljoin, urlparse

import httpx
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from .content import SAMPLE_POSTS

logger = logging.getLogger(__name__)


class BlogRepository:
    def __init__(self) -> None:
        self.table_name = os.getenv("AZURE_STORAGE_TABLE_NAME", "posts")
        self.container_name = os.getenv("AZURE_STORAGE_BLOB_CONTAINER", "images")
        blob_url = os.getenv("AZURE_STORAGE_BLOB_URL")
        table_url = os.getenv("AZURE_STORAGE_TABLE_URL")
        self.is_cloud_backed = bool(blob_url and table_url)
        self._table = None
        self._container = None
        self._local_posts = {post["slug"]: dict(post) for post in SAMPLE_POSTS}
        self._local_images: dict[str, tuple[bytes, str]] = {}

        if self.is_cloud_backed:
            credential = DefaultAzureCredential()
            self._table = TableServiceClient(table_url, credential=credential).get_table_client(self.table_name)
            self._container = BlobServiceClient(blob_url, credential=credential).get_container_client(self.container_name)

    def initialize(self) -> None:
        if not self.is_cloud_backed:
            logger.info("Storage endpoints are not configured; using bundled sample content")
            return

        try:
            self._table.create_table()
        except ResourceExistsError:
            pass
        try:
            self._container.create_container()
        except ResourceExistsError:
            pass

        with httpx.Client(timeout=15, follow_redirects=True) as client:
            for post in SAMPLE_POSTS:
                blob_client = self._container.get_blob_client(post["image_blob"])
                blob_properties = blob_client.get_blob_properties() if blob_client.exists() else None
                is_fallback = (
                    blob_properties is not None
                    and blob_properties.content_settings.content_type == "image/svg+xml"
                )
                if blob_properties is None or is_fallback:
                    try:
                        response = client.get(post["image_source"])
                        response.raise_for_status()
                        image = response.content
                        content_type = response.headers.get("content-type", "image/jpeg")
                    except Exception:
                        logger.warning("Could not fetch %s; uploading local fallback", post["image_source"], exc_info=True)
                        image = (Path(__file__).parent / "static" / "placeholder.svg").read_bytes()
                        content_type = "image/svg+xml"
                    blob_client.upload_blob(
                        image,
                        overwrite=True,
                        content_settings=ContentSettings(content_type=content_type),
                    )

                self._table.upsert_entity(
                    {
                        "PartitionKey": "published",
                        "RowKey": post["slug"],
                        "title": post["title"],
                        "lead": post["lead"],
                        "published_at": post["published_at"],
                        "image_blob": post["image_blob"],
                        "story": json.dumps(post["story"]),
                        "source_url": post["source_url"],
                    }
                )

    @staticmethod
    def _normalize(post: dict) -> dict:
        result = dict(post)
        story = result.get("story", [])
        result["story"] = json.loads(story) if isinstance(story, str) else story
        result["slug"] = result.get("RowKey", result.get("slug"))
        return result

    def list_posts(self) -> list[dict]:
        if not self.is_cloud_backed:
            return sorted(self._local_posts.values(), key=lambda item: item["published_at"], reverse=True)
        posts = [self._normalize(dict(item)) for item in self._table.query_entities("PartitionKey eq 'published'")]
        return sorted(posts, key=lambda item: item["published_at"], reverse=True)

    def get_post(self, slug: str) -> dict | None:
        if not self.is_cloud_backed:
            return self._local_posts.get(slug)
        try:
            return self._normalize(dict(self._table.get_entity("published", slug)))
        except ResourceNotFoundError:
            return None

    def get_image(self, blob_name: str) -> tuple[bytes, str] | None:
        if not self.is_cloud_backed:
            if blob_name in self._local_images:
                return self._local_images[blob_name]
            post = next(
                (item for item in self._local_posts.values() if item.get("image_blob") == blob_name),
                None,
            )
            if post is None or not post.get("image_source"):
                return None
            try:
                image = self._download_image(str(post["image_source"]))
            except (httpx.HTTPError, ValueError):
                logger.warning("Could not fetch local image %s", post["image_source"], exc_info=True)
                return None
            self._local_images[blob_name] = image
            return image
        try:
            downloader = self._container.download_blob(blob_name)
            properties = downloader.properties
            return downloader.readall(), properties.content_settings.content_type or "application/octet-stream"
        except ResourceNotFoundError:
            return None

    @staticmethod
    def _validate_public_image_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Image URL must use HTTP or HTTPS")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        except socket.gaierror as exc:
            raise ValueError("Image host could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Image URL must resolve to a public address")

    @classmethod
    def _download_image(cls, url: str) -> tuple[bytes, str]:
        current_url = url
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            for _ in range(4):
                cls._validate_public_image_url(current_url)
                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Image redirect has no destination")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if not content_type.startswith("image/"):
                        raise ValueError("Image URL did not return an image")
                    content_length = int(response.headers.get("content-length", "0"))
                    if content_length > 8 * 1024 * 1024:
                        raise ValueError("Image exceeds the 8 MB limit")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            raise ValueError("Image exceeds the 8 MB limit")
                        chunks.append(chunk)
                    return b"".join(chunks), content_type
        raise ValueError("Image redirected too many times")

    def save_post(self, post: dict, image_url: str | None = None) -> dict:
        image_blob = str(post.get("image_blob") or f"{post['slug']}.jpg")
        if image_url:
            image, content_type = self._download_image(image_url)
            if self.is_cloud_backed:
                self._container.get_blob_client(image_blob).upload_blob(
                    image,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                )
            else:
                self._local_images[image_blob] = (image, content_type)

        saved = {
            "slug": str(post["slug"]),
            "title": str(post["title"]),
            "lead": str(post["lead"]),
            "published_at": str(post["published_at"]),
            "image_blob": image_blob,
            "story": list(post["story"]),
            "source_url": str(post.get("source_url", "")),
            "image_source": str(image_url or post.get("image_source", "")),
            "author": str(post["author"]),
        }
        if not self.is_cloud_backed:
            self._local_posts[saved["slug"]] = saved
            return saved

        self._table.upsert_entity(
            {
                "PartitionKey": "published",
                "RowKey": saved["slug"],
                "title": saved["title"],
                "lead": saved["lead"],
                "published_at": saved["published_at"],
                "image_blob": saved["image_blob"],
                "story": json.dumps(saved["story"]),
                "source_url": saved["source_url"],
                "author": saved["author"],
            }
        )
        return saved
