# Python trading SDK

Write your strategy in `main.py`. The SDK loads your competition API key, maintains HTTP connections, streams books, reconnects, and paces order requests. Your strategy uses ordinary Python methods. It does not need `async` or `await`.

This SDK provides the participant methods for a competition API key. Account login, competition listing, and administration happen through the platform frontend. The [Python method reference](docs/api-reference.md) explains the inputs, return values, and purpose of each SDK method. All participant instructions are included in this folder.

## Set up

Install Python 3.11 or newer first. Open a terminal in `trading-sdk` and run the command for your shell.

PowerShell on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Git Bash on Windows, or Bash on macOS:

```bash
bash setup.sh
```

The script installs uv locally if it is missing, creates a uv `.venv` with Python 3.12, installs this library and its dependencies through `requirements.txt`, and creates `.env`. It preserves an existing `.env` and reuses an existing virtual environment. Internet access is required on the first run. An installed Python with pip is required when bootstrapping uv.

To choose a Python version for a new environment, add `--python 3.11`. This option works with both scripts. The SDK supports Python 3.11 and newer.

Edit `.env`:

```dotenv
API_KEY=your_competition_api_key
COMPETITION_ID=1
BASE_URL=http://localhost:8080
ORDER_RATE_LIMIT=75
```

Get your API key from the competition's frontend. Use the competition's actual ID and server address. The server still requires the competition ID even though the API key is already scoped to that competition. The default ID is `1`.

`ORDER_RATE_LIMIT` controls the combined submission and cancellation rate in this client. The server currently allows 75 requests per second per user, shared across that user's clients. Lower this setting if several strategies share the same user or the server limit changes. Raising it does not raise the server's allowance.

Process environment variables override `.env`. Keep `.env` private; Git ignores it.

## Run your strategy

PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
```

Git Bash:

```bash
.venv/Scripts/python.exe main.py
```

macOS:

```bash
.venv/bin/python main.py
```

You do not need to activate the virtual environment. The supplied template prints the best bid and ask, chooses an open pair if `PAIR_ID` is unset, and places no orders. Edit `strategy(client)` and set the Python constant `PAIR_ID` near the top of `main.py` to the integer pair ID you want to trade. This is not an environment setting. The template prints available pair IDs at startup. With `PAIR_ID=None`, it selects the first currently open pair on each callback; previously watched pairs stay subscribed until released.

If you see `ModuleNotFoundError`, rerun setup in this folder and use the `.venv` Python command above. Installing dependencies into a different Python environment does not make them available to the one running your strategy. In an editor, select this folder's `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS as the interpreter.

To activate the environment in PowerShell, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python main.py
```

In Git Bash use `source .venv/Scripts/activate`; in macOS Bash use `source .venv/bin/activate`. After activation, `python` uses this environment. Run `deactivate` to leave it. `.venv`, local setup tools in `.tools`, and `.env` are Git-ignored. Keep virtual environments and credentials out of shared ZIPs.

```python
from trading_sdk import TradingClient

def strategy(client):
    book = client.market.order_book(2)
    if not book["asks"]:
        return
    # Add your trading logic here. This example only observes the book.
    print(book["asks"][0]["price"])

with TradingClient.from_env() as client:
    client.run(strategy, interval=1.0)
```

`run` calls your function on the calling thread. It pauses between callbacks when a stream disconnects or the competition pauses. New order submissions also wait for stream recovery. The SDK cannot interrupt Python code already running inside your callback, so keep callbacks short. Cancellation remains available during recovery.

## Prices and quantities

Use human amounts, such as price `"150.42"` and quantity `"10"`. The API sends signed integer strings at a scale of 10,000. The SDK converts `"150.42"` to wire value `"1504200"` and converts that wire value back to `Decimal("150.42")`.

```python
from decimal import Decimal

order = client.orders.create(
    2,
    side="buy",
    qty="10",
    price=Decimal("150.42"),
    order_type="limit",
)
client.orders.cancel(order["order_id"])
```

Amounts accept strings, `Decimal`, and integers. An integer `10` means ten units. Floats are rejected. The SDK rejects unsupported precision or int64 overflow instead of rounding. Pair-specific tick and lot sizes still apply; the server checks them. Read the pair's `min_price_increment` and `min_qty_increment`, which the SDK also converts to human `Decimal` amounts.

Do not scale inputs yourself. Passing `"1504200"` as a price means a human price of 1,504,200. See [amount conversion](docs/amounts.md) for the exact rules.

## Errors and recovery

HTTP failures raise exceptions with the server's status, code, message, details, and original payload. Network failures are visible too. The template prints an error and exits with a nonzero status when a call fails. Stream failures and asynchronous order rejections print automatically through the `trading_sdk` logger, with no error handler required.

On a stream disconnect the SDK reconnects, refreshes balances and complete order/fill history, and restores depth with the new stream ID. The strategy resumes when all managed streams are ready. Failed recovery stops the strategy with an exception. There is no automatic retry of order submissions or cancellations. A lost response may hide a successful mutation; inspect history before deciding what to do next.

See [errors and recovery](docs/errors-and-recovery.md) for configuration and limits.


## Reference

- [Documentation index](docs/README.md)
- [Python method reference](docs/api-reference.md)
- [Amounts](docs/amounts.md)
- [Streaming](docs/streaming.md)
- [Errors and recovery](docs/errors-and-recovery.md)
