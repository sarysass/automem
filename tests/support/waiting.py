from __future__ import annotations

import time
from typing import Callable, TypeVar

import httpx


T = TypeVar("T")


def wait_for_condition(
    condition: Callable[[], T | None],
    *,
    description: str,
    timeout: float = 10.0,
    interval: float = 0.05,
) -> T:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            result = condition()
        except Exception as exc:  # pragma: no cover - exercised through HTTP readiness polling
            last_error = exc
        else:
            if result is not None:
                return result
        time.sleep(interval)

    if last_error is not None:
        raise TimeoutError(f"Timed out waiting for {description}: {last_error}") from last_error
    raise TimeoutError(f"Timed out waiting for {description}")


def wait_for_http_ready(
    base_url: str,
    *,
    path: str = "/v1/healthz",
    expected_statuses: tuple[int, ...] = (200, 401),
    timeout: float = 10.0,
    interval: float = 0.05,
) -> httpx.Response:
    with httpx.Client(base_url=base_url, timeout=1.0, trust_env=False) as client:
        def probe() -> httpx.Response | None:
            response = client.get(path)
            if response.status_code in expected_statuses:
                return response
            return None

        return wait_for_condition(
            probe,
            description=f"HTTP readiness on {base_url}{path}",
            timeout=timeout,
            interval=interval,
        )
