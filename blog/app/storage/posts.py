"""Shared post storage used by public and author routes."""

from ..repository import BlogRepository

posts = BlogRepository()
