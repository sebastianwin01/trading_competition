"""Errors preserve server payloads without including authentication headers."""

from typing import Any


class SDKError(Exception):
    """Base class for SDK errors."""


class ConfigurationError(SDKError, ValueError):
    pass


class ValidationError(SDKError, ValueError):
    pass


class APIError(SDKError):
    def __init__(self, status: int, payload: Any, *, retry_after: str | None = None):
        self.status = status
        self.payload = payload
        self.retry_after = retry_after
        record = payload if isinstance(payload, dict) else {}
        nested = record.get("error")
        error = nested if isinstance(nested, dict) else record
        self.code = error.get("code") or record.get("reason")
        self.details = error.get("details")
        self.order_id = record.get("order_id") or error.get("order_id")
        message = error.get("message")
        if not message:
            message = nested if isinstance(nested, str) else f"HTTP {status}"
        super().__init__(f"{status} {self.code or ''} {message}".strip())


class AuthenticationError(APIError):
    pass


class RateLimitError(APIError):
    pass


class NetworkError(SDKError):
    pass


class OrderOutcomeUnknown(NetworkError):
    """A mutation failed in transit. Check history before deciding what to do next."""


class ProtocolError(SDKError):
    pass


class StreamError(SDKError):
    pass


class OrderRejected(SDKError):
    def __init__(self, payload: dict):
        self.payload = payload
        self.order_id = payload.get("order_id")
        self.reason = payload.get("reason") or payload.get("rejection_reason")
        super().__init__(f"Order {self.order_id} rejected: {self.reason or 'unspecified reason'}")
