import os
import uuid
import time
import threading
import base64
import requests
import datetime
from decimal import Decimal, ROUND_UP, ROUND_HALF_EVEN
from urllib.parse import urlparse
# pyrefly: ignore [missing-import]
from polymarket_us import PolymarketUS
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, ed25519
from cryptography.hazmat.backends import default_backend
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv


load_dotenv("API_key.env")

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_PRIVATE_KEY_PATH = os.getenv('KALSHI_PRIVATE_KEY_PATH')
KALSHI_API_KEY_ID = os.getenv("KALSHI_KEY_ID")


with open(KALSHI_PRIVATE_KEY_PATH, "rb") as _f:
    _kalshi_pk = serialization.load_pem_private_key(
        _f.read(), password=None, backend=default_backend()
    )


def _kalshi_request(method: str, path: str, data: dict | None = None):
    """Authenticated Kalshi API request (GET or POST)."""
    ts = str(int(datetime.datetime.now().timestamp() * 1000))
    sign_path = urlparse(KALSHI_BASE_URL + path).path
    msg = f"{ts}{method}{sign_path}".encode("utf-8")
    sig = _kalshi_pk.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    headers = {
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }
    url = KALSHI_BASE_URL + path
    if method == "GET":
        return requests.get(url, headers=headers)
    return requests.post(url, headers=headers, json=data)


def get_kalshi_balance() -> float:
    """Return available Kalshi balance in dollars."""
    resp = _kalshi_request("GET", "/portfolio/balance")
    # return resp.json()["balance"] / 100
    return 1000000


PM_KEY_ID = os.getenv("PM_KEY_ID")
PM_SECRET_KEY = os.getenv("PM_SECRET_KEY")

_pm_ed_key = ed25519.Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(PM_SECRET_KEY)[:32]
)


def _pm_auth_headers(method: str, path: str) -> dict:
    """Build Ed25519-signed auth headers for Polymarket US REST API."""
    ts = str(int(time.time() * 1000))
    message = f"{ts}{method}{path}"
    sig = base64.b64encode(_pm_ed_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": PM_KEY_ID,
        "X-PM-Timestamp": ts,
        "X-PM-Signature": sig,
        "Content-Type": "application/json",
    }


def get_pm_balance() -> float:
    """Return available Polymarket balance in dollars."""
    path = "/v1/account/balances"
    resp = requests.get(
        f"https://api.polymarket.us{path}",
        headers=_pm_auth_headers("GET", path),
    )
    # return float(resp.json()["balances"][0]["currentBalance"])
    return 1000000



def place_kalshi_buy_order(ticker, side, price_cents, count):
    """
    Place an IOC limit order on Kalshi.
    price_cents: int (1-99 range, cents, representing the price of the option being bought)
    count:       Decimal (number of contracts)
    """
    # Map "yes"/"no" side to Kalshi V2 book side ("bid"/"ask") and adjust price if needed
    if side == "yes":
        api_side = "bid"
        api_price_cents = price_cents
    elif side == "no":
        api_side = "ask"
        api_price_cents = 100 - price_cents
    else:
        api_side = side
        api_price_cents = price_cents

    price_dollars_str = f"{api_price_cents / 100:.4f}"

    data = {
        "ticker": ticker,
        "side": api_side,
        "count": str(count),
        "price": price_dollars_str,
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": str(uuid.uuid4()),
    }
    return _kalshi_request("POST", "/portfolio/events/orders", data)

_pm_client = PolymarketUS(key_id=PM_KEY_ID, secret_key=PM_SECRET_KEY)

def place_pm_buy_order(slug, intent, price_cent, count):
    """Place an IOC limit order on Polymarket US."""
    price_dollar_str = price_cent/100

    if intent == 'yes':
        intent = "ORDER_INTENT_BUY_LONG"
    
    if intent == "no":
        intent = "ORDER_INTENT_BUY_SHORT"
        price_dollar_str = (100 - price_cent)/100

    return _pm_client.orders.create({
        "marketSlug": slug,
        "intent": intent,
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": str(price_dollar_str), "currency": "USD"},
        "quantity": str(count),
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
    })


# place_kalshi_order("ticker", 'yes', 10, 1) ask for yes is 10 cent
# buy 1 yes for 10 cent
# place_kalshi_order("ticker", 'no', 10, 1) ask for no is 10 cent

# place_pm_order("tc-temp-nychigh-2026-08-03-gte86lt87f", 'buy_yes', 3, 1)
# buy 1 yes for 3 cent

# place_pm_order("tc-temp-nychigh-2026-08-03-lt80f", 'buy_no', 79, 1)
# Buy 1 NO for 79 cent

# "ORDER_INTENT_BUY_LONG" BUY YES
# "ORDER_INTENT_BUY_SHORT" BUY NO
# "ORDER_INTENT_SELL_LONG"
# "ORDER_INTENT_SELL_SHORT"

