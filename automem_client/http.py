"""HTTP client construction and response decoding for automem clients."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


def _default_url() -> str:
    url = os.environ.get("MEMORY_URL") or (
        f"http://{os.environ.get('BIND_HOST', '127.0.0.1')}:{os.environ.get('BIND_PORT', '8888')}"
    )
    return url.rstrip("/")


def _default_key() -> str:
    return os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")


def build_client(
    *,
    url: str | None = None,
    key: str | None = None,
    timeout: float = 30.0,
) -> httpx.Client:
    """Construct an httpx.Client for the automem API.

    URL and API key resolve from MEMORY_URL/BIND_HOST+BIND_PORT and
    MEMORY_API_KEY/ADMIN_API_KEY respectively when not passed.
    trust_env=False so adapters do not pick up unintended HTTPS_PROXY etc.
    """
    return httpx.Client(
        base_url=url if url is not None else _default_url(),
        headers={"X-API-Key": key if key is not None else _default_key()},
        timeout=timeout,
        trust_env=False,
    )


def decode(response: httpx.Response) -> Any:
    """Raise on HTTP error, otherwise decode the JSON body."""
    if response.status_code >= 400:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        detail = response.text.strip() or "<empty response>"
        raise RuntimeError(
            f"Expected JSON response from automem, got "
            f"{response.headers.get('content-type', 'unknown')}: {detail}"
        ) from exc
