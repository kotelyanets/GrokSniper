"""
main.py
-------
Entry point for the GrokSniper AI Trading Engine.

Starts the FastAPI server on port 8000. The server handles DB initialisation
via its lifespan handler and exposes all endpoints to the Next.js dashboard.

Run with:
    python -m backend.src.main
  or (from inside backend/):
    python src/main.py
"""

import logging
import os

from dotenv import load_dotenv

# Load .env BEFORE any backend imports so module-level env reads
# in database.py (and elsewhere) are satisfied immediately.
load_dotenv()

import uvicorn  # noqa: E402

from backend.src.api.server import app  # noqa: E402  (also triggers DB setup)

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("groksniper.main")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("╔══════════════════════════════════╗")
    logger.info("║     GrokSniper AI  —  Starting   ║")
    logger.info("╚══════════════════════════════════╝")
    logger.info("FastAPI server starting on http://0.0.0.0:8000")
    logger.info("Docs available at  http://localhost:8000/docs")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
