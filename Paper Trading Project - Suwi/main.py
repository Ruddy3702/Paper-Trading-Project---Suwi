from flask import Flask, render_template
from fyers_apiv3 import fyersModel
from flask_bootstrap import Bootstrap5

app = Flask(__name__)
bootstrap = Bootstrap5(app)

@app.route("/")
def home():

    return render_template("index.html")

@app.route("/stocks")
def database():
    # data = get_data()
    return render_template("database.html")
                           # all_stocks = data)

@app.route("/news")
def get_news():
    return render_template("news.html")

@app.route("/transactions")
def transactions():
    return render_template("transactions.html")

@app.route("/portfolio")
def portfolio():
    return render_template("portfolio.html")

if __name__ == "__main__":
    app.run(debug= True)