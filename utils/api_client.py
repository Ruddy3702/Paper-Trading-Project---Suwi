from fyers_apiv3 import fyersModel
import requests, os, hashlib, time, json
from utils.models import UserData, db
from utils.crypto_utils import decrypt, encrypt
from flask_login import current_user
from flask import url_for

PIN = os.getenv("PIN","1234")
FYERS_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
FYERS_VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "../Data")
os.makedirs(DATA_DIR, exist_ok=True)

ACCESS_TOKEN_FILE = os.path.join(BASE_DIR, "access_token.txt")  # not used but kept
TOKEN_CACHE_FILE = os.path.join(DATA_DIR, "token_cache.json")


def get_fyers_credentials():
    if not current_user.is_authenticated:
        raise RuntimeError("User not logged in")

    return {
        "client_id": decrypt(current_user.fyers_client_id),
        "secret_key": decrypt(current_user.fyers_secret_key),
    }


def load_user_data():
    user_data = UserData.query.filter_by(user=current_user.user).first()
    return user_data


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
        print("FYERS AUTH FAILED:", data)
        return None

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token")

    current_user.fyers_refresh_token = encrypt(refresh_token)

    if not refresh_token:
        print("FYERS RESPONSE MISSING REFRESH TOKEN:", data)
        return None

    current_user.fyers_auth_code = None
    db.session.commit()

    # Cache access token with timestamp
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"access_token": access_token, "timestamp": time.time()}, f)

    print("Fyers access/refresh tokens updated from auth_code.")
    return access_token


def get_auth_code():
    fyers_client_id = decrypt(current_user.fyers_client_id)
    fyers_secret_key = decrypt(current_user.fyers_secret_key)

    redirect_uri = url_for(
        "fyers_callback",
        _external=True,
        _scheme="https"
    )

    session = fyersModel.SessionModel(
        client_id=fyers_client_id,
        secret_key=fyers_secret_key,
        redirect_uri=redirect_uri,
        response_type="code"
    )

    return session.generate_authcode()


def get_fyers_authcode(*, client_id, secret_key):
    session = fyersModel.SessionModel(
        client_id=client_id,
        secret_key=secret_key,
        redirect_uri= os.getenv("FYERS_REDIRECT_URL"),
        response_type="code"
    )
    return session.generate_authcode()


def get_fyers_access_token():
    """
    Returns:
        access_token (str) if valid
        None if user must re-auth
    Safe for Render. Never raises.
    """

    if not current_user.is_authenticated:
        return None

    if not current_user.fyers_refresh_token:
        return None

    # Reuse cached access token if still valid (12 hours)
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r") as f:
                cache = json.load(f)

            access_token = cache.get("access_token")
            timestamp = cache.get("timestamp", 0)

            if access_token and (time.time() - timestamp) < 43200:
                return access_token
        except Exception:
            pass  # ignore corrupt cache

    # Refresh token flow
    creds = get_fyers_credentials()
    if not creds:
        return None

    FYERS_CLIENT_ID = creds["client_id"]
    FYERS_SECRET_KEY = creds["secret_key"]

    if not FYERS_CLIENT_ID or not FYERS_SECRET_KEY:
        return None

    try:
        refresh_token = decrypt(current_user.fyers_refresh_token)
    except Exception:
        return None

    hash_input = f"{FYERS_CLIENT_ID}:{FYERS_SECRET_KEY}"
    appIdHash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    payload = {
        "grant_type": "refresh_token",
        "appIdHash": appIdHash,
        "refresh_token": refresh_token,
        "pin": PIN,
    }

    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(FYERS_REFRESH_URL, headers=headers, json=payload, timeout=10)
        data = response.json()
    except Exception:
        return None

    #  Refresh token expired → force reconnect
    if data.get("code") == -501:
        current_user.fyers_refresh_token = None
        db.session.commit()
        return None

    if response.status_code != 200 or "access_token" not in data:
        return None

    access_token = data["access_token"]

    #  Cache access token
    try:
        with open(TOKEN_CACHE_FILE, "w") as f:
            json.dump(
                {"access_token": access_token, "timestamp": time.time()},
                f
            )
    except Exception:
        pass  # cache failure should not break app

    return access_token


