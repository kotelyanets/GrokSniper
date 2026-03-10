import asyncio
from backend.src.db.database import engine
from sqlalchemy import text

async def main():
    try:
        async with engine.begin() as conn:
            print("Altering trades.reason column type to TEXT...")
            await conn.execute(text("ALTER TABLE trades ALTER COLUMN reason TYPE TEXT;"))
            print("Migration successful.")
    except Exception as e:
        print(f"Migration error: {e}")
    finally:
        await engine.dispose()

asyncio.run(main())
