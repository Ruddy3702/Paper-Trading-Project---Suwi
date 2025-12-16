import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_wtf import FlaskForm
from wtforms import DecimalField, SubmitField, StringField, URLField, PasswordField
from flask_bootstrap import Bootstrap5
from wtforms.validators import InputRequired, NumberRange
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, LoginManager, login_required, current_user, logout_user
from decimal import Decimal
from utils.models import db, UserData, Transaction
from utils.stock_utils import get_data, get_database, search, calculate_portfolio, get_price, get_historic_data
from utils.api_client import load_user_data, get_auth_code, exchange_auth_code_for_tokens
from utils.crypto_utils import encrypt

#        CONFIG SECTION
app = Flask(__name__)
bootstrap = Bootstrap5(app)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")

db_uri = os.getenv("DB_URI")
if not db_uri:
    raise RuntimeError("DB_URI not set")

if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql+psycopg://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,     # detects dead connections
    "pool_recycle": 280,       # seconds (Render kills idle conns ~300s)
    "pool_size": 5,
    "max_overflow": 5,
}

db.init_app(app)

#LOGIN CODE
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

#user loader callback
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(UserData, str(user_id))

with app.app_context():
    db.create_all()

# login form
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

class AuthCodeForm(FlaskForm):
    fyers_client_id = StringField("Fyers Client ID", validators=[InputRequired()])
    fyers_secret_key = StringField("Fyers Secret Key", validators=[InputRequired()])
    submit = SubmitField("Submit")

class BuySellForm(FlaskForm):
    quantity = DecimalField("Quantity", validators=[InputRequired(), NumberRange(min=1)], places=2)
    remarks = StringField("Remarks")
    submit = SubmitField("Confirm")

class GetNewsForm(FlaskForm):
    query = StringField("Query", validators=[InputRequired()])
    submit = SubmitField("Confirm")


@app.route("/login", methods = ["GET", "POST"])
def login():
    form = LoginForm()
    if request.method == "POST":
        user = request.form.get("user")
        password = request.form.get("password")

        user = UserData.query.filter_by(user=user).first()
        if not user:
            flash("Please register first.", "error")
            return redirect(url_for('register'))

        if not check_password_hash(user.password, password):
            flash("Invalid email or password, please try again.", "error")
            return redirect(url_for('login'))

        login_user(user)
        next_page = request.args.get("next")

        return redirect(next_page or url_for('home'))
    return render_template('login.html', logged_in=current_user.is_authenticated, form= form)


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if request.method =="POST":
        user_id = request.form.get('user')
        password = request.form.get('password')
        existing_user = UserData.query.filter_by(user=user_id).first()
        if existing_user:
            flash("You already have an account", "info")
            return redirect(url_for("login"))
        try:
            balance = Decimal(request.form.get('balance'))
            if balance <= 0:
                raise ValueError
        except:
            flash("Invalid starting balance")
            return redirect(url_for("register"))
        new_user = UserData(
            user = user_id,
            password = generate_password_hash(password=str(password), method='pbkdf2:sha256', salt_length=8),
            email = encrypt(request.form.get('email')),
            fyers_client_id = encrypt(request.form.get('fyers_client_id')),
            fyers_secret_key = encrypt(request.form.get('fyers_secret_key')),
            google_api_key = encrypt(request.form.get('google_api_key')),
            cx = encrypt(request.form.get('cx')),
            balance = balance,
        )
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for("home"))
    return render_template('register.html', form= form)


@app.route("/get-auth-code", methods = ["GET", "POST"])
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

    # Token saved successfully
    flash("Fyers connected successfully.", "success")
    return redirect(url_for("home"))


@app.route("/logout", methods = ["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route("/", methods = ["GET", "POST"])
@login_required
def home():
    return render_template("index.html", logged_in=True)


@app.route("/stocks", methods=["GET", "POST"])
@login_required
def database():
    sort_by = request.args.get("sort_by")
    order = request.args.get("order", "desc")  # default descending
    data = get_database()
    if not data:
        flash(f"Please connect Fyers first")
        return redirect(url_for("get_code"))

    if sort_by:
        reverse = True if order == "desc" else False

        if sort_by == "trend":
            # Bullish first
            data.sort(key=lambda x: 0 if x["v"].get("trend") == "Bullish" else 1, reverse=reverse)
        else:
            data.sort(key=lambda x: x["v"].get(sort_by, 0) or 0, reverse=reverse)

    return render_template("database.html", all_stocks=data, sort_by=sort_by, order=order, logged_in= current_user.is_authenticated)


@app.route("/stock/<symbol>")
@login_required
def stock_info(symbol):
    data = get_data(symbol)

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
    if request.method == "POST" and form.validate():
        qty = form.quantity.data
        ltp = Decimal(str(data["v"]["lp"]))
        txn_val = qty * ltp
        if txn_val > current_user.balance:
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

        current_user.balance -= txn_val
        db.session.add(new_transaction)
        db.session.commit()
        return redirect(url_for("database"))
    return render_template("buy-sell.html", balance = current_user.balance, stock=data, form=form,
                           logged_in= current_user.is_authenticated, action="BUY")


@app.route("/sell/<symbol>", methods=["GET", "POST"])
@login_required
def sell(symbol):
    form = BuySellForm()
    data = get_data(symbol)

    if request.method == "POST" and form.validate():
        qty = Decimal(str(form.quantity.data))
        ltp = Decimal(str(data["v"]["lp"]))

        if ltp == 0 or ltp == None:
            flash("Invalid quantity", "danger")
            return redirect(url_for("sell", symbol=symbol))

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
        current_user.balance += txn_val
        db.session.add(new_transaction)
        db.session.commit()
        return redirect(url_for("database"))
    return render_template("buy-sell.html", balance = current_user.balance, stock=data, form=form,
                           logged_in= current_user.is_authenticated, action="SELL")


@app.route("/news", methods=["GET", "POST"])
@login_required
def get_news():
    form = GetNewsForm()
    if request.method == "POST":
        query = form.query.data
        data = search(query)["items"]
        return render_template("news.html", data=data, form=form, logged_in= current_user.is_authenticated)
    return render_template("news.html", form=form, logged_in= current_user.is_authenticated)


@app.route("/transactions")
@login_required
def transactions():
    results = db.session.execute(
        db.select(Transaction)
        .where(Transaction.user_id == current_user.user)
        .order_by(Transaction.timestamp.desc())
    ).scalars()

    transaction_data = []
    total_realised_pnl = Decimal("0.00")

    for tx in results:
        current_price = get_price(tx.symbol)

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
            "current_price": current_price,
        })

    return render_template(
        "transactions.html",
        data=transaction_data,
        total_pnl=total_realised_pnl,
        logged_in=current_user.is_authenticated,
    )

@app.route("/portfolio")
@login_required
def portfolio():
    portfolio = calculate_portfolio()
    total_unrealised_pnl = sum(p["unrealised_pnl"] for p in portfolio)
    total_market_value =  sum(p["market_value"] for p in portfolio)
    return render_template("portfolio.html",
                           logged_in= current_user.is_authenticated, data=portfolio,
                           total_unrealised_pnl = total_unrealised_pnl, tmv =total_market_value)


@app.route("/candles/<symbol>")
@login_required
def candles(symbol):
    range_key = request.args.get("range", "1M")
    data = get_historic_data(symbol, range_key)
    if not data or data.get("s") != "ok":
        print("FYERS ERROR:", data)
        return jsonify([]), 200   # return empty data safely

    return jsonify(data.get("candles", []))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


