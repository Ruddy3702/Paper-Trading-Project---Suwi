from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, DateTime, Integer
from datetime import datetime
import uuid
from flask_login import UserMixin

# This is where the data lives
# db = sqlite3.connect("transaction_data.db")
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class= Base)

class Transaction(db.Model):
    txn_id: Mapped[str] = mapped_column(String(40), primary_key=True, unique= True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(15), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY/SELL
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now())
    remarks: Mapped[str] = mapped_column(String(255))

    def to_dict(self):
        return {
            "user_id" : self.user_id,
            "txn_id": self.txn_id,
            "symbol": self.symbol,
            "type": self.type,
            "quantity": self.quantity,
            "cost_price": self.cost_price,
            "total_value": round(self.total_value, 2),
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "remarks": self.remarks or "NA",
        }

class Portfolio(db.Model):
    user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str] = mapped_column(String(15), primary_key=True, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    market_price: Mapped[float] = mapped_column(Float)
    total_value: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now())

    def to_dict(self):
        return {
            "user_id" : self.user_id,
            "symbol": self.symbol,
            "type": self.type,
            "quantity": self.quantity,
            "cost_price": self.avg_price,
            "total_value": round(self.total_value, 2),
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "remarks": self.remarks or "NA",
        }

class UserData(UserMixin, db.Model):
    user: Mapped[str] = mapped_column(String(15), primary_key= True, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(50), nullable=False)
    fyers_client_id: Mapped[str] = mapped_column(String(50), nullable=False)
    fyers_secret_key: Mapped[str] = mapped_column(String(50), nullable=False)
    fyers_redirect_url: Mapped[str] = mapped_column(String(100), nullable=False)
    google_api_key: Mapped[str] = mapped_column(String(150), nullable=False)
    cx: Mapped[str] = mapped_column(String(150), nullable=False)
    fyers_auth_code: Mapped[str] = mapped_column(String(600), nullable=False)

    def get_id(self):
        return self.user

    def to_dict(self):
        return {
            "user_id" : self.user_id,
            "password": self.password,
            "fyers_client_id": self.fyers_client_id,
            "fyers_secret_key": self.fyers_secret_key,
            "fyers_redirect_url": self.fyers_redirect_url,
            "google_api_key": self.google_api_key,
            "cx": self.cx,
            "fyers_auth_code": self.fyers_auth_code,
        }
