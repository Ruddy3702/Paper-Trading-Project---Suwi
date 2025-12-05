from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime
from datetime import datetime
import uuid

# This is where the data lives
# db = sqlite3.connect("transaction_data.db")
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class= Base)

class Transaction(db.Model):
    id: Mapped[str] = mapped_column(String(40), primary_key=True, unique= True, default=lambda: str(uuid.uuid4()))
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
            "id": self.id,
            "symbol": self.symbol,
            "type": self.type,
            "quantity": self.quantity,
            "cost_price": self.cost_price,
            "total_value": round(self.total_value, 2),
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "remarks": self.remarks or "NA",
        }

class Portfolio(db.Model):
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
            "symbol": self.symbol,
            "type": self.type,
            "quantity": self.quantity,
            "cost_price": self.avg_price,
            "total_value": round(self.total_value, 2),
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "remarks": self.remarks or "NA",
        }

