# GrokSniper AI – Full System Overview (v2)

This document supersedes `PROJECT_OVERVIEW.md` and provides a **complete, up‑to‑date analysis of the
entire codebase**.  The goal is to give new contributors (or yourself in six months) a single reference
that explains how the trading bot actually works from the ground up.

> ⚠️  The original overview focused heavily on the early MVP.  The project has
> since evolved into a full‑stack platform with machine learning, real‑time
> websockets, backtesting utilities, and a polished React/Next.js dashboard.  All
> of that is covered here.

---

## 1. High‑level architecture

| Layer | Technologies | Responsibilities |
|-------|--------------|------------------|
| **Client** | Next.js (app router, TypeScript, Tailwind CSS) | Dashboard UI, user settings, live charts, historical tables, manual triggers |
| **API/Engine** | FastAPI, asyncio, SQLAlchemy‑async | 24/7 automation loop, REST endpoints, background tasks, DB access, exchange
| **Core services** | custom Python modules | RSS scraping, AI/ML analysis, CCXT exchange wrapper, Telegram, WebSocket
| **Database** | PostgreSQL / SQLite (SQLAlchemy models) | Persist news logs, trades, ML data |
| **ML & Scripts** | scikit‑learn, pandas, custom scripts | Data gathering, model training, hyperparameter search, backtester |

Everything lives under `backend/src` with clear package separation; the frontend
is in `frontend/`.  Environment variables in `.env` control behaviour (testnet vs
the real Binance, API keys, risk parameters, etc.).

---

## 2. Backend

### 2.1. Entry point & startup

* `backend/src/main.py` loads `.env`, configures logging and starts Uvicorn.
* `server.app` (FastAPI) defines a **lifespan handler** that ensures the DB tables
  are created and also spawns two long‑running background tasks:
  * `monitor_open_positions_ws` – real‑time WebSocket supervisor (see §2.5).
  * `_automation_loop` – the core 60‑second cycle that handles news + TA scans.

### 2.2. Database

Schema defined in `db/models.py`:

* **NewsLog** – raw text from RSS/twitter/manual sources plus ticker,
  sentiment score/confidence, timestamps. Used for ML training, UI history, and
  audit trails.
* **Trade** – every BUY/SELL attempt, including parent‑child links so sells are
  connected to their originating buys. Contains state flags (`is_closed`),
  `highest_price` (updated by the WS manager), and status codes.

The async engine and session factory live in `db/database.py` with a convenient
`get_session()` context manager.

### 2.3. Services

* **rss_scraper.py** – iterates a hard‑coded list of crypto RSS feeds, dedups
  URLs, strips HTML, and returns the first unprocessed article.
* **ai_analyzer.py / grok_ai.py** – two slightly different wrappers around the
  xAI/Grok API.  Both send the news text and require a strict JSON‑only response
  containing `ticker`, `sentiment_score` (‑1…1) and `confidence` (0‑100).  They
  both fall back to mock data if the key is missing or calls fail.
* **exchange.py** – CCXT wrapper for Binance (testnet/live toggle).
  Fundamental features:
  - Market orders (BUY/SELL) with dry‑run mode if API keys are absent.
  - Balance and price fetching.
  - Technical indicator calculations (EMA20/50, RSI, MACD, volume SMA) using
    pandas‑ta.  Also `get_top_tickers()` and `is_btc_healthy()` helper methods.
* **telegram_bot.py** – sends Markdown messages to one or more chat IDs.
* **ws_manager.py** – heartbeat of Phase‑24 architecture.  Spawns one asyncio
  task per open BUY trade that listens to Binance’s public trade stream and
  evaluates exit conditions in milliseconds.  When a rule fires the watcher
  executes a market sell, updates the DB, and notifies Telegram.
  A supervisor periodically (every 5 s) queries the DB for new positions and
  cancels watchers on shutdown.

### 2.4. Machine learning

Stable extra layer that “calibrates” raw Grok sentiment with historical data.

* **ml/bootcamp.py** – crawl CryptoCompare news, match each article to the
  subsequent 1‑hour return via the Binance public klines, and dump labelled
  rows into `news_logs`.  Includes a lightweight heuristic ticker extractor.
  This allows training without any LLM at network‑rate speed.
* **ml/model.py** – pulls tagged rows from `news_logs`, vectorises the text
  with TF‑IDF, and fits a `RandomForestRegressor` which predicts a 1‑h return.
  The model bundle (vectoriser + forest) is saved to `ml/saved_model.pkl`.
* **ml/predictor.py** – loads the bundle and converts a predicted return into a
  score in ‑1…1, optionally blending with the original Grok score
  (ML_WEIGHT=0.7, GROQ_WEIGHT=0.3).  This function is called in the automation
  loop (see §2.6) when processing new news.

### 2.5. Automation loop

Implemented in `server.py`:

1. **Parallel execution** – each cycle kicks off `scan_charts_for_opportunities`
   (see §2.6) as a background task and immediately polls RSS for fresh news.
2. **News handling**
   * Sentiment analysis via Grok/ML.
   * Persist log to database.
   * Telegram alert (formatted with score, confidence, emoji and AI `reason`).
   * **Confluence gate**:
     1.  Calibrated sentiment ≥ 0.5 with confidence ≥ 80. (Gate 1)
     2.  Volume anomaly – current 15‑min volume > 1.5× 20‑period SMA. (Gate 2)
     3.  Market regime – BTC must be healthy via `is_btc_healthy()`, or ticker is
         BTC. (Gate 3)
     4.  Coin must be in top‑20 by 24 h volume.
     5.  Basic TA check: RSI < 70 and price > EMA‑50.
   * If all gates pass, compute dynamic position sizing (reserve, 0.98 buffer,
     `MAX_ORDER_USDT` cap, dust check), place BUY order via exchange, log trade,
     and send Telegram BUY notification.
3. **TA scanner** (executed concurrently) – 1 h timeframe “elite confluence”
   algorithm that looks for bullish EMA alignment, MACD crossover, neutral
   RSI (40‑65), bullish candle body, and volume spike.  On a signal it
   calculates a position size and places a BUY order, identical to the
   news‑driven flow but without the AI gates.  This routine is also used by
   the standalone backtester script.
4. **Milestone tracking** – after each cycle the loop fetches current equity
   from the exchange, updates the all‑time high and, if a new milestone is
   crossed (`$500, $1 000, $2 500, …`), sends a celebratory Telegram message
   recommending the user bump up `RESERVE_USDT`.
5. **Error handling & state** – the `bot_state` dict is updated regularly and
   exposed via a REST endpoint for the dashboard (see §2.7).  Failures in any
   sub‑task are logged but do not halt the loop.

**Manual trigger**: `/api/trigger` lets the frontend press a “Test Bot” button
that runs one RSS scan and returns how many new items were found.

### 2.6. Position management

Earlier versions polled open trades every 60 s and evaluated exit conditions; by
Phase 24 this work moved into `ws_manager.py` which uses Binance’s trade
websocket to watch price ticks in real time.  The rules are:

1. Hard stop‑loss – 3 % below entry.
2. Fixed take‑profit – +10 %.
3. Delayed trailing – activates after +4 % and trails 1.5 % behind the peak.

When any condition is hit the watcher executes a market SELL, updates the
parent BUY row (`is_closed=True`, copy of the sell with `parent_id`), and
sends a detailed Telegram alert (entry, exit, peak, P&L).  The supervisor
ensures a watcher exists for each open trade and cleans them up when positions
close or the app shuts down.  The old 60‑second polling logic still exists but
is now essentially dormant.

### 2.7. REST API

`server.py` exposes the following endpoints used by the frontend (and manual
tools):

* `/api/news` – list recent `NewsLog` entries.
* `/api/trades` – list recent trades (BUY & SELL).
* `/api/bot-state` – returns current `bot_state` for dashboard status card.
* `/api/trigger` – force an RSS scan (see above).

CORS is enabled to allow the Next.js client to talk to the FastAPI server.
Additional internal endpoints support the automation loop but are not documented
here (they are defined inline in the Python source).

### 2.8. Utility scripts

* `backend/src/scripts/backtester.py` – reusable golden‑strategy backtester with
  grid‑search support.  Used offline to tune exit parameters or to stress‑test
  the 1‑h TA scanner.
* `backend/src/scripts/ml_bootcamp.py` – see §2.4.
* `clean_junk.py` and `fix_db.py` are superficial helpers for the repo, not core
  trading logic.

---

## 3. Frontend

The dashboard is built with Next.js (app router) and Tailwind CSS.  Key features:

* **Home page (`/`)** – live portfolio stats, AI engine status card, latest news
  feed, quick “Test Bot” button, and an embedded `LiveChart` component powered by
  TradingView (see `components/LiveChart.tsx`).
* **Analysis page** – paginated list of `NewsLog` entries with sentiment badges
  and confidence bars; supports filtering and manual refresh.
* **Trades page** – historical table of all trades, counts of buys/sells, ability
  to adjust page size and load more.
* **Settings page** – UI form for API keys, risk parameters, dry‑run toggle (UI
  only; values are not persisted anywhere), and other controls.
* **Global layout** – top navigation, dark theme, responsive design.  Components
  like `StatCard`, `SentimentBadge`, and `BotStatusCard` are reused across pages.

The client polls the API every 10‑15 seconds for fresh data and shows loading
skeletons to keep the UI feeling responsive.  There’s also client‑side
pagination and simple state management via React hooks.

---

## 4. Configuration & deployment

* `.env` file in project root contains all adjustable parameters:
  `DATABASE_URL`, `BINANCE_*` keys, `GROK_API_KEY`, `RESERVE_USDT`, `MAX_ORDER_USDT`,
  `TELEGRAM_*`, `APP_ENV`, etc.
* `docker-compose.yml` exists to spin up Postgres + FastAPI + Next.js if
  containerisation is desired (not used for development by default).
* `backend/requirements.txt` lists all Python dependencies; the frontend uses
  `package.json` with Next.js 14+ and Tailwind 3.

---

## 5. Development notes

* The entire system can run in dry‑run mode without any API keys; exchange
  calls return mock prices, and the Telegram service logs warnings instead of
  sending messages.
* Logging is heavily used for diagnostics; enable `LOG_LEVEL=DEBUG` to trace
  internal state.
* ML training and bootcamp are **optional** – the bot functions with raw Grok
  scores alone but benefits from calibrated sentiment once enough data has
  been collected and a model trained.
* Unit tests are not provided, but the modular design makes individual
  components easy to invoke from a REPL or a Jupyter notebook.

---

## 6. Summary

GrokSniper AI has grown from a simple news‑driven buy‑signal bot into a full‑blown
trading platform.  It now combines:

* **Real‑time news scraping & AI analysis**
* **Technical analysis scanners (news‑gated and pure TA)**
* **Machine learning calibration & bootcamp data pipeline**
* **24/7 automation loop with milestone alerts**
* **Enterprise‑grade position management via websockets**
* **Polished Next.js dashboard for visibility & manual control**
* **Extensible folder structure and helper scripts for research/backtesting**

Refer back to this file when exploring the repository – it’s the single
location that explains **what every major module does and how they fit
together**.

Happy hacking!
