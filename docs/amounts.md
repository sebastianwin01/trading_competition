# Amount conversion

The API uses signed int64 values encoded as JSON strings with a scale of 10,000. The SDK handles this conversion for order requests, REST responses, and SSE events. Participants work with human decimal amounts.

| Human amount | API wire value | SDK response |
| --- | --- | --- |
| `"150.42"` | `"1504200"` | `Decimal("150.42")` |
| `"10"` | `"100000"` | `Decimal("10")` |
| `"0.0001"` | `"1"` | `Decimal("0.0001")` |
| `"-3.25"` | `"-32500"` | `Decimal("-3.25")` |

Use `str`, `Decimal`, or `int`. Floats and booleans raise `ValidationError`. Four decimal places are the smallest supported increment. Extra trailing zeros are fine, but a nonzero fifth decimal place raises an error. Values must be finite and within the API's signed int64 range. The SDK never rounds an amount to make it valid.

```python
from decimal import Decimal

price = Decimal("150.42")
quantity = Decimal("10")
order = client.orders.create(2, side="buy", price=price, qty=quantity)
assert order["qty"] == Decimal("10")
```

The largest human amount is `922337203685477.5807`; the smallest signed amount is `-922337203685477.5808`. Orders require positive prices and quantities. Balances may be negative.

## Tick and lot sizes

Wire precision and pair increments are separate rules. A pair may allow only prices in `0.01` increments and quantities in `1` increments, even though the wire can represent `0.0001`.

```python
dictionary = client.competition.retrieve()
pair = dictionary["pairs"]["2"]
price_tick = pair["min_price_increment"]
quantity_lot = pair["min_qty_increment"]
print(price_tick, quantity_lot)  # Decimal values in human units
```

The server validates tick alignment and notional size. The SDK forwards its rejection details. Choose how your strategy rounds to a tick; the SDK will not make that trading decision.

## Response types

Responses are ordinary dictionaries and lists. Monetary fields become `Decimal`, including book prices and quantities, balances, equity, candle OHLCV values, initial marks, and pair increments. IDs remain integers. Dictionary asset/pair keys remain strings, matching JSON. Timestamps remain strings. Unknown fields remain available. Optional monetary values remain `None` when null and remain absent when omitted.

`Decimal` is not JSON serializable by default. If you save SDK responses, use an explicit encoder such as `json.dumps(response, default=str)`. That produces human decimal strings, not the API's wire representation.

`to_wire` and `from_wire` are available for diagnostics:

```python
from trading_sdk import from_wire, to_wire

assert to_wire("150.42") == "1504200"
assert str(from_wire("1504200")) == "150.42"
```

Do not pass `to_wire` output into `orders.create`; the client would scale it again.
