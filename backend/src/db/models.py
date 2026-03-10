"""
models.py
---------
SQLAlchemy ORM models for GrokSniper AI.
These mirror the tables defined in database/init.sql exactly.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.src.db.database import Base


# ---------------------------------------------------------------------------
# news_logs
# ---------------------------------------------------------------------------
class NewsLog(Base):
    """Raw news / tweet enriched with Grok AI sentiment analysis."""

    __tablename__ = "news_logs"
    __table_args__ = (
        CheckConstraint(
            "sentiment_score BETWEEN -1.0 AND 1.0",
            name="ck_news_logs_sentiment_range",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name="ck_news_logs_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(
        Numeric(4, 3), nullable=True
    )
    confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    micro_features: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {5m_volatility, 15m_volume_spike}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<NewsLog id={self.id} ticker={self.ticker} "
            f"sentiment={self.sentiment_score}>"
        )


# ---------------------------------------------------------------------------
# trades
# ---------------------------------------------------------------------------
class Trade(Base):
    """Every trade order placed (or attempted) by the bot."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("action IN ('BUY', 'SELL')", name="ck_trades_action"),
        CheckConstraint("amount > 0", name="ck_trades_amount_positive"),
        CheckConstraint("price > 0", name="ck_trades_price_positive"),
        CheckConstraint(
            "status IN ('pending', 'filled', 'failed', 'completed', 'success')",
            name="ck_trades_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(24, 8), nullable=False)
    highest_price: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    lowest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # ATR-based dynamic stop
    position_size_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)  # USD value equivalent dynamically calculated
    side: Mapped[str] = mapped_column(String(10), default="LONG")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN"
    )
    is_closed: Mapped[bool] = mapped_column(nullable=False, default=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Trade id={self.id} ticker={self.ticker} "
            f"action={self.action} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# paper_trades
# ---------------------------------------------------------------------------
class PaperTrade(Base):
    """Virtual trade execution — used in Paper Trading mode (PAPER_TRADE=True)."""

    __tablename__ = "paper_trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)          # "LONG" or "SHORT"
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    size_usdt: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")  # OPEN / CLOSED
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<PaperTrade id={self.id} ticker={self.ticker} "
            f"action={self.action} status={self.status}>"
        )


# ---------------------------------------------------------------------------
# agent_decision_logs
# ---------------------------------------------------------------------------
class AgentDecisionLog(Base):
    """Records why the CrewAI agents approved or rejected a trade signal."""

    __tablename__ = "agent_decision_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)         # 0.0 – 1.0
    cio_reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    market_regime: Mapped[str | None] = mapped_column(String(20), nullable=True)  # e.g. "BULLISH"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDecisionLog id={self.id} ticker={self.ticker} "
            f"approved={self.is_approved}>"
        )

