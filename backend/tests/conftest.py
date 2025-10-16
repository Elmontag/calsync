"""Shared pytest fixtures and configuration for backend tests."""
import os


os.environ.setdefault("CALSYNC_SECRET_KEY", "insecure-test-key")
