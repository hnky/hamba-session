import json
import logging
import os
from pathlib import Path

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

        seeded_slugs = {post["slug"] for post in SAMPLE_POSTS}
        for entity in self._table.query_entities(
            "PartitionKey eq 'published'", select=["PartitionKey", "RowKey"]
        ):
            if entity["RowKey"] not in seeded_slugs:
                self._table.delete_entity(entity["PartitionKey"], entity["RowKey"])

    @staticmethod
    def _normalize(post: dict) -> dict:
        result = dict(post)
        story = result.get("story", [])
        result["story"] = json.loads(story) if isinstance(story, str) else story
        result["slug"] = result.get("RowKey", result.get("slug"))
        return result

    def list_posts(self) -> list[dict]:
        if not self.is_cloud_backed:
            return sorted(SAMPLE_POSTS, key=lambda item: item["published_at"], reverse=True)
        posts = [self._normalize(dict(item)) for item in self._table.query_entities("PartitionKey eq 'published'")]
        return sorted(posts, key=lambda item: item["published_at"], reverse=True)

    def get_post(self, slug: str) -> dict | None:
        if not self.is_cloud_backed:
            return next((post for post in SAMPLE_POSTS if post["slug"] == slug), None)
        try:
            return self._normalize(dict(self._table.get_entity("published", slug)))
        except ResourceNotFoundError:
            return None

    def get_image(self, blob_name: str) -> tuple[bytes, str] | None:
        if not self.is_cloud_backed:
            return None
        try:
            downloader = self._container.download_blob(blob_name)
            properties = downloader.properties
            return downloader.readall(), properties.content_settings.content_type or "application/octet-stream"
        except ResourceNotFoundError:
            return None
