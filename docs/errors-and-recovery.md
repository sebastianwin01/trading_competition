# Errors and recovery

The starter template needs no async error handler. HTTP calls raise normal exceptions; stream failures and asynchronous rejections print automatically. Failed recovery stops `run` with a visible exception. The template exits with status 1 for SDK errors.

## Exception types

| Exception | Meaning |
| --- | --- |
| `ConfigurationError` | Missing key, invalid configuration, or ordinary REST request after close |
| `ValidationError` | Invalid order arguments, IDs, amounts, filters, or candle bucket |
| `APIError` | Server rejected an HTTP request |
| `AuthenticationError` | HTTP 401 or 403, including a key scoped to another competition |
| `RateLimitError` | HTTP 429 |
| `NetworkError` | A read request or stream control request failed in transit |
| `OrderOutcomeUnknown` | An order submission or cancellation failed in transit |
| `ProtocolError` | Invalid JSON, malformed money values, or an invalid stream handshake |
| `StreamError` | Stream disconnect, failed recovery, unavailable managed book, or stream startup on a closed client |
| `OrderRejected` | A rejection received through an order-status event |

All exceptions inherit `SDKError`. Server HTTP exceptions expose `.status`, `.code`, `.details`, `.payload`, `.order_id`, and `.retry_after`. The SDK supports nested structured errors and the backend's string error/reason shape. Non-JSON HTTP failures retain the server's text. Error payloads remain in their original wire representation so no server detail is lost.

| Error attribute | Type and meaning |
| --- | --- |
| `APIError.status` | `int`, server HTTP status |
| `APIError.code` | `str` or `None`, structured code or server reason; not every failure has a code |
| `APIError.details` | Server-provided value or `None`; its shape depends on the failure |
| `APIError.payload` | Original JSON value, or a dictionary containing non-JSON response text; amounts here remain in the server's representation |
| `APIError.order_id` | `int` or `None`, order ID when the server recorded and returned one |
| `APIError.retry_after` | `str` or `None`, server retry advice; the SDK does not automatically act on it |
| `OrderRejected.order_id` | `int` or `None`, rejected order ID from the notification |
| `OrderRejected.reason` | `str` or `None`, rejection reason from the notification |
| `OrderRejected.payload` | Original decoded notification dictionary |

Use `str(error)` for the displayed message. `AuthenticationError` and `RateLimitError` inherit `APIError`. `OrderOutcomeUnknown` inherits `NetworkError`. Other exceptions have their normal exception message, without the HTTP attributes above. `OrderRejected` is an asynchronous report; it does not cause an already successful submission call to raise retroactively.

```python
from trading_sdk import APIError

try:
    order = client.orders.create(2, side="buy", qty="10", price="150.42")
except APIError as error:
    print(error.status, error.code, error.details)
    raise
```

Handling an exception yourself is optional. Allowing it to reach the supplied template stops the strategy and prints its message. The SDK never hides it or returns an empty success value for an error.

## Unknown order outcomes

An order may reach the server even when the client loses the HTTP response. The SDK does not automatically retry mutations, HTTP 429 responses, or server errors. An order-route network failure raises `OrderOutcomeUnknown`.

Inspect `orders.list` and `fills.list` before deciding whether to submit again. The current order API does not accept a client idempotency key, so matching an unknown submission against history may require operator judgment. Do not treat a failed HTTP call as proof that the server did nothing. A server error after matching or settlement also needs inspection.

## Rate limits

The current Go server uses one 75-token bucket refilled at 75 requests per second per user. Both `POST /api/orders` and `DELETE /api/orders/{id}` consume it. The SDK spaces these requests using one thread-safe limiter, without an initial burst. Market-data reads and depth configuration do not consume this local limiter.

Set `ORDER_RATE_LIMIT` in `.env`, or pass `order_rate_limit` to the client. The limit must be positive and finite. Independent SDK clients do not share a local limiter, while the server combines requests from all clients for one user. Divide the available rate across your strategies. The server remains authoritative and can return 429 even when the SDK paces its own requests.

## Reconnection

Reconnect delay starts at 0.25 seconds and doubles up to 8 seconds. The default allows five reconnect attempts after a failed connection. A successful ready connection resets the consecutive failure count. `ProtocolError` stops recovery immediately. So does `APIError` with a status below 500, except 429; this includes authentication failures. HTTP 429, 5xx responses, and other connection failures can reconnect within the configured limits.

`recovery_timeout=45` bounds each strategy or managed-book wait for all streams to become ready. Recovery refreshes the competition dictionary, balances, complete orders, and complete fills through REST. Each depth connection obtains a new stream ID and book snapshot. A large history can increase recovery cost; performance testing should measure it.

A depth-only reconnection also refreshes private REST state before readiness, even when the private/global stream stayed connected or the previous depth connection never became ready. Simultaneously reconnecting streams can each fetch history; this increases request volume. A previous book cannot make a reconnected stream ready without a fresh snapshot. Repeated `start()` calls on an already-ready client reuse state and do not trigger another refresh.

Competition pause/resume events pause and resume the supplied strategy loop. Termination stops it. Order cancellation remains callable during recovery, allowing explicit cancellation attempts. The current backend rejects cancellation while the competition is paused; the SDK forwards that error. A custom long-running callback is responsible for returning control to the runner.

Default reports use the `trading_sdk` logger. The template configures it to print warnings and errors. Applications can route this logger to a file. `client.errors()` provides the recent reports as ordinary exception objects, but a strategy does not have to drain them for reporting to work.
