# Python method reference

This is the complete participant reference. Use the SDK with this folder and a running competition server. You do not need the platform API contract, Swagger, frontend, or backend source.

Your strategy calls Python methods. The SDK supplies authentication and competition context, converts amounts, reuses connections, paces orders, and manages background streams. Setup is in the [starter guide](../README.md). Recovery is in [errors and recovery](errors-and-recovery.md).

## Find a method

| Task | Method |
| --- | --- |
| Configure a client | [`TradingClient(...)`, `from_env(...)`](#configure-the-client) |
| Check the server | [`health()`](#clienthealth) |
| Discover assets and pairs | [`competition.retrieve()`](#clientcompetitionretrieve) |
| Read active competition time | [`competition.time()`](#clientcompetitiontime) |
| Retrieve your existing key | [`competition.api_key()`](#clientcompetitionapi_key) |
| Read rankings | [`competition.leaderboard()`](#clientcompetitionleaderboard) |
| Read your holdings | [`balances.list()`](#clientbalanceslist) |
| Submit an order | [`orders.create(...)`](#clientorderscreate) |
| Cancel a resting order | [`orders.cancel(...)`](#clientorderscancelorder_id) |
| Read or iterate through orders | [`orders.list(...)`](#clientorderslist), [`orders.iter_all(...)`](#clientordersiter_all) |
| Read or iterate through executions | [`fills.list(...)`](#clientfillslist), [`fills.iter_all(...)`](#clientfillsiter_all) |
| Read a book once | [`market.snapshot(...)`](#clientmarketsnapshotpair_id) |
| Read an automatically updating book | [`market.order_book(...)`](#clientmarketorder_bookpair_id) |
| Read trade candles | [`market.candles(...)`](#clientmarketcandles) |
| Start, reuse, or release subscriptions | [`streams.subscribe(...)`](#clientstreamssubscribepair_idnone), [`streams.release(...)`](#clientstreamsreleasepair_id) |
| Configure depth manually | [`streams.set_depth(...)`, `clear_depth(...)`](#manual-depth-controls) |
| Start and wait for readiness | [`start()`](#clientstart) |
| Run a strategy | [`run(...)`](#clientrun) |
| Read recovery data | [`recovery_snapshot`](#clientrecovery_snapshot) |
| Read optional notifications | [`events()`, `errors()`](#clientevents-and-clienterrors) |
| Close connections | [`close()`](#clientclose) |
| Inspect amount conversion | [`to_wire(...)`, `from_wire(...)`](#amount-helpers) |

## Types, IDs, and failures

In signatures, `*` separates keyword-only arguments. Pass `side="buy"`, rather than a second positional argument to `orders.create`.

| Type | Meaning |
| --- | --- |
| `Amount` | `str`, `int`, or `decimal.Decimal` in human units. `"10"` and integer `10` both mean ten units. Floats and booleans are invalid. |
| `Decimal` | A Python `decimal.Decimal`, never a scaled integer string. Prices, quantities, balances, equity, marks, increments, and candle values use this type. |
| ID | A positive Python `int`, at most `9223372036854775807`. Booleans, numeric strings, and zero are invalid method arguments. |
| `dict` / `list` | Ordinary containers. Responses retain additional server fields. Optional fields can be absent or `None`; check before using them. |
| Timestamp | A `str` retained as received, not a `datetime`. Candles and submission acknowledgements use UTC ISO timestamps. History can use `YYYY-MM-DD HH:MM:SS`. |

Asset and pair maps have string keys. Use `dictionary["pairs"][str(pair_id)]` to look up an integer ID. A pair is a market between a base and a quote asset. Price is quote units per base unit; order quantity is in base units. See [amounts](amounts.md) for precision, signed limits, and tick/lot rules.

All remote methods can raise `AuthenticationError` for rejected credentials, `RateLimitError` for a server rate limit, `APIError` for other server failures, `NetworkError` for transport failure, or `ProtocolError` for unusable response data. Ordinary REST requests after `close()` raise `ConfigurationError`; stream startup and managed-book reads raise `StreamError`. A streaming order submission can take that same stream error path. Order transport failures instead raise `OrderOutcomeUnknown`. Method sections add restrictions and common failures; they do not limit what errors a server can return. The return schemas describe successful calls.

These are the supported participant methods. Resource constructors, resource `.get` helpers, transport objects, and attributes beginning with `_` are implementation details. Use the client and its grouped methods below.

## Configure the client

```python
TradingClient(
    api_key, competition_id=1, *, base_url="http://localhost:8080",
    order_rate_limit=75, timeout=10.0, recovery_timeout=45.0,
    max_reconnect_attempts=5, reconnect_delay=0.25,
    stream_read_timeout=None, auto_stream=True,
)
TradingClient.from_env(path=".env", **overrides)
```

Both return a `TradingClient` scoped to one competition and participant. Construction does not contact the server. Context entry starts streaming by default and waits for recovery. Use one client for the strategy's lifetime.

| Input | Type and default | Purpose / accepted values |
| --- | --- | --- |
| `api_key` | Required nonempty `str` | Competition key from the frontend. Keep it private. |
| `competition_id` | ID, `1` | Competition your key belongs to. It must still be configured with a competition key. |
| `base_url` | `str`, `"http://localhost:8080"` | HTTP or HTTPS server origin. No path except `/`, query, fragment, or embedded credentials. |
| `order_rate_limit` | Positive finite number, `75` | Combined submissions and cancellations per second for this client. Does not change the server limit. |
| `timeout` | Positive finite seconds, `10.0` | Connect, write, pool, and ordinary response read timeouts. |
| `recovery_timeout` | Positive finite seconds, `45.0` | Maximum duration of each wait for all managed streams to become ready. |
| `max_reconnect_attempts` | Nonnegative `int`, `5` | Retries after an unsuccessful stream connection. `0` allows the initial attempt only. |
| `reconnect_delay` | Positive finite seconds, `0.25` | Initial delay, doubled on consecutive failures up to 8 seconds. |
| `stream_read_timeout` | Positive finite seconds or `None`, default `None` | Maximum silence between stream bytes. `None` permits quiet markets. A finite timeout also reconnects healthy quiet streams. |
| `auto_stream` | `bool`, `True` | Start the private stream on context entry and before submission. `False` permits REST-only use until streaming is explicitly started. |

`from_env` accepts a `str` or `pathlib.Path` for `path`. A relative path is relative to your working directory. It reads only that file, without searching parent directories. The starter uses the file beside `main.py`. A missing file is allowed if the process environment or overrides supply a key.

| Environment setting | Constructor input | Default |
| --- | --- | --- |
| `API_KEY` | `api_key` | None; a nonempty key is required |
| `COMPETITION_ID` | `competition_id` | `1` |
| `BASE_URL` | `base_url` | `http://localhost:8080` |
| `ORDER_RATE_LIMIT` | `order_rate_limit` | `75` |

Process environment values override the file; keyword overrides override both. Overrides can set any public constructor option. The four environment values must parse before overrides are applied, so fix malformed numeric values in the file or environment. Loading does not change the process environment. Invalid IDs raise `ValidationError`; missing credentials and invalid numeric configuration raise `ConfigurationError`.

```python
from trading_sdk import TradingClient

with TradingClient.from_env(".env", order_rate_limit=25) as client:
    print(client.competition_id, client.base_url)
```

`competition_id` is an `int`; `base_url` is a `str` without a trailing slash. Treat configuration as read-only. To change credentials, competition, or connection settings, close the client and create another.

## `client.health()`

Check whether the server responds. No inputs. Returns `{"status": "ok"}`, a `dict` with `status: str`. This does not validate competition access or guarantee that a pair is tradable.

## `client.competition.retrieve()`

Discover assets, markets, lifecycle state, and trading increments. No inputs. Fetches fresh data each call. Returns `dict`:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `int` | Competition ID |
| `name` | `str` | Competition name |
| `status` | `str` | `pending`, `active`, `paused`, `terminated`, or `cancelled` |
| `home_asset_id` | `int` | Home currency used for equity |
| `equity_floor` | `Decimal` | Competition risk threshold in home currency |
| `assets` | `dict[str, dict]` | Definitions keyed by string asset ID; can be empty |
| `pairs` | `dict[str, dict]` | Definitions keyed by string pair ID; can be empty |
| `current_user` | `dict` | Contains `is_competition_admin: bool`; this flag does not give the SDK admin methods |

Each asset has `symbol: str`, `kind: str`, `instrument_type: str`, and `trading_status: str`. `display_name: str` is optional. Current kinds are `currency`, `equity`, `bond`, and `other`; trading status is `open` or `closed`. Instrument type is a more specific server-defined label, such as `equity_stock`, and can be an empty string. Treat it as descriptive metadata rather than a fixed SDK enum. Check both asset statuses as well as pair status before considering a market tradable.

Each pair has `base_asset_id: int`, `quote_asset_id: int`, `initial_mark: Decimal`, `min_price_increment: Decimal`, `min_qty_increment: Decimal`, and `trading_status: str`. `"open"` means open for trading; `"closed"` means closed. Pair openness alone is insufficient when the competition is paused or an underlying asset is closed. `initial_mark` is the configured initial price, not a current quote.

```python
dictionary = client.competition.retrieve()
pair_id = next(
    (int(key) for key, pair in dictionary["pairs"].items()
     if pair["trading_status"] == "open"),
    None,
)
if pair_id is not None:
    pair = dictionary["pairs"][str(pair_id)]
    symbol = dictionary["assets"][str(pair["base_asset_id"])]["symbol"]
    print(symbol, pair["min_price_increment"], pair["min_qty_increment"])
```

An unknown or inaccessible competition returns an error. Discover or configure actual pair IDs; `2` in examples is illustrative.

## `client.competition.time()`

Read elapsed active competition time for scheduling strategy actions. No inputs. Returns:

```python
{"competition_id": 1, "status": "active", "active_elapsed_ms": 900000}
```

`competition_id` and `active_elapsed_ms` are `int`; `status` uses the competition states above. The clock is in milliseconds, advances only while active, freezes during pauses, and stays fixed after termination. It is not a wall-clock timestamp.

## `client.competition.api_key()`

Retrieve your already-issued key for the configured competition. No inputs. Returns `{"competition_id": int, "api_key": str}`. It does not create, rotate, or obtain initial credentials. Since the SDK already authenticates with that key, strategies rarely need this method. Never print or share its return value. The server can reject the call if no key has been generated or the competition is not eligible.

## `client.competition.leaderboard()`

Read equity rankings in the competition's home currency. No inputs. Returns a `dict` with `competition_id: int`, `status: str`, and `leaderboard: list[dict]`, possibly empty. Each entry has `user_id: int`, `github_username: str`, `equity: Decimal`, and `rank: int`, starting at 1.

```python
from decimal import Decimal

ranking = {
    "competition_id": 1, "status": "active",
    "leaderboard": [{"user_id": 123, "github_username": "trader_alice",
                     "equity": Decimal("1500"), "rank": 1}],
}
```

Active rankings use current marks; a terminated competition uses its stored final ranking. Equity is not a cash balance.

## `client.balances.list()`

Read your current per-asset holdings. No inputs. Fetches fresh data each call. Returns `list[dict]`, possibly empty:

```python
from decimal import Decimal

balances = [
    {"asset_id": 1, "quantity": Decimal("1000")},
    {"asset_id": 2, "quantity": Decimal("-3.25")},
]
```

Each row has `asset_id: int` and `quantity: Decimal`. Quantity is an absolute balance, not a change, and may be negative. Join IDs to `competition.retrieve()["assets"]` using string keys to find symbols. Balances are not an equity calculation or buying-power guarantee.

## `client.orders.create(...)`

```python
client.orders.create(pair_id, *, side, qty, order_type="limit", price=None)
```

Submit one order for your participant and competition. The SDK converts human amounts, waits for managed-stream readiness when streaming is enabled, and shares pacing with cancellation. It sends exactly one submission and never automatically retries it.

| Input | Type / default | Accepted values |
| --- | --- | --- |
| `pair_id` | Required ID | A pair in your competition |
| `side` | Required `str` | `"buy"` or `"sell"`, lowercase |
| `qty` | Required `Amount` | Positive base quantity, aligned to the pair's quantity increment |
| `order_type` | `str`, `"limit"` | One of the five types below |
| `price` | `Amount` or `None`, default `None` | Positive quote-per-base price when provided, aligned to the price increment |

| Order type | Price input | Purpose |
| --- | --- | --- |
| `"limit"` | Required | Buy no higher than the limit or sell no lower; unfilled quantity may rest. |
| `"market"` | Omit or use `None` | Execute against available liquidity without a price limit. Unfilled quantity does not rest. |
| `"ioc"` | Optional | Execute immediately and cancel the remainder. With price it is limit IOC; without price it is market IOC. |
| `"post_only"` | Required | Add liquidity. Reject an order that would immediately take another participant's liquidity. |
| `"fok"` | Required | Fill the entire quantity immediately within the limit, or reject without a partial fill. |

The server also checks competition/instrument state, participation, notional size, risk, and self-trade prevention. Valid Python inputs do not guarantee acceptance.

On success, returns a `dict` acknowledgement:

| Field | Type | Meaning |
| --- | --- | --- |
| `order_id` | `int` | ID for cancellation and history filters |
| `competition_id`, `pair_id` | `int` | Competition and pair |
| `side`, `order_type` | `str` | Submitted side and type |
| `qty` | `Decimal` | Original requested quantity |
| `remaining_qty` | `Decimal` | Unexecuted quantity at acknowledgement; a cancelled remainder can be nonzero |
| `status` | `str` | Matching result, commonly `open`, `partially_filled`, `filled`, or `cancelled` |
| `price` | `Decimal`, optional | Submitted limit, omitted for unpriced orders |
| `created_at` | `str` | Creation time |

```python
from decimal import Decimal

order = client.orders.create(2, side="buy", qty="10", price="150.42")
# Example when the order rests without a fill:
# {"order_id": 42, "competition_id": 1, "pair_id": 2,
#  "side": "buy", "order_type": "limit", "qty": Decimal("10"),
#  "remaining_qty": Decimal("10"), "status": "open",
#  "price": Decimal("150.42"), "created_at": "2026-06-21T19:00:00Z"}
```

Acknowledgement is not a promise of a full fill. Use status, remaining quantity, and fill history. Orders can change immediately after the response.

Invalid arguments raise `ValidationError` before submission. Rejection raises `APIError`; `.order_id` identifies a rejected history row if the server recorded one. Transit failure raises `OrderOutcomeUnknown`: inspect history before deciding whether to resubmit. Stream readiness failures can stop submission. The runner pauses callbacks during a competition pause; direct `create` calls still face the server's active-state checks.

## `client.orders.cancel(order_id)`

Cancel the unfilled portion of your resting order. Input is an ID from a submission's `order_id` or a history row's `id`. Open and partially filled resting orders can be cancelled. Previous fills stay executed.

Returns `{}` on success, without an order record. Read history or notifications for the resulting status. Shares submission pacing and never retries automatically.

```python
client.orders.cancel(order["order_id"])
```

Invalid IDs raise `ValidationError`. Terminal, no-longer-resting, nonexistent, or other users' orders commonly raise `APIError` with `.status == 404`; `.code` can be `None`. Cancellation is callable during recovery, but the server rejects it while the competition is paused. Transit failure raises `OrderOutcomeUnknown`; check history before retrying.

## `client.orders.list(...)`

```python
client.orders.list(*, limit=50, offset=0, status=None, pair_id=None)
```

Read a fresh page of your open and terminal orders, newest order ID first.

| Input | Type / default | Meaning |
| --- | --- | --- |
| `limit` | `int`, `50` | Page size, 1 through 100 |
| `offset` | `int`, `0` | Number of matching rows to skip, at least zero |
| `status` | `str` or `None`, default `None` | Exact filter: `open`, `partially_filled`, `filled`, `cancelled`, or `rejected`. `None` includes all. |
| `pair_id` | ID or `None`, default `None` | One pair, or all pairs when `None` |

`status="open"` excludes partially filled orders. To inspect all potentially resting orders, include both statuses when reading unfiltered history. Booleans are invalid pagination inputs. Invalid arguments raise `ValidationError`.

Returns `{"orders": list[dict], "total": int, "limit": int, "offset": int}`. `total` counts all matching rows. An empty page normally has `[]`; handle `None` defensively with `page["orders"] or []`.

| Order-row field | Type | Meaning |
| --- | --- | --- |
| `id` | `int` | Order ID. History uses `id`; submission uses `order_id`. |
| `competition_id`, `pair_id` | `int` | Competition and pair |
| `side`, `order_type` | `str` | Same values as submission |
| `qty` | `Decimal` | Original quantity |
| `remaining_qty` | `Decimal` | Unexecuted quantity; a terminal order can have a cancelled remainder |
| `status` | `str` | One of the filters above |
| `price` | `Decimal`, optional | Omitted for unpriced orders; handle `None` defensively |
| `rejection_reason` | `str`, optional | Rejection or another recorded lifecycle reason; can be absent or `None` |
| `created_at` | `str` | Creation time |

```python
page = client.orders.list(limit=50, pair_id=2)
for row in page["orders"] or []:
    print(row["id"], row["status"], row["remaining_qty"], row.get("price"))
```

## `client.orders.iter_all(...)`

```python
client.orders.iter_all(*, limit=100, status=None, pair_id=None)
```

Return a lazy `Iterator[dict]` yielding individual rows with the order schema above, newest first. `limit` is a page size from 1 through 100; filters match `orders.list`. Starts at offset zero. Empty history yields nothing. An empty or `None` row collection within the page ends iteration, as does reaching the observed total. The page itself must be a dictionary.

```python
for row in client.orders.iter_all(pair_id=2):
    if row["status"] in {"open", "partially_filled"}:
        print(row["id"], row["remaining_qty"])
```

Requests and validation occur during iteration, not iterator creation, so failures can occur partway through a loop. Passing `offset` or unknown filters raises Python `TypeError` during iteration. Offset pagination over live history can skip or repeat rows during concurrent activity; it is not an atomic snapshot. Deduplicate by `id` when needed.

## `client.fills.list(...)`

```python
client.fills.list(*, limit=50, offset=0, pair_id=None, order_id=None)
```

Read a fresh page of your executions, newest fill ID first. One order can have many fills. `limit` and `offset` follow the order pagination rules. `pair_id` and `order_id` are IDs or `None`, default `None` to include all matches. Invalid inputs raise `ValidationError`.

Returns `{"fills": list[dict], "total": int, "limit": int, "offset": int}`. Total counts all matching executions. Read empty pages with `page["fills"] or []`.

| Fill-row field | Type | Meaning |
| --- | --- | --- |
| `id` | `int` | Fill ID |
| `order_id` | `int` | Your order for this execution |
| `pair_id` | `int` | Executed pair |
| `price` | `Decimal` | Execution price, quote units per base |
| `qty` | `Decimal` | Executed base quantity, not original order quantity |
| `side` | `str` | Your side, `buy` or `sell` |
| `role` | `str` | `maker` for your resting liquidity, `taker` when your order took liquidity |
| `created_at` | `str` | Execution time |

```python
page = client.fills.list(order_id=42)
executed = sum((row["qty"] for row in page["fills"] or []), start=0)
# This sums only this page. Use iter_all for multiple pages.
```

## `client.fills.iter_all(...)`

```python
client.fills.iter_all(*, limit=100, pair_id=None, order_id=None)
```

Return a lazy `Iterator[dict]` over individual fill rows with the schema and filters above. `limit` is a page size from 1 through 100. Empty history yields nothing. Validation and remote failures occur during iteration. Passing `offset` or unknown filters raises Python `TypeError` during iteration. The live-pagination limitations of `orders.iter_all` apply.

```python
from decimal import Decimal

executed = sum(
    (fill["qty"] for fill in client.fills.iter_all(order_id=42)),
    start=Decimal("0"),
)
```

## Book return value

Both book methods return `dict` with `pair_id: int`, `bids: list[dict]`, and `asks: list[dict]`. Each level has `price: Decimal` and `qty: Decimal`. Quantity is the total displayed quantity at that price. Bids are highest price first; asks are lowest first. Either side can be `[]`.

```python
from decimal import Decimal

book = {
    "pair_id": 2,
    "bids": [{"price": Decimal("150.42"), "qty": Decimal("3")}],
    "asks": [],
}
best_bid = book["bids"][0]["price"] if book["bids"] else None
best_ask = book["asks"][0]["price"] if book["asks"] else None
```

## `client.market.snapshot(pair_id)`

Fetch one current book without opening a depth subscription. Input is a pair ID; invalid IDs raise `ValidationError`. Returns the book schema above. Each call requests a new snapshot. The returned object does not update later. The server can reject it when no matching engine runs for the pair.

```python
book = client.market.snapshot(2)
```

## `client.market.order_book(pair_id)`

Read the latest managed book. Input is a pair ID; invalid IDs raise `ValidationError`. First use starts that pair's depth subscription and ensures a private/global subscription. Each call waits for all managed streams to recover, then returns a separate copy of the book schema above.

```python
book = client.market.order_book(2)
```

Later calls reuse the subscription; the internal book updates between calls. A previously returned dictionary stays a fixed copy. An empty book is valid after readiness. This method does not make a REST book request on every call.

Each watched pair uses an additional stream connection. Depth stays subscribed until `release(pair_id)` or `close()`. Readiness timeout raises `StreamError`; invalid access, closed instruments, and fatal stream failures propagate. `auto_stream=False` does not disable streaming explicitly requested by this method.

## `client.market.candles(...)`

```python
client.market.candles(pair_id, *, bucket="1m")
```

Read historical trade candles for indicators. `pair_id` is an ID; `bucket` is a `str`, one of `"1m"`, `"5m"`, `"15m"`, or `"1h"`, default `"1m"`. Invalid inputs raise `ValidationError`. This SDK method exposes no date-range or pagination arguments.

Returns `{"pair_id": int, "bucket": str, "candles": list[dict] | None}`. No trades can produce `None`; use `result["candles"] or []`. Candles are oldest first and derive from executions. Empty buckets have no synthetic candle. The latest bucket can still change.

The method provides no completed-bucket flag or retention-horizon guarantee. Fetching again makes another server request. Choose your own policy for using or excluding the newest candle; elapsed wall time and a stable-looking value alone are not an SDK finality guarantee.

| Candle field | Type | Meaning |
| --- | --- | --- |
| `timestamp` | `str` | UTC bucket start time |
| `open`, `high`, `low`, `close` | `Decimal` | First, highest, lowest, and last execution price |
| `volume` | `Decimal` | Total executed base quantity |

```python
result = client.market.candles(2, bucket="5m")
for candle in result["candles"] or []:
    print(candle["timestamp"], candle["close"], candle["volume"])
```

## `client.start()`

Start or reuse the private/global stream and wait for all managed streams. No inputs. Returns the same `TradingClient`. Initial connection and reconnection refresh competition state and private history. Calling `start()` on an already-ready client does not fetch fresh history; use resource reads for that. This does not subscribe to every pair.

Context entry calls this when `auto_stream=True`; `run` calls it too. With `auto_stream=False`, this explicitly enables streaming. Authentication failures, fatal stream failures, and readiness timeout propagate. An ended competition cannot start a new subscription.

## `client.run(...)`

```python
client.run(strategy, *, interval=1.0, max_iterations=None)
```

Run your strategy on the calling thread while streams run in the background. Returns `None`. Each callback receives this client; the runner ignores the callback's return value.

| Input | Type / default | Meaning |
| --- | --- | --- |
| `strategy` | Required callable | A function accepting one `TradingClient` |
| `interval` | Positive finite seconds, `1.0` | Wait after each completed callback. Callback duration adds to the time between starts. |
| `max_iterations` | Nonnegative `int` or `None`, default `None` | Number of callbacks; `None` runs until stopped. `0` starts/waits for streams but calls no strategy. |

```python
def strategy(client):
    book = client.market.order_book(2)
    if book["asks"]:
        print(book["asks"][0]["price"])

with TradingClient.from_env() as client:
    client.run(strategy, interval=1.0, max_iterations=10)
```

The runner enables streaming even with `auto_stream=False`. It waits during recovery and competition pauses, then resumes. Termination or competition cancellation stops it. It cannot interrupt an executing callback; keep callbacks short. Interval is a delay, not a guaranteed wall-clock schedule.

Pending status is not a callback pause condition. If the server permits a stream while pending, callbacks can run, although new orders still require an active competition. For a trading decision, check current competition and instrument state. `max_iterations` bounds callback count, not wall-clock duration; a pause can extend the run indefinitely.

Invalid numeric controls raise `ConfigurationError`. SDK failures propagate, and failures inside the loop also log. Strategy exceptions propagate; programming errors are not swallowed. Ctrl+C raises `KeyboardInterrupt`, handled by the starter. Returning from `run` does not close the client; use its context manager or `close()`.

## `client.recovery_snapshot`

Read a copy of the last successful refresh without making a request. This is a property. It is `{}` before the first recovery, otherwise:

| Field | Type | Meaning |
| --- | --- | --- |
| `competition` | `dict` | Same schema as `competition.retrieve()` |
| `balances` | `list[dict]` | Same schema as `balances.list()` |
| `orders` | `list[dict]` | Order-history rows from all pages |
| `fills` | `list[dict]` | Fill-history rows from all pages |

It is not a continuously current portfolio or an atomic transaction across reads. Use resource methods for fresh private data. Changing this copy does not alter SDK state.

## `client.events()` and `client.errors()`

Both take no inputs and return immediately. These optional queues expose notifications the SDK already handles; the starter needs no async handler.

`events()` returns `list[Event]` and clears queued events. Each `Event` has `name: str` and `data: dict`; see [event payloads](streaming.md#event-payloads). `Event(name, data)` is an exported dataclass; constructing one does not send anything to the server.

`errors()` returns `list[SDKError]` and clears errors already logged by the SDK. It does not record every exception from direct calls, which raise to the caller. Both return `[]` when empty. Each queue retains at most 1,000 entries. Event overflow logs a report. Neither is a durable trading record.

```python
for event in client.events():
    if event.name == "fill":
        print(event.data["fill_id"], event.data["price"], event.data["qty"])
```

## `client.close()`

Stop managed subscriptions and close HTTP connections. No inputs. Returns `None`. Repeated calls are safe. An executing callback cannot be interrupted. A closed client cannot reopen; create a new one.

Draining `events()` or `errors()`, reading `recovery_snapshot`, and releasing an already-unregistered pair remain safe after close. They do not reopen connections. Avoid using any closed subscription for live data.

The context manager starts streaming when enabled and closes on exit, including on exceptions. It does not suppress exceptions.

## `client.streams.subscribe(pair_id=None)`

Explicitly start or reuse a subscription. Prefer `market.order_book` for automatic depth. `pair_id` is an ID or `None`, default `None`. `None` selects private/global notifications. A pair selects its depth stream, also starting private/global streaming if needed. Invalid IDs raise `ValidationError`. Closed, ended, or fatally failed clients cannot subscribe.

Returns a `Subscription` immediately; startup is asynchronous. Repeating the call for a registered pair reuses its subscription. Later startup errors log and surface through readiness checks.

| Subscription member | Type / behavior |
| --- | --- |
| `pair_id` | `int` for depth, `None` for private/global |
| `stream_id` | Connected `str`, or `None` before/between connections; changes on reconnect |
| `ready` | `bool` for this subscription, not every stream |
| `failure` | Terminal `SDKError` or `None` |
| `book()` | No inputs. Returns a copy of the book when depth is ready; otherwise raises `StreamError`. Private/global has no book. Does not wait. |
| `close()` | No inputs. Returns `None`, stopping this subscription. Prefer `streams.release(pair_id)` so the manager also unregisters it. Closing it directly leaves the stopped subscription registered; future readiness waits can time out. |

Use `client.start()` to wait for all streams, or `market.order_book` to start and wait for depth. Do not call `Subscription.start()` yourself; the manager owns startup. Treat attributes as read-only.

## `client.streams.release(pair_id)`

Stop and unregister a depth subscription. Input is an ID; invalid IDs raise `ValidationError`. Returns `None`. Releasing an unwatched pair safely does nothing. Private/global events continue. The next `subscribe` or `order_book` creates a new subscription.

```python
client.streams.release(2)
```

## Manual depth controls

These advanced methods control a connected stream belonging to you. Prefer `order_book` and `release`. Manually changing a managed stream can disagree with its registered pair and leave readiness checks waiting.

For a managed pair, release its original `pair_id`, then read `order_book` again to create a correctly registered subscription. If the private/global subscription was closed directly, or a readiness timeout has already marked the whole client fatal, close the client and create a new one. Manually clearing depth is not a substitute for releasing a managed pair.

### `client.streams.set_depth(stream_id, pair_id)`

Set one stream's depth pair and request its snapshot. Inputs are a nonempty `str` stream ID and a pair ID. Invalid values raise `ValidationError`.

Returns `dict` with `status: str`, currently `"depth_updated"`; `pair_id: int`; and `previous_pair_id: int`, where zero means no previous pair. Optional `snapshot` uses the book schema. A server can successfully set depth without a snapshot if its matching engine is unavailable. Do not assume the snapshot is present.

Expired/disconnected IDs, another user's stream, a pair outside the competition, or a closed pair can fail. Use the current stream ID; old IDs fail after reconnect. SDK exceptions preserve the server's reason.

### `client.streams.clear_depth(stream_id)`

Clear depth while retaining private/global notifications on the connection. Input is a nonempty `str` stream ID; invalid values raise `ValidationError`. Returns `None`. Does not close or unregister a managed subscription. Expired IDs and ownership failures propagate. Use `release(pair_id)` to stop managed depth safely.

## Amount helpers

```python
from trading_sdk import Amount, from_wire, to_wire

to_wire(value)     # Amount -> str
from_wire(value)   # str -> Decimal
```

These are diagnostic/interoperability helpers. Normal methods already convert amounts.

`to_wire` accepts a finite `Amount` with at most four nonzero decimal places in the signed range. Returns a signed integer string at scale 10,000. Zero and negative values are allowed here; orders require positive amounts. Invalid type, precision, or range raises `ValidationError`.

`from_wire` accepts a decimal integer `str`, with an optional leading minus and at most 20 characters, within the signed 64-bit range. There is no leading plus, decimal point, or surrounding whitespace. For example, `"1504200"` returns `Decimal("150.42")`. Floats, human decimal strings like `"150.42"`, and invalid wire values raise `ProtocolError`. Exact ranges and examples are in [amounts](amounts.md).

Never pass `to_wire` output into `orders.create`; it would be interpreted as a human amount and scaled again.
