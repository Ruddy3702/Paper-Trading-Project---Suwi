from fyers_apiv3 import fyersModel
import requests, os, hashlib, time, json
from utils.models import UserData, db
from utils.crypto_utils import decrypt, encrypt
from flask_login import current_user
from flask import url_for

# CONFIG
PIN = os.getenv("PIN", "1234")
if not PIN:
    raise RuntimeError("FYERS PIN not set in environment")

FYERS_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
FYERS_VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"

ACCESS_TOKEN_TTL = 43200  # 12 hours


# Helpers
def get_fyers_credentials():
    if not current_user.is_authenticated:
        return None

    return {
        "client_id": decrypt(current_user.fyers_client_id),
        "secret_key": decrypt(current_user.fyers_secret_key),
    }


# Auth Flow
def exchange_auth_code_for_tokens(auth_code: str) -> str | None:
    """
    Exchanges auth_code → access_token + refresh_token
    Stores both securely in DB.
    """
    creds = get_fyers_credentials()
    if not creds:
        return None

    client_id = creds["client_id"]
    secret_key = creds["secret_key"]

    hash_input = f"{client_id}:{secret_key}"
    appIdHash = hashlib.sha256(hash_input.encode()).hexdigest()

    payload = {
        "grant_type": "authorization_code",
        "appIdHash": appIdHash,
        "code": auth_code,
    }

    try:
        resp = requests.post(
            FYERS_VALIDATE_AUTH_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return None

    if resp.status_code != 200 or "access_token" not in data:
        return None

    access_token = data["access_token"]
    refresh_token = data.get("refresh_token")

    if not refresh_token:
        return None
    current_user.fyers_refresh_token = encrypt(refresh_token)
    current_user.fyers_access_token = encrypt(access_token)
    current_user.fyers_token_ts = int(time.time())

    db.session.commit()
    return access_token


def get_auth_code():
    creds = get_fyers_credentials()
    if not creds:
        return None

    redirect_uri = url_for("fyers_callback", _external=True, _scheme="https")

    session = fyersModel.SessionModel(
        client_id=creds["client_id"],
        secret_key=creds["secret_key"],
        redirect_uri=redirect_uri,
        response_type="code",
    )
    return session.generate_authcode()


# Token Mgmt
def get_fyers_access_token() -> str | None:
    """
    Returns a valid access token.
    - Uses DB cache if valid
    - Refreshes if expired
    - Never raises
    """

    if not current_user.is_authenticated:
        return None

    if not current_user.fyers_refresh_token:
        return None

    if current_user.fyers_access_token and current_user.fyers_token_ts and (time.time() - current_user.fyers_token_ts) < ACCESS_TOKEN_TTL:
        try:
            return decrypt(current_user.fyers_access_token)
        except Exception:
            pass

    creds = get_fyers_credentials()
    if not creds:
        return None

    try:
        refresh_token = decrypt(current_user.fyers_refresh_token)
    except Exception:
        return None

    hash_input = f"{creds['client_id']}:{creds['secret_key']}"
    appIdHash = hashlib.sha256(hash_input.encode()).hexdigest()

    payload = {
        "grant_type": "refresh_token",
        "appIdHash": appIdHash,
        "refresh_token": refresh_token,
        "pin": PIN,
    }

    try:
        resp = requests.post(
            FYERS_REFRESH_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return None

    # Refresh token expired
    if data.get("code") == -501:
        current_user.fyers_refresh_token = None
        current_user.fyers_access_token = None
        current_user.fyers_token_ts = None
        db.session.commit()
        return None

    if resp.status_code != 200 or "access_token" not in data:
        return None

    access_token = data["access_token"]

    current_user.fyers_access_token = encrypt(access_token)
    current_user.fyers_token_ts = int(time.time())
    db.session.commit()

    return access_token
