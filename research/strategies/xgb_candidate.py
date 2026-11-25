"""
Stage D candidate: the legacy XGBoost model, rebuilt to fit the strategy interface.

NOT a benchmark. Trial #1 in the trial log.

What it does, at each week's last close T:
  1. Uses the model trained on data up to the end of the previous calendar year
     (walk-forward, expanding window, retrained yearly). Training rows whose
     label wasn't known by that cutoff are dropped, so no future returns leak in.
  2. Scores every stock: P(beats the median stock over the next `horizon` days,
     measured from the next open).
  3. Holds the top N stocks whose probability exceeds `min_prob`, equally
     weighted (1/N each, <= 25%). Fewer qualifiers -> the rest stays in cash.

Fixes versus the legacy model:
  - Label is tradable (next open -> open H days later), not close-to-close.
  - No early stopping on the evaluation set (fixed number of trees), so the
    evaluation isn't tuned on itself.
  - Judged by strategy returns after costs, not accuracy.
  - No feature scaler (trees don't need one) and no global 80/20 split.
"""

from __future__ import annotations

import pandas as pd
from xgboost import XGBClassifier

from research.strategies.features import FEATURE_COLS, WARMUP_ROWS, build_features, build_labels
from shared.strategy import PriceView, Strategy
from shared.universe import STOCKS, etf

# Legacy hyperparameters, minus early stopping. Fixed: not tuned on any period.
XGB_PARAMS = dict(
    n_estimators=300, max_depth=5, learning_rate=0.05, subsample=0.8,
    colsample_bytree=0.8, min_child_weight=5, reg_alpha=0.1, reg_lambda=1.0,
    eval_metric="logloss", tree_method="hist", random_state=0, n_jobs=4,
)


def train_model(field, cutoff: pd.Timestamp, horizon: int) -> tuple[XGBClassifier | None, int]:
    """Train on all rows on/before `cutoff` whose label is fully known by `cutoff`."""
    stocks = list(STOCKS)
    X = build_features(field, stocks, etf("broad_index"), "^VIX")
    y = build_labels(field, stocks, horizon)
    data = X.join(y, how="inner").dropna()
    data = data[data.index.get_level_values("date") <= cutoff]
    if len(data) < 1000:
        return None, len(data)
    model = XGBClassifier(**XGB_PARAMS)
    model.fit(data[FEATURE_COLS].to_numpy(), data["label"].astype(int).to_numpy())
    return model, len(data)


class XGBCandidate(Strategy):
    name = "xgb_candidate"
    rebalance = "weekly"

    def __init__(self, horizon: int = 5, top_n: int = 5, min_prob: float = 0.5,
                 min_train_years: int = 3):
        self.horizon, self.top_n, self.min_prob = horizon, top_n, min_prob
        self.min_train_years = min_train_years
        self._models: dict[int, XGBClassifier | None] = {}
        self.train_rows: dict[int, int] = {}

    def params(self) -> dict:
        return {"horizon_days": self.horizon, "top_n": self.top_n, "min_prob": self.min_prob,
                "retrain": "yearly, expanding window", "min_train_years": self.min_train_years,
                "label": f"open(T+1)->open(T+1+{self.horizon}) beats cross-sectional median",
                "xgb": {k: v for k, v in XGB_PARAMS.items() if k != "n_jobs"}}

    def _model_for(self, data: PriceView) -> XGBClassifier | None:
        year = data.asof.year
        if year not in self._models:
            cutoff = pd.Timestamp(year - 1, 12, 31)
            first = data.dates[0]
            if cutoff.year - first.year + 1 < self.min_train_years + 1:  # +1 year feature warm-up
                self._models[year] = None
            else:
                end = data.dates.searchsorted(cutoff, side="right")
                field = lambda n: data.field(n).iloc[:end]       # nothing after the cutoff
                self._models[year], self.train_rows[year] = train_model(field, cutoff, self.horizon)
        return self._models[year]

    def target_weights(self, data: PriceView) -> pd.Series:
        model = self._model_for(data)
        if model is None:
            return pd.Series(dtype=float)
        field = lambda n: data.field(n).iloc[-WARMUP_ROWS:]
        X = build_features(field, list(STOCKS), etf("broad_index"), "^VIX")
        today = X.xs(data.asof, level="date", drop_level=True) if data.asof in X.index.get_level_values(0) else None
        if today is None or today.empty:
            return pd.Series(dtype=float)
        today = today.dropna()
        if today.empty:
            return pd.Series(dtype=float)
        prob = pd.Series(model.predict_proba(today[FEATURE_COLS].to_numpy())[:, 1], index=today.index)
        picks = prob[prob > self.min_prob].nlargest(self.top_n).index
        return pd.Series(1.0 / self.top_n, index=picks)

    def predict_proba(self, data: PriceView) -> pd.Series:
        """Diagnostic: today's probabilities for every stock."""
        model = self._model_for(data)
        X = build_features(lambda n: data.field(n).iloc[-WARMUP_ROWS:], list(STOCKS), etf("broad_index"), "^VIX")
        today = X.xs(data.asof, level="date").dropna()
        return pd.Series(model.predict_proba(today[FEATURE_COLS].to_numpy())[:, 1], index=today.index)
