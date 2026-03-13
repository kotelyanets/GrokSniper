<div align="center">

# 🎯 GrokSniper AI

### Autonomous Crypto Trading System Powered by Multi-Agent AI

*Real-Time Execution · Institutional-Grade Analytics · 24/7 Autonomous Operation*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)

[![CrewAI](https://img.shields.io/badge/CrewAI-Multi--Agent-FF6F00?style=for-the-badge)](https://crewai.com)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-7B61FF?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com)
[![Binance](https://img.shields.io/badge/Binance-CCXT-F0B90B?style=for-the-badge&logo=binance&logoColor=black)](https://binance.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot_API-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://telegram.org)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge)](LICENSE)

<br/>

**GrokSniper AI** is a fully autonomous algorithmic trading system that combines a **Multi-Agent AI Council** (CrewAI + Claude), high-speed **FastAPI WebSockets**, and a **Next.js real-time dashboard** to identify and execute high-conviction trades across crypto markets.

<br/>

[Getting Started](#-getting-started) · [Features](#-key-features) · [Architecture](#-architecture) · [API Reference](#-api-reference) · [Deployment](#-deployment)

</div>

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [Environment Variables](#%EF%B8%8F-environment-variables)
- [API Reference](#-api-reference)
- [Testing](#-testing)
- [Deployment](#%EF%B8%8F-deployment)
- [Disclaimer](#%EF%B8%8F-disclaimer)
- [License](#-license)

---

## ✨ Key Features

### 🧠 Multi-Agent AI Council — "Board of Directors"

A sophisticated multi-agent architecture where specialized CrewAI agents collaborate to make trading decisions:

| Agent | Role | Capabilities |
|:------|:-----|:-------------|
| **Quant Strategist** | Technical Analyst | Multi-timeframe analysis (1m/5m/15m/1h/4h), EMA crossovers, RSI momentum gating, ATR-based volatility stops, order book imbalance detection |
| **Risk Guardian** | Risk Filter | Real-time news sentiment evaluation, position safety assessment, adverse condition veto power |
| **Lead CIO** | Final Authority | Synthesizes all agent outputs into a unified LONG/SHORT/HOLD verdict with strict deterministic reasoning (temperature: 0.1) |

### 🛡️ Cost-Optimized Signal Pipeline

A **Pure Python Pre-Filter Gate** evaluates market conditions *before* invoking expensive LLM agents, blocking choppy or low-conviction setups to dramatically reduce API token costs while maintaining signal quality.

### ⚡ Real-Time Execution Engine

- **Sniper Limit Orders** — Places limit orders at maker fee (0%), with automatic fallback to market orders after 15 seconds if unfilled
- **WebSocket Streaming** — Sub-second order fills, stop-loss updates, and trailing-stop activations
- **Bi-directional Trading** — Full long and short position support with inverted stop-loss logic

### 📊 Live Dashboard & Analytics

- **Real-Time Stats** — Portfolio balance, 24h P&L, win rate, AI efficiency score
- **Live Price Charts** — Recharts + TradingView Lightweight Charts with entry/exit markers
- **Equity Curve** — Portfolio performance over time with drawdown visualization
- **Agent Decision Log** — Complete audit trail of every AI agent's reasoning per trade
- **Trade History** — Paginated, filterable, sortable trade ledger with P&L metrics

### 🤖 Telegram Integration

- **Trade Alerts** — Instant buy/sell notifications with ticker, price, RSI, volume spike, and reason
- **Portfolio Summaries** — Automated 4-hour equity snapshots
- **News Broadcasts** — Analyzed articles with sentiment scores and source links
- **Milestone Celebrations** — Alerts when equity crosses major thresholds ($1K, $5K, $10K)
- **Command Processing** — Control the bot directly from Telegram

### 🔬 Machine Learning & Backtesting

- **ML Alpha Predictions** — TF-IDF + gradient-boosted model for news-driven hype trade detection
- **Walk-Forward Optimization** — Out-of-sample parameter validation
- **Monte Carlo Simulation** — Risk-adjusted return projections
- **Pareto Optimizer** — Multi-objective strategy tuning

### 🔒 Risk Management

- **Reserve Fund Protection** — Configurable capital lockout to protect profits
- **Dynamic Position Sizing** — Kelly Criterion-based allocation with max order caps
- **3-Stage Confluence Gate** — Sentiment ≥ 0.5, volume anomaly ≥ 1.5x SMA, BTC regime health check
- **Multi-Exit Strategy** — Take profit, stop loss, RSI overbought, and sentiment flip triggers
- **Kill Switch** — Emergency stop button accessible from dashboard and Telegram

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Next.js Dashboard                             │
│            React 19 · Tailwind CSS · Recharts · WebSocket           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │Dashboard │ │ Trades   │ │ Analysis │ │Analytics │ │ Settings │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└────────────────────────┬────────────────────────────────────────────┘
                         │ WebSocket + REST API
┌────────────────────────▼────────────────────────────────────────────┐
│                       FastAPI Backend                                │
│                                                                     │
│  ┌─ Signal Pipeline ──────────────────────────────────────────────┐ │
│  │                                                                │ │
│  │  RSS Scraper ──▶ Grok AI + FinBERT ──▶ Pre-Filter Gate        │ │
│  │                     (Sentiment)          (Cost Optimizer)      │ │
│  │                                               │                │ │
│  │                                               ▼                │ │
│  │                                    ┌─────────────────┐         │ │
│  │                                    │  CrewAI Council  │         │ │
│  │                                    │  ┌─────────────┐ │         │ │
│  │                                    │  │   Quant      │ │         │ │
│  │                                    │  │  Strategist  │ │         │ │
│  │                                    │  ├─────────────┤ │         │ │
│  │                                    │  │    Risk      │ │         │ │
│  │                                    │  │  Guardian    │ │         │ │
│  │                                    │  ├─────────────┤ │         │ │
│  │                                    │  │  Lead CIO   │ │         │ │
│  │                                    │  │  (Decision)  │ │         │ │
│  │                                    │  └─────────────┘ │         │ │
│  │                                    └────────┬────────┘         │ │
│  │                                             │                  │ │
│  └─────────────────────────────────────────────┼──────────────────┘ │
│                                                ▼                    │
│  ┌─ Execution Layer ─────────────────────────────────────────────┐  │
│  │  Execution Engine ──▶ CCXT (Binance) ──▶ WebSocket Manager   │  │
│  │       │                                        │              │  │
│  │       ▼                                        ▼              │  │
│  │  Risk Manager ◀──── Position Monitoring ──── Trailing Stop   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  │
│  │ ML Predictor │  │  Telegram    │  │  Redis   │  │ PostgreSQL │  │
│  │ (scikit-learn)│  │  Notifier    │  │  Cache   │  │ (SQLAlchemy)│  │
│  └─────────────┘  └──────────────┘  └──────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🛠 Tech Stack

| Layer | Technology | Details |
|:------|:-----------|:--------|
| **Backend** | Python 3.11+, FastAPI, Uvicorn | Async API server with background automation loops |
| **AI Agents** | CrewAI, Anthropic Claude, Groq Llama | Multi-agent orchestration with deterministic reasoning |
| **Sentiment** | xAI Grok API, FinBERT (HuggingFace) | Dual-source sentiment analysis (cloud + local) |
| **ML** | scikit-learn, TF-IDF, pandas | Alpha signal prediction and feature engineering |
| **Frontend** | Next.js 16, React 19, TypeScript | App Router with real-time WebSocket integration |
| **Styling** | Tailwind CSS 4, Framer Motion | Cyberpunk-themed dark UI with ambient effects |
| **Charts** | Recharts, TradingView Lightweight Charts | Real-time price action and portfolio visualization |
| **Database** | PostgreSQL 15, SQLAlchemy (async) | Persistent storage for trades, news, and agent decisions |
| **Cache** | Redis 7 | High-speed caching layer |
| **Exchange** | Binance via CCXT | Extensible to any CCXT-supported exchange |
| **Notifications** | Telegram Bot API | Real-time alerts, summaries, and command processing |
| **Infrastructure** | Docker Compose | Multi-container orchestration with health checks |

---

## 📁 Project Structure

```
GrokSniper/
│
├── backend/
│   ├── src/
│   │   ├── main.py                    # Application entry point
│   │   ├── config.py                  # Global configuration
│   │   │
│   │   ├── api/                       # FastAPI layer
│   │   │   ├── server.py              #   App bootstrap, CORS, lifespan
│   │   │   ├── routes.py              #   REST & WebSocket endpoints
│   │   │   ├── automation.py          #   24/7 background trading loops
│   │   │   ├── sizing.py              #   Position sizing (Kelly Criterion)
│   │   │   └── state.py               #   Shared bot state management
│   │   │
│   │   ├── agents/                    # CrewAI multi-agent system
│   │   │   ├── board_of_directors.py  #   Agent council orchestration
│   │   │   ├── strategist.py          #   Quant Strategist agent
│   │   │   ├── lead_cio.py            #   Lead CIO agent
│   │   │   ├── fundamental.py         #   Fundamental analysis agent
│   │   │   ├── trading_tools.py       #   Agent trading tools
│   │   │   └── data_tools.py          #   Agent data tools
│   │   │
│   │   ├── services/                  # Core business logic
│   │   │   ├── exchange.py            #   CCXT Binance integration
│   │   │   ├── execution_engine.py    #   Smart limit → market fallback
│   │   │   ├── crew_analyzer.py       #   CrewAI orchestration
│   │   │   ├── ws_manager.py          #   WebSocket trade execution
│   │   │   ├── rss_scraper.py         #   News feed scraping
│   │   │   ├── grok_ai.py             #   xAI Grok sentiment
│   │   │   ├── finbert_analyzer.py    #   Local FinBERT model
│   │   │   ├── market_sentiment.py    #   Sentiment aggregation
│   │   │   ├── risk_manager.py        #   Position & risk controls
│   │   │   ├── mtf_filter.py          #   Multi-timeframe analysis
│   │   │   ├── pre_filter.py          #   Cost-optimized Python gate
│   │   │   ├── regime_detector.py     #   Market regime detection
│   │   │   ├── telegram_bot.py        #   Telegram notifications
│   │   │   ├── telegram_listener.py   #   Telegram command processing
│   │   │   ├── shadow_logger.py       #   L2 order book tracking
│   │   │   ├── memory_manager.py      #   Agent memory & context
│   │   │   └── visuals.py             #   Chart/graph generation
│   │   │
│   │   ├── db/                        # Database layer
│   │   │   ├── database.py            #   SQLAlchemy async engine
│   │   │   └── models.py             #   ORM models (Trade, NewsLog, etc.)
│   │   │
│   │   ├── ml/                        # Machine learning
│   │   │   ├── model.py               #   Model training pipeline
│   │   │   └── predictor.py           #   Prediction inference
│   │   │
│   │   ├── backtesting/               # Strategy validation
│   │   │   ├── walk_forward.py        #   Walk-forward optimization
│   │   │   ├── monte_carlo.py         #   Monte Carlo simulation
│   │   │   └── pareto_optimizer.py    #   Multi-objective optimizer
│   │   │
│   │   ├── core/                      # Core engine
│   │   │   └── engine.py              #   Trading signal engine
│   │   │
│   │   └── scripts/                   # Utilities
│   │       ├── auto_optimizer.py      #   Automated strategy tuning
│   │       ├── backtester.py          #   Manual backtesting
│   │       ├── micro_backtester.py    #   Micro-strategy backtesting
│   │       ├── ml_bootcamp.py         #   ML model training
│   │       └── stress_test.py         #   System stress testing
│   │
│   ├── tests/                         # pytest test suite (18 test files)
│   └── requirements.txt
│
├── frontend/
│   ├── app/                           # Next.js App Router
│   │   ├── layout.tsx                 #   Root layout (sidebar, nav)
│   │   ├── page.tsx                   #   Dashboard home
│   │   ├── trades/page.tsx            #   Trade history
│   │   ├── analysis/page.tsx          #   AI analysis & reasoning
│   │   ├── analytics/page.tsx         #   Portfolio analytics
│   │   └── settings/page.tsx          #   Bot configuration
│   │
│   ├── components/
│   │   ├── LiveChart.tsx              #   Real-time price chart
│   │   ├── PortfolioChart.tsx         #   Equity curve
│   │   ├── WinRateChart.tsx           #   Win/loss statistics
│   │   ├── KillSwitchButton.tsx       #   Emergency stop control
│   │   └── NavLinks.tsx               #   Sidebar navigation
│   │
│   └── package.json
│
├── database/
│   └── init.sql                       # PostgreSQL schema
│
├── scripts/
│   ├── migrate_to_live.py             # Testnet → live migration
│   └── setup_vps.sh                   # VPS setup script
│
├── docker-compose.yml                 # Multi-container orchestration
├── Dockerfile                         # Backend container image
├── .env.example                       # Environment variable template
├── README_DEPLOY.md                   # Cloud deployment guide
├── PROJECT_OVERVIEW.md                # Detailed feature documentation
└── LICENSE                            # Proprietary license
```

---

## 🚀 Getting Started

### Prerequisites

| Requirement | Version | Purpose |
|:------------|:--------|:--------|
| **Python** | ≥ 3.11 | Backend runtime |
| **Node.js** | ≥ 18 | Frontend build |
| **Docker** *(recommended)* | Latest | Containerized deployment |
| **PostgreSQL** | ≥ 15 | Database (or use Docker) |

**Required API Keys:**

| Service | Purpose | Get it at |
|:--------|:--------|:----------|
| Binance | Exchange trading | [binance.com](https://www.binance.com) |
| Anthropic (Claude) | AI trading agents | [console.anthropic.com](https://console.anthropic.com) |
| Telegram Bot | Notifications & control | [@BotFather](https://t.me/BotFather) |
| xAI Grok *(optional)* | News sentiment analysis | [x.ai](https://x.ai) |
| Groq *(optional)* | Free-tier LLM fallback | [console.groq.com](https://console.groq.com) |

### Option A: Docker Quick Start (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/kotelyanets/GrokSniper.git
cd GrokSniper

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Environment Variables section)

# 3. Launch all services
docker compose up -d --build

# 4. Verify services are running
docker compose ps

# 5. Access the dashboard
#    → http://localhost:3000
#    → API: http://localhost:8000/api/health
```

### Option B: Manual Setup

<details>
<summary><strong>Click to expand manual setup instructions</strong></summary>

#### 1. Clone & Configure

```bash
git clone https://github.com/kotelyanets/GrokSniper.git
cd GrokSniper
cp .env.example .env
# Edit .env with your API keys
```

#### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

#### 3. Frontend

```bash
cd frontend
npm install
cd ..
```

#### 4. Database

Ensure PostgreSQL is running and create the database:

```bash
psql -U postgres -c "CREATE DATABASE groksniper;"
psql -U postgres -d groksniper -f database/init.sql
```

#### 5. Launch

```bash
# Terminal 1 — Backend
cd backend
source venv/bin/activate
uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend
npm run dev
```

The dashboard will be available at `http://localhost:3000` and the API at `http://localhost:8000`.

</details>

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and configure the following variables:

<details>
<summary><strong>Click to expand full environment variable reference</strong></summary>

| Variable | Description | Default |
|:---------|:------------|:--------|
| **Database** | | |
| `POSTGRES_DB` | PostgreSQL database name | `groksniper` |
| `POSTGRES_USER` | PostgreSQL username | `groksniper_user` |
| `POSTGRES_PASSWORD` | PostgreSQL password | — |
| `DATABASE_URL` | Full connection string | `postgresql+asyncpg://...` |
| **Redis** | | |
| `REDIS_PASSWORD` | Redis auth password | — |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| **Exchange** | | |
| `BINANCE_API_KEY` | Binance API key | — |
| `BINANCE_API_SECRET` | Binance API secret | — |
| `BINANCE_TESTNET` | Use Binance testnet | `True` |
| `BYBIT_API_KEY` | Bybit API key *(optional)* | — |
| `BYBIT_API_SECRET` | Bybit API secret *(optional)* | — |
| **AI Services** | | |
| `ANTHROPIC_API_KEY` | Claude API key for CrewAI | — |
| `CLAUDE_MODEL` | Claude model identifier | `claude-sonnet-4-20250514` |
| `GROK_API_KEY` | xAI Grok API key | — |
| `GROQ_API_KEY` | Groq free-tier key *(optional)* | — |
| **Telegram** | | |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | — |
| `TELEGRAM_CHAT_ID` | Target chat ID | — |
| `ALLOWED_TELEGRAM_ID` | Authorized user ID | — |
| **Trading** | | |
| `PAPER_TRADE` | Enable paper trading mode | `True` |
| `DRY_RUN` | Dry run (no real orders) | `True` |
| `WATCHLIST` | Comma-separated tickers | `BTC,ETH,SOL,DOGE,XRP` |
| `SCAN_INTERVAL` | Scan interval in seconds | `900` |
| `INITIAL_EQUITY` | Starting equity for paper trading | `1000` |
| **App** | | |
| `APP_ENV` | Environment | `development` |
| `LOG_LEVEL` | Logging level | `INFO` |

</details>

---

## 📡 API Reference

### REST Endpoints

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/bot-status` | Current bot status and mode |
| `GET` | `/api/stats` | Portfolio stats, holdings, P&L |
| `GET` | `/api/trades` | Trade history |
| `GET` | `/api/trades/{id}/reasoning` | AI reasoning for a specific trade |
| `GET` | `/api/news` | Latest news with sentiment scores |
| `GET` | `/api/analytics` | Portfolio analytics & performance |
| `POST` | `/api/trigger` | Trigger manual analysis scan |
| `POST` | `/api/buy` | Execute manual buy order |
| `POST` | `/api/sell` | Execute manual sell order |
| `POST` | `/api/trades/{id}/close` | Close a specific position |
| `POST` | `/api/reset-paper-test` | Reset paper trading data |

### WebSocket Endpoints

| Endpoint | Description |
|:---------|:------------|
| `ws://localhost:8000/ws/dashboard` | Real-time dashboard updates (stats, positions, news) |

---

## 🧪 Testing

The project includes a comprehensive test suite with **18 test modules** covering all critical components:

```bash
# Run the full test suite
pytest backend/tests/ -v

# Run specific test modules
pytest backend/tests/test_exchange.py -v       # Exchange integration
pytest backend/tests/test_risk_manager.py -v   # Risk management
pytest backend/tests/test_engine.py -v         # Trading engine
pytest backend/tests/test_api.py -v            # API endpoints
pytest backend/tests/test_sizing.py -v         # Position sizing
```

Test modules include:
- `test_api.py` — API endpoint validation
- `test_engine.py` / `test_engine_cycle.py` — Trading engine logic
- `test_exchange.py` — Exchange connectivity
- `test_risk_manager.py` — Risk controls and limits
- `test_sizing.py` — Position sizing calculations
- `test_pnl_math.py` — P&L computation accuracy
- `test_ws_manager.py` — WebSocket manager
- `test_rss_scraper.py` — News scraping
- `test_analytics.py` — Analytics calculations
- `test_telegram_tools.py` — Telegram integration
- `test_memory_manager.py` — Agent memory system
- `test_quant_analyst.py` / `test_risk_guardian.py` — AI agent behavior

---

## ☁️ Deployment

For production deployment on a Linux VPS, see the full **[Cloud Deployment Guide](README_DEPLOY.md)**.

**Quick overview:**

```bash
# On your VPS (Ubuntu 22.04+)
curl -fsSL https://get.docker.com | sh
systemctl enable docker

git clone https://github.com/kotelyanets/GrokSniper.git
cd GrokSniper
cp .env.example .env
nano .env   # Configure API keys & set DATABASE_URL to use 'postgres' hostname

docker compose up -d --build
docker compose logs -f sniper-bot   # Watch live logs
```

| Command | Description |
|:--------|:------------|
| `docker compose ps` | Check service status |
| `docker compose logs -f sniper-bot` | Stream bot logs |
| `docker compose restart sniper-bot` | Restart the bot |
| `docker compose down` | Stop all services |
| `docker compose up -d --build` | Rebuild after code changes |

> The `restart: unless-stopped` policy ensures automatic recovery after server reboots.

---

## ⚠️ Disclaimer

> **This software is for educational and research purposes only.**
>
> Algorithmic trading involves substantial risk of financial loss. Past performance does not guarantee future results. The authors assume no liability for any trading losses incurred through the use of this system.
>
> - Always conduct your own due diligence before using any trading system.
> - Never trade with capital you cannot afford to lose.
> - Start with **paper trading mode** (`PAPER_TRADE=True`) to validate strategies before risking real capital.
> - Use **Binance Testnet** (`BINANCE_TESTNET=True`) for initial testing.

---

## 📄 License

This project is **proprietary software**. All rights reserved.

You may download and view the source code for **personal, educational, and non-commercial purposes only**. Modification, distribution, commercial use, and deployment as a service are expressly prohibited without written consent.

See [LICENSE](LICENSE) for the full terms.

---

<div align="center">

<br/>

**Built with precision by [Andrii Kotelyanets](https://github.com/kotelyanets)**

*GrokSniper AI — Where AI meets the markets* 🎯

<br/>

<sub>© 2026 Andrii Kotelyanets. All rights reserved.</sub>

</div>
