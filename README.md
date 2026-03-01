<p align="center">
  <h1 align="center">🎯 GrokSniper AI</h1>
  <p align="center">
    <strong>Autonomous Algorithmic Trading System</strong><br/>
    <em>Multi-Agent AI Council · Real-Time Execution · Institutional-Grade Analytics</em>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/CrewAI-Multi--Agent-FF6F00?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Claude-Anthropic-7B61FF?style=for-the-badge" />
</p>

---

## Overview

**GrokSniper AI** is a fully autonomous algorithmic trading system driven by a **Multi-Agent AI Council** (CrewAI + Claude), high-speed **FastAPI WebSockets**, and a **Next.js real-time dashboard**. Designed to operate at institutional-grade standards, it combines advanced technical analysis, sentiment filtering, and machine-learning alpha generation to identify and execute high-conviction trades across crypto markets.

---

## Key Features

### 🧠 Multi-Agent AI Engine
A **"Board of Directors"** architecture consisting of specialized CrewAI agents:
- **Quant Strategist** — Deep technical analysis across multiple timeframes (1m/5m/15m/1h/4h), EMA crossovers, RSI momentum gating, and ATR-based volatility stops.
- **Risk Filter** — Real-time news sentiment analysis to veto trades during adverse market conditions.
- **Lead CIO** — Final decision authority that synthesizes all agent outputs into a unified trade/no-trade verdict.

### 🛡️ Cost-Optimized Architecture
A **Pure Python Pre-Filter Gate** evaluates market conditions before invoking LLM agents, blocking choppy or low-conviction setups to dramatically reduce API token costs while maintaining signal quality.

### ⚡ Real-Time Execution
- **WebSocket Streaming** for instant order fills, stop-loss updates, and trailing-stop activations.
- **Telegram Integration** for live trade alerts, portfolio summaries, and system health notifications.
- **Next.js Dashboard** with sub-second UI updates via persistent WebSocket connections.

### 📊 Advanced Analytics
- **Paper Trading Mode** — Full simulation with realistic fee modeling (0.1% taker).
- **Agent Decision Logging** — Complete audit trail of every AI agent's reasoning per trade.
- **Live Equity Curve** — Real-time P&L charting with Recharts.
- **ML Alpha Predictions** — TF-IDF + gradient-boosted model for news-driven hype trade detection.

### 📉 Short Selling Support
Bi-directional trading with inverted stop-loss and trailing-stop logic for both long and short positions.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Next.js Dashboard                     │
│           (Tailwind CSS · Recharts · WebSocket)          │
└──────────────────────┬───────────────────────────────────┘
                       │ WebSocket / REST
┌──────────────────────▼───────────────────────────────────┐
│                   FastAPI Backend                         │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ TA Scanner   │  │  Pre-Filter  │  │  WS Manager    │  │
│  │ (ccxt/TA)    │  │  (Python)    │  │  (Execution)   │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                │                   │           │
│  ┌──────▼────────────────▼───────────────────▼────────┐  │
│  │              CrewAI Agent Council                   │  │
│  │  Quant Strategist · Risk Filter · Lead CIO         │  │
│  │              (Claude / Anthropic)                   │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ ML Predictor │  │  Telegram    │  │  SQLAlchemy    │  │
│  │ (sklearn)    │  │  Notifier    │  │  (PostgreSQL)  │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer        | Technology                                               |
|:-------------|:---------------------------------------------------------|
| **Backend**  | Python 3.11+, FastAPI, Uvicorn, ccxt, SQLAlchemy         |
| **AI/ML**    | CrewAI, Anthropic Claude, scikit-learn, TF-IDF           |
| **Frontend** | Next.js 14, React 18, TypeScript, Tailwind CSS, Recharts |
| **Infra**    | Docker, PostgreSQL, WebSockets, Telegram Bot API         |
| **Exchange** | Binance (via ccxt) — extensible to any ccxt-supported CEX|

---

## Project Structure

```
sniper_bot/
├── backend/
│   ├── src/
│   │   ├── server.py          # FastAPI application & automation loop
│   │   ├── ws_manager.py      # WebSocket trade execution engine
│   │   ├── ta_scanner.py      # Multi-timeframe technical analysis
│   │   ├── ml_predictor.py    # ML alpha signal generator
│   │   ├── telegram_bot.py    # Notification service
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   └── crew/              # CrewAI agent definitions
│   ├── requirements.txt
│   └── venv/
├── frontend/
│   ├── app/                   # Next.js App Router pages
│   ├── components/            # React UI components
│   ├── package.json
│   └── tailwind.config.ts
├── database/
│   └── init.sql               # Schema initialization
├── docker-compose.yml
├── Dockerfile
├── .env.example               # Template for environment variables
└── README.md
```

---

## Getting Started

### Prerequisites

- **Python** ≥ 3.11
- **Node.js** ≥ 18
- **PostgreSQL** (or use the Docker Compose setup)
- API keys for: **Binance**, **Anthropic (Claude)**, **Telegram Bot**

### 1. Clone the Repository

```bash
git clone https://github.com/kotelyanets/GrokSniper.git
cd GrokSniper
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

### 3. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

### 4. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

### 5. Launch with Docker (Recommended)

```bash
docker-compose up --build
```

### 6. Launch Manually

```bash
# Terminal 1 — Backend
cd backend && uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
cd frontend && npm run dev
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables include:

| Variable               | Description                          |
|:-----------------------|:-------------------------------------|
| `BINANCE_API_KEY`      | Binance exchange API key             |
| `BINANCE_SECRET_KEY`   | Binance exchange secret              |
| `ANTHROPIC_API_KEY`    | Claude API key for CrewAI agents     |
| `TELEGRAM_BOT_TOKEN`   | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID`     | Target Telegram chat ID              |
| `DATABASE_URL`         | PostgreSQL connection string         |

---

## Disclaimer

> **⚠️ This software is for educational and research purposes only.** Algorithmic trading involves substantial risk of financial loss. Past performance does not guarantee future results. The authors assume no liability for any trading losses incurred through the use of this system. Always conduct your own due diligence and never trade with capital you cannot afford to lose.

---

## License

This project is proprietary software. All rights reserved.

---

<p align="center">
  <sub>Built with precision by the GrokSniper team.</sub>
</p>
