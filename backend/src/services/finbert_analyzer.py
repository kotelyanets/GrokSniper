"""
finbert_analyzer.py
-------------------
Local FinBERT sentiment engine (ProsusAI/finbert via HuggingFace transformers).
Runs entirely on CPU or CUDA — NO external API calls, ZERO cost.
"""

import logging
from functools import lru_cache

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
from transformers.utils import logging as hf_logging

logger = logging.getLogger(__name__)

# Suppress verbose HuggingFace load warnings
hf_logging.set_verbosity_error()

# FinBERT maps its output labels to these canonical names.
_LABEL_MAP = {
    "positive": "positive",
    "negative": "negative",
    "neutral":  "neutral",
}


@lru_cache(maxsize=1)
def _load_pipeline():
    """
    Load (and cache) the FinBERT pipeline once per process.
    The first call will download ~400 MB of model weights from HuggingFace Hub
    and cache them locally in ~/.cache/huggingface.  Subsequent calls are instant.
    """
    device = 0 if torch.cuda.is_available() else -1  # 0 = first GPU, -1 = CPU
    device_label = "CUDA" if device == 0 else "CPU"
    logger.info(f"[FinBERT] Loading ProsusAI/finbert on {device_label}...")

    tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")

    sentiment_pipeline = pipeline(
        task="text-classification",
        model=model,
        tokenizer=tokenizer,
        device=device,
        truncation=True,
        max_length=512,
    )
    logger.info("[FinBERT] Model loaded and ready.")
    return sentiment_pipeline


async def analyze_news_sentiment(text: str) -> dict:
    """
    Analyse the sentiment of a financial news string using local FinBERT.

    Parameters
    ----------
    text : str
        Raw news headline or body text (will be truncated to 512 tokens).

    Returns
    -------
    dict with keys:
        label      – "positive" | "negative" | "neutral"
        score      – float confidence in [0.0, 1.0]
        model      – identifier string ("finbert-local")
        error      – present only on failure, contains the error message
    """
    if not text or not text.strip():
        return {"label": "neutral", "score": 0.0, "model": "finbert-local"}

    try:
        pipe = _load_pipeline()

        # pipeline() is CPU-bound; run it in the default thread-pool via asyncio
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: pipe(text)[0])

        raw_label = result["label"].lower()
        label = _LABEL_MAP.get(raw_label, "neutral")
        confidence = round(float(result["score"]), 4)

        return {
            "label": label,
            "score": confidence,
            "model": "finbert-local",
        }

    except Exception as exc:
        logger.error(f"[FinBERT] Sentiment analysis failed: {exc}", exc_info=True)
        return {
            "label": "neutral",
            "score": 0.0,
            "model": "finbert-local",
            "error": str(exc),
        }
