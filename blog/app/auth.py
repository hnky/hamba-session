"""Password, API-key, signed-session, and CSRF authentication for authors."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

SESSION_COOKIE = "hamba_author"
SESSION_MAX_AGE = 8 * 60 * 60
PBKDF2_ITERATIONS = 600_000


@dataclass(frozen=True)
class Author:
    username: str
    password_hash: str
    api_key_hash: str

    @property
    def is_admin(self) -> bool:
        return self.username == "admin"


class AuthorAuth:
    def __init__(self, raw_config: str = "") -> None:
        self._authors: dict[str, Author] = {}
        self._session_secret = b""
        if not raw_config:
            return
        try:
            config = json.loads(raw_config)
            if not isinstance(config, dict):
                return
            session_secret = config.get("session_secret", "")
            users = config.get("users", [])
            if not isinstance(session_secret, str) or len(session_secret) < 32:
                return
            if not isinstance(users, list):
                return
            for user in users:
                if not isinstance(user, dict):
                    raise ValueError("Invalid author entry")
                author = Author(
                    username=str(user["username"]),
                    password_hash=str(user["password_hash"]),
                    api_key_hash=str(user["api_key_hash"]),
                )
                self._authors[author.username] = author
            if not all(author.username and author.password_hash and author.api_key_hash for author in self._authors.values()):
                raise ValueError("Incomplete author entry")
            self._session_secret = session_secret.encode("utf-8")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._authors = {}
            self._session_secret = b""

    @property
    def is_configured(self) -> bool:
        return bool(self._authors and self._session_secret)

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> str:
        actual_salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), actual_salt, PBKDF2_ITERATIONS
        )
        return "pbkdf2_sha256${}${}${}".format(
            PBKDF2_ITERATIONS,
            actual_salt.hex(),
            digest.hex(),
        )

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        return "sha256$" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), expected_hex)
        except (TypeError, ValueError):
            return False

    def verify_login(self, username: str, password: str) -> Author | None:
        author = self._authors.get(username)
        encoded = author.password_hash if author else self.hash_password("invalid")
        valid = self._verify_password(password, encoded)
        return author if author and valid else None

    def verify_api_key(self, api_key: str) -> Author | None:
        candidate = self.hash_api_key(api_key)
        for author in self._authors.values():
            if hmac.compare_digest(candidate, author.api_key_hash):
                return author
        return None

    @staticmethod
    def _encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def create_session(self, author: Author) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(24)
        payload = self._encode(
            json.dumps(
                {
                    "username": author.username,
                    "expires": int(time.time()) + SESSION_MAX_AGE,
                    "csrf": csrf,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature = self._encode(
            hmac.new(self._session_secret, payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}", csrf

    def read_session(self, token: str | None) -> tuple[Author, str] | None:
        if not token or not self.is_configured:
            return None
        try:
            payload, signature = token.split(".", 1)
            expected = self._encode(
                hmac.new(self._session_secret, payload.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                return None
            data = json.loads(self._decode(payload))
            if int(data["expires"]) < int(time.time()):
                return None
            author = self._authors.get(str(data["username"]))
            csrf = str(data["csrf"])
            return (author, csrf) if author and csrf else None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


@lru_cache(maxsize=1)
def get_auth() -> AuthorAuth:
    raw_config = os.getenv("AUTHOR_CONFIG")
    # The local bootstrap file must never enable default credentials in Azure.
    if raw_config is None and not any(
        os.getenv(name)
        for name in ("CONTAINER_APP_NAME", "CONTAINER_APP_REVISION", "AZURE_STORAGE_TABLE_URL")
    ):
        config_path = Path(__file__).resolve().parents[1] / ".author-config.json"
        if config_path.is_file():
            raw_config = config_path.read_text(encoding="utf-8")
    return AuthorAuth(raw_config or "")
