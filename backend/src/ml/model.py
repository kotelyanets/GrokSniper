"""
model.py
--------
ML Training Pipeline for GrokSniper AI — Phase 28.1+

Trains a RandomForestRegressor to predict the 1-hour forward return
after a news event using ONLY TF-IDF on raw_text.  Groq sentiment scores
are NOT used as features so the model works on data collected by the
high-speed bootcamp (ml_bootcamp.py) as well as live trading logs.

Usage:
    python -m backend.src.ml.model

Requires:
    - scikit-learn, joblib
    - A running PostgreSQL database with populated news_logs
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

import joblib
import numpy as np
from dotenv import load_dotenv
from scipy.sparse import hstack as sparse_hstack, csr_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer

load_dotenv()

from backend.src.db.database import AsyncSessionLocal
from backend.src.db.models import NewsLog

logger = logging.getLogger("groksniper.ml.model")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ML_DIR     = Path(__file__).parent
MODEL_PATH = ML_DIR / "saved_model.pkl"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_SAMPLES        = 50    # minimum labelled samples needed to train
TFIDF_MAX_FEATURES = 5000  # vocabulary size for the text vectorizer
RETURN_TAG_RE      = re.compile(r"^\[RETURN:([+-]?\d+\.\d+)\]\s*")


# ---------------------------------------------------------------------------
# Data extraction helper
# ---------------------------------------------------------------------------
def _extract_return_from_text(raw_text: str) -> tuple[str, float | None]:
    """
    Strips the [RETURN:±0.001234] prefix embedded by the bootcamp and
    returns (clean_text, actual_return).
    If no prefix is found, returns (raw_text, None).
    """
    m = RETURN_TAG_RE.match(raw_text or "")
    if m:
        try:
            actual_return = float(m.group(1))
            clean_text    = raw_text[m.end():]
            return clean_text, actual_return
        except ValueError:
            pass
    return raw_text, None


# ---------------------------------------------------------------------------
# Build training data from DB
# ---------------------------------------------------------------------------
async def _fetch_training_data() -> list[dict]:
    """
    Fetches news_logs rows that have an actual_return embedded in raw_text
    (bootcamp rows) OR that are old enough to have a computable forward return
    if the exchange service is available.

    Priority:
      1. Bootcamp rows with [RETURN:...] tag — no exchange call needed.
      2. Live trading logs without a tag — skipped here (no exchange in this path).

    Also loads micro_features (5m_volatility, 15m_volume_spike) when available.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    samples: list[dict] = []

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        stmt = (
            select(NewsLog)
            .where(NewsLog.created_at <= cutoff)
            .where(NewsLog.raw_text.isnot(None))
            .order_by(NewsLog.created_at.desc())
            .limit(10_000)  # cap to keep memory sensible
        )
        result = await session.execute(stmt)
        logs   = result.scalars().all()

    logger.info(f"ML Trainer: Found {len(logs)} candidate rows.")

    for log in logs:
        clean_text, actual_return = _extract_return_from_text(log.raw_text or "")

        if actual_return is None:
            continue

        if not clean_text.strip():
            continue

        # Parse micro_features JSON if available
        micro = None
        if hasattr(log, 'micro_features') and log.micro_features:
            try:
                micro = json.loads(log.micro_features)
            except (json.JSONDecodeError, TypeError):
                pass

        samples.append({
            "raw_text"       : clean_text,
            "actual_return"  : actual_return,
            "micro_features" : micro,
        })

    logger.info(f"ML Trainer: {len(samples)} labelled samples available for training.")
    micro_count = sum(1 for s in samples if s["micro_features"] is not None)
    logger.info(f"ML Trainer: {micro_count}/{len(samples)} samples have micro-features.")
    return samples


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def _build_features(samples: list[dict]):
    """
    Transforms raw samples into a combined feature matrix:
      1. TF-IDF on raw_text (sparse)
      2. Numerical micro-features: [5m_volatility, 15m_volume_spike] (dense → sparse)

    If micro_features are available on ≥50% of samples, they are included.
    Otherwise, the model trains on TF-IDF only (backward compatibility).

    Returns:
        X          — sparse feature matrix
        y          — numpy array of actual_return
        vectorizer — fitted TfidfVectorizer (saved in bundle for inference)
        has_micro  — bool: whether micro features were included
    """
    texts = [s["raw_text"] for s in samples]
    y     = np.array([s["actual_return"] for s in samples], dtype=np.float32)

    vectorizer = TfidfVectorizer(
        max_features = TFIDF_MAX_FEATURES,
        stop_words   = "english",
        ngram_range  = (1, 2),
        sublinear_tf = True,
    )
    X_text = vectorizer.fit_transform(texts)

    # Check micro-feature coverage
    micro_count = sum(1 for s in samples if s.get("micro_features") is not None)
    has_micro = micro_count >= len(samples) * 0.5

    if has_micro:
        # Build numerical matrix: [5m_volatility, 15m_volume_spike]
        micro_array = []
        for s in samples:
            mf = s.get("micro_features")
            if mf:
                micro_array.append([
                    float(mf.get("5m_volatility", 0.0)),
                    float(mf.get("15m_volume_spike", 1.0)),
                ])
            else:
                micro_array.append([0.0, 1.0])  # neutral defaults for missing rows

        X_micro = csr_matrix(np.array(micro_array, dtype=np.float32))
        X = sparse_hstack([X_text, X_micro])
        logger.info(f"ML Trainer: Combined features — TF-IDF({X_text.shape[1]}) + micro(2) = {X.shape[1]} cols")
    else:
        X = X_text
        logger.info(f"ML Trainer: TF-IDF only — {X.shape[1]} cols (micro coverage {micro_count}/{len(samples)} < 50%)")

    return X, y, vectorizer, has_micro


# ---------------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------------
async def train_model() -> bool:
    """
    Full training pipeline. Returns True on success, False if aborted.
    """
    logger.info("ML Trainer: Starting training pipeline…")

    samples = await _fetch_training_data()

    if len(samples) < MIN_SAMPLES:
        logger.warning(
            f"ML Trainer: Only {len(samples)} labelled samples available "
            f"(need {MIN_SAMPLES}). Aborting — run the bootcamp first."
        )
        return False

    logger.info(f"ML Trainer: Building feature matrix from {len(samples)} samples…")
    X, y, vectorizer, has_micro = _build_features(samples)

    model = RandomForestRegressor(
        n_estimators   = 200,
        max_depth      = 10,
        min_samples_leaf = 5,
        oob_score      = True,
        n_jobs         = -1,
        random_state   = 42,
    )
    logger.info("ML Trainer: Fitting RandomForestRegressor on combined features…")
    model.fit(X, y)

    oob = getattr(model, "oob_score_", None)
    logger.info(
        f"ML Trainer: Training complete. "
        f"OOB R² = {oob:.4f}" if oob is not None else "ML Trainer: Training complete."
    )

    # Save bundle: vectorizer + model + micro flag
    bundle = {"vectorizer": vectorizer, "model": model, "has_micro": has_micro}
    joblib.dump(bundle, MODEL_PATH)
    logger.info(f"ML Trainer: Model saved to {MODEL_PATH} (has_micro={has_micro})")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = asyncio.run(train_model())
    if success:
        print("✅ ML model trained and saved successfully.")
    else:
        print("⚠️  Training aborted: not enough labelled data yet. Run ml_bootcamp.py first.")
