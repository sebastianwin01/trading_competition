import copy
import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path

from dotenv import dotenv_values

from .errors import ConfigurationError, SDKError, StreamError
from .resources import Balances, Competition, Fills, Market, Orders, Streams, positive_id
from .stream import Subscription, rejection_from
from .transport import Transport

logger = logging.getLogger("trading_sdk")


class TradingClient:
    """Competition-scoped client with synchronous methods and background streams."""

    def __init__(self, api_key: str, competition_id=1, *, base_url="http://localhost:8080",
                 order_rate_limit=75, timeout=10.0, recovery_timeout=45.0,
                 max_reconnect_attempts=5, reconnect_delay=0.25, stream_read_timeout=None,
                 auto_stream=True, _http_transport=None, _stream_transport=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ConfigurationError("Set API_KEY in .env before running your strategy.")
        positive_id(competition_id, "competition_id")
        from urllib.parse import urlsplit
        url = urlsplit(base_url)
        if (url.scheme not in {"http", "https"} or not url.netloc or url.username is not None
                or url.query or url.fragment or url.path not in {"", "/"}):
            raise ConfigurationError("base_url must be an http(s) origin without credentials.")
        for name, value in {
            "timeout": timeout, "recovery_timeout": recovery_timeout,
            "reconnect_delay": reconnect_delay,
        }.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"{name} must be a finite positive number.")
        if (not isinstance(max_reconnect_attempts, int)
                or isinstance(max_reconnect_attempts, bool) or max_reconnect_attempts < 0):
            raise ConfigurationError("max_reconnect_attempts must be a nonnegative integer.")
        if stream_read_timeout is not None and (
            not math.isfinite(stream_read_timeout) or stream_read_timeout <= 0
        ):
            raise ConfigurationError("stream_read_timeout must be positive or None.")
        self._api_key = api_key
        self.competition_id = competition_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.recovery_timeout = recovery_timeout
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.stream_read_timeout = stream_read_timeout
        self.auto_stream = auto_stream
        self._stream_transport = _stream_transport
        self._transport = Transport(api_key, base_url, timeout, order_rate_limit, _http_transport)
        self._path = f"/api/competitions/{competition_id}"
        self._condition = threading.Condition(threading.RLock())
        self._subscriptions = {}
        self._fatal = None
        self._closed = False
        self._ended = False
        self._status = None
        self._recovery_snapshot = {}
        self._events = deque(maxlen=1000)
        self._errors = deque(maxlen=1000)
        self._event_overflow_reported = False
        self.competition = Competition(self)
        self.balances = Balances(self)
        self.orders = Orders(self)
        self.fills = Fills(self)
        self.market = Market(self)
        self.streams = Streams(self)

    @classmethod
    def from_env(cls, path: str | Path = ".env", **overrides):
        """Read .env without mutating process environment; environment takes precedence."""
        file_values = dotenv_values(path)

        def value(key, default):
            return os.environ.get(key, file_values.get(key) or default)

        try:
            settings = {
                "api_key": value("API_KEY", ""),
                "competition_id": int(value("COMPETITION_ID", "1")),
                "base_url": value("BASE_URL", "http://localhost:8080"),
                "order_rate_limit": float(value("ORDER_RATE_LIMIT", "75")),
            }
        except ValueError as exc:
            raise ConfigurationError(
                "COMPETITION_ID and ORDER_RATE_LIMIT must be numbers."
            ) from exc
        settings.update(overrides)
        return cls(**settings)

    def _request(self, method, path, **kwargs):
        if self._closed:
            raise ConfigurationError("This client is closed. Create a new client.")
        return self._transport.request(method, path, **kwargs)

    def health(self):
        return self._request("GET", "/health")

    def start(self):
        self._subscribe(None)
        self._wait_ready()
        return self

    def _subscribe(self, pair_id):
        with self._condition:
            if self._closed or self._ended:
                raise StreamError("The client is closed or the competition has ended.")
            if self._fatal is not None:
                raise self._fatal
            if pair_id is not None and None not in self._subscriptions:
                self._subscribe(None)
            subscription = self._subscriptions.get(pair_id)
            if subscription is None:
                subscription = Subscription(self, pair_id)
                self._subscriptions[pair_id] = subscription
                subscription.start()
            return subscription

    def _release(self, pair_id):
        with self._condition:
            subscription = self._subscriptions.pop(pair_id, None)
            self._condition.notify_all()
        if subscription:
            subscription.close()

    def _wait_ready(self):
        deadline = time.monotonic() + self.recovery_timeout
        with self._condition:
            while not self._closed and not self._ended:
                if self._fatal is not None:
                    raise self._fatal
                if self._subscriptions and all(s.ready for s in self._subscriptions.values()):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    error = StreamError("Stream recovery timed out. Strategy stopped.")
                    self._fatal = error
                    raise error
                self._condition.wait(min(remaining, 0.25))
        return False

    def _before_order(self):
        if self.auto_stream:
            self.start()
        if self._fatal is not None:
            raise self._fatal
        if self._ended:
            raise StreamError("Competition ended; no new orders can be submitted.")
        if self._subscriptions:
            self._wait_ready()

    def _recover(self):
        # REST reads do not use cached private values. Streams have no replay cursor.
        # Consume all history pages so recovery does not assume a single-page history.
        dictionary = self.competition.retrieve()
        balances = self.balances.list()
        orders = list(self.orders.iter_all())
        fills = list(self.fills.iter_all())
        with self._condition:
            self._status = dictionary["status"]
            self._recovery_snapshot = {
                "competition": dictionary, "balances": balances, "orders": orders, "fills": fills,
            }
            self._condition.notify_all()
        if self._status in {"terminated", "cancelled"}:
            self._end()

    @property
    def recovery_snapshot(self):
        """Copy of the last recovery REST reads, not a continuously current portfolio."""
        with self._condition:
            return copy.deepcopy(self._recovery_snapshot)

    def _receive(self, event, *, record=True):
        with self._condition:
            if record:
                if len(self._events) == self._events.maxlen and not self._event_overflow_reported:
                    self._report(StreamError(
                        "Event history exceeded 1000 entries; oldest discarded."
                    ))
                    self._event_overflow_reported = True
                self._events.append(event)
            if event.name == "comp_state_change":
                self._status = event.data.get("status", self._status)
                if self._status in {"terminated", "cancelled"}:
                    self._end()
            self._condition.notify_all()
        rejection = rejection_from(event)
        if rejection:
            self._report(rejection)
        if event.name in {"error", "stream_error"}:
            message = event.data.get("message") or event.data.get("error") or "Server stream error"
            error = StreamError(str(message))
            self._report(error)
            self._fail(error)

    def _report(self, error):
        with self._condition:
            self._errors.append(error)
            self._condition.notify_all()
        logger.error("%s", error)

    def errors(self):
        """Drain errors already reported to stderr; no handler is required."""
        with self._condition:
            result = list(self._errors)
            self._errors.clear()
            return result

    def events(self):
        """Drain recent global/private events. Managed books have their own latest state."""
        with self._condition:
            result = list(self._events)
            self._events.clear()
            self._event_overflow_reported = False
            return result

    def _fail(self, error):
        with self._condition:
            self._fatal = error
            self._condition.notify_all()

    def _end(self):
        with self._condition:
            self._ended = True
            self._condition.notify_all()

    def run(self, strategy, *, interval=1.0, max_iterations=None):
        """Call strategy(client) synchronously. Pause for recovery and competition pauses."""
        if not math.isfinite(interval) or interval <= 0:
            raise ConfigurationError("interval must be a finite positive number.")
        if max_iterations is not None and (
            not isinstance(max_iterations, int) or isinstance(max_iterations, bool)
            or max_iterations < 0
        ):
            raise ConfigurationError("max_iterations must be a nonnegative integer or None.")
        if self._ended:
            return
        self.start()
        count = 0
        try:
            while max_iterations is None or count < max_iterations:
                if not self._wait_ready():
                    return
                with self._condition:
                    if self._status == "paused":
                        self._condition.wait(0.25)
                        continue
                strategy(self)
                count += 1
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._ended or self._closed or self._fatal is not None,
                        timeout=interval,
                    )
        except SDKError as error:
            self._report(error)
            raise

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            subscriptions = list(self._subscriptions.values())
            self._subscriptions.clear()
            self._condition.notify_all()
        for subscription in subscriptions:
            subscription.close()
        self._transport.close()

    def __enter__(self):
        try:
            if self.auto_stream:
                self.start()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()
