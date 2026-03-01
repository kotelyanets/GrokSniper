# GrokSniper AI - Features & Functionality Overview

GrokSniper AI is a fully autonomous, sentiment-driven cryptocurrency trading bot. It combines real-time news scraping, advanced AI sentiment analysis (via xAI's Grok), and strict technical analysis (TA) to execute high-probability trades on Binance. It features a modern web dashboard and real-time Telegram alerts.

Here is a comprehensive breakdown of all the core functionalities currently implemented in the project:

---

## 1. 24/7 Autonomous Trading Loop
At the heart of the backend (built with FastAPI and Python) runs a continuous automation loop that executes every 60 seconds without human intervention.
*   **RSS News Scraping**: Constantly polls major crypto news sources for the latest headlines and articles.
*   **Grok AI Sentiment Analysis**: Sends raw news text to the Grok AI model to extract the mentioned `ticker`, calculate a `sentiment_score` (-1.0 to 1.0), and assess its `confidence` level (0-100%).
*   **Database Logging**: All processed news, AI analyses, and executed trades are permanently logged in a relational database (PostgreSQL/SQLite via SQLAlchemy) for historical tracking and frontend display.

## 2. Elite Accuracy "Confluence" BUY Gate
To protect capital, the bot does not buy based on news alone. Before any `BUY` order is placed, a ticker must survive a strict three-stage Confluence Gate:
*   **Gate 1: Strong Sentiment**: The AI must output a bullish sentiment score of `≥ 0.5` with a confidence of `≥ 80%`.
*   **Gate 2: Volume Anomaly (Whale Tracking)**: The current 15-minute candle volume must be at least **1.5x greater** than the 20-period Volume Simple Moving Average (SMA). This ensures institutional money is moving the asset.
*   **Gate 3: Market Regime (BTC Health)**: Unless the ticker is BTC itself, the bot refuses to buy altcoins if Bitcoin is in a downtrend. BTC must be trading above its 50-period Exponential Moving Average (EMA-50).
*   **Basic TA Check**: The asset must not be heavily overbought (RSI must be `< 70`) and must be in a local uptrend (Price `>` EMA-50).
*   *If any gate fails, the trade is rejected and a specific reason is logged to the console.*

## 3. Smart Position & Capital Management
The bot acts responsibly with the user's portfolio balances.
*   **Reserve Fund**: Reads a `RESERVE_USDT` threshold from the `.env` file. The bot will *never* use this capital for trading, effectively locking in profits.
*   **Dynamic Position Sizing**: Instead of static order amounts, the bot calculates `(Available USDT - Reserve) * 0.98` to determine the total usable cash.
*   **Max Order Cap**: Limits exposure per trade via `MAX_ORDER_USDT` (e.g., max $1,000 per trade).
*   **Dust Prevention**: Silently aborts trades if the calculated size falls below Binance's $10 minimum order requirement.

## 4. Active Position Management (SELL Logic)
Once a position is open, the bot monitors it every 60 seconds and auto-executes a Market SELL if any of the following exit conditions are met:
*   **Take Profit (TP)**: The coin price increases by `+1.5%`.
*   **Stop Loss (SL)**: The coin price drops by `-1.0%`.
*   **Extreme Overbought**: The 15-minute RSI crosses above `85`.
*   **Sentiment Flip**: A new, highly negative news article breaks about the coin (AI Score `< -0.4`).
*   *Sells are linked to their parent buys in the database to calculate accurate P&L data.*

## 5. Live Dashboard (Next.js & Frontend)
A sleek, modern web UI provides a command center for the bot.
*   **Real-time Stats**: Displays Total Portfolio Balance, 24h P&L, Total Trades, and Signals Processed.
*   **Top Holdings**: Visually breaks down the user's current crypto allocations.
*   **Active Positions**: A dedicated table tracking currently open trades, their entry prices, sizes, and times.
*   **Trade History**: A historical ledger of completed buys and sells with P&L metrics.
*   **Live News Feed**: A scrolling feed of the latest scraped news alongside the AI's instant verdict (Bullish/Bearish, exact score, and ticker).

## 6. Comprehensive Telegram Integration
The bot acts as a personal pocket assistant, pushing critical updates directly to Telegram.
*   **News Broadcasts**: Sends a formatted alert for every analyzed news article, complete with emojis, the exact sentiment score, the AI's descriptive reasoning, and a link to the original source.
*   **Trade Execution Alerts**: When a BUY or SELL occurs, it sends an immediate receipt including the Ticker, execution Price, Order Size, Technical Indicators (RSI, Volume Spike), and the specific reason for the trade (e.g., "Reason: Take Profit (1.5%)").
*   **Milestone Celebrations**: The bot tracks the highest portfolio equity. When equity crosses major milestones (like $1,000, $5,000, $10,000), it sends a celebratory alert recommending the user update their `RESERVE_USDT` to lock in the new wealth. 
*   **Multi-Recipient Support**: Capable of broadcasting these updates to a set of authorized chat IDs.

## 7. Exchange Interoperability
*   **CCXT Driven**: Uses the standard CCXT library for exchange communication, currently configured for Binance.
*   **Testnet/Live Toggle**: Environment variables seamlessly switch the bot between Binance Testnet (paper trading) and the Mainnet (real money).
