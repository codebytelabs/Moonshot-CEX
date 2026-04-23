"""Shared pytest fixtures and configuration."""

import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop_policy():
    """Session-scoped event-loop policy for pytest-asyncio.

    Replaces the deprecated custom `event_loop` fixture. Returning a policy is
    the modern way to control how pytest-asyncio creates loops for tests.
    """
    return asyncio.DefaultEventLoopPolicy()
