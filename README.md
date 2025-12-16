Problem
Retail traders need a safe environment to understand portfolio P&L, execution logic, and market behaviour without risking capital.

What this app does
Simulates real world equity trading using live market data,
Tracks realised and unrealised P&L accurately,
Supports multi user portfolios with isolated balances,
Provides historical charts for decision making,

Key Features
User authentication,
Virtual wallet with reset,
Buy/Sell execution at market price,
Portfolio level and trade level P&L,
Candlestick charts with multiple timeframes,

Tech Stack
Backend: Flask, SQLAlchemy,
Frontend: Jinja2, Bootstrap,
Charts: Plotly / JS,
Data: Fyers API,
Auth: Flask Login,
Hosting: Render

Design Decisions
Market orders only to keep execution deterministic,
Prices locked at execution time to avoid P&L drift,
Separate realised vs unrealised P&L for clarity

Intentional Limitations:
No derivatives or margin,
Single exchange,
No order book


1. Fyers API (Market Data / Trading Simulation)

Dashboard
https://myapi.fyers.in/dashboard

Steps
Register and create a Fyers developer account.

Generate:
Client ID
Secret Key

Set the Redirect URL exactly as:
http://127.0.0.1:5000/fyers/callback
Keep this unchanged to ensure smooth token refresh during development.

To obtain the Auth Code:
Start the application
Open the auth URL
Click Get Auth Code
Complete login and consent

Notes
Access tokens are generated dynamically using the auth code.
Keys must be stored as environment variables.
Never commit Client ID or Secret Key to GitHub.

2. Google Custom Search API (News / Web Data)

Documentation
https://developers.google.com/custom-search/v1/introduction

Create Search Engine
https://programmablesearchengine.google.com/controlpanel/create

Steps
Create a new Programmable Search Engine.
When prompted, select:
Search the entire web

Obtain:
API Key
Search Engine ID (CX)
Store both as environment variables.
