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

async def fix_schema():
    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        print("Adding missing columns...")
        try:
            await conn.execute(text("ALTER TABLE news_logs ADD COLUMN IF NOT EXISTS micro_features TEXT;"))
            print("Added micro_features to news_logs")
        except Exception as e:
            print("Error adding micro_features:", e)

        try:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS highest_price NUMERIC(24, 8);"))
            print("Added highest_price to trades")
        except Exception as e:
            print("Error adding highest_price:", e)

        try:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS lowest_price DOUBLE PRECISION;"))
            print("Added lowest_price to trades")
        except Exception as e:
            print("Error adding lowest_price:", e)

        try:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS stop_loss_price DOUBLE PRECISION;"))
            print("Added stop_loss_price to trades")
        except Exception as e:
            print("Error adding stop_loss_price:", e)

        try:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS side VARCHAR(10) DEFAULT 'LONG';"))
            print("Added side to trades")
        except Exception as e:
            print("Error adding side:", e)

        try:
            await conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS reason VARCHAR(50);"))
            print("Added reason to trades")
        except Exception as e:
            print("Error adding reason:", e)

    print("Schema update complete!")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(fix_schema())
