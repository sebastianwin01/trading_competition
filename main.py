"""Edit strategy(). This starter observes the book and places no orders."""

import logging
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from time import monotonic

from trading_sdk import SDKError, TradingClient


# ==========================================
# STEP 1: STRATEGY CONFIGURATION
# ==========================================

# Focus on one market to avoid opening 26 streams.
PAIR_ID = 157  # ANTH/USD

# Safety switch: True = analyze only, False = submit real orders.
DRY_RUN = True

# Maximum USD amount allowed per order.
MAX_ORDER_USD = Decimal("1500")

# Maximum target exposure to ANTH.
MAX_POSITION_USD = Decimal("1500")

# Maximum acceptable spread for a NEW purchase.
MAX_SPREAD_PCT = Decimal("1.0")

# Moving-average signal thresholds.
BUY_THRESHOLD = Decimal("0.99")
SELL_THRESHOLD = Decimal("1.01")
EXIT_THRESHOLD = Decimal("0.975")

# Minimum time between actual order submissions.
ORDER_COOLDOWN = 60

last_order_time = 0.0


# ==========================================
# STEP 2: QUANTITY ROUNDING
# ==========================================

def round_to_lot(quantity, lot_size):
    """
    Round the desired quantity DOWN to the
    minimum permitted trading increment.
    """
    steps = (quantity / lot_size).to_integral_value(
        rounding=ROUND_DOWN
    )

    return steps * lot_size


# ==========================================
# STEP 3: TRADING STRATEGY
# ==========================================

def strategy(client: TradingClient):
    global last_order_time

    print("\n--- STRATEGY STARTED ---", flush=True)

    # A. RETRIEVE COMPETITION INFORMATION
    info = client.competition.retrieve()

    pairs = info["pairs"]
    assets = info["assets"]

    pair = pairs.get(str(PAIR_ID))

    # Do not trade if the competition or pair is closed.
    if (
        info["status"] != "active"
        or pair is None
        or pair["trading_status"] != "open"
    ):
        print("Competition or pair is not active.")
        return

    # Identify the base and quote assets.
    base_id = pair["base_asset_id"]
    quote_id = pair["quote_asset_id"]

    base_asset = assets[str(base_id)]
    quote_asset = assets[str(quote_id)]

    base = base_asset["symbol"]
    quote = quote_asset["symbol"]

    # We express our risk limits in USD.
    if quote != "USD":
        print("This example only supports USD-quoted pairs.")
        return

    # Both underlying assets must be open.
    if (
        base_asset["trading_status"] != "open"
        or quote_asset["trading_status"] != "open"
    ):
        print("One of the assets is closed.")
        return

    # B. RETRIEVE THE LIVE ORDER BOOK
    # Only one order_book() call is needed.
    book = client.market.order_book(PAIR_ID)

    # Do not calculate statistics from incomplete books.
    if not book["bids"] or not book["asks"]:
        print("Waiting for complete order-book data.")
        return

    # Best available prices and quantities.
    best_bid = book["bids"][0]["price"]
    best_ask = book["asks"][0]["price"]

    bid_qty = book["bids"][0]["qty"]
    ask_qty = book["asks"][0]["qty"]

    # Validate prices and available quantities.
    if (
        best_bid <= 0
        or best_ask <= best_bid
        or bid_qty <= 0
        or ask_qty <= 0
    ):
        print("Invalid or empty market data.")
        return

    # C. CALCULATE MARKET STATISTICS

    # Difference between selling and buying quotations.
    spread = best_ask - best_bid

    # Average of best bid and best ask.
    mid_price = (best_bid + best_ask) / 2

    # Spread relative to the mid-price.
    spread_pct = spread / mid_price * 100

    # Notional liquidity at the top of the order book.
    bid_liquidity = best_bid * bid_qty
    ask_liquidity = best_ask * ask_qty

    # Quantity imbalance between buyers and sellers.
    imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)

    print(f"Market: {base}/{quote}")
    print(f"Bid: {best_bid} | Ask: {best_ask}")
    print(f"Spread: {spread_pct:.3f}%")
    print(f"Mid-price: {mid_price:.4f}")
    print(f"Bid liquidity: {bid_liquidity:.2f} USD")
    print(f"Ask liquidity: {ask_liquidity:.2f} USD")
    print(f"Imbalance: {imbalance:.3f}")

    # D. CALCULATE A SIMPLE MOVING AVERAGE
    # Retrieve historical 1-minute trade candles.
    result = client.market.candles(PAIR_ID, bucket="1m")
    candles = result["candles"] or []

    # Require five candles plus the current candle.
    if len(candles) < 6:
        print("Waiting for more price history.")
        return

    # Exclude the newest candle because it may be incomplete.
    closes = [c["close"] for c in candles[-6:-1]]

    # Average closing price of five previous candles.
    moving_average = sum(
        closes, Decimal("0")
    ) / Decimal("5")

    print(f"5-period moving average: {moving_average:.4f}")

    # E. CHECK CURRENT HOLDINGS
    # Read balances instead of assuming we hold nothing.
    balances = client.balances.list()

    holdings = {
        item["asset_id"]: item["quantity"]
        for item in balances
    }

    base_balance = holdings.get(base_id, Decimal("0"))
    quote_balance = holdings.get(quote_id, Decimal("0"))

    print(f"{base} balance: {base_balance}")
    print(f"{quote} balance: {quote_balance}")

    # This strategy does not manage short positions.
    if base_balance < 0:
        print("Negative holdings detected. No action.")
        return

    # F. DETERMINE A TRADING SIGNAL
    side = None
    price = None
    desired_qty = Decimal("0")
    reason = ""

    # SELL: Reduce an existing long position.
    # This also applies to existing ANTH holdings.
    if base_balance > 0:

        # Exit when the market rises above the average.
        # This is a signal, not proof of profitability.
        if mid_price >= moving_average * SELL_THRESHOLD:
            reason = "Price above moving average"

        # Defensive exit if price falls significantly
        # below the moving average.
        elif mid_price <= moving_average * EXIT_THRESHOLD:
            reason = "Downside risk-exit signal"

        if reason:
            side = "sell"

            # Sell at no less than the best current bid.
            price = best_bid

            # Never sell more than we hold or than
            # the displayed bid quantity.
            desired_qty = min(
                base_balance,
                bid_qty,
                MAX_ORDER_USD / price
            )

    # BUY: Enter only when we hold no base asset.
    elif (
        mid_price <= moving_average * BUY_THRESHOLD
        and spread_pct <= MAX_SPREAD_PCT
        and imbalance >= Decimal("-0.25")
    ):
        side = "buy"
        reason = "Price below moving average"

        # Buy at no more than the best current ask.
        price = best_ask

        # Limit the order by capital, holdings exposure,
        # cash availability, and displayed ask quantity.
        desired_qty = min(
            MAX_ORDER_USD / price,
            MAX_POSITION_USD / price,
            quote_balance / price,
            ask_qty
        )

    # G. HANDLE NO-SIGNAL CONDITIONS
    if side is None:
        print("Signal: HOLD - no suitable trade.")
        return

    # H. RESPECT EXCHANGE QUANTITY INCREMENTS
    lot_size = pair["min_qty_increment"]

    if lot_size <= 0:
        print("Invalid minimum quantity increment.")
        return

    order_qty = round_to_lot(desired_qty, lot_size)

    if order_qty <= 0:
        print("Order is too small for the permitted lot size.")
        return

    print(f"Signal: {side.upper()}")
    print(f"Reason: {reason}")
    print(f"Quantity: {order_qty}")
    print(f"Limit price: {price}")

    # I. PAPER MODE
    # Do not send real orders while DRY_RUN is True.
    if DRY_RUN:
        print("DRY RUN: Order not submitted.")
        return

    # J. APPLY ORDER COOLDOWN
    if monotonic() - last_order_time < ORDER_COOLDOWN:
        print("Cooldown active. No order submitted.")
        return

    # K. PREVENT DUPLICATE RESTING ORDERS
    # Include both open and partially filled orders.
    for order in client.orders.iter_all(pair_id=PAIR_ID):
        if order["status"] in {"open", "partially_filled"}:
            print("Existing resting order. No new order.")
            return

    # L. EXECUTE A SMALL LIMIT IOC ORDER
    # IOC = Immediate Or Cancel.
    # The order can fill immediately up to its limit,
    # with any unfilled quantity cancelled.
    # Execution is not guaranteed.

    last_order_time = monotonic()

    order = client.orders.create(
        PAIR_ID,
        side=side,
        qty=order_qty,
        price=price,
        order_type="ioc"
    )

    # The acknowledgement is not a guarantee
    # that the full quantity was executed.
    print(f"Order ID: {order['order_id']}")
    print(f"Order status: {order['status']}")
    print(f"Remaining quantity: {order['remaining_qty']}")


# ==========================================
# STEP 4: MAIN PROGRAM
# ==========================================

def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

    try:
        # Load credentials from your existing .env file.
        with TradingClient.from_env(
            Path(__file__).with_name(".env")
        ) as client:

            info = client.recovery_snapshot["competition"]

            print(
                f"Competition {client.competition_id}: "
                f"{info['name']}"
            )

            print(f"Selected pair ID: {PAIR_ID}")

            mode = "DRY RUN" if DRY_RUN else "LIVE TRADING"
            print(f"Mode: {mode}")

            # Run every 10 seconds, with a maximum of
            # three callbacks for the first test.
            client.run(
                strategy,
                interval=10.0,
                max_iterations=3
            )

    except KeyboardInterrupt:
        print("Strategy stopped.")

    except SDKError as error:
        print(f"Strategy stopped: {error}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
