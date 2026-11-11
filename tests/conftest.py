"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Only test on asyncio backend."""
    return "asyncio"

