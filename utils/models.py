from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, DateTime, Integer, LargeBinary, Numeric, Enum, ForeignKey
from datetime import datetime
import uuid
from flask_login import UserMixin

# This is where the data lives
# db = sqlite3.connect("transaction_data.db")
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class= Base)

class Transaction(db.Model):
    txn_id: Mapped[str] = mapped_column(String(40), primary_key=True, unique= True, default=lambda: str(uuid.uuid4().hex[:10]))
    user_id = mapped_column(String(100), ForeignKey("user_data.user"),nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type = mapped_column(Enum("BUY", "SELL", name="txn_type"), nullable=False)
    quantity = mapped_column(Numeric(12, 4), nullable=False)
    execution_price = mapped_column(Numeric(12, 2), nullable=False)
    total_value = mapped_column(Numeric(14, 2), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    remarks: Mapped[str] = mapped_column(String(255))
    realised_pnl = mapped_column(Numeric(14, 2), nullable=True)

    def to_dict(self):
        return {
            "user_id" : self.user_id,
            "txn_id": self.txn_id,
            "symbol": self.symbol,
            "type": self.type,
            "quantity": self.quantity,
            "execution_price": self.execution_price,
            "total_value": round(self.total_value, 2),
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "remarks": self.remarks or "NA",
            "realised_pnl" : self.realised_pnl,
        }

# class Portfolio(db.Model):
#     user_id: Mapped[str] = mapped_column(String(40), nullable=False)
#     symbol: Mapped[str] = mapped_column(String(15), primary_key=True, unique=True, nullable=False)
#     name: Mapped[str] = mapped_column(String(50), nullable=False)
#     quantity: Mapped[float] = mapped_column(Float, nullable=False)
#     avg_price: Mapped[float] = mapped_column(Float, nullable=False)
#     market_price: Mapped[float] = mapped_column(Float)
#     total_value: Mapped[float] = mapped_column(Float)
#     unrealized_pnl: Mapped[float] = mapped_column(Float)
#     last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now())
#
#     def to_dict(self):
#         return {
#             "user_id" : self.user_id,
#             "symbol": self.symbol,
#             "type": self.type,
#             "quantity": self.quantity,
#             "cost_price": self.avg_price,
#             "total_value": round(self.total_value, 2),
#             "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
#             "remarks": self.remarks or "NA",
#         }

class UserData(UserMixin, db.Model):
    user: Mapped[str] = mapped_column(String(100), primary_key= True, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(200), nullable=False)
    fyers_client_id =  mapped_column(LargeBinary, nullable=False)
    fyers_secret_key =  mapped_column(LargeBinary, nullable=False)
    fyers_refresh_token = mapped_column(LargeBinary, nullable=True)
    fyers_access_token = mapped_column(LargeBinary, nullable=True)
    fyers_token_ts = mapped_column(Integer, nullable=True)
    google_api_key =  mapped_column(LargeBinary, nullable=False)
    cx =  mapped_column(LargeBinary, nullable=False)
    email = mapped_column(LargeBinary, unique=True, nullable=False)
    balance = mapped_column(Numeric(12, 2), default=100000)

    def get_id(self):
        return self.user

    def to_dict(self):
        return {
            "user" : self.user,
            "fyers_client_id": self.fyers_client_id,
            "fyers_secret_key": self.fyers_secret_key,
            "google_api_key": self.google_api_key,
            "cx": self.cx,
            "email" : self.email,
            "balance" : self.balance
        }

    @property
    def fyers_connected(self):
        return self.fyers_refresh_token is not None
