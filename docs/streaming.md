# Streaming and depth

The SDK receives SSE on background threads. Strategy code uses synchronous methods.

```python
book_a = client.market.order_book(2)
book_b = client.market.order_book(3)
```

The first read starts that pair's depth subscription automatically. Later reads reuse it and return a copy of the latest absolute book. Books keep updating between strategy callbacks.

The server supports one depth pair per SSE connection. The SDK uses one private/global connection and one additional connection for each requested pair. A strategy reading two pairs uses three SSE connections. Private events received on pair connections do not enter the participant's event history again, which prevents duplicate fills and rejection reports.

## Subscription lifetime

Subscriptions remain open until `client.close()` or explicit release:

```python
client.streams.release(2)
```

The next book read starts the subscription again. The SDK does not guess when a strategy has stopped using a pair. Automatic idle shutdown and connection overhead are follow-ups for performance testing. A strategy that reads many pairs will retain many connections unless it releases them.

On connect, the SDK waits for `stream_ready`, uses the new stream ID to set pair depth, and receives a full snapshot. Each reconnect repeats this sequence. The SDK requests `pair_id=0` initially to disable the server's implicit single-pair subscription, then sets depth explicitly.

After a depth reconnect, the SDK invalidates the old internal book and waits for a snapshot from the new connection. It also refreshes private REST history before making that subscription ready. When many streams reconnect together, each can fetch history, so recovery cost grows with both history size and connection count.

## Events

`client.events()` returns recent global/private events and drains that optional event history. Each event has `.name` and `.data`. Payloads retain unknown fields, and unknown event names also reach this history. Monetary fields use `Decimal` values.

| Event | Meaning |
| --- | --- |
| `stream_ready` | Connection handshake, consumed by the SDK |
| `market_summary_snapshot` | All pair marks and trading statuses |
| `lob_snapshot` | Full pair book after subscription, consumed by its depth manager |
| `lob_curr_state` | Absolute replacement book, consumed by its depth manager |
| `balance_update` | Absolute asset balance |
| `fill` | Participant execution notification |
| `order_status_change` | Order lifecycle update; rejected orders print an error automatically |
| `self_trade_prevention` | Cancellation notice emitted by the current backend |
| `info_event` | Competition announcement or corporate action |
| `comp_state_change` | Competition lifecycle update |
| `competition_ended` | Stop the strategy loop and close on context exit |
| `error` or `stream_error` | Print the error and stop the managed strategy |

The optional event history retains the most recent 1,000 events. Overflow is reported. Use REST order and fill history for durable records. `errors()` also retains up to 1,000 recent reports, while logging prints errors when they occur.

## Event payloads

`events()` returns `Event` objects, not raw stream text. `event.name` is a string; `event.data` is a dictionary with the following fields. IDs are integers and amounts are human `Decimal` values. Unknown names and additional fields remain available. Use `.get()` for optional fields.

| Name | Data fields and purpose |
| --- | --- |
| `market_summary_snapshot` | `competition_id: int`, `pairs: list[dict]`. Each pair has `pair_id: int`, `trading_status: str`, and `mark_price: Decimal`. Initial marks/statuses on connection; this is not a continuously updated portfolio. |
| `balance_update` | `asset_id: int`, `quantity: Decimal`. Replace that asset's balance with this absolute quantity. Do not add it as a delta. |
| `fill` | `fill_id: int`, `pair_id: int`, `price: Decimal`, `qty: Decimal`, `side: str`, `role: str`, `created_at: str`. Side is your `buy`/`sell`; role is `maker`/`taker`. This notification has no `order_id`; use fill history to find your corresponding order. History uses `id` for the fill ID. |
| `order_status_change` | `order_id: int`, `status: str`, optional `reason: str`. Update that order's lifecycle state. Rejected status automatically produces an `OrderRejected` report. Use order history for the full order record. |
| `self_trade_prevention` | `cancelled_order_id: int`, `reason: str`. Your resting order was cancelled to avoid matching against your own order. |
| `info_event` | Competition announcement or action. Payload contents depend on the configured event; `event_id: int` and `payload_json: str` can be provided. There is no single fixed strategy payload schema. Inspect fields before interpreting them. |
| `comp_state_change` | `status: str`, possibly additional lifecycle data. The runner reacts to paused, resumed, terminated, or cancelled state. |
| `error`, `stream_error` | Server error data, potentially `message: str` or `error: str`, plus other details. The SDK logs it and sets a fatal stream failure. Subsequent readiness checks raise `StreamError`. |

The SDK consumes `stream_ready` privately. It has `stream_id: str` and optional `default_depth_pair: int | None`, but is not added to `events()`. Pair `lob_snapshot` and `lob_curr_state` notifications update managed books and are not duplicated into this private/global queue. Their data has the [book return schema](api-reference.md#book-return-value).

`competition_ended` is consumed as a stop signal before it enters the queue; do not wait to see it in `events()`. The managed runner stops. Stream reconnection does not replay missed notifications. Use REST history methods for complete orders and fills.

Fatal `error` and `stream_error` notifications are reported from every managed connection, including pair-depth connections. Pair-only error notifications stop managed reads and the runner without being duplicated into the private/global `events()` queue; their report is available through `errors()` and logging.

```python
for event in client.events():
    if event.name == "balance_update":
        asset_id = event.data["asset_id"]
        new_quantity = event.data["quantity"]
        print(asset_id, new_quantity)
    elif event.name == "fill":
        print(event.data["fill_id"], event.data["price"], event.data["qty"])
```

## Freshness and reconnect limits

The stream has no documented replay cursor or heartbeat. Reconnection fetches balances and complete order/fill history before resuming the managed strategy loop. Existing pair subscriptions restore their snapshots before the loop resumes. This provides current REST reads and new books, but not a replay of every event missed during disconnection or one atomic snapshot across all endpoints.

`recovery_snapshot` is a copy of the last recovery reads. It is not a continuously current portfolio. `balances.list`, `orders.list`, and `fills.list` fetch fresh data each time. Books are copies of the latest stream data.

By default `stream_read_timeout=None` allows a quiet market to remain connected. An abrupt socket failure triggers recovery, but a network partition that leaves an idle socket half-open may take the operating system time to detect. Set `stream_read_timeout` to bound silence if your strategy requires it. A finite timeout also reconnects healthy quiet streams because the server does not send heartbeat bytes.

The supplied `run` loop pauses between callbacks during recovery. Your custom loops must use `start` and managed book reads appropriately if they need the same readiness checks. The SDK cannot interrupt a callback already executing. Every new order submission through a streaming client waits for managed streams to recover.
