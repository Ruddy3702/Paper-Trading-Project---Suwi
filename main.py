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
# # Flask secret key
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY

# SQLAlchemy DB URI
DB_URI = f"sqlite:///{os.path.join(app.instance_path, 'transaction_data.db')}"

bootstrap = Bootstrap5(app)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI

# print("DB PATH:", os.path.abspath("transaction_data.db"))
db.init_app(app)
# print("INSTANCE PATH:", app.instance_path)

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
    fyers_redirect_url =URLField("Fyers Redirect URL",validators=[InputRequired()])
    google_api_key =StringField("Google API Key",validators=[InputRequired()])
    cx = StringField("Google CX",validators=[InputRequired()])
    balance = StringField("Starting Balance", validators=[InputRequired()])
    submit = SubmitField("Submit")

class AuthCodeForm(FlaskForm):
    fyers_client_id = StringField("Fyers Client ID", validators=[InputRequired()])
    fyers_secret_key = StringField("Fyers Secret Key", validators=[InputRequired()])
    fyers_redirect_url = URLField("Fyers Redirect URL", validators=[InputRequired()])
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

        print("LOGIN POST", user, password)

        user = UserData.query.filter_by(user=user).first()
        if not user:
            print("Please register first.")
            return redirect(url_for('register'))

        if not check_password_hash(user.password, password):
            print("Invalid email or password, please try again.")
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
            print("You already have an account")
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
            fyers_redirect_url = encrypt(request.form.get('fyers_redirect_url')),
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
    # return render_template('make_auth_code.html', form = form)


@app.route("/fyers/callback")
@login_required
def fyers_callback():
    auth_code = request.args.get("auth_code")
    if not auth_code:
        flash("Fyers login failed.", "danger")
        return redirect(url_for("home"))

    exchange_auth_code_for_tokens(auth_code)
    login_user(current_user)

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
    load_user_data(current_user)
    return render_template("index.html", logged_in= current_user.is_authenticated)


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
    articles = search(symbol)
    news_data = search(symbol)["items"]

    historic_data = get_historic_data(symbol, "1M")["candles"]

    return render_template("stock.html", stock=data,
                           logged_in= current_user.is_authenticated,
                           latest_news = articles, news_data = news_data, candles= historic_data)


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
        realized_pnl = (ltp - avg_cost) * qty

        new_transaction = Transaction(
            user_id= current_user.user,
            symbol=symbol,
            name=data["v"]["name"],
            type="SELL",
            quantity=qty,
            execution_price=ltp,
            total_value=txn_val,
            realized_pnl=realized_pnl,
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
    results = db.session.execute(db.select(Transaction).where(Transaction.user_id == current_user.user)).scalars()
    transaction_data = []
    for tx in results:
        current_price = get_price(tx.symbol)
        pnl = tx.realized_pnl if tx.type == "SELL" else None
        transaction_data.append(
            {
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
            }
        )
    return render_template("transactions.html", data=transaction_data, logged_in= current_user.is_authenticated)


@app.route("/portfolio")
@login_required
def portfolio():
    final_portfolio = calculate_portfolio()
    return render_template("portfolio.html",
                           logged_in= current_user.is_authenticated, data=final_portfolio)


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
    app.run(host="0.0.0.0", port=5000, debug=True)


