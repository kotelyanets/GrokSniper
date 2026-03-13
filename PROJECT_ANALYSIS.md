# GrokSniper AI — Project Analysis

## Overview

**GrokSniper AI** is a fully autonomous algorithmic cryptocurrency trading system combining multi-agent AI decision-making (CrewAI + Claude), real-time market sentiment analysis, advanced technical analysis, and institutional-grade risk management.

**Tech Stack**: Python 3.13 · FastAPI · CrewAI · Claude (Anthropic) · Groq · Next.js 16 · React 19 · PostgreSQL 15 · Redis · Docker · Telegram Bot

**Scale**: ~155 source files · ~19K lines of code (12.3K Python, 1.5K TypeScript, 5K tests)

---

## Architecture

```
┌─────────────────────────────────────┐
│    Next.js Frontend Dashboard       │
│  (Real-time WebSocket + Recharts)   │
└────────────────┬────────────────────┘
                 │ WebSocket / REST
┌────────────────▼────────────────────┐
│       FastAPI Backend (8000)        │
│  ┌──────────────────────────────┐   │
│  │ 24/7 Automation Loop (60s)   │   │
│  │ • RSS News Scraping          │   │
│  │ • Pre-Filter Gate (ADX/RSI)  │   │
│  │ • CrewAI Agent Council       │   │
│  │ • Execution Engine           │   │
│  └──────────────────────────────┘   │
└────────────────┬────────────────────┘
                 │
     ┌───────────┼───────────┐
     │           │           │
┌────▼──┐  ┌────▼──┐  ┌────▼──────┐
│Binance│  │Postgres│  │ Telegram  │
│ CCXT  │  │  DB    │  │   Bot     │
└───────┘  └───────┘  └───────────┘
```

### Key Modules

| Module | Path | Purpose |
|--------|------|---------|
| API Layer | `backend/src/api/` | FastAPI server, REST/WebSocket endpoints, automation loops |
| Core Engine | `backend/src/core/` | AI pipeline: OHLCV → sentiment → Claude decision |
| Services | `backend/src/services/` | Exchange, execution, news, sentiment, risk, Telegram (17 files) |
| CrewAI Agents | `backend/src/agents/` | Board of Directors, Strategist, Lead CIO, tools (10 files) |
| Database | `backend/src/db/` | Async SQLAlchemy ORM (NewsLog, Trade, PaperTrade, AgentDecisionLog) |
| ML/Backtesting | `backend/src/ml/`, `backend/src/backtesting/` | ML predictor, Monte Carlo, Pareto optimization |
| Frontend | `frontend/` | Next.js dashboard with live charts, analytics, trade history |

---

## Strengths

- ✅ **Async-first design** — proper asyncio/await patterns throughout
- ✅ **Environment-driven configuration** — no hardcoded secrets, `.env.example` provided
- ✅ **SQL injection safe** — SQLAlchemy ORM with parameterized queries
- ✅ **Good logging coverage** — 250+ structured logger calls
- ✅ **Type hints present** — Pydantic models, type annotations
- ✅ **Solid test suite** — 17 test files, 100+ tests with pytest-asyncio
- ✅ **Cost-optimized AI** — Pre-filter gate blocks 50-80% of unnecessary LLM invocations
- ✅ **Modular architecture** — clear separation of concerns

---

## Issues Found & Fixes Applied

### 🔴 Critical — Fixed

#### 1. Bare `except:` clauses (CWE-396: Catch Overly Broad Exceptions)
- **Files**: `core/agents/quant_analyst.py:62`, `core/agents/risk_guardian.py:54`
- **Risk**: Catches `SystemExit`, `KeyboardInterrupt` — can mask critical failures
- **Fix**: Changed to `except (json.JSONDecodeError, ValueError):`

#### 2. `subprocess.run(shell=True)` (CWE-78: OS Command Injection)
- **File**: `agents/project_tools.py:142`
- **Risk**: Shell injection if command string is manipulated; blocklist is insufficient
- **Fix**: Changed to `shlex.split(command)` with `shell=False`

#### 3. Weak authentication default (CWE-287: Improper Authentication)
- **File**: `services/telegram_listener.py:30-37`
- **Risk**: When `ALLOWED_TELEGRAM_ID` is not set, **any** Telegram user can control the bot
- **Fix**: Changed default to deny access when not configured, with a warning log

#### 4. Misleading mock sentiment data (CWE-1188: Insecure Default Initialization)
- **Files**: `services/ai_analyzer.py:29-34`, `services/grok_ai.py:33-37`
- **Risk**: Mock data returned bullish sentiment (0.85/92%) when API keys are missing — could trigger real trades on fake data
- **Fix**: Changed mock values to neutral (0.0 score, 0% confidence) with explicit "MOCK DATA" label

### 🟡 Medium — Recommendations

#### 5. No CI/CD pipeline
- **Status**: No `.github/workflows/` directory exists
- **Recommendation**: Add GitHub Actions workflow for automated testing, linting, and Docker builds on PR/push

#### 6. No backend linting configuration
- **Status**: No `ruff`, `black`, `flake8`, or `mypy` configured
- **Recommendation**: Add `ruff` with a `pyproject.toml` config for consistent code style

#### 7. WebSocket lacks authentication
- **File**: `api/routes.py:477` — `/ws/dashboard` accepts all connections
- **Recommendation**: Add token-based authentication before `websocket.accept()`

#### 8. No rate limiting on API endpoints
- **File**: `api/routes.py` — REST and WebSocket endpoints have no rate limiting
- **Recommendation**: Add `slowapi` middleware or custom rate limiter

#### 9. No timeouts on async LLM calls
- **Files**: `api/automation.py`, `services/telegram_listener.py`
- **Recommendation**: Wrap external API calls with `asyncio.wait_for()` to prevent indefinite blocking

### 🟢 Low — Nice to Have

#### 10. Broad `except Exception` handlers
- **Files**: Multiple (automation.py, telegram_listener.py, telegram_bot.py)
- **Recommendation**: Catch specific exceptions (ConnectionError, TimeoutError, etc.)

#### 11. Missing API documentation
- **Status**: FastAPI auto-docs at `/docs` but no custom descriptions
- **Recommendation**: Add Pydantic model descriptions and endpoint docstrings

#### 12. Filename typo
- **File**: `PROJECT_OVERIVIEW2.md` — should be `PROJECT_OVERVIEW2.md`

---

## Testing

| Component | Status | Details |
|-----------|--------|---------|
| Test framework | ✅ | pytest + pytest-asyncio |
| Test files | ✅ | 17 files (~5K lines) |
| Async support | ✅ | `asyncio_mode = auto` in pytest.ini |
| Mocks | ✅ | Mock exchange, DB session, Anthropic responses |
| CI/CD | ❌ | No automated test runs |

### Run tests
```bash
pytest backend/tests/ -v
```

---

## Security Summary

| Check | Status |
|-------|--------|
| Hardcoded secrets | ✅ None found |
| SQL injection | ✅ ORM-based (safe) |
| Command injection | ✅ Fixed (`shell=False`) |
| Authentication | ✅ Fixed (deny-by-default) |
| Bare exceptions | ✅ Fixed (specific types) |
| Mock data bias | ✅ Fixed (neutral values) |
| HTTPS enforcement | ⚠️ HTTP default in dev |
| WebSocket auth | ⚠️ Not implemented |
| Rate limiting | ⚠️ Not implemented |
| Input validation | ⚠️ Minimal |

---

## Dependency Summary

### Backend (29 packages)
- **Core**: FastAPI 0.115.8, SQLAlchemy 2.0.38, asyncpg 0.30.0
- **Trading**: CCXT 4.4.24, pandas_ta 0.3.14b
- **AI/ML**: CrewAI 0.80.0, transformers 4.40.0, torch 2.2.0, scikit-learn 1.6.1
- **NLP**: langchain-groq 0.2.0, feedparser 6.0.11
- **Infra**: Uvicorn 0.34.0, httpx 0.28.1, python-telegram-bot 21.0

### Frontend (Next.js 16 + React 19)
- **Viz**: Recharts 3.7.0, lightweight-charts 5.1.0, Three.js
- **UI**: Tailwind CSS 4, Framer Motion 12.35.0, Lucide icons

---

*Analysis performed: March 2026*
