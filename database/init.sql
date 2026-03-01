-- =============================================================================
-- GrokSniper AI — Database Initialisation Script
-- Executed automatically on first PostgreSQL container start-up.
-- =============================================================================

-- Enable the pgcrypto extension so we can generate UUID v4 values server-side.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- Table: news_logs
-- Stores raw news articles/tweets together with Grok AI sentiment analysis.
-- =============================================================================
CREATE TABLE IF NOT EXISTS news_logs (
    id              UUID            DEFAULT gen_random_uuid() PRIMARY KEY,
    source          VARCHAR(100)    NOT NULL,                          -- e.g. "twitter", "reuters", "coindesk"
    raw_text        TEXT            NOT NULL,                          -- original article / post body
    ticker          VARCHAR(20),                                       -- extracted ticker symbol, e.g. "BTC"
    sentiment_score NUMERIC(4, 3)   CHECK (sentiment_score BETWEEN -1.0 AND 1.0),
    confidence      SMALLINT        CHECK (confidence BETWEEN 0 AND 100),
    micro_features  TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Index for fast look-ups by ticker and time range
CREATE INDEX IF NOT EXISTS idx_news_logs_ticker      ON news_logs (ticker);
CREATE INDEX IF NOT EXISTS idx_news_logs_created_at  ON news_logs (created_at DESC);

-- =============================================================================
-- Table: trades
-- Records every trade order placed by the bot.
-- =============================================================================
CREATE TABLE IF NOT EXISTS trades (
    id          UUID            DEFAULT gen_random_uuid() PRIMARY KEY,
    ticker      VARCHAR(20)     NOT NULL,                              -- e.g. "BTCUSDT"
    action      VARCHAR(10)     NOT NULL CHECK (action IN ('BUY', 'SELL')),
    amount      NUMERIC(24, 8)  NOT NULL CHECK (amount > 0),          -- base-asset quantity
    price       NUMERIC(24, 8)  NOT NULL CHECK (price > 0),           -- execution price (quote asset)
    highest_price NUMERIC(24, 8),
    lowest_price  DOUBLE PRECISION,
    stop_loss_price DOUBLE PRECISION,
    side        VARCHAR(10)     DEFAULT 'LONG',
    reason      VARCHAR(50),
    status      VARCHAR(20)     NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'CLOSED', 'FAILED')),
    is_closed   BOOLEAN         NOT NULL DEFAULT FALSE,
    parent_id   UUID            REFERENCES trades(id),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes for trade history queries and status filtering
CREATE INDEX IF NOT EXISTS idx_trades_ticker      ON trades (ticker);
CREATE INDEX IF NOT EXISTS idx_trades_status      ON trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_created_at  ON trades (created_at DESC);
