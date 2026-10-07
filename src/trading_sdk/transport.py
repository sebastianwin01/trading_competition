import math
import threading
import time
from typing import Any

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    NetworkError,
    OrderOutcomeUnknown,
    ProtocolError,
    RateLimitError,
)
from .money import decode


class OrderLimiter:
    """Pace submissions and cancellations together, without an initial burst."""

    def __init__(self, rate: float):
        if not math.isfinite(rate) or rate <= 0:
            raise ConfigurationError("order_rate_limit must be a finite positive number.")
        self.rate = rate
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self):
        with self._lock:
            delay = self._next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next = time.monotonic() + 1 / self.rate


def check_response(response: httpx.Response):
    if response.is_success:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text or f"HTTP {response.status_code}"}
    cls = (
        AuthenticationError if response.status_code in (401, 403)
        else RateLimitError if response.status_code == 429 else APIError
    )
    raise cls(response.status_code, payload, retry_after=response.headers.get("Retry-After"))


class Transport:
    def __init__(self, api_key, base_url, timeout, rate, http_transport=None):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key, "User-Agent": "trading-competition-sdk/0.1.0"},
            timeout=timeout,
            transport=http_transport,
            follow_redirects=False,
            trust_env=False,
        )
        self.limiter = OrderLimiter(rate)

    def request(self, method: str, path: str, *, body=None, params=None, raw=False) -> Any:
        if path.startswith("/api/orders") and method in ("POST", "DELETE"):
            self.limiter.acquire()
        try:
            response = self.http.request(
                method, path, json=body,
                params={k: v for k, v in (params or {}).items() if v is not None},
            )
        except httpx.HTTPError as exc:
            if path.startswith("/api/orders") and method in ("POST", "DELETE"):
                raise OrderOutcomeUnknown(
                    f"{method} {path} failed in transit. Do not retry blindly; check order history."
                ) from exc
            raise NetworkError(f"{method} {path} failed: {type(exc).__name__}") from exc
        check_response(response)
        if response.status_code == 204:
            return None
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProtocolError(f"{method} {path} returned invalid JSON.") from exc
        return payload if raw else decode(payload)

    def close(self):
        self.http.close()
