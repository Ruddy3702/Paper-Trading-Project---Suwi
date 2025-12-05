from fyers_apiv3 import fyersModel
import pandas as pd
import requests, os, hashlib, time, json

CLIENT_ID = os.getenv("CLIENT_ID")
SECRET_KEY = os.getenv("SECRET_KEY")
PIN = os.getenv("PIN")
FYERS_REFRESH_URL   = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../Data")
os.makedirs(DATA_DIR, exist_ok=True)
REFRESH_TOKEN_FILE = os.path.join(BASE_DIR, "refresh_token.txt")
ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "access_token.txt")
TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "token_cache.json")

def get_fyers_access_token():
    """Fetch or reuse Fyers access token, refreshing only every 12 hours."""

    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r") as f:
            cache = json.load(f)
            access_token = cache.get("access_token")
            timestamp = cache.get("timestamp", 0)


        if access_token and (time.time() - timestamp) < 43200:
            print("Using cached Fyers access token.")
            return access_token


    if not os.path.exists(REFRESH_TOKEN_FILE):
        raise FileNotFoundError(
            f"Refresh token file not found: {REFRESH_TOKEN_FILE}"
        )

    with open(REFRESH_TOKEN_FILE, "r") as f:
        refresh_token = f.read().strip()

    hash_input = f"{CLIENT_ID}:{SECRET_KEY}"
    appIdHash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    payload = {
        "grant_type": "refresh_token",
        "appIdHash": appIdHash,
        "refresh_token": refresh_token,
        "pin": PIN
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(FYERS_REFRESH_URL, headers=headers, json=payload)
    data = response.json()

    if response.status_code != 200 or "access_token" not in data:
        raise Exception(f"❌ Token refresh failed: {data}")

    access_token = data["access_token"]


    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"access_token": access_token, "timestamp": time.time()}, f)

    print("Fyers access token refreshed successfully.")
    return access_token


def write_equity_data(n):
    """Writes n rows of (symbol, name) and (symbol) to files in /Data"""
    input_path = os.path.join(DATA_DIR, "NSE_CM.csv")
    eq_names_path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
    eq_only_path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")

    # Read base data
    data = pd.read_csv(input_path, header=0)
    df = pd.DataFrame(data)

    # Filter for -EQ
    equities = df[df['symbol'].str.endswith('-EQ')]
    eq = equities[['symbol']].head(n)
    name_eq = equities[['symbol', 'name']].head(n)

    # Save outputs
    name_eq.to_csv(eq_names_path, index=False)
    eq.to_csv(eq_only_path, index=False)

    print(f"Wrote {n} rows to:")
    print(f"   • {eq_names_path}")
    print(f"   • {eq_only_path}")


def enrich_stock_data(stock):
    """Compute fields for a single stock from Fyers API response."""

    eq_names_path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
    file = pd.read_csv(eq_names_path, header=0)
    name_dict = file.set_index("symbol")["name"].to_dict()

    ticker_symbol = stock['v']['symbol']
    v = stock.get("v", {})
    lp = v.get("lp", 0)
    prev_close = v.get("prev_close_price", 0)
    spread = v.get("spread", 0)
    open_price = v.get("open_price", 0)
    high_price = v.get("high_price", 0)
    low_price = v.get("low_price", 0)
    volume = v.get("volume", 0)

    v['name'] = name_dict[ticker_symbol]
    v["price_change"] = round(lp - prev_close, 2) if lp and prev_close else None
    v["percent_change"] = round((lp - prev_close) / prev_close * 100, 2) if prev_close else None
    v["day_range_percent"] = round((high_price - low_price) / low_price * 100, 2) if low_price else None
    v["from_open_percent"] = round((lp - open_price) / open_price * 100, 2) if open_price else None
    v["spread_percent"] = round((spread / lp) * 100, 2) if lp else None
    v["trend"] = "Bullish" if lp > open_price else "Bearish"
    v["liquidity_score"] = round(volume / spread, 2) if spread else None

    stock["v"] = v
    return stock


def get_database(symbols=None):
    """Get data on multiple stocks (optional: only specific symbols)"""
    #Try using existing token first
    access_token = get_fyers_access_token()

    fyers = fyersModel.FyersModel(
        client_id=CLIENT_ID,
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

    quotes_data = response.get("d", response)

    for i, stock in enumerate(quotes_data):
        if not isinstance(stock, dict) or "v" not in stock:
            continue  # Skip bad or string entries like 'ok'
        quotes_data[i] = enrich_stock_data(stock)

    print("Data fetched successfully.")
    return quotes_data


def get_data(symbol):
    """Fetch single stock data with 5-min cache fallback."""
    cache_file = os.path.join(DATA_DIR, "stock_cache.json")

    # --- Load cache ---
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}

    # --- Check for valid cache (5 min TTL) ---
    if symbol in cache:
        cached_entry = cache[symbol]
        if time.time() - cached_entry["timestamp"] < 300:  # 5 minutes
            print(f"Using cached data for {symbol}")
            return cached_entry["data"]

    # --- Fetch new data ---
    access_token = get_fyers_access_token()
    fyers = fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=access_token,
        is_async=False,
        log_path=os.path.join(DATA_DIR, "fyers_logs")
    )
    data = {"symbols": f"{symbol}"}
    response = fyers.quotes(data=data)
    quotes_data = response.get('d', response)
    stock = quotes_data[0]
    enriched_stock = enrich_stock_data(stock)

    # --- Save to cache ---
    cache[symbol] = {"data": enriched_stock, "timestamp": time.time()}
    with open(cache_file, "w") as f:
        json.dump(cache, f)

    print(f"Data fetched successfully for {symbol}.")
    return enriched_stock


def search(name):
    query = name
    # GOOGLE API
    yourAPIKey = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("CX")
    response = requests.get(url =f"https://www.googleapis.com/customsearch/v1?key={yourAPIKey}&cx={cx}&q={query}")
    response.raise_for_status()
    data = response.json()
    return data


def historic_OHCL():

    stock_api_key = os.getenv("STOCK_API_KEY")
    symbol= "INFY.BSE"

    stock_params = {
        "symbol": symbol,
        "function": "TIME_SERIES_DAILY",
        "outputsize": "compact",
        "datatype": "json",
        "apikey": stock_api_key
    }
    response_stock = requests.get(url="https://www.alphavantage.co/query", params=stock_params)
    response_stock.raise_for_status()
    data = response_stock.json()
    print(data)
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
    print(ten_articles)
    return ten_articles
def get_news():
    import http.client

    conn = http.client.HTTPSConnection("real-time-news-data.p.rapidapi.com")

    headers = {
        'x-rapidapi-key': os.getenv("RAPIDAPI_KEY"),
        'x-rapidapi-host': "real-time-news-data.p.rapidapi.com"
    }

    conn.request("GET", "/search?query=Football&limit=10&time_published=anytime&country=US&lang=en", headers=headers)

    res = conn.getresponse()
    data = res.read()

    print(data.decode("utf-8"))

