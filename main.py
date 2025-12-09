import os
from flask import Flask, render_template, request, redirect, url_for
from flask_wtf import FlaskForm
from wtforms import DecimalField, SubmitField, StringField
from flask_bootstrap import Bootstrap5
from wtforms.validators import InputRequired, NumberRange

from dotenv import load_dotenv
load_dotenv()

# Import your models and DB
from utils.models import db, Transaction, Portfolio
from utils.api_client import get_data, get_database, search

#        CONFIG SECTION

# Flask secret key
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "aloo-banchodiya")

# SQLAlchemy DB URI
DB_URI = os.getenv("DB_URI", "sqlite:///transaction_data.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY

bootstrap = Bootstrap5(app)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
db.init_app(app)

with app.app_context():
    db.create_all()


# buy/sell form
class BuySellForm(FlaskForm):
    quantity = DecimalField("Quantity", validators=[InputRequired(), NumberRange(min=1)], places=2)
    remarks = StringField("Remarks")
    submit = SubmitField("Confirm")


class GetNewsForm(FlaskForm):
    query = StringField("Query", validators=[InputRequired()])
    submit = SubmitField("Confirm")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/stocks")
def database():
    sort_by = request.args.get("sort_by")
    order = request.args.get("order", "desc")  # default descending
    data = get_database()

    if sort_by:
        reverse = True if order == "desc" else False

        if sort_by == "trend":
            # Bullish first
            data.sort(key=lambda x: 0 if x["v"].get("trend") == "Bullish" else 1, reverse=reverse)
        else:
            data.sort(key=lambda x: x["v"].get(sort_by, 0) or 0, reverse=reverse)

    return render_template("database.html", all_stocks=data, sort_by=sort_by, order=order)


@app.route("/stock/<symbol>")
def stock_info(symbol):
    data = get_data(symbol)
    return render_template("stock.html", stock=data)


@app.route("/buy/<symbol>", methods=["POST", "GET"])
def buy(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty = form.quantity.data
    ltp = data["v"]["lp"]
    if request.method == "POST":
        new_transaction = Transaction(
            symbol=symbol,
            name=data["v"]["name"],
            type="BUY",
            quantity=float(qty),
            cost_price=ltp,
            total_value=float(qty) * float(ltp),
            remarks=form.remarks.data,
        )
        db.session.add(new_transaction)
        db.session.commit()
        return redirect(url_for("transactions"))
    return render_template("buy.html", stock=data, form=form)


@app.route("/sell/<symbol>", methods=["GET", "POST"])
def sell(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty = form.quantity.data
    ltp = data["v"]["lp"]
    if request.method == "POST":
        new_transaction = Transaction(
            symbol=symbol,
            name=data["v"]["name"],
            type="SELL",
            quantity=float(qty),
            cost_price=ltp,
            total_value=float(qty) * float(ltp),
            remarks=form.remarks.data,
        )
        db.session.add(new_transaction)
        db.session.commit()
        return redirect(url_for("transactions"))
    return render_template("sell.html", stock=data, form=form)


@app.route("/news", methods=["GET", "POST"])
def get_news():
    form = GetNewsForm()
    if request.method == "POST":
        query = form.query.data
        data = search(query)["items"]
        return render_template("news.html", data=data, form=form)
    return render_template("news.html", form=form)


@app.route("/transactions")
def transactions():
    results = Transaction.query.all()
    transaction_data = []
    for tx in results:
        stock_data = get_data(tx.symbol)
        current_price = stock_data["v"]["lp"]
        pnl = (tx.quantity * current_price) - tx.total_value
        transaction_data.append(
            {
                "id": tx.id,
                "symbol": tx.symbol,
                "type": tx.type,
                "quantity": tx.quantity,
                "cost_price": tx.cost_price,
                "total_value": tx.total_value,
                "timestamp": tx.timestamp,
                "remarks": tx.remarks,
                "pnl": round(pnl, 2),
                "current_price": stock_data["v"]["lp"],
            }
        )
    return render_template("transactions.html", data=transaction_data)


@app.route("/portfolio")
def portfolio():
    return render_template("portfolio.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
