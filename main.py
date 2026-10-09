"""Edit strategy(). This starter observes the book and places no orders."""

import logging
from pathlib import Path

from trading_sdk import SDKError, TradingClient

# Choose a pair ID from the competition dictionary printed on startup.
PAIR_ID = None


def strategy(client: TradingClient):
    """Called once per second while the competition and streams are ready."""
    pair_id = PAIR_ID
    if pair_id is None:
        pairs = client.competition.retrieve()["pairs"] # type=dict, keyed by string pair ID
        pair_id = next(
            (int(key) for key, pair in pairs.items() if pair.get("trading_status") == "open"),
            None,
        )
    if pair_id is None:
        print("No open trading pair. Waiting.")
        return

    book = client.market.order_book(pair_id)
    best_bid = book["bids"][0]["price"] if book["bids"] else None
    best_ask = book["asks"][0]["price"] if book["asks"] else None
    print(f"Pair {pair_id}: bid={best_bid}, ask={best_ask}")

    # Add your strategy here. Amounts are human decimal strings or Decimal values.
    # Use the pair's min_price_increment and min_qty_increment from the dictionary.
    # order = client.orders.create(pair_id, side="buy", qty="1", price="150.42")
    # client.orders.cancel(order["order_id"])

# def strategy(client: TradingClient):
#     """Called once per second while the competition and streams are ready."""

#     all_competition_info = client.competition.retrieve()
#     pairs = client.competition.retrieve()["pairs"] # type=dict, keyed by string pair ID

#     # Go through all pairs
#     for pair_key, pair in pairs.items():
#         if pair.get("trading_status") == "open":
#             # Can trade pair
#             pair_id = int(pair_key)

#             book = client.market.order_book(pair_id)
#             best_bid = book["bids"][0]["price"] if book["bids"] else None
#             best_ask = book["asks"][0]["price"] if book["asks"] else None

#             # Decide to trade it?
            
    
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
