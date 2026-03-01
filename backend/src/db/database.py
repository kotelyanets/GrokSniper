"""
database.py
-----------
Async SQLAlchemy engine + session factory for GrokSniper AI.

Usage (FastAPI-style dependency injection):
    async def some_route(session: AsyncSession = Depends(get_session)):
        ...

Or as an async context manager anywhere else:
    async with get_session() as session:
        result = await session.execute(select(Trade))
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# ---------------------------------------------------------------------------
# Load .env from the project root (two levels above this file)
# ---------------------------------------------------------------------------
load_dotenv()

DATABASE_URL: str | None = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Make sure a .env file exists in the project root and contains DATABASE_URL, "
        "or that the variable is exported in your shell environment."
    )

# ---------------------------------------------------------------------------
# Engine
# echo=False in production; set to True locally for SQL debug logs
# ---------------------------------------------------------------------------
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("APP_ENV", "production") == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Declarative base — imported by models.py
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dependency / context-manager helper
# ---------------------------------------------------------------------------
@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session and handle commit/rollback automatically."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
