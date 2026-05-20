import os
import logging
from pathlib import Path
import joblib

logger = logging.getLogger("groksniper.ml_service")

# Path to the trained ML bundle
MODEL_PATH = Path(__file__).parent.parent / "ml" / "saved_model.pkl"

def get_ml_status() -> dict:
    """
    Reads the saved machine learning bundle and extracts:
    - OOB Score (Out-Of-Bag accuracy proxy for Random Forest)
    - Top 20 Most Important Features (Words or N-grams)
    - Total features tracked
    - Micro-feature inclusion status
    """
    if not MODEL_PATH.exists():
        return {
            "status": "not_trained",
            "message": "No machine learning model found. Run ml_bootcamp.py to train.",
            "metrics": None
        }

    try:
        # Load the bundle containing both the model and vectorizer
        bundle = joblib.load(MODEL_PATH)
        model = bundle.get("model")
        vectorizer = bundle.get("vectorizer")
        has_micro = bundle.get("has_micro", False)

        if not model or not vectorizer:
            return {"status": "error", "message": "Corrupted or outdated model bundle.", "metrics": None}

        # 1. Extract Accuracy Metric
        oob_score = getattr(model, "oob_score_", 0.0)

        # 2. Extract Feature Importances
        importances = model.feature_importances_
        feature_names = vectorizer.get_feature_names_out()

        # If model was trained with micro features, they are appended to the end of the feature matrix
        if has_micro:
            # Manually append the two micro-feature names
            feature_names = list(feature_names) + ["[5m_volatility]", "[15m_volume_spike]"]

        # 3. Zip and sort to find the top influential words
        # Note: Random Forest importances show how much a feature reduces impurity, 
        # not necessarily if it's "bullish" or "bearish", just that it's "important".
        feat_imp = list(zip(feature_names, importances))
        feat_imp.sort(key=lambda x: x[1], reverse=True)

        top_20 = [{"word": str(feat), "importance": float(imp)} for feat, imp in feat_imp[:20]]

        last_modified = os.path.getmtime(MODEL_PATH)

        return {
            "status": "trained",
            "message": "Model loaded successfully.",
            "metrics": {
                "accuracy_oob": round(float(oob_score), 4),
                "total_features": len(feature_names),
                "has_micro_features": has_micro,
                "top_features": top_20,
                "last_trained_timestamp": last_modified
            }
        }
    except Exception as e:
        logger.error(f"Failed to extract ML status: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "metrics": None}
