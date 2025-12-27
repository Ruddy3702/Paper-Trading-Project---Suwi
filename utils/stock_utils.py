import datetime
import os, json, time, requests
from datetime import timedelta, datetime
from sqlalchemy import func
import pandas as pd
from utils.api_client import get_fyers_credentials, get_fyers_access_token
from fyers_apiv3 import fyersModel
from utils.crypto_utils import decrypt, encrypt
from flask_login import current_user
from utils.models import db, Transaction
from flask import g
from pathlib import Path
from decimal import Decimal

GLOBAL_MARKET_CACHE = {
    "data": None,
    "ts": 0
}

GLOBAL_TTL = 300  # 5 minutes
CACHE_TTL = 30  # seconds (adjust: 5–30s for market data)
NAME_MAP = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "Data")
os.makedirs(DATA_DIR, exist_ok=True)

# def write_equity_data(n):
#     """Writes n rows of (symbol, name) and (symbol) to files in /Data"""
#     input_path = os.path.join(DATA_DIR, "NSE_CM.csv")
#     eq_names_path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
#     eq_only_path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")
#
#     data = pd.read_csv(input_path, header=0)
#     df = pd.DataFrame(data)
#
#     equities = df[df['symbol'].str.endswith('-EQ')]
#     eq = equities[['symbol']].head(n)
#     name_eq = equities[['symbol', 'name']].head(n)
#
#     name_eq.to_csv(eq_names_path, index=False)
#     eq.to_csv(eq_only_path, index=False)
#
#     print(f"Wrote {n} rows to:")
#     print(f"   • {eq_names_path}")
#     print(f"   • {eq_only_path}")


def enrich_stock_data(stock: dict) -> dict:
    name_map = get_name_map()
    v = stock.get("v", {})

    symbol = v.get("symbol")
    if not symbol:
        return stock

    lp = v.get("lp") or 0
    prev_close = (v.get("prev_close_price") or v.get("close_price") or v.get("previous_close") or 0)
    open_price = v.get("open_price") or 0
    high_price = v.get("high_price") or 0
    low_price = v.get("low_price") or 0
    spread = v.get("spread") or 0
    volume = v.get("volume") or 0

    v["name"] = name_map.get(symbol, symbol)

    if prev_close:
        price_change = lp - prev_close
        percent_change = (price_change / prev_close) * 100
        v["ch"] = round(price_change, 2)
        v["chp"] = round(percent_change, 2)
    else:
        v["ch"] = None
        v["chp"] = None

    v.update({
        "day_range_percent": round((high_price - low_price) / low_price * 100, 2) if low_price else None,
        "from_open_percent": round((lp - open_price) / open_price * 100, 2) if open_price else None,
        "spread_percent": round((spread / lp) * 100, 2) if lp else None,
        "trend": "Bullish" if lp > open_price else "Bearish" if lp < open_price else "Neutral",
        "liquidity_score": round(volume / spread, 2) if spread else None,
    })

    stock["v"] = v
    return stock


def get_database(symbols=None):
    access_token = get_fyers_access_token()
    if not access_token:
        return None

    creds = get_fyers_credentials()
    fyers = fyersModel.FyersModel(
        client_id=creds["client_id"],
        token=access_token,
        is_async=False,
        log_path=""
    )

    cache_file = os.path.join(DATA_DIR, "stock_cache.json")
    cache = {}

    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    now = time.time()

    # Resolve symbol list
    if symbols:
        eq_list = symbols
    else:
        path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")
        df = pd.read_csv(path)
        eq_list = df["symbol"].tolist()

    if not eq_list:
        return []

    fresh_data = []
    to_fetch = []

    for sym in eq_list:
        if (sym in cache and now - cache[sym].get("timestamp", 0) < CACHE_TTL
            and "data" in cache[sym]):
            fresh_data.append(enrich_stock_data(cache[sym]["data"]))
        else:
            to_fetch.append(sym)

    if to_fetch:
        response = fyers.quotes({"symbols": ",".join(to_fetch)})
        raw = response.get("d", [])

        for stock in raw:
            if not isinstance(stock, dict) or "v" not in stock:
                continue

            symbol = stock["v"].get("symbol")
            if not symbol:
                continue

            cache[symbol] = {"data": stock, "timestamp": time.time()}

            fresh_data.append(enrich_stock_data(stock))

        try:
            with open(cache_file, "w") as f:
                json.dump(cache, f)
        except Exception:
            pass

    return fresh_data


def get_historic_data(symbol, range_key):
    creds = get_fyers_credentials()
    access_token = get_fyers_access_token()
    if not access_token:
        return {"s": "error", "candles": []}

    fyers = fyersModel.FyersModel(
        client_id=creds["client_id"],
        token=access_token,
        is_async=False,
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
    return {"s": "ok", "candles": merged}


def get_name_map():
    global NAME_MAP
    if NAME_MAP is None:
        df = pd.read_csv(os.path.join(DATA_DIR, "NSE_EQ_names.csv"))
        NAME_MAP = df.set_index("symbol")["name"].to_dict()
    return NAME_MAP


def get_data(symbol):
    access_token = get_fyers_access_token()
    if not access_token:
        return None

    creds = get_fyers_credentials()
    fyers = fyersModel.FyersModel(
        client_id=creds["client_id"],
        token=access_token,
        is_async=False,
        log_path=""
    )

    response = fyers.quotes({"symbols": symbol})
    data = response.get("d", [])

    if not data:
        return None

    return enrich_stock_data(data[0])


def search(name):
    try:
        key = decrypt(current_user.google_api_key)
        cx = decrypt(current_user.cx)
    except Exception:
        return {"items": []}
    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": name},
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return {"items": []}


def calculate_portfolio():
    positions = {}
    txns = db.session.execute(
        db.select(Transaction)
        .where(Transaction.user_id == current_user.user)
        .order_by(Transaction.timestamp)
    ).scalars()

    for tx in txns:
        symbol = tx.symbol
        qty = Decimal(tx.quantity)
        price = Decimal(tx.execution_price)

        if symbol not in positions:
            positions[symbol] = {
                "quantity": Decimal("0"),
                "total_cost": Decimal("0"),
                "name": tx.name,
            }

        if tx.type == "BUY":
            positions[symbol]["quantity"] += qty
            positions[symbol]["total_cost"] += qty * price

        elif tx.type == "SELL":
            avg_price = (
                positions[symbol]["total_cost"] / positions[symbol]["quantity"]
                if positions[symbol]["quantity"] > 0 else Decimal("0")
            )
            positions[symbol]["quantity"] -= qty
            positions[symbol]["total_cost"] -= qty * avg_price

    portfolio = []
    for symbol, p in positions.items():
        if p["quantity"] <= 0:
            continue

        avg_price = p["total_cost"] / p["quantity"]
        portfolio.append({
            "symbol": symbol,
            "name": p["name"],
            "quantity": p["quantity"],
            "avg_price": avg_price,
        })
    return portfolio


def get_price(symbol):
    if not hasattr(g, "price_cache"):
        g.price_cache = {}

    if symbol in g.price_cache:
        return g.price_cache[symbol]

    data = get_data(symbol)  # your existing cached function
    price = Decimal(str(data["v"]["lp"]))
    g.price_cache[symbol] = price
    return price


def get_prices_bulk(symbols):
    data = get_database(symbols)
    if not data:
        return {}

    price_map = {}
    for stock in data:
        sym = stock["v"]["symbol"]
        ltp = stock["v"]["lp"]
        price_map[sym] = Decimal(str(ltp))

    return price_map


def get_quantity_held(symbol):
    buys = db.session.query(
        func.coalesce(func.sum(Transaction.quantity), 0)).filter( Transaction.user_id == current_user.user, Transaction.symbol == symbol, Transaction.type == "BUY").scalar()

    sells = db.session.query(
        func.coalesce(func.sum(Transaction.quantity), 0)).filter(Transaction.user_id == current_user.user, Transaction.symbol == symbol, Transaction.type == "SELL").scalar()

    return (buys or Decimal("0")) - (sells or Decimal("0"))


def load_symbols_from_csv(query=None):
    df = pd.read_csv(os.path.join(DATA_DIR, "NSE_EQ_names.csv"))
    if query:
        query = query.lower()
        df = df[df["symbol"].str.lower().str.contains(query) |
                df["name"].str.lower().str.contains(query)]

    symbols = df["symbol"].tolist()
    return [f"NSE:{s}" if not s.startswith("NSE:") else s for s in symbols]


def get_global_market_data(force_refresh=False):
    """
    Returns live data for ALL NSE stocks.
    Cached for GLOBAL_TTL seconds.
    """
    now = time.time()

    if (
        not force_refresh
        and GLOBAL_MARKET_CACHE["data"] is not None
        and now - GLOBAL_MARKET_CACHE["ts"] < GLOBAL_TTL
    ):
        return GLOBAL_MARKET_CACHE["data"]

    # Load all symbols
    path = os.path.join(DATA_DIR, "NSE_EQ_only.csv")
    symbols = pd.read_csv(path)["symbol"].tolist()

    # ---- FYERS CALL (1 or 2 batches) ----
    # assuming FYERS can take ~1000 symbols safely
    BATCH_SIZE = 1000
    all_data = []

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        batch_data = get_database(batch)
        if batch_data:
            all_data.extend(batch_data)

    # Update cache
    GLOBAL_MARKET_CACHE["data"] = all_data
    GLOBAL_MARKET_CACHE["ts"] = now

    return all_data


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