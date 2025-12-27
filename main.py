from datetime import datetime, time
import os, pytz, pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_wtf import FlaskForm
from wtforms import DecimalField, SubmitField, StringField, PasswordField, SelectField
from flask_bootstrap import Bootstrap5
from wtforms.validators import InputRequired, NumberRange
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, LoginManager, login_required, current_user, logout_user
from decimal import Decimal
from utils.models import db, UserData, Transaction
from utils.stock_utils import (get_data, get_database, search, calculate_portfolio,
                               get_historic_data, get_prices_bulk, get_quantity_held,
                               load_symbols_from_csv, get_global_market_data)
from utils.api_client import get_auth_code, exchange_auth_code_for_tokens
from utils.crypto_utils import encrypt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "Data")

# Config section
app = Flask(__name__)
bootstrap = Bootstrap5(app)

db_uri = os.getenv("DB_URI")
if not db_uri:
    raise RuntimeError("DB_URI not set")
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
    "pool_size": 5,
    "max_overflow": 5,
}
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")
db.init_app(app)

#LOGIN CODE
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(UserData, str(user_id))

with app.app_context():
    db.create_all()

class LoginForm(FlaskForm):
    user = StringField("Username",validators=[InputRequired()])
    password = PasswordField("Password",validators=[InputRequired()])
    submit = SubmitField("Submit")

class RegisterForm(FlaskForm):
    user = StringField("Username", validators=[InputRequired()])
    password = PasswordField("Password", validators=[InputRequired()])
    email = StringField("Email", validators=[InputRequired()])
    fyers_client_id = StringField("Fyers Client ID",validators=[InputRequired()])
    fyers_secret_key = StringField("Fyers Secret Key",validators=[InputRequired()])
    google_api_key =StringField("Google API Key",validators=[InputRequired()])
    cx = StringField("Google CX",validators=[InputRequired()])
    balance = StringField("Starting Balance", validators=[InputRequired()])
    submit = SubmitField("Submit")

class BuySellForm(FlaskForm):
    quantity = DecimalField("Quantity", validators=[InputRequired(), NumberRange(min=1)], places=2)
    remarks = StringField("Remarks")
    submit = SubmitField("Confirm")

class GetNewsForm(FlaskForm):
    query = StringField("Query", validators=[InputRequired()])
    submit = SubmitField("Confirm")

class BalanceForm(FlaskForm):
    amount = DecimalField("Add/Withdraw Amount", validators = [InputRequired(),NumberRange(min=0.01)])
    action = SelectField("Action", choices=[("ADD", "Add Balance"), ("SUB", "Withdraw Funds")], validators=[InputRequired()])
    submit = SubmitField("Confirm")


@app.route("/login", methods = ["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = form.user.data
        password = form.password.data

        user = UserData.query.filter_by(user=user).first()
        if not user:
            flash("Please register first.", "error")
            return redirect(url_for('register'))

        if not check_password_hash(user.password, password):
            flash("Invalid username or password, please try again.", "error")
            return redirect(url_for('login'))

        login_user(user)
        next_page = request.args.get("next")

        return redirect(next_page or url_for('home'))
    return render_template('login.html', logged_in=current_user.is_authenticated, form= form)


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user_id = form.user.data
        password = form.password.data
        existing_user = UserData.query.filter_by(user=user_id).first()
        if existing_user:
            flash("You already have an account", "info")
            return redirect(url_for("login"))
        try:
            balance = Decimal(form.balance.data)
            if balance <= 0:
                raise ValueError
        except:
            flash("Invalid starting balance")
            return redirect(url_for("register"))
        new_user = UserData(
            user = user_id,
            password = generate_password_hash(password=str(password), method='pbkdf2:sha256', salt_length=8),
            email = encrypt(form.email.data),
            fyers_client_id = encrypt(form.fyers_client_id.data),
            fyers_secret_key = encrypt(form.fyers_secret_key.data),
            google_api_key = encrypt(form.google_api_key.data),
            cx = encrypt(form.cx.data),
            balance = balance,
        )
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for("home"))
    return render_template('register.html', form= form)


@app.route("/get-auth-code", methods = ["GET"])
@login_required
def get_code():
    auth_link = get_auth_code()
    flash(f"<a href= {auth_link}>Click Here For Auth Code</a>",'success')
    return redirect(url_for('home'))


@app.route("/fyers/callback")
@login_required
def fyers_callback():
    auth_code = request.args.get("auth_code")

    if not auth_code:
        flash("Fyers login failed: auth code missing.", "danger")
        return redirect(url_for("home"))
    access_token = exchange_auth_code_for_tokens(auth_code)

    if not access_token:
        flash(
            "Fyers connection failed. Please reconnect your account.",
            "danger"
        )
        return redirect(url_for("get_code"))
    flash("Fyers connected successfully.", "success")
    return redirect(url_for("home"))


@app.route("/logout", methods = ["GET"])
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route("/", methods = ["GET", "POST"])
@login_required
def home():
    return render_template("index.html", logged_in=True)


@app.route("/stocks", methods=["GET"])
@login_required
def database():
    force_refresh = request.args.get("refresh") == "1"

    raw_q = request.args.get("q")
    query = raw_q.strip().lower() if raw_q and raw_q.lower() != "none" else None

    page = max(int(request.args.get("page", 1)), 1)
    per_page = max(int(request.args.get("per_page", 100)), 1)

    sort_by = request.args.get("sort_by")
    order = request.args.get("order", "desc")
    reverse = order == "desc"

    GLOBAL_SORT_FIELDS = {"volume", "chp", "lp"}

    all_data = get_global_market_data(force_refresh=force_refresh)

    if all_data is None:
        flash("Please connect Fyers first")
        return redirect(url_for("get_code"))

    if query:
        all_data = [
            s for s in all_data if query in s["v"]["symbol"].lower()
            or query in s["v"]["name"].lower()]

    if sort_by:
        if sort_by == "trend":
            all_data.sort(key=lambda x: 0 if x["v"].get("trend") == "Bullish"
            else 1, reverse=reverse)
        else:
            all_data.sort(key=lambda x: x["v"].get(sort_by) or 0,
                reverse=reverse)

    total = len(all_data)
    start = (page - 1) * per_page
    end = start + per_page
    data = all_data[start:end]

    has_next = total > page * per_page
    has_prev = page > 1

    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    online = (current_user.fyers_connected and now.weekday() < 5
        and time(9, 15) <= now.time() <= time(15, 30))

    return render_template("database.html", all_stocks=data,
                           page=page, per_page=per_page, total=total, has_next=has_next,
                           has_prev=has_prev, logged_in=True, status=online, query=query,
                           sort_by=sort_by, order=order)


@app.route("/api/search-stock")
@login_required
def search_stock_api():
    q = request.args.get("q", "").strip().lower()

    if len(q) < 2:
        return jsonify([])

    # Load NSE names once
    path = os.path.join(DATA_DIR, "NSE_EQ_names.csv")
    df = pd.read_csv(path)

    matches = df[df["symbol"].str.lower().str.contains(q) | df["name"].str.lower().str.contains(q)].head(5)

    symbols = matches["symbol"].tolist()

    if not symbols:
        return jsonify([])

    data = get_database(symbols)

    results = []
    for stock in data:
        v = stock["v"]
        results.append({
            "symbol": v["symbol"],
            "name": v["name"],
            "price": v["lp"],
            "chp": v["chp"],
        })

    return jsonify(results)


@app.route("/stock/<symbol>")
@login_required
def stock_info(symbol):
    data = get_data(symbol)
    if not data:
        flash("Live data unavailable. Please reconnect FYERS.", "danger")
        return redirect(url_for("database"))

    news_data = search(symbol)["items"]

    historic_data = get_historic_data(symbol, "1M")["candles"]

    return render_template("stock.html", stock=data,
                           logged_in= current_user.is_authenticated,
                           news_data = news_data,
                           candles= historic_data)


@app.route("/buy/<symbol>", methods=["POST", "GET"])
@login_required
def buy(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty_held = get_quantity_held(symbol)

    if not data or "v" not in data or data["v"].get("lp") is None:
        flash("Live price unavailable. Please reconnect FYERS.", "danger")
        return redirect(url_for("database"))

    if form.validate_on_submit():
        qty = form.quantity.data
        ltp = Decimal(str(data["v"]["lp"]))
        txn_val = qty * ltp
        if txn_val > Decimal(current_user.balance):
            flash(f"Your balance is not enough for this transaction", "error")
            return redirect(url_for("buy", symbol =symbol))
        new_transaction = Transaction(
            user_id = current_user.user,
            symbol=symbol,
            name=data["v"]["name"],
            type="BUY",
            quantity=qty,
            execution_price=ltp,
            total_value=txn_val,
            remarks=form.remarks.data,
        )

        current_user.balance = Decimal(current_user.balance) - txn_val
        db.session.add(new_transaction)
        db.session.commit()
        next_page = request.args.get("next")
        return redirect(next_page or url_for("database"))
    return render_template("buy-sell.html", balance = current_user.balance, stock=data, form=form,
                           logged_in= current_user.is_authenticated, action="BUY", quantity_held=qty_held)


@app.route("/sell/<symbol>", methods=["GET", "POST"])
@login_required
def sell(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty_held = get_quantity_held(symbol)
    if not data or "v" not in data or data["v"].get("lp") is None:
        flash("Live price unavailable. Please reconnect FYERS.", "danger")
        return redirect(url_for("database"))

    if form.validate_on_submit():
        qty = Decimal(form.quantity.data)
        ltp = Decimal(str(data["v"]["lp"]))
        txn_val = qty * ltp
        portfolio = calculate_portfolio()
        position = next((p for p in portfolio if p["symbol"] == symbol), None)
        if not position or position["quantity"] < qty:
            flash("You do not have enough quantity to sell.")
            return redirect(url_for("sell", symbol=symbol))
        avg_cost = Decimal(position["avg_price"])
        realised_pnl = (ltp - avg_cost) * qty

        new_transaction = Transaction(
            user_id= current_user.user,
            symbol=symbol,
            name=data["v"]["name"],
            type="SELL",
            quantity=qty,
            execution_price=ltp,
            total_value=txn_val,
            realised_pnl=realised_pnl,
            remarks=form.remarks.data,
        )
        current_user.balance = Decimal(current_user.balance) + txn_val
        db.session.add(new_transaction)
        db.session.commit()
        next_page = request.args.get("next")
        return redirect(next_page or url_for("database"))
    return render_template("buy-sell.html", balance = current_user.balance, stock=data, form=form,
                           logged_in= current_user.is_authenticated, action="SELL", quantity_held=qty_held)


@app.route("/news", methods=["GET", "POST"])
@login_required
def get_news():
    form = GetNewsForm()
    if form.validate_on_submit():
        query = form.query.data
        data = search(query)["items"]
        if not data:
            flash("News unavailable right now", "info")
            return redirect(url_for("home"))
        return render_template("news.html", data=data, form=form, logged_in= current_user.is_authenticated)
    return render_template("news.html", form=form, logged_in= current_user.is_authenticated)


@app.route("/transactions")
@login_required
def transactions():
    page = int(request.args.get("page", 1))
    per_page = 20

    stmt = (db.select(Transaction).where(Transaction.user_id == current_user.user)
            .order_by(Transaction.timestamp.desc()).limit(per_page).offset((page - 1) * per_page))

    results = db.session.execute(stmt).scalars().all()
    total_count = db.session.query(Transaction).filter(Transaction.user_id == current_user.user).count()

    has_next = page * per_page < total_count
    has_prev = page > 1

    symbols = {tx.symbol for tx in results}
    price_map = {}

    if current_user.fyers_connected and symbols:
        price_map = get_prices_bulk(list(symbols))

    transaction_data = []
    total_realised_pnl = Decimal("0.00")

    for tx in results:
        pnl = tx.realised_pnl if tx.type == "SELL" else Decimal("0.00")
        total_realised_pnl += pnl

        transaction_data.append({
            "txn_id": tx.txn_id,
            "symbol": tx.symbol,
            "type": tx.type,
            "quantity": tx.quantity,
            "execution_price": tx.execution_price,
            "total_value": tx.total_value,
            "timestamp": tx.timestamp,
            "remarks": tx.remarks,
            "pnl": pnl,
            "current_price": price_map.get(tx.symbol),
        })

    return render_template(
        "transactions.html",
        data=transaction_data,
        total_pnl=total_realised_pnl,
        page=page,
        per_page=per_page,
        has_next=has_next,
        has_prev=has_prev,
        logged_in=True,
    )


@app.route("/portfolio")
@login_required
def portfolio():
    portfolio = calculate_portfolio()

    sort_by = request.args.get("sort_by")
    order = request.args.get("order", "desc")

    symbols = [p["symbol"] for p in portfolio]

    price_map = {}
    if current_user.fyers_connected and symbols:
        price_map = get_prices_bulk(symbols)

    total_unrealised_pnl = Decimal("0")
    total_market_value = Decimal("0")

    for p in portfolio:
        ltp = price_map.get(p["symbol"])

        if ltp is None:
            p["ltp"] = None
            p["market_value"] = None
            p["unrealised_pnl"] = None
            continue

        p["ltp"] = ltp
        p["market_value"] = ltp * p["quantity"]
        p["unrealised_pnl"] = (ltp - p["avg_price"]) * p["quantity"]

        total_unrealised_pnl += p["unrealised_pnl"]
        total_market_value += p["market_value"]

    if sort_by:
        reverse = order == "desc"
        if sort_by == "pnl":
            portfolio.sort(key=lambda x: x.get("unrealised_pnl") if x.get("unrealised_pnl") is not None else Decimal("-1e18"), reverse=reverse)
        elif sort_by == "value":
            portfolio.sort(key=lambda x: x.get("market_value") if x.get("market_value") is not None else Decimal("-1e18"), reverse=reverse)
        elif sort_by == "qty":
            portfolio.sort(key=lambda x: x["quantity"], reverse=reverse)
        elif sort_by == "symbol":
            portfolio.sort(key=lambda x: x["symbol"], reverse=reverse)

    if not current_user.fyers_connected:
        flash("Live prices unavailable. Connect FYERS to view P&L.", "info")

    return render_template("portfolio.html", data=portfolio, total_unrealised_pnl=total_unrealised_pnl,
                           tmv=total_market_value, logged_in=True)


@app.route("/candles/<symbol>")
@login_required
def candles(symbol):
    range_key = request.args.get("range", "1M")
    data = get_historic_data(symbol, range_key)

    if not data or data.get("s") != "ok":
        return jsonify({"candles": []}), 200

    return jsonify({"candles": data.get("candles", [])}), 200


@app.route("/balance", methods= ["GET", "POST"])
@login_required
def balance():
    form = BalanceForm()
    if form.validate_on_submit():
        user = current_user
        amount = form.amount.data
        action = form.action.data
        if action == "ADD":
            user.balance += amount
        elif action == "SUB":
            if amount > Decimal(user.balance):
                flash("Insufficient balance", "danger")
                return redirect(url_for("balance"))
            user.balance -= amount
        db.session.commit()
        flash(f"Balance updated. New balance is  ₹ {user.balance}","success")
        return redirect(url_for("home"))
    return render_template('balance.html', form=form)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


