import asyncio
from backend.src.db.database import AsyncSessionLocal
from sqlalchemy import text

async def reset_db():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM trades"))
        await session.execute(text("DELETE FROM paper_trades"))
        await session.execute(text("DELETE FROM news_logs"))
        await session.execute(text("DELETE FROM agent_decision_logs"))
        await session.commit()
    print("Database Reset Complete! Test ready.")

if __name__ == "__main__":
    asyncio.run(reset_db())
