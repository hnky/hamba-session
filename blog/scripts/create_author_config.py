#!/usr/bin/env python3
"""Generate an AUTHOR_CONFIG value without writing credentials to source files."""

import getpass
import argparse
import json
import os
from pathlib import Path
import secrets
import sys

from app.auth import AuthorAuth


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Write local-only config; permit demo passwords")
    parser.add_argument("--username", help="Author username (otherwise prompted)")
    parser.add_argument("--password-stdin", action="store_true", help="Read a local demo password from stdin")
    args = parser.parse_args()
    if args.password_stdin and not args.local:
        parser.error("--password-stdin is only permitted with --local")
    username = (args.username or input("Author username: ")).strip()
    if not username:
        raise SystemExit("Username is required")
    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("Author password: ")
    confirmation = password if args.password_stdin else getpass.getpass("Confirm password: ")
    if not password:
        raise SystemExit("Password is required")
    if len(password) < 12 and not args.local:
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
    if args.local:
        path = Path(__file__).resolve().parents[1] / ".author-config.json"
        # Exclusive creation prevents accidental credential replacement.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(config, file)
        print("Local author configuration created. It is excluded from Git and container builds.")
        return
    print("\nStore these values securely. The API key is shown only now.\n")
    print(f"API key: {api_key}")
    print("AUTHOR_CONFIG=" + json.dumps(config, separators=(",", ":")))


if __name__ == "__main__":
    main()
