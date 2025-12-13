import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

fernet = Fernet(os.getenv("FERNET_KEY").encode())

def encrypt(value: str) -> bytes:
    return fernet.encrypt(value.encode())

def decrypt(value: bytes) -> str:
    return fernet.decrypt(value).decode()