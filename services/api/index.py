"""Vercel entry point for Chronicle's FastAPI application.

The Vercel API project should use services/api as its Root Directory.
"""
from app.main import app

__all__ = ["app"]
