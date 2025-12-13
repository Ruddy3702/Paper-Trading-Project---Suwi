from fyers_apiv3 import fyersModel
import pandas as pd
import requests, os, hashlib, time, json
from utils.models import UserData, db
from utils.crypto_utils import decrypt, encrypt
from flask_login import current_user
# =========================
#        CONFIG
# =========================

PIN = os.getenv("PIN","1234")

# Fyers credentials
def get_fyers_credentials():
    if not current_user.is_authenticated:
        raise RuntimeError("User not logged in")

    return {
        "client_id": decrypt(current_user.fyers_client_id),
        "secret_key": decrypt(current_user.fyers_secret_key),
        "auth_code": decrypt(current_user.fyers_auth_code) if current_user.fyers_auth_code else None,
        "fyers_redirect_url": decrypt(current_user.fyers_redirect_url),
    }



FYERS_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
FYERS_VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../Data")
os.makedirs(DATA_DIR, exist_ok=True)

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "access_token.txt")  # not used but kept
TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "token_cache.json")

def load_user_data(current_user):
    user_data = UserData.query.filter_by(user=current_user.user).first()
    print(type(user_data))

# =========================
#   AUTH CODE → TOKENS
# =========================

def exchange_auth_code_for_tokens(auth_code: str) -> str:
    """
    Use a one-time auth_code to obtain a fresh access_token + refresh_token.
    - Writes refresh_token to refresh_token.txt
    - Caches access_token + timestamp in token_cache.json
    Returns: access_token (str)
    """
    creds = get_fyers_credentials()
    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]
    if not FYERS_CLIENT_ID or not FYERS_SECRET_KEY:
        raise Exception("CLIENT_ID/SECRET_KEY not set in environment.")

    # Per Fyers docs: SHA256(client_id + secret_key)
    hash_input = f"{FYERS_CLIENT_ID}:{FYERS_SECRET_KEY}"
    appIdHash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    payload = {
        "grant_type": "authorization_code",
        "appIdHash": appIdHash,
        "code": auth_code,
    }

    headers = {"Content-Type": "application/json"}
    resp = requests.post(FYERS_VALIDATE_AUTH_URL, headers=headers, json=payload)
    data = resp.json()

    if resp.status_code != 200 or "access_token" not in data:
        raise Exception(f"Auth-code exchange failed: {data}")

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token")

    current_user.fyers_refresh_token = encrypt(refresh_token)
    current_user.fyers_auth_code = None
    db.session.commit()

    # Cache access token with timestamp
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"access_token": access_token, "timestamp": time.time()}, f)

    print("Fyers access/refresh tokens updated from auth_code.")
    return access_token


# =========================
#   ACCESS TOKEN HANDLER
# =========================

def get_fyers_authcode(*, client_id, secret_key, redirect_uri):
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri=redirect_uri,
        response_type="code"
    )
    return session.generate_authcode()


def get_fyers_access_token() -> str:
    """Fetch or reuse Fyers access token, refreshing only every 12 hours."""

    creds = get_fyers_credentials()
    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]

    # 1) Use cached access token if still valid (12 hours)
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r") as f:
                cache = json.load(f)
        except json.JSONDecodeError:
            cache = {}

        access_token = cache.get("access_token")
        timestamp = cache.get("timestamp", 0)

        if access_token and (time.time() - timestamp) < 43200:
            print("Using cached Fyers access token.")
            return access_token

    # 2) Refresh token must exist in DB
    if not current_user.fyers_refresh_token:
        raise RuntimeError(
            "Fyers session expired. Please reconnect your Fyers account."
        )

    refresh_token = decrypt(current_user.fyers_refresh_token)

    if not FYERS_CLIENT_ID or not FYERS_SECRET_KEY:
        raise RuntimeError("Fyers credentials missing.")

    # Per Fyers docs
    hash_input = f"{FYERS_CLIENT_ID}:{FYERS_SECRET_KEY}"
    appIdHash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    payload = {
        "grant_type": "refresh_token",
        "appIdHash": appIdHash,
        "refresh_token": refresh_token,
        "pin": PIN,
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(FYERS_REFRESH_URL, headers=headers, json=payload)
    data = response.json()

    # Refresh token expired / invalid
    if data.get("code") == -501:
        raise RuntimeError(
            "Fyers session expired. Please reconnect your Fyers account."
        )

    if response.status_code != 200 or "access_token" not in data:
        raise RuntimeError(f"Fyers token refresh failed: {data}")

    access_token = data["access_token"]

    # Cache access token
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump(
            {"access_token": access_token, "timestamp": time.time()},
            f
        )

    print("Fyers access token refreshed successfully.")
    return access_token


# =========================
#   APP LOGIC BELOW
# =========================

def write_equity_data(n):
    """Writes n rows of (symbol, name) and (symbol) to files in /Data"""
    input_path = os.path.join(DATA_DIR, "NSE_CM.csv")
    eq_names_path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
    eq_only_path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")

    data = pd.read_csv(input_path, header=0)
    df = pd.DataFrame(data)

    equities = df[df['symbol'].str.endswith('-EQ')]
    eq = equities[['symbol']].head(n)
    name_eq = equities[['symbol', 'name']].head(n)

    name_eq.to_csv(eq_names_path, index=False)
    eq.to_csv(eq_only_path, index=False)

    print(f"Wrote {n} rows to:")
    print(f"   • {eq_names_path}")
    print(f"   • {eq_only_path}")


def enrich_stock_data(stock: dict) -> dict:
    eq_names_path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
    file = pd.read_csv(eq_names_path, header=0)
    name_dict = file.set_index("symbol")["name"].to_dict()

    v = stock.get("v", {})
    ticker_symbol = v.get("symbol")
    if not ticker_symbol:
        # If this ever happens, just return stock unchanged
        return stock

    lp = v.get("lp", 0)
    prev_close = v.get("prev_close_price", 0)
    spread = v.get("spread", 0)
    open_price = v.get("open_price", 0)
    high_price = v.get("high_price", 0)
    low_price = v.get("low_price", 0)
    volume = v.get("volume", 0)

    v["name"] = name_dict.get(ticker_symbol, ticker_symbol)

    price_change = round(lp - prev_close, 2) if lp and prev_close else 0
    percent_change = round((lp - prev_close) / prev_close * 100, 2) if prev_close else 0

    v["price_change"] = price_change
    v["percent_change"] = percent_change

    # aliases to match your template and sort_by options
    v["ch"] = price_change
    v["chp"] = percent_change

    v["day_range_percent"] = round((high_price - low_price) / low_price * 100, 2) if low_price else None
    v["from_open_percent"] = round((lp - open_price) / open_price * 100, 2) if open_price else None
    v["spread_percent"] = round((spread / lp) * 100, 2) if lp else None
    v["trend"] = "Bullish" if lp > open_price else "Bearish"
    v["liquidity_score"] = round(volume / spread, 2) if spread else None

    stock["v"] = v
    return stock


def get_database(symbols=None):
    creds = get_fyers_credentials()
    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]
    access_token = get_fyers_access_token()

    fyers = fyersModel.FyersModel(
        client_id=FYERS_CLIENT_ID,
        token=access_token,
        is_async=False,
        log_path=os.path.join(DATA_DIR, "fyers_logs")
    )

    if symbols:
        eq_list = symbols
    else:
        eq_only_path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")
        file = pd.read_csv(eq_only_path, header=0)
        eq_list = file["symbol"].tolist()

    eq_str = ",".join(eq_list)
    data = {"symbols": eq_str}
    response = fyers.quotes(data=data)

    raw_quotes = response.get("d", response)

    cleaned_quotes = []
    for stock in raw_quotes:
        if not isinstance(stock, dict) or "v" not in stock:
            continue

        v = stock.get("v", {})

        # drop error / invalid rows (like ORICONENT with code -300)
        if (
            not isinstance(v, dict)
            or "symbol" not in v
            or v.get("code") not in (None, 0)
        ):
            continue

        cleaned_quotes.append(enrich_stock_data(stock))

    print("Data fetched successfully.")
    return cleaned_quotes


def get_data(symbol):
    """Fetch single stock data with 5-min cache fallback."""
    cache_file = os.path.join(DATA_DIR, "stock_cache.json")
    creds = get_fyers_credentials()
    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]

    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}

    if symbol in cache:
        cached_entry = cache[symbol]
        if time.time() - cached_entry["timestamp"] < 300:
            print(f"Using cached data for {symbol}")
            return cached_entry["data"]

    access_token = get_fyers_access_token()
    fyers = fyersModel.FyersModel(
        client_id=FYERS_CLIENT_ID,
        token=access_token,
        is_async=False,
        log_path=os.path.join(DATA_DIR, "fyers_logs")
    )
    data = {"symbols": f"{symbol}"}
    response = fyers.quotes(data=data)
    quotes_data = response.get('d', response)
    stock = quotes_data[0]
    enriched_stock = enrich_stock_data(stock)

    cache[symbol] = {"data": enriched_stock, "timestamp": time.time()}
    with open(cache_file, "w") as f:
        json.dump(cache, f)

    print(f"Data fetched successfully for {symbol}.")
    return enriched_stock


def search(name):
    query = name
    yourAPIKey = decrypt(current_user.google_api_key)
    cx = decrypt(current_user.cx)
    response = requests.get(
        url=f"https://www.googleapis.com/customsearch/v1",
        params={
            "key": yourAPIKey,
            "cx": cx,
            "q": query
        }
    )
    response.raise_for_status()
    data = response.json()
    return data


# def get_stock_news(company_name):
#     news_api_key = decrypt(current_user.news_api_key)
#
#     news_params = {
#         "q": company_name,
#         "searchIn": "title,description",
#         "language": "en",
#         "sortBy": "popularity",
#         "apiKey": news_api_key
#     }
#     response_news = requests.get(url="https://newsapi.org/v2/everything", params=news_params)
#     response_news.raise_for_status()
#     article = response_news.json()["articles"]
#     ten_articles = article[:10]
#     return ten_articles