import datetime
import os, json, time, requests
from datetime import timedelta, datetime

import pandas as pd
from utils.api_client import get_fyers_credentials, get_fyers_access_token
from fyers_apiv3 import fyersModel
from utils.crypto_utils import decrypt, encrypt
from flask_login import current_user
from utils.models import db, Transaction
from flask import g
from decimal import Decimal

CACHE_TTL = 30  # seconds (adjust: 5–30s for market data)
NAME_MAP = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../Data")
os.makedirs(DATA_DIR, exist_ok=True)


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
    name_map = get_name_map()
    v = stock.get("v", {})

    symbol = v.get("symbol")
    if not symbol:
        return stock

    lp = v.get("lp") or 0
    prev_close = v.get("prev_close_price") or 0
    open_price = v.get("open_price") or 0
    high_price = v.get("high_price") or 0
    low_price = v.get("low_price") or 0
    spread = v.get("spread") or 0
    volume = v.get("volume") or 0

    v["name"] = name_map.get(symbol, symbol)

    price_change = lp - prev_close if prev_close else 0
    percent_change = (price_change / prev_close * 100) if prev_close else 0

    v.update({
        "price_change": round(price_change, 2),
        "percent_change": round(percent_change, 2),
        "ch": round(price_change, 2),
        "chp": round(percent_change, 2),
        "day_range_percent": round((high_price - low_price) / low_price * 100, 2) if low_price else None,
        "from_open_percent": round((lp - open_price) / open_price * 100, 2) if open_price else None,
        "spread_percent": round((spread / lp) * 100, 2) if lp else None,
        "trend": "Bullish" if lp > open_price else "Bearish",
        "liquidity_score": round(volume / spread, 2) if spread else None,
    })

    stock["v"] = v
    return stock


def get_database(symbols=None):
    creds = get_fyers_credentials()
    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]
    access_token = get_fyers_access_token()

    cache_file = os.path.join(DATA_DIR, "stock_cache.json")
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
        except json.JSONDecodeError:
            cache = {}

    now = time.time()

    if cache:
        if symbols:
            required_symbols = set(symbols)
        else:
            eq_only_path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")
            file = pd.read_csv(eq_only_path, header=0)
            required_symbols = set(file["symbol"].tolist())

        cached_symbols = set(cache.keys())

        # All required symbols exist in cache
        if required_symbols.issubset(cached_symbols):
            # All cached data still fresh
            if all(now - cache[s]["timestamp"] < CACHE_TTL for s in required_symbols):
                print("Using cached market data (API skipped).")
                return [
                    enrich_stock_data(cache[s]["data"])
                    for s in required_symbols
                ]

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

        symbol = v.get("symbol")
        if symbol:
            cache[symbol] = {
                "data": stock,
                "timestamp": time.time()
            }

        cleaned_quotes.append(enrich_stock_data(stock))
    with open(cache_file, "w") as f:
        json.dump(cache, f)
    print("Data fetched successfully.")
    return cleaned_quotes


def get_historic_data(symbol, range_key):
    print("RANGE KEY RECEIVED:", range_key)
    creds = get_fyers_credentials()
    fyers = fyersModel.FyersModel(
        client_id=creds["client_id"],
        is_async=False,
        token=get_fyers_access_token(),
        log_path=""
    )

    now = datetime.now()

    days_map = {
        "5D": 5,
        "1M": 30,
        "3M": 90,
        "6M": 180,
        "1Y": 365,
        "3Y": 1095,
        "5Y": 1825
    }

    total_days = days_map.get(range_key, 30)

    all_candles = []
    end = now

    while total_days > 0:
        chunk_days = min(365, total_days)
        start = end - timedelta(days=chunk_days)

        payload = {
            "symbol": symbol,
            "resolution": "1D",
            "date_format": "1",
            "range_from": start.strftime("%Y-%m-%d"),
            "range_to": end.strftime("%Y-%m-%d")
        }

        resp = fyers.history(payload)

        if resp.get("s") != "ok":
            print("FYERS HISTORY FAILED:", resp)
            break

        candles = resp.get("candles", [])
        all_candles.extend(candles)

        # 🔥 critical fix
        end = start - timedelta(days=1)
        total_days -= chunk_days

    # Deduplicate + sort
    unique = {c[0]: c for c in all_candles}
    merged = list(unique.values())
    merged.sort(key=lambda x: x[0])
    print(len(merged))
    return {"s": "ok", "candles": merged}


def get_name_map():
    global NAME_MAP
    if NAME_MAP is None:
        path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
        df = pd.read_csv(path)
        NAME_MAP = df.set_index("symbol")["name"].to_dict()
    return NAME_MAP


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


def get_avg_price(stock):
    results = Transaction.query.filter(Transaction.user_id == current_user.user, Transaction.symbol == stock).all()
    print(results)
    portfolio = {}
    for tx in results:
        symbol = tx.symbol
        avg_cost = portfolio[symbol]["total_cost"] / portfolio[symbol]["quantity"]
        portfolio[symbol]["quantity"] -= tx.quantity
        portfolio[symbol]["total_cost"] -= tx.quantity * avg_cost


def calculate_portfolio():
    results = db.session.execute(db.select(Transaction).where(Transaction.user_id == current_user.user).order_by(Transaction.timestamp)).scalars()
    portfolio = {}
    for tx in results:
        symbol = tx.symbol

        if symbol not in portfolio:
            portfolio[symbol] = {
                "symbol": symbol,
                "name": tx.name,
                "quantity": Decimal("0"),
                "total_cost": Decimal("0"),
            }

        if tx.type == "BUY":
            portfolio[symbol]["quantity"] += tx.quantity
            portfolio[symbol]["total_cost"] += tx.quantity * tx.execution_price


        elif tx.type == "SELL":
            avg_cost = portfolio[symbol]["total_cost"] / portfolio[symbol]["quantity"]
            portfolio[symbol]["quantity"] -= tx.quantity
            portfolio[symbol]["total_cost"] -= tx.quantity * avg_cost

    final_portfolio = []

    for symbol, data in portfolio.items():
        if data["quantity"] <= 0:
            continue  # skip fully sold positions

        ltp = get_price(symbol)
        avg_price = data["total_cost"] / data["quantity"]
        market_value = data["quantity"] * Decimal(str(ltp))
        pnl = market_value - data["total_cost"]

        final_portfolio.append({
            "symbol": symbol,
            "name": data["name"],
            "quantity": round(data["quantity"], 2),
            "avg_price": round(avg_price, 2),
            "ltp": ltp,
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
        })
    return final_portfolio


def get_price(symbol):
    if not hasattr(g, "price_cache"):
        g.price_cache = {}

    if symbol in g.price_cache:
        return g.price_cache[symbol]

    data = get_data(symbol)  # your existing cached function
    price = Decimal(str(data["v"]["lp"]))
    g.price_cache[symbol] = price
    return price


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