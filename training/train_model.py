"""
XGBoost training script for the binary classifier.
"""

import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, log_loss
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from training.dataset import prepare_datasets, FEATURE_COLS


def train(tickers: list[str] | None = None):
    X_train, y_train, X_val, y_val, scaler = prepare_datasets(tickers)

    model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=1.0,
        eval_metric="logloss",
        early_stopping_rounds=20,
        verbosity=1,
    )

    print(f"[train] Training XGBClassifier on CPU "
          f"(n_estimators=300, max_depth=5, lr=0.05, "
          f"early_stopping=20)\n")

    start = time.perf_counter()
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=20,
    )
    duration = time.perf_counter() - start

    best_iter = model.best_iteration
    print(f"\n[train] Best iteration: {best_iter}")

    y_pred = model.predict(X_val)
    y_prob = model.predict_proba(X_val)[:, 1]

    val_acc = accuracy_score(y_val, y_pred)
    val_logloss = log_loss(y_val, y_prob)

    print(f"[train] Validation Accuracy : {val_acc:.4f}")
    print(f"[train] Validation Log-Loss : {val_logloss:.4f}")
    print(f"[train] CPU Training Time   : {duration:.2f}s")

    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]
    print(f"\n[train] Top 10 Feature Importances:")
    for rank, idx in enumerate(indices[:10], 1):
        print(f"  {rank:2d}. {FEATURE_COLS[idx]:<20s}  {importances[idx]:.4f}")

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    save_path = config.MODELS_DIR / "trading_model_xgb.json"
    model.save_model(str(save_path))
    print(f"\n[train] Model saved to {save_path}")

    return val_acc, val_logloss


if __name__ == "__main__":
    tickers = sys.argv[1:] or None
    train(tickers)
