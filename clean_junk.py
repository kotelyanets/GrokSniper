import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    DB_USER, DB_PASS = os.getenv("DB_USER", "postgres"), os.getenv("DB_PASS", "postgres")
    DB_HOST, DB_PORT, DB_NAME = os.getenv("DB_HOST", "localhost"), os.getenv("DB_PORT", "5432"), os.getenv("DB_NAME", "sniper_db")
    DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

async def clean():
    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        # Удаляем все сделки, где тикер не является нормальной криптой (BTC, ETH и т.д.)
        await conn.execute(text("DELETE FROM trades WHERE ticker = '这是测试币' OR ticker = '456';"))
    print("🧹 Мусорные монеты успешно удалены!")
    await engine.dispose()

asyncio.run(clean())