import os
from cryptography.fernet import Fernet

key = os.getenv("FERNET_KEY")
if not key:
    raise RuntimeError("FERNET_KEY not set")

fernet = Fernet(key.encode())

def encrypt(value: str) -> bytes:
    return fernet.encrypt(value.encode())

def decrypt(value: bytes) -> str:
    return fernet.decrypt(value).decode()