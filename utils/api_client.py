from fyers_apiv3 import fyersModel
import pandas as pd
import requests, os, hashlib, time, json

# =========================
#        CONFIG
# =========================

# Fyers credentials
FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID")          # e.g. "ABCD1234-100"
FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY")        # app secret from Fyers app
PIN = os.getenv("PIN")                      # Fyers PIN (string)

# Optional: only needed when refresh token is invalid/expired
FYERS_AUTH_CODE = os.getenv("FYERS_AUTH_CODE")  # short-lived auth_code from redirect URL

FYERS_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
FYERS_VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../Data")
os.makedirs(DATA_DIR, exist_ok=True)

REFRESH_TOKEN_FILE = os.path.join(BASE_DIR, "refresh_token.txt")
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "access_token.txt")  # not used but kept
TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "token_cache.json")


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

    # Save refresh token for future refresh calls
    if refresh_token:
        with open(REFRESH_TOKEN_FILE, "w") as f:
            f.write(refresh_token)

    # Cache access token with timestamp
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"access_token": access_token, "timestamp": time.time()}, f)

    print("Fyers access/refresh tokens updated from auth_code.")
    return access_token


# =========================
#   ACCESS TOKEN HANDLER
# =========================

def get_fyers_access_token() -> str:
    """Fetch or reuse Fyers access token, refreshing only every 12 hours."""

    # 1) Use cached token if still valid (12 hours)
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r") as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}

        access_token = cache.get("access_token")
        timestamp = cache.get("timestamp", 0)

        if access_token and (time.time() - timestamp) < 43200:  # 12 * 60 * 60
            print("Using cached Fyers access token.")
            return access_token

    # 2) Try refresh_token flow
    if not os.path.exists(REFRESH_TOKEN_FILE):
        # No refresh token at all, fall back to auth_code if available
        if FYERS_AUTH_CODE:
            print("No refresh_token.txt found. Using FYERS_AUTH_CODE to get new tokens.")
            return exchange_auth_code_for_tokens(FYERS_AUTH_CODE)
        raise FileNotFoundError(
            f"Refresh token file not found: {REFRESH_TOKEN_FILE}. "
            "Generate a new auth_code and set FYERS_AUTH_CODE."
        )

    with open(REFRESH_TOKEN_FILE, "r") as f:
        refresh_token = f.read().strip()

    if not FYERS_CLIENT_ID or not FYERS_SECRET_KEY:
        raise Exception("FYERS_CLIENT_ID/FYERS_SECRET_KEY not set in environment.")

    hash_input = f"{FYERS_CLIENT_ID}{FYERS_SECRET_KEY}"
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

    # 2a) Refresh token invalid/expired → use auth_code if present
    if data.get("code") == -501:
        if FYERS_AUTH_CODE:
            print("Refresh token invalid/expired (-501). Using FYERS_AUTH_CODE to get new tokens.")
            return exchange_auth_code_for_tokens(FYERS_AUTH_CODE)
        raise Exception(
            " Token refresh failed: invalid/expired refresh token (-501).\n"
            "Generate a new auth_code from Fyers login, set FYERS_AUTH_CODE, "
            "and run again to auto-generate a new refresh_token.txt."
        )

    if response.status_code != 200 or "access_token" not in data:
        raise Exception(f" Token refresh failed: {data}")

    access_token = data["access_token"]

    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"access_token": access_token, "timestamp": time.time()}, f)

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
    yourAPIKey = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("CX")
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


def get_stock_news():
    company_name = "INFY.BSE"
    news_api_key = os.getenv("NEWS_API_KEY")

    news_params = {
        "q": company_name,
        "searchIn": "title,description",
        "language": "en",
        "sortBy": "popularity",
        "apiKey": news_api_key
    }
    response_news = requests.get(url="https://newsapi.org/v2/everything", params=news_params)
    response_news.raise_for_status()
    article = response_news.json()["articles"]
    ten_articles = article[:10]
    return ten_articles


