"""Background SSE connections. Strategies interact with synchronous methods."""

import copy
import json
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import APIError, OrderRejected, ProtocolError, SDKError, StreamError
from .money import decode
from .transport import check_response


@dataclass(frozen=True)
class Event:
    name: str
    data: Any


def parse_sse(lines):
    """Parse event/data fields, comments, CRLF, and multiline JSON data."""
    name, data = "message", []
    for line in lines:
        if line == "":
            if data:
                try:
                    payload = json.loads("\n".join(data))
                except ValueError as exc:
                    raise ProtocolError(f"Invalid JSON in SSE event {name}.") from exc
                if not isinstance(payload, dict):
                    raise ProtocolError(f"Expected an object in SSE event {name}.")
                yield Event(name, decode(payload))
            name, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data.append(value)
    # SSE dispatch requires a blank line. A truncated final frame is discarded.


class Subscription:
    def __init__(self, client, pair_id):
        self.client = client
        self.pair_id = pair_id
        self.stream_id = None
        self.ready = False
        self.failure = None
        self._book = None
        self._stop = threading.Event()
        self._response = None
        self._http = httpx.Client(
            base_url=client.base_url,
            headers={"X-API-Key": client._api_key, "Accept": "text/event-stream"},
            timeout=httpx.Timeout(client.timeout, read=client.stream_read_timeout),
            transport=client._stream_transport,
            trust_env=False,
            follow_redirects=False,
        )
        self._thread = threading.Thread(
            target=self._run, name=f"trading-sdk-stream-{pair_id or 'private'}", daemon=True,
        )

    def start(self):
        self._thread.start()

    def _set_ready(self, value):
        with self.client._condition:
            self.ready = value
            self.client._condition.notify_all()

    def _run(self):
        failures = 0
        attempted_before = False
        while not self._stop.is_set() and not self.client._ended:
            self._set_ready(False)
            with self.client._condition:
                # A new connection needs its own snapshot before returning depth.
                self._book = None
            try:
                # Explicit 0 prevents the server's single-pair automatic subscription.
                with self._http.stream("GET", self.client._path + "/stream",
                                       params={"pair_id": 0}) as response:
                    self._response = response
                    if not response.is_success:
                        response.read()
                        check_response(response)
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise ProtocolError("Expected a text/event-stream response.")
                    handshake = False
                    state_refreshed = False
                    for event in parse_sse(response.iter_lines()):
                        if self._stop.is_set() or self.client._ended:
                            return
                        if event.name == "stream_ready":
                            stream_id = event.data.get("stream_id")
                            if not isinstance(stream_id, str) or not stream_id:
                                raise ProtocolError("stream_ready is missing its stream_id.")
                            self.stream_id = stream_id
                            handshake = True
                            if self.pair_id is not None:
                                result = self.client.streams.set_depth(stream_id, self.pair_id)
                                if result.get("snapshot"):
                                    self._store_book(result["snapshot"])
                            continue
                        if not handshake:
                            raise ProtocolError("SSE data arrived before stream_ready.")
                        if event.name == "market_summary_snapshot":
                            if self.pair_id is None or attempted_before:
                                self.client._recover()
                            state_refreshed = True
                            if self.pair_id is None:
                                self._set_ready(True)
                            elif self._book is not None:
                                self._set_ready(True)
                        if event.name in {"lob_snapshot", "lob_curr_state"}:
                            if event.data.get("pair_id") == self.pair_id:
                                self._store_book(event.data)
                                if state_refreshed:
                                    self._set_ready(True)
                        if event.name == "competition_ended":
                            self.client._end()
                            return
                        if self.pair_id is None or event.name in {"error", "stream_error"}:
                            self.client._receive(event, record=self.pair_id is None)
                        if self.ready:
                            failures = 0
                    if not self._stop.is_set() and not self.client._ended:
                        raise StreamError(
                            "SSE connection closed; reconnecting and refreshing state."
                        )
            except Exception as exc:
                if self._stop.is_set() or self.client._ended or self.client._closed:
                    return
                self._set_ready(False)
                error = exc if isinstance(exc, SDKError) else StreamError(
                    f"Stream {self.pair_id or 'private'} failed: {type(exc).__name__}."
                )
                self.client._report(error)
                failures += 1
                fatal = isinstance(exc, ProtocolError) or (
                    isinstance(exc, APIError) and exc.status < 500 and exc.status != 429
                )
                if fatal or failures > self.client.max_reconnect_attempts:
                    self.failure = error
                    self.client._fail(error)
                    return
                delay = min(self.client.reconnect_delay * 2 ** (failures - 1), 8.0)
                if self._stop.wait(delay):
                    return
            finally:
                self._response = None
                self.stream_id = None
                attempted_before = True
        self._set_ready(False)

    def _store_book(self, book):
        if not isinstance(book, dict) or not all(k in book for k in ("pair_id", "bids", "asks")):
            raise ProtocolError("Malformed order book event.")
        with self.client._condition:
            self._book = copy.deepcopy(book)
            self.client._condition.notify_all()

    def book(self):
        with self.client._condition:
            if self._book is None or not self.ready:
                raise StreamError("The pair's depth stream is not ready.")
            return copy.deepcopy(self._book)

    def close(self):
        self._stop.set()
        self._set_ready(False)
        # HTTPX exposes its network stream on live responses. Shutdown wakes a
        # blocked socket read immediately, including quiet Go-server streams.
        response = self._response
        if response is not None:
            network = response.extensions.get("network_stream")
            sock = network.get_extra_info("socket") if network is not None else None
            if sock is not None:
                import socket
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            response.close()
        if threading.current_thread() is not self._thread and self._thread.ident is not None:
            self._thread.join(timeout=self.client.timeout + 1)
        self._http.close()


def rejection_from(event):
    if event.name == "order_status_change" and event.data.get("status") == "rejected":
        return OrderRejected(event.data)
    return None
