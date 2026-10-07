"""Convert human decimal amounts to signed int64 strings at a 10,000 scale."""

import re
from decimal import Decimal, DecimalException, localcontext
from typing import Any

from .errors import ProtocolError, ValidationError

Amount = str | int | Decimal
SCALE = 10_000
MIN_INT64 = -(2**63)
MAX_INT64 = 2**63 - 1
MONEY_FIELDS = frozenset({
    "price", "qty", "quantity", "remaining_qty", "equity", "equity_floor",
    "initial_mark", "min_price_increment", "min_qty_increment", "mark_price",
    "open", "high", "low", "close", "volume", "strike", "delta",
})


def to_wire(value: Amount) -> str:
    """Reject floats, rounding, nonfinite amounts and int64 overflow."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError("Use a decimal string, int, or Decimal for amounts, not float.")
    try:
        amount = Decimal(value)
        if not amount.is_finite():
            raise ValidationError("Amounts must be finite.")
        if amount.is_zero():
            return "0"
        if amount.adjusted() > 14:
            raise ValidationError("Amount exceeds the API's signed int64 range.")
        parts = amount.as_tuple()
        trailing_zeros = 0
        for digit in reversed(parts.digits):
            if digit != 0:
                break
            trailing_zeros += 1
        if parts.exponent + trailing_zeros < -4:
            raise ValidationError("Amounts support at most four decimal places; no rounding.")
        with localcontext() as context:
            context.prec = 40
            scaled = amount * SCALE
            if scaled != scaled.to_integral_value():
                raise ValidationError("Amounts support at most four decimal places; no rounding.")
            if not MIN_INT64 <= scaled <= MAX_INT64:
                raise ValidationError("Amount exceeds the API's signed int64 range.")
            return str(int(scaled))
    except (DecimalException, ValueError, OverflowError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("Invalid decimal amount.") from exc


def from_wire(value: str) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+", value):
        raise ProtocolError("Expected a signed scaled integer string from the server.")
    if len(value) > 20 or not MIN_INT64 <= int(value) <= MAX_INT64:
        raise ProtocolError("Server amount exceeds the signed int64 range.")
    with localcontext() as context:
        context.prec = 40
        return Decimal(value) / SCALE


def decode(value: Any) -> Any:
    """Decode known monetary fields, retaining unknown fields and integer IDs."""
    if isinstance(value, list):
        return [decode(item) for item in value]
    if isinstance(value, dict):
        return {
            key: from_wire(item) if key in MONEY_FIELDS and item is not None else decode(item)
            for key, item in value.items()
        }
    return value
