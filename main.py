
import logging
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from time import monotonic

from trading_sdk import SDKError, TradingClient


# ==========================================
# STEP 1: STRATEGY CONFIGURATION
# ==========================================

PAIR_ID = 157                 # ANTH/USD
DRY_RUN = True                # No real trades initially

MAX_ORDER_USD = Decimal("2500")
MAX_POSITION_USD = Decimal("100000")

MAX_SPREAD_PCT = Decimal("0.50")

# Buy when price is 0.5% to 12% above the
# recent moving average (momentum strategy).
MIN_MOMENTUM_PCT = Decimal("0.50")
MAX_MOMENTUM_PCT = Decimal("12.0")

# Sell part of the position if the price
# falls more than 2% below the moving average.
SELL_THRESHOLD = Decimal("0.98")

# Minimum seconds between submitted orders.
ORDER_COOLDOWN = 60
last_order_time = 0.0


# ==========================================
# STEP 2: ROUND QUANTITY TO VALID LOT SIZE
# ==========================================

def round_to_lot(quantity, lot_size):
    steps = (quantity / lot_size).to_integral_value(
        rounding=ROUND_DOWN
    )
    return steps * lot_size


# ==========================================
# STEP 3: STRATEGY FUNCTION
# ==========================================

def strategy(client: TradingClient):
    global last_order_time

    print("\n--- STRATEGY STARTED ---", flush=True)

    # A. GET COMPETITION INFORMATION
    info = client.competition.retrieve()
    pair = info["pairs"].get(str(PAIR_ID))

    if (
        info["status"] != "active"
        or pair is None
        or pair["trading_status"] != "open"
    ):
        print("Market or competition is not active.")
        return

    assets = info["assets"]

    base_id = pair["base_asset_id"]
    quote_id = pair["quote_asset_id"]

    base_asset = assets[str(base_id)]
    quote_asset = assets[str(quote_id)]

    base = base_asset["symbol"]
    quote = quote_asset["symbol"]

    if quote != "USD":
        print("This strategy requires a USD quote.")
        return

    if (
        base_asset["trading_status"] != "open"
        or quote_asset["trading_status"] != "open"
    ):
        print("Underlying asset is not open.")
        return

    # B. GET LIVE ORDER BOOK
    book = client.market.order_book(PAIR_ID)

    if not book["bids"] or not book["asks"]:
        print("Waiting for bid/ask data.")
        return

    best_bid = book["bids"][0]["price"]
    best_ask = book["asks"][0]["price"]

    bid_qty = book["bids"][0]["qty"]
    ask_qty = book["asks"][0]["qty"]

    if (
        best_bid <= 0
        or best_ask <= best_bid
        or bid_qty <= 0
        or ask_qty <= 0
    ):
        print("Invalid order book.")
        return

    # C. CALCULATE SPREAD AND LIQUIDITY
    spread = best_ask - best_bid
    mid_price = (best_bid + best_ask) / 2
    spread_pct = spread / mid_price * 100

    total_qty = bid_qty + ask_qty
    imbalance = (bid_qty - ask_qty) / total_qty

    print(f"Market: {base}/{quote}")
    print(f"Bid: {best_bid} | Ask: {best_ask}")
    print(f"Spread: {spread_pct:.3f}%")
    print(f"Order book imbalance: {imbalance:.3f}")

    # D. GET HISTORICAL PRICE DATA
    candles = (
        client.market.candles(PAIR_ID, bucket="1m")
        ["candles"] or []
    )

    # Five previous candles, excluding newest candle.
    if len(candles) < 6:
        print("Not enough historical data.")
        return

    closes = [c["close"] for c in candles[-6:-1]]

    moving_average = (
        sum(closes, Decimal("0")) / Decimal("5")
    )

    if moving_average <= 0:
        return

    # Percentage difference from moving average.
    momentum_pct = (
        (mid_price - moving_average)
        / moving_average * 100
    )

    print(f"Moving average: {moving_average:.4f}")
    print(f"Momentum: {momentum_pct:.2f}%")

    # E. GET CURRENT PORTFOLIO BALANCES
    balances = client.balances.list()

    holdings = {
        row["asset_id"]: row["quantity"]
        for row in balances
    }

    base_balance = holdings.get(base_id, Decimal("0"))
    usd_balance = holdings.get(quote_id, Decimal("0"))

    # Negative position requires separate short-risk logic.
    if base_balance < 0:
        print("Short position detected. No trade.")
        return

    # Conservative valuation at the purchase price.
    position_value = base_balance * best_ask

    print(f"{base} holdings: {base_balance}")
    print(f"USD cash: {usd_balance}")
    print(f"Position value: ${position_value:.2f}")

    # F. INITIALIZE TRADING DECISION
    side = None
    price = None
    desired_qty = Decimal("0")

    # G. BUY SIGNAL
    # Unlike the previous version, we can BUY even
    # when we already own some ANTH shares.
    #
    # Conditions:
    # - Positive momentum within selected bounds
    # - Spread no wider than 0.5%
    # - At least as much bid quantity as ask quantity
    # - Position remains below $100,000

    buy_signal = (
        MIN_MOMENTUM_PCT <= momentum_pct <= MAX_MOMENTUM_PCT
        and spread_pct <= MAX_SPREAD_PCT
        and imbalance >= Decimal("0")
        and position_value < MAX_POSITION_USD
    )

    # H. SELL SIGNAL
    # Reduce the position if market price falls
    # more than 2% below its recent moving average.
    sell_signal = (
        base_balance > 0
        and mid_price < moving_average * SELL_THRESHOLD
    )

    # Handle downside risk first.
    if sell_signal:
        side = "sell"
        price = best_bid

        # Sell a limited quantity, never more than owned.
        desired_qty = min(
            base_balance,
            bid_qty,
            MAX_ORDER_USD / price
        )

    elif buy_signal:
        side = "buy"
        price = best_ask

        # Calculate remaining room under position limit.
        remaining_budget = (
            MAX_POSITION_USD - position_value
        )

        # Restrict spending by order size, cash balance,
        # remaining position budget and available asks.
        desired_qty = min(
            MAX_ORDER_USD / price,
            remaining_budget / price,
            max(usd_balance, Decimal("0")) / price,
            ask_qty
        )

    else:
        print("Signal: HOLD")
        return

    # I. ROUND TO EXCHANGE'S QUANTITY INCREMENT
    lot_size = pair["min_qty_increment"]

    if lot_size <= 0:
        print("Invalid lot size.")
        return

    order_qty = round_to_lot(desired_qty, lot_size)

    if order_qty <= 0:
        print("Order below minimum quantity.")
        return

    print(f"Signal: {side.upper()}")
    print(f"Order quantity: {order_qty}")
    print(f"Limit price: {price}")
    print(f"Order value: ${order_qty * price:.2f}")

    # J. PAPER TEST: DO NOT SUBMIT ACTUAL ORDERS
    if DRY_RUN:
        print("DRY RUN: No order submitted.")
        return

    # K. COOLDOWN TO REDUCE OVERTRADING
    if monotonic() - last_order_time < ORDER_COOLDOWN:
        print("Cooldown active.")
        return

    # L. PREVENT DUPLICATE RESTING ORDERS
    # Keep this return statement.
    for order in client.orders.iter_all(pair_id=PAIR_ID):
        if order["status"] in {"open", "partially_filled"}:
            print(f"Resting order {order['id']} detected.")
            print("No new order submitted.")
            return

    # M. SUBMIT LIMIT IMMEDIATE-OR-CANCEL ORDER
    # Buy at or below the ask, sell at or above the bid.
    # A fill is not guaranteed. Unfilled units are cancelled.

    last_order_time = monotonic()

    order = client.orders.create(
        PAIR_ID,
        side=side,
        qty=order_qty,
        price=price,
        order_type="ioc"
    )

    print(f"Order ID: {order['order_id']}")
    print(f"Status: {order['status']}")
    print(f"Remaining: {order['remaining_qty']}")


# ==========================================
# STEP 4: MAIN PROGRAM
# ==========================================

def main():
    logging.basicConfig(level=logging.WARNING)

    try:
        with TradingClient.from_env(
            Path(__file__).with_name(".env")
        ) as client:

            info = client.recovery_snapshot["competition"]

            print(
                f"Competition {client.competition_id}: "
                f"{info['name']}"
            )

            print(f"Selected Pair: {PAIR_ID}")
            print(
                "Mode: DRY RUN" if DRY_RUN
                else "Mode: LIVE TRADING"
            )

            # Run three supervised test iterations.
            client.run(
                strategy,
                interval=10.0,
                max_iterations=10
            )

    except KeyboardInterrupt:
        print("Strategy stopped.")

    except SDKError as error:
        print(f"Strategy stopped: {error}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
