"""
predictor.py
------------
ML Predictor for GrokSniper AI — Phase 28.1+

Loads the trained TF-IDF → RandomForest bundle and maps raw news text
directly to a predicted 1-hour return, which is then converted into a
calibrated sentiment score in [-1.0, 1.0].

The model is trained exclusively on raw_text features; no Groq sentiment
score or confidence value is required for inference.

Usage:
    from backend.src.ml.predictor import calibrate_score

    # With a Groq score available (live trading path):
    calibrated = calibrate_score(raw_text, original_score)

    # Groq-less / bootcamp-trained path:
    calibrated = calibrate_score(raw_text)
"""

import logging
from pathlib import Path

import numpy as np
from scipy.sparse import hstack as sparse_hstack, csr_matrix

logger = logging.getLogger("groksniper.ml.predictor")

# ---------------------------------------------------------------------------
# Model path
# ---------------------------------------------------------------------------
MODEL_PATH = Path(__file__).parent / "saved_model.pkl"

# ---------------------------------------------------------------------------
# Blend weights
# When a Groq score IS available blend ML + Groq; otherwise use ML alone.
# ---------------------------------------------------------------------------
ML_WEIGHT   = 0.70   # weight for the text-based ML prediction
GROQ_WEIGHT = 0.30   # weight for the raw Groq score (only when provided)

# Clamp window: 99th percentile of realistic 1-hour crypto returns
MAX_RETURN_CLAMP = 0.20   # ±20 %


# ---------------------------------------------------------------------------
# Bundle loader (cached in module-level variable to avoid repeated disk I/O)
# ---------------------------------------------------------------------------
_bundle_cache: dict | None = None


def _load_bundle() -> dict | None:
    """
    Loads the joblib bundle {vectorizer, model} from disk.
    Result is cached after the first successful load.
    Returns None if the model file does not exist (cold start).
    """
    global _bundle_cache
    if _bundle_cache is not None:
        return _bundle_cache

    if not MODEL_PATH.exists():
        return None

    try:
        import joblib
        _bundle_cache = joblib.load(MODEL_PATH)
        logger.info("ML Predictor: Model bundle loaded from %s", MODEL_PATH)
        return _bundle_cache
    except Exception as e:
        logger.warning("ML Predictor: Failed to load model — %s", e)
        return None


def _invalidate_cache() -> None:
    """Call this after retraining so the next prediction reloads from disk."""
    global _bundle_cache
    _bundle_cache = None


# ---------------------------------------------------------------------------
# Utility: predicted return → sentiment score space
# ---------------------------------------------------------------------------
def _return_to_score(predicted_return: float) -> float:
    """
    Maps a raw predicted 1-hour return (e.g. +0.03 = +3 %) into [-1.0, 1.0].
    Clamps to ±MAX_RETURN_CLAMP then scales linearly.
    """
    clamped = max(-MAX_RETURN_CLAMP, min(MAX_RETURN_CLAMP, predicted_return))
    return round(clamped / MAX_RETURN_CLAMP, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def calibrate_score(
    raw_text      : str,
    original_score: float | None = None,
    micro_features: dict | None = None,
) -> float:
    """
    Predicts a calibrated sentiment score from raw news text.

    Args:
        raw_text:       The news article text (headline + body).
        original_score: Optional Groq raw sentiment score in [-1.0, 1.0].
                        If provided, the final score blends ML + Groq.
                        If None, the ML prediction is used exclusively.
        micro_features: Optional dict with "5m_volatility" and "15m_volume_spike".
                        Required for models trained with micro-market context.

    Returns:
        calibrated_score in [-1.0, 1.0].
        Falls back to original_score (or 0.0) on cold start or errors.
    """
    bundle = _load_bundle()

    if bundle is None:
        logger.debug("ML Predictor: No model found (cold start). Using fallback.")
        return original_score if original_score is not None else 0.0

    try:
        vectorizer = bundle["vectorizer"]
        model      = bundle["model"]
        has_micro  = bundle.get("has_micro", False)

        X = vectorizer.transform([raw_text or ""])

        # Append micro-features if the model was trained with them
        if has_micro:
            mf = micro_features or {}
            micro_vec = csr_matrix(np.array([[
                float(mf.get("5m_volatility", 0.0)),
                float(mf.get("15m_volume_spike", 1.0)),
            ]], dtype=np.float32))
            X = sparse_hstack([X, micro_vec])

        predicted_return = float(model.predict(X)[0])
        ml_score         = _return_to_score(predicted_return)

        if original_score is not None:
            calibrated = (ML_WEIGHT * ml_score) + (GROQ_WEIGHT * original_score)
        else:
            calibrated = ml_score

        calibrated = round(max(-1.0, min(1.0, calibrated)), 4)

        logger.debug(
            "ML Predictor: predicted_return=%.4f  ml_score=%.3f  "
            "original_score=%s  calibrated=%.3f  micro=%s",
            predicted_return,
            ml_score,
            f"{original_score:.3f}" if original_score is not None else "N/A",
            calibrated,
            "yes" if has_micro and micro_features else "no",
        )

        return calibrated

    except Exception as e:
        logger.warning("ML Predictor: Calibration failed — %s. Using fallback.", e)
        return original_score if original_score is not None else 0.0


def predict_return(raw_text: str, micro_features: dict | None = None) -> float | None:
    """
    Lower-level helper: returns the raw predicted 1-hour return as a float,
    or None on cold start / error.  Useful for logging and analytics.
    """
    bundle = _load_bundle()
    if bundle is None:
        return None
    try:
        X = bundle["vectorizer"].transform([raw_text or ""])

        # Append micro-features if the model was trained with them
        if bundle.get("has_micro", False):
            mf = micro_features or {}
            micro_vec = csr_matrix(np.array([[
                float(mf.get("5m_volatility", 0.0)),
                float(mf.get("15m_volume_spike", 1.0)),
            ]], dtype=np.float32))
            X = sparse_hstack([X, micro_vec])

        return float(bundle["model"].predict(X)[0])
    except Exception as e:
        logger.warning("ML Predictor: predict_return failed — %s", e)
        return None
