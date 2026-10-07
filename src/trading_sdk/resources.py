from collections.abc import Iterator
from urllib.parse import quote

from .errors import ValidationError
from .money import Amount, to_wire

# Keep the endpoint inventory testable against the actual Go routes.
ENDPOINTS = {
    ("GET", "/health"),
    ("GET", "/api/competitions/{id}"),
    ("GET", "/api/competitions/{id}/time"),
    ("GET", "/api/competitions/{id}/api-key"),
    ("GET", "/api/competitions/{id}/balances"),
    ("GET", "/api/competitions/{id}/leaderboard"),
    ("GET", "/api/competitions/{id}/orders"),
    ("GET", "/api/competitions/{id}/fills"),
    ("GET", "/api/competitions/{id}/pairs/{pairId}/lob"),
    ("GET", "/api/competitions/{id}/pairs/{pairId}/candles"),
    ("GET", "/api/competitions/{id}/stream"),
    ("PUT", "/api/competitions/{id}/streams/{streamId}/depth"),
    ("DELETE", "/api/competitions/{id}/streams/{streamId}/depth"),
    ("POST", "/api/orders"),
    ("DELETE", "/api/orders/{id}"),
}


def positive_id(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValidationError(f"{name} must be a positive int64 integer.")
    return value


def page_params(limit, offset, **filters):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValidationError("limit must be an integer between 1 and 100.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValidationError("offset must be a nonnegative integer.")
    for key in ("pair_id", "order_id"):
        if filters.get(key) is not None:
            positive_id(filters[key], key)
    return {"limit": limit, "offset": offset, **filters}


class Resource:
    def __init__(self, client):
        self.client = client

    def get(self, suffix="", **params):
        return self.client._request("GET", self.client._path + suffix, params=params)


class Competition(Resource):
    def retrieve(self):
        return self.get()

    def time(self):
        return self.get("/time")

    def api_key(self):
        """Return the key for the already authenticated participant; keep it secret."""
        return self.get("/api-key")

    def leaderboard(self):
        return self.get("/leaderboard")


class Balances(Resource):
    def list(self):
        return self.get("/balances")


class History(Resource):
    key = ""

    def _list(self, limit, offset, **filters):
        return self.get("/" + self.key, **page_params(limit, offset, **filters))

    def iter_all(self, *, limit=100, **filters) -> Iterator[dict]:
        """Fetch offset pages lazily; history can change while iterating."""
        offset = 0
        while True:
            page = self.list(limit=limit, offset=offset, **filters)
            rows = page[self.key] or []
            yield from rows
            offset += len(rows)
            if not rows or offset >= page["total"]:
                return


class Orders(History):
    key = "orders"

    def list(self, *, limit=50, offset=0, status=None, pair_id=None):
        if status is not None and status not in {
            "open", "filled", "partially_filled", "cancelled", "rejected",
        }:
            raise ValidationError("Invalid order status filter.")
        return self._list(limit, offset, status=status, pair_id=pair_id)

    def create(self, pair_id: int, *, side: str, qty: Amount,
               order_type="limit", price: Amount | None = None):
        positive_id(pair_id, "pair_id")
        if side not in {"buy", "sell"}:
            raise ValidationError("side must be buy or sell.")
        if order_type not in {"limit", "market", "ioc", "post_only", "fok"}:
            raise ValidationError("order_type must be limit, market, ioc, post_only, or fok.")
        if order_type in {"limit", "post_only", "fok"} and price is None:
            raise ValidationError(f"price is required for {order_type} orders.")
        if order_type == "market" and price is not None:
            raise ValidationError("Omit price for market orders.")
        quantity = to_wire(qty)
        if int(quantity) <= 0:
            raise ValidationError("qty must be positive.")
        body = {
            "competition_id": self.client.competition_id, "pair_id": pair_id,
            "side": side, "order_type": order_type, "qty": quantity,
        }
        if price is not None:
            body["price"] = to_wire(price)
            if int(body["price"]) <= 0:
                raise ValidationError("price must be positive.")
        self.client._before_order()
        return self.client._request("POST", "/api/orders", body=body)

    def cancel(self, order_id: int):
        positive_id(order_id, "order_id")
        # Cancellations stay available during pauses and stream recovery.
        return self.client._request("DELETE", f"/api/orders/{order_id}")


class Fills(History):
    key = "fills"

    def list(self, *, limit=50, offset=0, pair_id=None, order_id=None):
        return self._list(limit, offset, pair_id=pair_id, order_id=order_id)


class Market(Resource):
    def snapshot(self, pair_id: int):
        positive_id(pair_id, "pair_id")
        return self.get(f"/pairs/{pair_id}/lob")

    def candles(self, pair_id: int, *, bucket="1m"):
        positive_id(pair_id, "pair_id")
        if bucket not in {"1m", "5m", "15m", "1h"}:
            raise ValidationError("bucket must be 1m, 5m, 15m, or 1h.")
        return self.get(f"/pairs/{pair_id}/candles", bucket=bucket)

    def order_book(self, pair_id: int):
        """Start depth automatically, wait for recovery, and return a copy of the book."""
        stream = self.client.streams.subscribe(pair_id)
        self.client._wait_ready()
        return stream.book()


class Streams(Resource):
    def subscribe(self, pair_id: int | None = None):
        if pair_id is not None:
            positive_id(pair_id, "pair_id")
        return self.client._subscribe(pair_id)

    def release(self, pair_id: int):
        """Close a managed pair stream; global/private events remain active."""
        positive_id(pair_id, "pair_id")
        self.client._release(pair_id)

    def set_depth(self, stream_id: str, pair_id: int):
        positive_id(pair_id, "pair_id")
        return self.client._request(
            "PUT", self._depth_path(stream_id), body={"pair_id": pair_id},
        )

    def clear_depth(self, stream_id: str):
        return self.client._request("DELETE", self._depth_path(stream_id))

    def _depth_path(self, stream_id):
        if not isinstance(stream_id, str) or not stream_id:
            raise ValidationError("stream_id must be a nonempty string.")
        return f"{self.client._path}/streams/{quote(stream_id, safe='')}/depth"
