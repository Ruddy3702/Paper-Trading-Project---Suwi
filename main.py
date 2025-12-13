import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import DecimalField, SubmitField, StringField, URLField, PasswordField
from flask_bootstrap import Bootstrap5
from wtforms.validators import InputRequired, NumberRange
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, LoginManager, login_required, current_user, logout_user
from dotenv import load_dotenv
from utils.api_client import get_fyers_authcode
from utils.crypto_utils import encrypt, decrypt
from utils.models import db
load_dotenv()

# Import your models and DB
from utils.models import db, UserData, Transaction
from utils.api_client import get_data, get_database, search, load_user_data

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

@property
def fyers_connected(self):
    return self.fyers_refresh_token is not None

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
    fyers_client_id = StringField("Fyers Client ID",validators=[InputRequired()])
    fyers_secret_key = StringField("Fyers Secret Key",validators=[InputRequired()])
    fyers_redirect_url =URLField("Fyers Redirect URL",validators=[InputRequired()])
    google_api_key =StringField("Google API Key",validators=[InputRequired()])
    cx = StringField("Google CX",validators=[InputRequired()])
    submit = SubmitField("Submit")

class AuthCodeForm(FlaskForm):
    fyers_client_id = StringField("Fyers Client ID", validators=[InputRequired()])
    fyers_secret_key = StringField("Fyers Secret Key", validators=[InputRequired()])
    fyers_redirect_url = URLField("Fyers Redirect URL", validators=[InputRequired()])
    submit = SubmitField("Submit")

# buy/sell form
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

        new_user = UserData(
            user = user_id,
            password = generate_password_hash(password=str(password), method='pbkdf2:sha256', salt_length=8),
            fyers_client_id = encrypt(request.form.get('fyers_client_id')),
            fyers_secret_key = encrypt(request.form.get('fyers_secret_key')),
            fyers_redirect_url = encrypt(request.form.get('fyers_redirect_url')),
            fyers_auth_code= None,
            google_api_key = encrypt(request.form.get('google_api_key')),
            cx = encrypt(request.form.get('cx')),
        )
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for("home"))
    return render_template('register.html', form= form)


@app.route("/get-auth-code", methods = ["GET", "POST"])
@login_required
def get_auth_code():
    fyers_client_id = decrypt(current_user.fyers_client_id)
    fyers_secret_key = decrypt(current_user.fyers_secret_key)
    fyers_redirect_url =decrypt(current_user.fyers_redirect_url)
    auth_link = get_fyers_authcode(client_id= fyers_client_id,
                                   secret_key= fyers_secret_key,
                                   redirect_uri= fyers_redirect_url)
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

    #save auth code temporarily
    current_user.fyers_auth_code = encrypt(auth_code)
    db.session.commit()

    #IMMEDIATELY exchange it for tokens
    from utils.api_client import exchange_auth_code_for_tokens
    exchange_auth_code_for_tokens(auth_code)

    flash("Fyers connected successfully.", "success")
    return redirect(url_for("home"))


@app.route("/reconnect-fyers")
@login_required
def reconnect_fyers():
    flash("Your Fyers session expired. Please reconnect.", "warning")
    return redirect(url_for("get_auth_code"))


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
    return render_template("stock.html", stock=data, logged_in= current_user.is_authenticated, latest_news = articles)


@app.route("/buy/<symbol>", methods=["POST", "GET"])
@login_required
def buy(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty = form.quantity.data
    ltp = data["v"]["lp"]
    if request.method == "POST":
        new_transaction = Transaction(
            user_id = current_user.user,
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
    return render_template("buy.html", stock=data, form=form, logged_in= current_user.is_authenticated)


@app.route("/sell/<symbol>", methods=["GET", "POST"])
@login_required
def sell(symbol):
    form = BuySellForm()
    data = get_data(symbol)
    qty = form.quantity.data
    ltp = data["v"]["lp"]
    if request.method == "POST":
        new_transaction = Transaction(
            user_id= current_user.user,
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
    return render_template("sell.html", stock=data, form=form, logged_in= current_user.is_authenticated)


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
    results = db.session.execute(db.select(Transaction).where(Transaction.user_id == current_user.user)).scalars()                         #--------------------------------------
    # results = Transaction.query.all()
    transaction_data = []
    for tx in results:
        stock_data = get_data(tx.symbol)
        current_price = stock_data["v"]["lp"]
        pnl = (tx.quantity * current_price) - tx.total_value
        transaction_data.append(
            {
                "txn_id": tx.txn_id,
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
    return render_template("transactions.html", data=transaction_data, logged_in= current_user.is_authenticated)


@app.route("/portfolio")
@login_required
def portfolio():
    return render_template("portfolio.html", logged_in= current_user.is_authenticated)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
