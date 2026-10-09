"""Edit strategy(). This starter observes the book and places no orders."""

import logging
from pathlib import Path

from trading_sdk import SDKError, TradingClient

# Choose a pair ID from the competition dictionary printed on startup.
PAIR_ID = None


# def strategy(client: TradingClient):
#     """Called once per second while the competition and streams are ready."""
#     pair_id = PAIR_ID
#     if pair_id is None:
#         pairs = client.competition.retrieve()["pairs"] # type=dict, keyed by string pair ID
#         pair_id = next(
#             (int(key) for key, pair in pairs.items() if pair.get("trading_status") == "open"),
#             None,
#         )
#     if pair_id is None:
#         print("No open trading pair. Waiting.")
#         return

#     book = client.market.order_book(pair_id)
#     best_bid = book["bids"][0]["price"] if book["bids"] else None
#     best_ask = book["asks"][0]["price"] if book["asks"] else None
#     print(f"Pair {pair_id}: bid={best_bid}, ask={best_ask}")

    # Add your strategy here. Amounts are human decimal strings or Decimal values.
    # Use the pair's min_price_increment and min_qty_increment from the dictionary.
    # order = client.orders.create(pair_id, side="buy", qty="1", price="150.42")
    # client.orders.cancel(order["order_id"])

def strategy(client: TradingClient):
    """
    Analyze all open trading pairs in the competition.

    The function:
    1. Retrieves available securities and trading pairs.
    2. Checks which markets are open.
    3. Reads the best bid and ask prices.
    4. Calculates spreads and mid-prices.
    5. Ranks markets by percentage spread.
    6. Displays the top 10 markets.

    This strategy DOES NOT place any orders.
    """

    # STEP 1: RETRIEVE COMPETITION INFORMATION
    # The API returns a dictionary containing information
    # about the competition, assets, and trading pairs.
    info = client.competition.retrieve()

    # Get the dictionary of trading pairs.
    # Each key is a pair ID stored as a string.
    pairs = info["pairs"]

    # Get the dictionary of assets.
    # This lets us convert asset IDs into symbols.
    assets = info["assets"]

    # STEP 2: CREATE AN EMPTY LIST
    # We will store each market's statistics here.
    # Each element will be a dictionary.
    opportunities = []

    # STEP 3: LOOP THROUGH ALL TRADING PAIRS
    # .items() returns both the key and its value.
    #
    # pair_key -> The trading pair ID (string)
    # pair     -> Dictionary describing that pair
    for pair_key, pair in pairs.items():

        # STEP 4: CHECK IF THE PAIR IS OPEN
        # If the pair is not open, skip to the next pair.
        #
        # continue skips the rest of the current iteration.
        if pair.get("trading_status") != "open":
            continue

        # Convert pair ID from string to integer.
        # The SDK requires an integer pair ID.
        pair_id = int(pair_key)

        # STEP 5: IDENTIFY THE ASSETS
        # Each pair connects two assets:
        #
        # Base asset  -> Asset being bought or sold
        # Quote asset -> Asset used to express its price
        #
        # Example: ANTH/USD
        # ANTH is the base asset and USD is the quote.
        base = assets[str(pair["base_asset_id"])]["symbol"]
        quote = assets[str(pair["quote_asset_id"])]["symbol"]

        # STEP 6: GET THE LIVE ORDER BOOK
        # The order book contains:
        #
        # bids -> Offers from buyers
        # asks -> Offers from sellers
        #
        # The SDK maintains the market data stream.
        book = client.market.order_book(pair_id)

        # STEP 7: CHECK FOR MISSING MARKET DATA
        # An empty bid list means no visible buy orders.
        # An empty ask list means no visible sell orders.
        #
        # We need both sides to calculate the spread.
        if not book["bids"] or not book["asks"]:
            continue

        # STEP 8: GET THE BEST BID AND ASK
        #
        # [0] selects the first price level.
        # ["price"] retrieves that level's price.
        #
        # Best bid -> Highest available buying price
        # Best ask -> Lowest available selling price
        best_bid = book["bids"][0]["price"]
        best_ask = book["asks"][0]["price"]

        # STEP 9: VALIDATE THE PRICES
        #
        # We skip:
        # - Zero or negative bids
        # - Markets where the ask is not above the bid
        #
        # This keeps our spread calculations meaningful.
        if best_bid <= 0 or best_ask <= best_bid:
            continue

        # STEP 10: CALCULATE THE BID-ASK SPREAD
        #
        # Spread = Ask - Bid
        #
        # Example:
        # Bid = 31.85
        # Ask = 32.08
        # Spread = 0.23
        spread = best_ask - best_bid

        # STEP 11: CALCULATE MID-PRICE
        #
        # Mid-price = (Bid + Ask) / 2
        #
        # Example:
        # (31.85 + 32.08) / 2 = 31.965
        #
        # The mid-price is a reference price,
        # not necessarily an executable price.
        mid_price = (best_bid + best_ask) / 2

        # STEP 12: CALCULATE PERCENTAGE SPREAD
        #
        # Spread % = (Spread / Mid-price) * 100
        #
        # This allows comparisons between securities
        # with different price levels.
        #
        # Example:
        # (0.23 / 31.965) * 100 = 0.720%
        spread_pct = (spread / mid_price) * 100

        # STEP 13: SAVE MARKET STATISTICS
        #
        # append() adds a new dictionary to our list.
        #
        # Each dictionary contains the trading pair
        # and its calculated statistics.
        opportunities.append({
            "pair_id": pair_id,
            "pair": f"{base}/{quote}",
            "bid": best_bid,
            "ask": best_ask,
            "spread": spread,
            "mid_price": mid_price,
            "spread_pct": spread_pct
        })

    # STEP 14: SORT MARKETS BY PERCENTAGE SPREAD
    #
    # sort() modifies the original list.
    #
    # key=lambda x: x["spread_pct"]
    # tells Python to sort using the spread percentage.
    #
    # reverse=True sorts from largest to smallest.
    opportunities.sort(
        key=lambda x: x["spread_pct"],
        reverse=True
    )

    # STEP 15: DISPLAY THE RESULTS
    print("\n--- TOP 10 MARKETS BY SPREAD ---")

    # [:10] selects the first 10 elements.
    # Because we already sorted the list,
    # these are the 10 markets with the largest spreads.
    for item in opportunities[:10]:

        # Each item is a dictionary.
        # We access its values using their keys.
        print(
            f"Pair {item['pair_id']} "
            f"({item['pair']}): "
            f"Bid={item['bid']}, "
            f"Ask={item['ask']}, "
            f"Spread={item['spread']:.4f}, "
            f"Mid={item['mid_price']:.4f}, "
            f"Spread%={item['spread_pct']:.2f}%"
        )

    # STEP 16: FUTURE TRADING LOGIC
    #
    # Later we can:
    # - Calculate fair values
    # - Track historical prices
    # - Measure order-book liquidity
    # - Detect potential trading signals
    # - Implement position and risk limits
    # - Submit and cancel orders
    #
    # For now, this function only analyzes market data.

    
        # 8. Trading logic will go here later
        # No orders are submitted yet.
            
    
#     pair_id = PAIR_ID
#     if pair_id is None:
#         pairs = client.competition.retrieve()["pairs"] # type=dict, keyed by string pair ID
#         pair_id = next(
#             (int(key) for key, pair in pairs.items() if pair.get("trading_status") == "open"),
#             None,
#         )
#     if pair_id is None:
#         print("No open trading pair. Waiting.")
#         return

#     book = client.market.order_book(pair_id)
#     best_bid = book["bids"][0]["price"] if book["bids"] else None
#     best_ask = book["asks"][0]["price"] if book["asks"] else None
#     print(f"Pair {pair_id}: bid={best_bid}, ask={best_ask}")

#     # Add your strategy here. Amounts are human decimal strings or Decimal values.
#     # Use the pair's min_price_increment and min_qty_increment from the dictionary.
#     # order = client.orders.create(pair_id, side="buy", qty="1", price="150.42")
#     # client.orders.cancel(order["order_id"])


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        with TradingClient.from_env(Path(__file__).with_name(".env")) as client:
            dictionary = client.recovery_snapshot["competition"]
            print(f"Competition {client.competition_id}: {dictionary['name']}")
            print(f"Available pair IDs: {', '.join(dictionary['pairs'])}")
            client.run(strategy, interval=1.0)
    except KeyboardInterrupt:
        print("Strategy stopped.")
    except SDKError as error:
        print(f"Strategy stopped: {error}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
