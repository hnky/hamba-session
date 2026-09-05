#!/usr/bin/env python3
"""Generate an AUTHOR_CONFIG value without writing credentials to source files."""

import getpass
import json
import secrets

from app.auth import AuthorAuth


def main() -> None:
    username = input("Author username: ").strip()
    if not username:
        raise SystemExit("Username is required")
    password = getpass.getpass("Author password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    api_key = "hamba_" + secrets.token_urlsafe(32)
    config = {
        "session_secret": secrets.token_urlsafe(48),
        "users": [
            {
                "username": username,
                "password_hash": AuthorAuth.hash_password(password),
                "api_key_hash": AuthorAuth.hash_api_key(api_key),
            }
        ],
    }
    print("\nStore these values securely. The API key is shown only now.\n")
    print(f"API key: {api_key}")
    print("AUTHOR_CONFIG=" + json.dumps(config, separators=(",", ":")))


if __name__ == "__main__":
    main()
