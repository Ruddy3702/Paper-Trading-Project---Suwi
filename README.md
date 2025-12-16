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

Links for Login:
