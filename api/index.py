"""Vercel entry point that reuses the FastAPI app defined in main.py."""

from main import app

__all__ = ["app"]
